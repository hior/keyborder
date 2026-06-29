"""
Keyboard Layout Border Indicator with System Tray
Shows a colored border around the screen based on current keyboard layout.
Includes system tray icon for easy control.

Features:
- Colored border indicating current keyboard layout
- Pause/Break to convert selected text between layouts (EN↔RU) and switch layout

Requirements: pip install pystray pillow
"""

import ctypes
from ctypes import wintypes
import tkinter as tk
import threading
import sys
import time
import traceback
import os

# Setup logging to file for crash debugging
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'layout_indicator.log')

def log_error(msg, flush=True):
    """Log error to file and console."""
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{timestamp}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
            if flush:
                f.flush()
                os.fsync(f.fileno())  # Force write to disk
    except Exception:
        pass

def global_exception_handler(exc_type, exc_value, exc_tb):
    """Global exception handler to catch unhandled exceptions."""
    error_msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
    log_error(f"UNHANDLED EXCEPTION:\n{error_msg}")
    sys.__excepthook__(exc_type, exc_value, exc_tb)

sys.excepthook = global_exception_handler

def thread_exception_handler(args):
    """Handler for exceptions in threads."""
    error_msg = ''.join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    log_error(f"THREAD EXCEPTION in {args.thread.name}:\n{error_msg}")

threading.excepthook = thread_exception_handler

try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False
    print("Note: Install 'pystray' and 'pillow' for system tray support")
    print("  pip install pystray pillow")

# Windows API
user32 = ctypes.windll.user32

# ============================================
# CONFIGURATION - Edit these to your liking!
# ============================================

# Colors by HKL (Keyboard Layout Handle) - actual values from your system
KLID_COLORS = {
    0xF0010409: ('#8B008B', 'US-Intl'),    # US International - purple/magenta
    0x04090409: ('#00CED1', 'US'),          # US standard - cyan
    0x04190419: ('#DC143C', 'RU'),          # Russian - red
}

# Fallback colors by language ID (if KLID not in the list above)
LANG_COLORS = {
    0x0409: ('#3498db', 'EN'),   # English - blue
    0x0419: ('#DC143C', 'RU'),   # Russian - red
}

DEFAULT_COLOR = ('#7f8c8d', '??')  # Unknown - gray

BORDER_THICKNESS = 6      # Border width in pixels (1-10 recommended)
BORDER_OPACITY_OUTER = 0.8   # Opacity at outer edge (0.0-1.0)
BORDER_OPACITY_INNER = 0.05  # Opacity at inner edge (0.0-1.0)
CHECK_INTERVAL_MS = 150   # How often to check layout (milliseconds)
SHOW_ALL_EDGES = True     # True = full frame, False = bottom only

# Text conversion hotkey (Pause/Break)
ENABLE_TEXT_CONVERSION = True  # Set to False to disable this feature

# Diagnostic: log scan codes of ambiguous VK 0xFF keys to layout_indicator.log
# (entries tagged [DIAG]). Useful to find a settings-button scan code on a new
# laptop — set SETTINGS_SCANCODE accordingly. Leave False for normal use.
DIAGNOSE_KEYS = False

# ============================================

# Character mapping for EN↔RU conversion (QWERTY ↔ ЙЦУКЕН)
EN_CHARS = r"""`qwertyuiop[]asdfghjkl;'zxcvbnm,./~QWERTYUIOP{}ASDFGHJKL:"ZXCVBNM<>?@#$^&"""
RU_CHARS = r"""ёйцукенгшщзхъфывапролджэячсмитьбю.ЁЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮ,"№;:?"""

# Build translation tables
EN_TO_RU = str.maketrans(EN_CHARS, RU_CHARS)
RU_TO_EN = str.maketrans(RU_CHARS, EN_CHARS)

# Hotkey constants
MOD_NOREPEAT = 0x4000
VK_PAUSE = 0x13
VK_SETTINGS = 0xFF  # Special settings key (Redmi Book and similar laptops)

# VK 0xFF is the "no mapping" virtual code — several physical keys report it
# (the settings button, the Fn-lock key, numpad nav keys under Num Lock).
# RegisterHotKey(0xFF) catches all of them, so we disambiguate by scan code:
# only the real settings button (scan 0x72) should trigger conversion.
SETTINGS_SCANCODE = 0x72  # Scan code of the dedicated settings/function button
HOTKEY_ID_PAUSE = 1
HOTKEY_ID_SETTINGS = 2
WM_HOTKEY = 0x0312

# Lock to prevent multiple simultaneous conversions
_conversion_lock = threading.Lock()
_conversion_in_progress = False

# Layout HKLs for switching (use your preferred EN layout)
HKL_EN = 0x04090409  # US standard (change to 0xF0010409 for US-Intl)
HKL_RU = 0x04190419  # Russian


def get_foreground_hwnd():
    """Get handle of foreground window."""
    try:
        return user32.GetForegroundWindow()
    except Exception as e:
        log_error(f"get_foreground_hwnd error: {e}")
        return None


def is_valid_hwnd(hwnd):
    """Check if hwnd is valid."""
    if not hwnd:
        return False
    try:
        return user32.IsWindow(hwnd)
    except Exception:
        return False


def get_keyboard_layout_for_hwnd(hwnd):
    """Get keyboard layout info for a window: (color, name)."""
    if not is_valid_hwnd(hwnd):
        return DEFAULT_COLOR

    try:
        thread_id = user32.GetWindowThreadProcessId(hwnd, None)
        if not thread_id:
            return DEFAULT_COLOR

        hkl = user32.GetKeyboardLayout(thread_id)

        # HKL is a handle - treat as unsigned 32-bit
        hkl_value = hkl & 0xFFFFFFFF

        # Try matching by full HKL value
        if hkl_value in KLID_COLORS:
            return KLID_COLORS[hkl_value]

        # Fallback to language ID only
        lang_id = hkl_value & 0xFFFF
        if lang_id in LANG_COLORS:
            return LANG_COLORS[lang_id]

        return DEFAULT_COLOR
    except Exception as e:
        log_error(f"get_keyboard_layout_for_hwnd error: {e}")
        return DEFAULT_COLOR


def get_keyboard_layout():
    """Get current keyboard layout info: (color, name)."""
    return get_keyboard_layout_for_hwnd(get_foreground_hwnd())


class RECT(ctypes.Structure):
    _fields_ = [
        ('left', ctypes.c_long),
        ('top', ctypes.c_long),
        ('right', ctypes.c_long),
        ('bottom', ctypes.c_long),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ('cbSize', ctypes.c_ulong),
        ('rcMonitor', RECT),
        ('rcWork', RECT),
        ('dwFlags', ctypes.c_ulong),
    ]


_MONITORENUMPROC = ctypes.WINFUNCTYPE(
    ctypes.c_bool,
    ctypes.c_void_p,  # hMonitor
    ctypes.c_void_p,  # hdcMonitor
    ctypes.POINTER(RECT),  # lprcMonitor
    ctypes.c_void_p   # dwData
)

# Shared list for monitor enum callback to avoid creating closures each call
_monitor_results = []

def _monitor_enum_callback(hMonitor, hdcMonitor, lprcMonitor, dwData):
    try:
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(hMonitor, ctypes.byref(info)):
            work = info.rcWork
            _monitor_results.append((work.left, work.top, work.right, work.bottom))
    except Exception as e:
        log_error(f"monitor_enum_callback error: {e}")
    return True

# Create callback ONCE at module level — prevents leaking C-level ffi closures
_monitor_callback = _MONITORENUMPROC(_monitor_enum_callback)


def get_all_monitors():
    """Get work areas for all monitors."""
    _monitor_results.clear()

    try:
        user32.EnumDisplayMonitors(None, None, _monitor_callback, 0)
    except Exception as e:
        log_error(f"get_all_monitors error: {e}")

    monitors = list(_monitor_results)

    # Return at least primary monitor if enumeration failed
    if not monitors:
        try:
            rect = RECT()
            SPI_GETWORKAREA = 0x0030
            ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
            monitors.append((rect.left, rect.top, rect.right, rect.bottom))
        except Exception:
            monitors.append((0, 0, 1920, 1080))  # Fallback

    return monitors


def get_work_area():
    """Get screen work area (excluding taskbar) - primary monitor only."""
    rect = RECT()
    SPI_GETWORKAREA = 0x0030
    ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
    return rect.left, rect.top, rect.right, rect.bottom


def get_resource_counts():
    """Return (handles, gdi_objects, user_objects) for this process.

    Used to track a slow handle leak: when these climb without bound the
    process eventually hits WinError 1450 (ERROR_NO_SYSTEM_RESOURCES) and
    window/timer creation starts failing. Returns (None, None, None) on error.
    """
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        hproc = kernel32.GetCurrentProcess()

        count = wintypes.DWORD(0)
        kernel32.GetProcessHandleCount(ctypes.c_void_p(hproc), ctypes.byref(count))

        # GR_GDIOBJECTS = 0, GR_USEROBJECTS = 1
        gdi = user32.GetGuiResources(ctypes.c_void_p(hproc), 0)
        usr = user32.GetGuiResources(ctypes.c_void_p(hproc), 1)
        return count.value, gdi, usr
    except Exception as e:
        log_error(f"get_resource_counts error: {e}")
        return None, None, None


def is_fullscreen(hwnd):
    """Check if the given window is fullscreen."""
    if not is_valid_hwnd(hwnd):
        return False

    try:
        # Get window rect
        window_rect = RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(window_rect)):
            return False

        # Get the monitor this window is on
        MONITOR_DEFAULTTONEAREST = 2
        hMonitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        if not hMonitor:
            return False

        # Get monitor info
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(hMonitor, ctypes.byref(info)):
            return False

        # Compare window rect with monitor rect (full screen, not work area)
        mon = info.rcMonitor
        win = window_rect

        return (win.left <= mon.left and
                win.top <= mon.top and
                win.right >= mon.right and
                win.bottom >= mon.bottom)
    except Exception as e:
        log_error(f"is_fullscreen error: {e}")
        return False


# ============================================
# Text conversion functions
# ============================================

def detect_layout(text):
    """Detect if text is predominantly EN or RU."""
    en_count = sum(1 for c in text if c in EN_CHARS)
    ru_count = sum(1 for c in text if c in RU_CHARS)
    return 'en' if en_count >= ru_count else 'ru'


def convert_text(text):
    """Convert text between EN and RU layouts."""
    layout = detect_layout(text)
    if layout == 'en':
        return text.translate(EN_TO_RU)
    else:
        return text.translate(RU_TO_EN)


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ('wVk', wintypes.WORD),
        ('wScan', wintypes.WORD),
        ('dwFlags', wintypes.DWORD),
        ('time', wintypes.DWORD),
        ('dwExtraInfo', ctypes.POINTER(ctypes.c_ulong)),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ('dx', wintypes.LONG),
        ('dy', wintypes.LONG),
        ('mouseData', wintypes.DWORD),
        ('dwFlags', wintypes.DWORD),
        ('time', wintypes.DWORD),
        ('dwExtraInfo', ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ('ki', KEYBDINPUT),
        ('mi', MOUSEINPUT),
    ]


class INPUT(ctypes.Structure):
    _anonymous_ = ('u',)
    _fields_ = [
        ('type', wintypes.DWORD),
        ('u', INPUT_UNION),
    ]


# ============================================
# Low-level keyboard hook used to read scan codes of VK 0xFF key presses,
# so we can tell the settings button apart from Fn-lock / numpad keys.
# Does NOT swallow keystrokes (always calls CallNextHookEx) -> dead keys safe.
# ============================================

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104

# Scan code of the most recent VK 0xFF keydown (set by the hook, read by the
# hotkey handler to disambiguate which physical key fired). Paired with a
# timestamp so the hotkey handler can reject a *stale* value: if Windows
# silently drops the low-level hook (it does this when a callback ever exceeds
# LowLevelHooksTimeout), this global stops updating and goes stale — without the
# freshness check a frozen 0x72 would let every VK 0xFF key (numpad nav keys,
# Fn-lock) falsely trigger conversion.
_last_settings_scan = None
_last_settings_scan_time = 0.0

# A genuine settings-button keydown lands microseconds before its WM_HOTKEY, so
# the recorded scan should be a few ms old at most. Anything older means the
# hook didn't record this keypress (dropped hook / different key) -> don't trust it.
SETTINGS_SCAN_FRESH_SEC = 0.5


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ('vkCode', wintypes.DWORD),
        ('scanCode', wintypes.DWORD),
        ('flags', wintypes.DWORD),
        ('time', wintypes.DWORD),
        ('dwExtraInfo', ctypes.POINTER(ctypes.c_ulong)),
    ]


_LL_KEYBOARD_PROC = ctypes.WINFUNCTYPE(
    ctypes.c_long,    # LRESULT
    ctypes.c_int,     # nCode
    wintypes.WPARAM,  # wParam
    wintypes.LPARAM,  # lParam
)

user32.CallNextHookEx.restype = ctypes.c_long
user32.CallNextHookEx.argtypes = [
    wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int, _LL_KEYBOARD_PROC, wintypes.HINSTANCE, wintypes.DWORD
]

# Block the hotkey thread on the message queue instead of busy-polling with
# time.sleep (which created a waitable-timer handle ~100x/sec — the canary that
# first failed with WinError 1450 under resource pressure).
user32.MsgWaitForMultipleObjectsEx.restype = wintypes.DWORD
user32.MsgWaitForMultipleObjectsEx.argtypes = [
    wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD
]
QS_ALLINPUT = 0x04FF           # wake on any input incl. QS_HOTKEY / posted msgs
MWMO_INPUTAVAILABLE = 0x0004


def _ll_keyboard_proc(nCode, wParam, lParam):
    """Record scan code of VK 0xFF key presses (settings vs Fn-lock/numpad)."""
    global _last_settings_scan, _last_settings_scan_time
    try:
        if nCode == 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            # VK 0xFF is the ambiguous code RegisterHotKey(0xFF) catches.
            if kb.vkCode == 0xFF:
                _last_settings_scan = kb.scanCode
                _last_settings_scan_time = time.time()
                if DIAGNOSE_KEYS:
                    log_error(
                        f"[DIAG] VK 0xFF keydown: scan=0x{kb.scanCode:02X} "
                        f"flags=0x{kb.flags:02X}"
                    )
    except Exception as e:
        log_error(f"_ll_keyboard_proc error: {e}")
    return user32.CallNextHookEx(None, nCode, wParam, lParam)


# Keep a reference so the C callback is not garbage-collected
_ll_keyboard_proc_ptr = _LL_KEYBOARD_PROC(_ll_keyboard_proc)


def install_kbd_hook():
    """Install the low-level keyboard hook. Returns the hook handle or None.

    Must be called from a thread that pumps messages (the hotkey thread).
    """
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        h_mod = kernel32.GetModuleHandleW(None)
        hook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, _ll_keyboard_proc_ptr, h_mod, 0
        )
        if not hook:
            err = kernel32.GetLastError()
            log_error(f"Failed to install keyboard hook (GetLastError={err})")
            return None
        return hook
    except Exception as e:
        log_error(f"Keyboard hook install error: {e}")
        return None


def get_window_class(hwnd):
    """Get window class name."""
    class_name = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, class_name, 256)
    return class_name.value


def is_console_window(hwnd):
    """Check if the window is a console (cmd, powershell, terminal)."""
    console_classes = [
        'ConsoleWindowClass',      # Classic cmd/powershell
        'CASCADIA_HOSTING_WINDOW_CLASS',  # Windows Terminal
        'PseudoConsoleWindow',     # New console host
    ]
    return get_window_class(hwnd) in console_classes


def is_classic_console(hwnd):
    """Check if this is a classic console (not Windows Terminal)."""
    return get_window_class(hwnd) == 'ConsoleWindowClass'


def send_key_press(vk):
    """Send a single key press (down + up)."""
    KEYEVENTF_KEYUP = 0x0002
    keys = [(vk, 0), (vk, KEYEVENTF_KEYUP)]
    return send_input_keys(keys)


def send_two_modifier_combo(mod1_vk, mod2_vk, key_vk):
    """Send two modifiers + key combination (e.g., Ctrl+Shift+Left)."""
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_EXTENDEDKEY = 0x0001

    # Extended keys: arrows, Insert, Delete, Home, End, Page Up/Down
    extended_keys = {0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x24, 0x23, 0x21, 0x22}
    key_flags = KEYEVENTF_EXTENDEDKEY if key_vk in extended_keys else 0

    # Send all events at once
    keys = [
        (mod1_vk, 0),                              # Ctrl down
        (mod2_vk, 0),                              # Shift down
        (key_vk, key_flags),                       # Key down
        (key_vk, key_flags | KEYEVENTF_KEYUP),     # Key up
        (mod2_vk, KEYEVENTF_KEYUP),                # Shift up
        (mod1_vk, KEYEVENTF_KEYUP),                # Ctrl up
    ]
    return send_input_keys(keys)


def type_text(text):
    """Type text character by character using SendInput with Unicode."""
    KEYEVENTF_UNICODE = 0x0004
    KEYEVENTF_KEYUP = 0x0002
    INPUT_KEYBOARD = 1

    for char in text:
        # Send unicode character
        inputs = (INPUT * 2)()

        # Key down
        inputs[0].type = INPUT_KEYBOARD
        inputs[0].ki.wVk = 0
        inputs[0].ki.wScan = ord(char)
        inputs[0].ki.dwFlags = KEYEVENTF_UNICODE
        inputs[0].ki.time = 0
        inputs[0].ki.dwExtraInfo = None

        # Key up
        inputs[1].type = INPUT_KEYBOARD
        inputs[1].ki.wVk = 0
        inputs[1].ki.wScan = ord(char)
        inputs[1].ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
        inputs[1].ki.time = 0
        inputs[1].ki.dwExtraInfo = None

        user32.SendInput(2, ctypes.byref(inputs), ctypes.sizeof(INPUT))
        time.sleep(0.01)


def switch_keyboard_layout(to_lang):
    """Switch keyboard layout to specified language ('en' or 'ru')."""
    WM_INPUTLANGCHANGEREQUEST = 0x0050

    hkl = HKL_EN if to_lang == 'en' else HKL_RU

    hwnd = get_foreground_hwnd()
    if hwnd:
        user32.PostMessageW(hwnd, WM_INPUTLANGCHANGEREQUEST, 0, hkl)


def send_input_keys(keys):
    """Send multiple key events at once using SendInput."""
    INPUT_KEYBOARD = 1

    # Map VK to scan codes for common keys
    scan_codes = {
        0x11: 0x1D,  # Ctrl
        0x10: 0x2A,  # Shift
        0x25: 0x4B,  # Left arrow
        0x43: 0x2E,  # C
        0x56: 0x2F,  # V
        0x58: 0x2D,  # X
        0x2D: 0x52,  # Insert
    }

    n = len(keys)
    inputs = (INPUT * n)()

    for i, (vk, flags) in enumerate(keys):
        inputs[i].type = INPUT_KEYBOARD
        inputs[i].ki.wVk = vk
        inputs[i].ki.wScan = scan_codes.get(vk, 0)
        inputs[i].ki.dwFlags = flags
        inputs[i].ki.time = 0
        inputs[i].ki.dwExtraInfo = None

    result = user32.SendInput(n, ctypes.byref(inputs), ctypes.sizeof(INPUT))
    return result == n


def send_key_combo(modifier_vk, key_vk):
    """Send modifier+key combination using SendInput."""
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_EXTENDEDKEY = 0x0001

    # Extended keys: arrows, Insert, Delete, Home, End, Page Up/Down
    extended_keys = {0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x24, 0x23, 0x21, 0x22}
    key_flags = KEYEVENTF_EXTENDEDKEY if key_vk in extended_keys else 0

    # Send all 4 events at once for atomicity
    keys = [
        (modifier_vk, 0),                        # Modifier down
        (key_vk, key_flags),                     # Key down
        (key_vk, key_flags | KEYEVENTF_KEYUP),   # Key up
        (modifier_vk, KEYEVENTF_KEYUP),          # Modifier up
    ]
    return send_input_keys(keys)


def send_ctrl_key(key_vk):
    """Send Ctrl+key combination."""
    VK_CONTROL = 0x11
    return send_key_combo(VK_CONTROL, key_vk)


def send_shift_key(key_vk):
    """Send Shift+key combination."""
    VK_SHIFT = 0x10
    return send_key_combo(VK_SHIFT, key_vk)


def get_clipboard_text():
    """Get text from clipboard. Returns None if failed."""
    CF_UNICODETEXT = 13

    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]

    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = ctypes.c_void_p

    if not user32.OpenClipboard(None):
        return None

    try:
        h_data = user32.GetClipboardData(CF_UNICODETEXT)
        if not h_data:
            return None

        p_data = kernel32.GlobalLock(h_data)
        if not p_data:
            return None

        try:
            text = ctypes.wstring_at(p_data)
            return text
        finally:
            kernel32.GlobalUnlock(h_data)
    finally:
        user32.CloseClipboard()


def set_clipboard_text(text):
    """Set text to clipboard. Returns True if successful."""
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002

    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]

    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]

    # Encode text as UTF-16 LE with null terminator
    text_bytes = (text + '\0').encode('utf-16-le')

    if not user32.OpenClipboard(None):
        return False

    try:
        user32.EmptyClipboard()

        h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(text_bytes))
        if not h_mem:
            return False

        p_mem = kernel32.GlobalLock(h_mem)
        if not p_mem:
            return False

        ctypes.memmove(p_mem, text_bytes, len(text_bytes))
        kernel32.GlobalUnlock(h_mem)

        user32.SetClipboardData(CF_UNICODETEXT, h_mem)
        return True
    finally:
        user32.CloseClipboard()


def clear_clipboard():
    """Clear the clipboard."""
    if user32.OpenClipboard(None):
        user32.EmptyClipboard()
        user32.CloseClipboard()


def get_console_last_word(hwnd):
    """Read the last word from console buffer before cursor."""
    kernel32 = ctypes.windll.kernel32

    # Get process ID of the window
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    # Detach from any current console and attach to target
    kernel32.FreeConsole()
    if not kernel32.AttachConsole(pid.value):
        return None

    # Get console handle
    STD_OUTPUT_HANDLE = -11
    h_console = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)

    if not h_console or h_console == -1:
        kernel32.FreeConsole()
        return None

    # Get cursor position
    class COORD(ctypes.Structure):
        _fields_ = [('X', ctypes.c_short), ('Y', ctypes.c_short)]

    class SMALL_RECT(ctypes.Structure):
        _fields_ = [('Left', ctypes.c_short), ('Top', ctypes.c_short),
                    ('Right', ctypes.c_short), ('Bottom', ctypes.c_short)]

    class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
        _fields_ = [
            ('dwSize', COORD),
            ('dwCursorPosition', COORD),
            ('wAttributes', ctypes.c_ushort),
            ('srWindow', SMALL_RECT),
            ('dwMaximumWindowSize', COORD),
        ]

    csbi = CONSOLE_SCREEN_BUFFER_INFO()
    if not kernel32.GetConsoleScreenBufferInfo(h_console, ctypes.byref(csbi)):
        return None

    cursor_x = csbi.dwCursorPosition.X
    cursor_y = csbi.dwCursorPosition.Y

    if cursor_x == 0:
        return None

    # Read the current line up to cursor
    buffer_size = cursor_x
    buffer = ctypes.create_unicode_buffer(buffer_size + 1)
    chars_read = ctypes.c_ulong()

    coord = COORD(0, cursor_y)
    kernel32.ReadConsoleOutputCharacterW(
        h_console, buffer, buffer_size, coord, ctypes.byref(chars_read)
    )

    line = buffer.value[:chars_read.value]

    # Detach from console
    kernel32.FreeConsole()

    # Extract last word
    line = line.rstrip()
    if not line:
        return None

    # Find last word (split by spaces)
    words = line.split()
    if words:
        return words[-1]

    return None


def convert_in_terminal(hwnd):
    """Convert selected text in Windows Terminal.

    User must select text first (double-click on word), then press hotkey.
    """
    VK_BACKSPACE = 0x08
    VK_C = 0x43

    time.sleep(0.1)

    # Try to copy with Ctrl+Shift+C (terminal copy shortcut)
    clear_clipboard()
    VK_CONTROL = 0x11
    VK_SHIFT = 0x10
    send_two_modifier_combo(VK_CONTROL, VK_SHIFT, VK_C)
    time.sleep(0.2)

    word = get_clipboard_text()

    if not word:
        return False

    word = word.strip()
    if not word:
        return False

    # Detect layout and convert
    source_layout = detect_layout(word)
    converted = convert_text(word)

    if converted == word:
        return False

    target_layout = 'ru' if source_layout == 'en' else 'en'

    # Press End to ensure cursor is at end of line
    VK_END = 0x23
    send_key_press(VK_END)
    time.sleep(0.03)

    # Delete the old word with backspaces
    for _ in range(len(word)):
        send_key_press(VK_BACKSPACE)
        time.sleep(0.01)

    time.sleep(0.05)

    # Type the converted text
    type_text(converted)

    # Switch layout
    time.sleep(0.05)
    switch_keyboard_layout(target_layout)
    return True


def convert_in_console(hwnd):
    """Convert last word in classic console using buffer reading."""
    VK_BACKSPACE = 0x08

    # Small delay
    time.sleep(0.1)

    # Try to read last word from console buffer
    word = get_console_last_word(hwnd)

    if not word:
        return False

    # Detect layout and convert
    source_layout = detect_layout(word)
    converted = convert_text(word)

    if converted == word:
        return False

    target_layout = 'ru' if source_layout == 'en' else 'en'

    # Delete the word with backspaces
    for _ in range(len(word)):
        send_key_press(VK_BACKSPACE)
        time.sleep(0.01)

    time.sleep(0.05)

    # Type the converted text
    type_text(converted)

    # Switch layout
    time.sleep(0.05)
    switch_keyboard_layout(target_layout)
    return True


def select_to_space_boundary():
    """Select backwards to space boundary, including punctuation.

    Strategy:
    1. Select word with Ctrl+Shift+Left
    2. Peek one char left - if it's punctuation, continue selecting
    3. If it's space/newline, we're done
    """
    VK_CONTROL = 0x11
    VK_SHIFT = 0x10
    VK_LEFT = 0x25
    VK_RIGHT = 0x27
    VK_INSERT = 0x2D

    # Punctuation that can "glue" words together (typed in wrong layout)
    GLUE_PUNCTUATION = set(';,.\'"[]{}/<>?!@#$%^&*()-_=+`~')

    clear_clipboard()
    max_iterations = 10

    for _ in range(max_iterations):
        # Select word with Ctrl+Shift+Left
        send_two_modifier_combo(VK_CONTROL, VK_SHIFT, VK_LEFT)
        time.sleep(0.03)

        # Copy selection
        send_ctrl_key(VK_INSERT)
        time.sleep(0.05)

        text = get_clipboard_text()
        if not text:
            return None

        # Peek one more character to the left
        send_key_combo(VK_SHIFT, VK_LEFT)
        time.sleep(0.02)

        send_ctrl_key(VK_INSERT)
        time.sleep(0.03)

        peeked = get_clipboard_text()

        if not peeked or len(peeked) == len(text):
            # Couldn't extend - we're at the beginning
            # Use lstrip to preserve trailing spaces
            return text.lstrip() if text else None

        first_char = peeked[0]

        if first_char in GLUE_PUNCTUATION:
            # Punctuation found - continue selecting (keep the extended selection)
            continue
        else:
            # Space or letter - undo the peek (deselect one char)
            send_key_combo(VK_SHIFT, VK_RIGHT)
            time.sleep(0.02)
            # Use lstrip to preserve trailing spaces
            return text.lstrip() if text else None

    # Safety: return whatever we have
    text = get_clipboard_text()
    # Use lstrip to preserve trailing spaces
    return text.lstrip() if text else None


def convert_selected_text():
    """Copy selected text, convert it, and paste back."""
    global _conversion_in_progress

    # Prevent multiple simultaneous conversions
    if not _conversion_lock.acquire(blocking=False):
        return False

    if _conversion_in_progress:
        _conversion_lock.release()
        return False

    _conversion_in_progress = True

    # Save current clipboard contents to restore later
    saved_clipboard = get_clipboard_text()

    try:
        hwnd = get_foreground_hwnd()

        # Handle console windows differently
        if is_console_window(hwnd):
            if is_classic_console(hwnd):
                return convert_in_console(hwnd)
            else:
                return convert_in_terminal(hwnd)

        # Regular application mode
        VK_INSERT = 0x2D

        # Small delay to ensure modifiers from hotkey are released
        time.sleep(0.05)

        # Clear clipboard first to detect if anything gets copied
        clear_clipboard()

        # Send Ctrl+X to cut selection (copies and deletes in one step)
        VK_X = 0x58
        send_ctrl_key(VK_X)
        time.sleep(0.08)  # Wait for cut to complete

        # Get cut text from clipboard
        selected_text = get_clipboard_text()

        # If nothing was selected/cut, select backwards to space boundary
        if not selected_text:
            selected_text = select_to_space_boundary()

            if selected_text:
                # Delete selected text with backspaces
                text_length = len(selected_text)
                VK_BACKSPACE = 0x08
                for _ in range(text_length):
                    send_key_press(VK_BACKSPACE)
                    time.sleep(0.005)
                time.sleep(0.05)

        if not selected_text:
            return False

        # Detect source layout and convert
        source_layout = detect_layout(selected_text)
        converted = convert_text(selected_text)

        if converted == selected_text:
            return False

        target_layout = 'ru' if source_layout == 'en' else 'en'

        # Put converted text to clipboard and paste
        set_clipboard_text(converted)
        VK_V = 0x56
        send_ctrl_key(VK_V)

        # Switch keyboard layout
        time.sleep(0.02)
        switch_keyboard_layout(target_layout)
        return True
    except Exception as e:
        log_error(f"convert_selected_text: EXCEPTION {e}")
        return False
    finally:
        # Restore original clipboard contents
        time.sleep(0.05)
        if saved_clipboard is not None:
            set_clipboard_text(saved_clipboard)
        else:
            clear_clipboard()
        _conversion_in_progress = False
        _conversion_lock.release()


class BorderLayer:
    """A single layer of the gradient border."""

    def __init__(self, master, x, y, w, h, color, alpha):
        self.window = None
        self.canvas = None
        self.base_alpha = alpha
        self.color = color          # last color applied to the canvas
        self._applied_alpha = alpha  # last alpha applied to the window

        try:
            self.window = tk.Toplevel(master)
            self.window.withdraw()
            self.window.overrideredirect(True)
            self.window.attributes('-topmost', True)
            self.window.attributes('-alpha', alpha)

            self.window.geometry(f'{w}x{h}+{x}+{y}')

            self.canvas = tk.Canvas(self.window, width=w, height=h,
                                   highlightthickness=0, bg=color)
            self.canvas.pack(fill='both', expand=True)

            self.window.deiconify()
            self._make_click_through()
        except Exception as e:
            log_error(f"BorderLayer.__init__ error: {e}")

    def _make_click_through(self):
        if not self.window:
            return
        try:
            self.window.update()
            hwnd = int(self.window.wm_frame(), 16)

            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x80000
            WS_EX_TRANSPARENT = 0x20
            WS_EX_TOOLWINDOW = 0x80
            WS_EX_NOACTIVATE = 0x08000000

            try:
                set_window_long = user32.SetWindowLongPtrW
            except AttributeError:
                set_window_long = user32.SetWindowLongW

            try:
                get_window_long = user32.GetWindowLongPtrW
            except AttributeError:
                get_window_long = user32.GetWindowLongW

            styles = get_window_long(hwnd, GWL_EXSTYLE)
            styles |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
            set_window_long(hwnd, GWL_EXSTYLE, styles)
        except Exception as e:
            print(f"Warning: Failed to make window click-through: {e}")

    def set_color(self, color):
        if not self.canvas:
            return
        try:
            self.canvas.configure(bg=color)
            self.color = color
        except (tk.TclError, RuntimeError):
            pass  # Window may be destroyed

    def set_alpha(self, alpha):
        if not self.window:
            return
        try:
            self.window.attributes('-alpha', alpha)
            self._applied_alpha = alpha
        except (tk.TclError, RuntimeError):
            pass  # Window may be destroyed

    def is_alive(self):
        """True if the underlying tk window/canvas still exist."""
        try:
            return bool(self.window) and bool(self.window.winfo_exists()) and \
                   bool(self.canvas) and bool(self.canvas.winfo_exists())
        except (tk.TclError, RuntimeError):
            return False

    def reassert_topmost(self):
        """Re-apply always-on-top so the border can't get stuck behind a
        window that briefly stole the top z-order."""
        if not self.window:
            return
        try:
            self.window.attributes('-topmost', True)
        except (tk.TclError, RuntimeError):
            pass

    def enforce(self, color, visible):
        """Idempotently re-assert desired color/alpha/topmost (self-healing).

        Only issues a tk call when the value actually drifted, so this is cheap
        to run on every watchdog tick.
        """
        if not self.window:
            return
        target_alpha = self.base_alpha if visible else 0.0
        if color != self.color:
            self.set_color(color)
        if abs(self._applied_alpha - target_alpha) > 1e-3:
            self.set_alpha(target_alpha)
        self.reassert_topmost()

    def destroy(self):
        if not self.window:
            return
        try:
            self.window.destroy()
        except (tk.TclError, RuntimeError):
            pass  # Already destroyed
        self.window = None
        self.canvas = None


class BorderWindow:
    """A gradient border made of multiple layers with varying opacity."""

    def __init__(self, master, edge, color, work_area):
        self.edge = edge
        self.layers = []

        # Work area for this monitor
        work_left, work_top, work_right, work_bottom = work_area
        work_w = work_right - work_left
        work_h = work_bottom - work_top

        # Create layers with gradient opacity (outer to inner)
        for i in range(BORDER_THICKNESS):
            # Calculate position for this layer
            if edge == 'top':
                x, y, w, h = work_left, work_top + i, work_w, 1
                t = i / max(1, BORDER_THICKNESS - 1)  # 0=outer (top), 1=inner
            elif edge == 'bottom':
                x, y, w, h = work_left, work_bottom - BORDER_THICKNESS + i, work_w, 1
                t = 1 - i / max(1, BORDER_THICKNESS - 1)  # 0=inner, 1=outer (bottom)
            elif edge == 'left':
                x, y, w, h = work_left + i, work_top, 1, work_h
                t = i / max(1, BORDER_THICKNESS - 1)  # 0=outer (left), 1=inner
            elif edge == 'right':
                x, y, w, h = work_right - BORDER_THICKNESS + i, work_top, 1, work_h
                t = 1 - i / max(1, BORDER_THICKNESS - 1)  # 0=inner, 1=outer (right)

            # Opacity: outer edge = OUTER, inner edge = INNER
            alpha = BORDER_OPACITY_OUTER + t * (BORDER_OPACITY_INNER - BORDER_OPACITY_OUTER)

            layer = BorderLayer(master, x, y, w, h, color, alpha)
            self.layers.append(layer)

    def set_color(self, color):
        for layer in self.layers:
            layer.set_color(color)

    def set_visible(self, visible):
        """Toggle visibility of all layers."""
        for layer in self.layers:
            alpha = layer.base_alpha if visible else 0.0
            layer.set_alpha(alpha)

    def is_alive(self):
        """True only if every layer window still exists."""
        return bool(self.layers) and all(layer.is_alive() for layer in self.layers)

    def enforce(self, color, visible):
        """Re-assert desired state on all layers (self-healing watchdog)."""
        for layer in self.layers:
            layer.enforce(color, visible)

    def destroy(self):
        for layer in self.layers:
            layer.destroy()


class LayoutIndicator:
    """Main application with Tkinter event loop."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()  # Hide main window

        self.borders = []  # List of BorderWindow objects
        self.current_color = None
        self.current_name = None
        self.running = True
        self.tray_icon = None
        self.borders_visible = True
        # Runtime on/off for text conversion (toggled from the tray menu).
        # The hotkey thread still runs; this just gates whether a hotkey
        # actually performs a conversion.
        self.conversion_enabled = ENABLE_TEXT_CONVERSION
        self.fullscreen_hidden = False  # Track if hidden due to fullscreen
        self.current_monitors = None  # Track monitor configuration
        self.hotkey_registered = False
        self.hotkey_thread = None
        self._pending_actions = []  # Thread-safe action queue
        self._borders_lock = threading.Lock()  # Protect borders list
        self._last_logged_hwnd = None  # For debugging window switches
        self._monitor_check_counter = 0  # Only check monitors every N cycles
        self._watchdog_counter = 0  # Re-assert border state every N cycles
        self._resource_log_counter = 0  # Log handle/GDI/USER counts every N cycles
        self._resource_baseline = None  # First (handles, gdi, user) sample

        # Create borders for all monitors
        self._create_borders()

        # Record a resource-count baseline so periodic samples show real growth
        self._log_resource_counts()

        # Start layout checking
        self._check_layout()

        # Start processing pending actions from other threads
        self._process_pending_actions()

        # Setup system tray if available
        if HAS_TRAY:
            self._setup_tray()

        # Setup hotkey for text conversion
        if ENABLE_TEXT_CONVERSION:
            self._setup_hotkey()

    def _schedule_action(self, action):
        """Schedule an action to run on the main tkinter thread."""
        self._pending_actions.append(action)

    def _process_pending_actions(self):
        """Process pending actions from other threads (runs on main thread)."""
        if not self.running:
            return

        while self._pending_actions:
            try:
                action = self._pending_actions.pop(0)
                action()
            except Exception as e:
                print(f"Error in pending action: {e}")

        self.root.after(50, self._process_pending_actions)

    def _create_borders(self):
        """Create border windows for all monitors."""
        with self._borders_lock:
            self._create_borders_locked()

    def _create_borders_locked(self):
        """Create border windows for all monitors. Caller must hold _borders_lock."""
        # Destroy existing borders
        for border in self.borders:
            try:
                border.destroy()
            except Exception as e:
                print(f"Error destroying border: {e}")
        self.borders = []

        # Determine which edges to show
        edges = ['top', 'bottom', 'left', 'right'] if SHOW_ALL_EDGES else ['bottom']

        # Get all monitors and create borders for each
        self.current_monitors = get_all_monitors()
        print(f"Found {len(self.current_monitors)} monitor(s)")

        color = self.current_color or DEFAULT_COLOR[0]
        for work_area in self.current_monitors:
            for edge in edges:
                try:
                    border = BorderWindow(self.root, edge, color, work_area)
                    # Respect current visibility state
                    if not self.borders_visible or self.fullscreen_hidden:
                        border.set_visible(False)
                    self.borders.append(border)
                except Exception as e:
                    print(f"Error creating border {edge}: {e}")

    def _enforce_border_state(self):
        """Watchdog: re-assert the desired border state every tick so the
        indicator self-heals.

        The rest of _check_layout is edge-triggered (it only acts when the
        layout/fullscreen state *changes*), and every tk failure is swallowed.
        That means a single missed/failed update — during a resource-pressure
        blip, a transient TclError, a missed fullscreen-exit, or a monitor
        flap — would otherwise leave the border stuck (invisible / wrong color
        / behind another window) until the app is restarted. Re-asserting the
        level state here recovers automatically once the transient passes.
        """
        desired_visible = self.borders_visible and not self.fullscreen_hidden
        color = self.current_color or DEFAULT_COLOR[0]
        with self._borders_lock:
            # If any border window was destroyed/lost, rebuild the whole set.
            if not self.borders or any(not b.is_alive() for b in self.borders):
                log_error("Watchdog: border window(s) missing, recreating")
                self._create_borders_locked()
                return
            for border in self.borders:
                try:
                    border.enforce(color, desired_visible)
                except Exception:
                    pass

    def _log_resource_counts(self):
        """Periodically log handle/GDI/USER counts to spot the slow leak."""
        handles, gdi, usr = get_resource_counts()
        if handles is None:
            return
        if self._resource_baseline is None:
            self._resource_baseline = (handles, gdi, usr)
        b = self._resource_baseline
        log_error(
            f"[RES] handles={handles} gdi={gdi} user={usr} "
            f"(delta since start: handles={handles - b[0]:+d} "
            f"gdi={gdi - b[1]:+d} user={usr - b[2]:+d})"
        )
    
    def _check_layout(self):
        """Periodically check keyboard layout."""
        if not self.running:
            return

        try:
            # Check if monitor configuration changed (every ~5 seconds, not every 150ms)
            self._monitor_check_counter += 1
            if self._monitor_check_counter >= 33:  # 33 * 150ms ≈ 5 seconds
                self._monitor_check_counter = 0
                monitors = get_all_monitors()
                if monitors != self.current_monitors:
                    print("Monitor configuration changed, recreating borders...")
                    self._create_borders()

            hwnd = get_foreground_hwnd()

            # Get window class (reuse buffer to avoid allocations every 150ms)
            current_class = get_window_class(hwnd) if is_valid_hwnd(hwnd) else ""

            # Skip fullscreen check for WPF apps (HwndWrapper) - may cause issues
            if "HwndWrapper" in current_class:
                fullscreen = False
            else:
                fullscreen = is_fullscreen(hwnd)

            color, name = get_keyboard_layout_for_hwnd(hwnd)

            # Hide borders in fullscreen apps
            with self._borders_lock:
                if fullscreen and not self.fullscreen_hidden:
                    self.fullscreen_hidden = True
                    for border in self.borders:
                        try:
                            border.set_visible(False)
                        except Exception:
                            pass
                elif not fullscreen and self.fullscreen_hidden:
                    self.fullscreen_hidden = False
                    if self.borders_visible:  # Respect manual toggle
                        for border in self.borders:
                            try:
                                border.set_visible(True)
                            except Exception:
                                pass

                if color != self.current_color:
                    self.current_color = color
                    self.current_name = name

                    for border in self.borders:
                        try:
                            border.set_color(color)
                        except Exception:
                            pass

                    # Update tray icon color
                    if self.tray_icon and HAS_TRAY:
                        self._update_tray_icon(color, name)

            # Watchdog: re-assert the desired border state so a single missed
            # update can't leave the border stuck until restart (~1s cadence).
            self._watchdog_counter += 1
            if self._watchdog_counter >= 7:  # 7 * 150ms ≈ 1 second
                self._watchdog_counter = 0
                self._enforce_border_state()

            # Periodically log resource counts to catch the slow handle leak.
            self._resource_log_counter += 1
            if self._resource_log_counter >= 2000:  # 2000 * 150ms ≈ 5 minutes
                self._resource_log_counter = 0
                self._log_resource_counts()
        except Exception as e:
            log_error(f"Error in _check_layout: {e}")

        self.root.after(CHECK_INTERVAL_MS, self._check_layout)

    def _setup_hotkey(self):
        """Setup global hotkeys for text conversion."""
        def hotkey_thread_func():
            # Create a message-only window for receiving hotkey messages
            # We need to register hotkey in the same thread that will process messages

            registered_hotkeys = []

            # Install keyboard hook to read scan codes (no swallow -> dead keys
            # safe). Lets us tell the settings button apart from Fn-lock/numpad.
            # Kept in a dict so the periodic self-heal below (and the filter
            # closure) always see the current handle.
            _hook_state = {'handle': install_kbd_hook()}
            if not _hook_state['handle']:
                log_error("settings-key scan-code filter disabled "
                          "(hook install failed)")

            # Register Pause/Break key
            if user32.RegisterHotKey(None, HOTKEY_ID_PAUSE, MOD_NOREPEAT, VK_PAUSE):
                registered_hotkeys.append(('Pause/Break', HOTKEY_ID_PAUSE))
            else:
                print("Warning: Failed to register Pause/Break hotkey")

            # Register Settings key (VK 0xFF - Redmi Book and similar)
            if user32.RegisterHotKey(None, HOTKEY_ID_SETTINGS, MOD_NOREPEAT, VK_SETTINGS):
                registered_hotkeys.append(('Settings key', HOTKEY_ID_SETTINGS))
            else:
                print("Warning: Failed to register Settings key hotkey")

            if not registered_hotkeys:
                print("No hotkeys registered - text conversion disabled")
                return

            self.hotkey_registered = True
            hotkey_names = ' or '.join(name for name, _ in registered_hotkeys)
            print(f"Hotkey registered: {hotkey_names} (convert selected text)")

            # Message structure
            class MSG(ctypes.Structure):
                _fields_ = [
                    ('hwnd', wintypes.HWND),
                    ('message', wintypes.UINT),
                    ('wParam', wintypes.WPARAM),
                    ('lParam', wintypes.LPARAM),
                    ('time', wintypes.DWORD),
                    ('pt', wintypes.POINT),
                ]

            msg = MSG()
            hotkey_ids = {hid for _, hid in registered_hotkeys}

            def is_false_settings_trigger():
                """True if the VK_SETTINGS hotkey came from a key other than the
                dedicated settings button (Fn-lock, numpad nav, etc.).

                The keyboard hook records the scan code (and time) of the last
                VK 0xFF keydown; only SETTINGS_SCANCODE is the real button.

                Fail-safe rules so a stale value can't cause false triggers:
                - The scan must be FRESH (recorded within SETTINGS_SCAN_FRESH_SEC).
                  A genuine press records the scan just before its WM_HOTKEY; a
                  stale value means the hook didn't see this keypress (e.g.
                  Windows silently dropped the hook), so we must NOT trust it.
                - The value is CONSUMED after reading, so it can never authorize
                  a second, different keypress.
                - If the hook isn't installed at all (scan permanently unknown),
                  don't filter — preserve the key's functionality.
                """
                global _last_settings_scan
                if not _hook_state['handle']:
                    return False  # no hook -> can't filter, allow
                scan = _last_settings_scan
                age = time.time() - _last_settings_scan_time
                _last_settings_scan = None  # consume so it can't be reused
                if scan is None or age > SETTINGS_SCAN_FRESH_SEC:
                    return True  # stale/missing -> treat as false trigger
                return scan != SETTINGS_SCANCODE

            # Message loop. Each iteration is wrapped so a transient OSError
            # (e.g. WinError 1450 under resource pressure) can't kill the
            # thread and permanently disable text conversion.
            PM_REMOVE = 0x0001
            reinstall_counter = 0
            while self.running:
                try:
                    # Block up to 100ms for input/messages instead of busy-polling.
                    # Wakes immediately on WM_HOTKEY (QS_HOTKEY ⊂ QS_ALLINPUT);
                    # the 100ms timeout lets us re-check self.running for shutdown.
                    user32.MsgWaitForMultipleObjectsEx(
                        0, None, 100, QS_ALLINPUT, MWMO_INPUTAVAILABLE
                    )

                    # Self-heal: Windows silently removes a low-level hook whose
                    # callback ever exceeds LowLevelHooksTimeout (can happen when
                    # the GIL is held during a conversion). There's no event for
                    # this, so periodically reinstall. Install the new hook first,
                    # then drop the old handle, so we're never left without one.
                    reinstall_counter += 1
                    if reinstall_counter >= 50:  # ~50 * 100ms ≈ 5 seconds
                        reinstall_counter = 0
                        new_hook = install_kbd_hook()
                        if new_hook:
                            old_hook = _hook_state['handle']
                            _hook_state['handle'] = new_hook
                            if old_hook:
                                try:
                                    user32.UnhookWindowsHookEx(old_hook)
                                except Exception:
                                    pass

                    while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                        if msg.message == WM_HOTKEY and msg.wParam in hotkey_ids:
                            # Respect the runtime menu toggle.
                            if not self.conversion_enabled:
                                continue
                            # VK_SETTINGS (0xFF) fires for several keys — only the
                            # real settings button (by scan code) should convert.
                            if msg.wParam == HOTKEY_ID_SETTINGS and is_false_settings_trigger():
                                continue
                            # Run conversion in a thread so it can't block the loop
                            threading.Thread(target=convert_selected_text, daemon=True).start()
                except Exception as e:
                    log_error(f"hotkey loop iteration error: {e}")
                    # Back off briefly without dying; tolerate sleep also failing.
                    try:
                        time.sleep(0.1)
                    except Exception:
                        pass

            # Unregister hotkeys when done
            for _, hid in registered_hotkeys:
                user32.UnregisterHotKey(None, hid)

            # Remove keyboard hook
            if _hook_state['handle']:
                try:
                    user32.UnhookWindowsHookEx(_hook_state['handle'])
                except Exception:
                    pass

        self.hotkey_thread = threading.Thread(target=hotkey_thread_func, daemon=True)
        self.hotkey_thread.start()

    _tray_image_cache = {}

    def _create_tray_image(self, color):
        """Create a colored square icon for the tray (cached by color)."""
        if color in self._tray_image_cache:
            return self._tray_image_cache[color]
        size = 64
        image = Image.new('RGB', (size, size), color)
        draw = ImageDraw.Draw(image)
        # Add a slight border
        draw.rectangle([0, 0, size-1, size-1], outline='#2c3e50', width=2)
        self._tray_image_cache[color] = image
        return image
    
    def _setup_tray(self):
        """Setup system tray icon."""
        def on_quit(icon, item):
            # Schedule quit on main thread to avoid tkinter threading issues
            def do_quit():
                self.running = False
                try:
                    icon.stop()
                except Exception:
                    pass
                try:
                    self.root.quit()
                except Exception:
                    pass
            self._schedule_action(do_quit)

        def toggle_borders(icon, item):
            # Schedule toggle on main thread to avoid tkinter threading issues
            def do_toggle():
                self.borders_visible = not self.borders_visible
                # Only actually toggle if not hidden due to fullscreen
                if not self.fullscreen_hidden:
                    with self._borders_lock:
                        for border in self.borders:
                            try:
                                border.set_visible(self.borders_visible)
                            except Exception:
                                pass
            self._schedule_action(do_toggle)

        def toggle_conversion(icon, item):
            # Flip the runtime flag. Read by the hotkey loop before converting.
            self.conversion_enabled = not self.conversion_enabled

        menu_items = [pystray.MenuItem('Toggle Borders', toggle_borders)]

        # Only offer the conversion switch if the feature is enabled in config
        # (otherwise the hotkey thread isn't running and the toggle is a no-op).
        if ENABLE_TEXT_CONVERSION:
            menu_items.append(pystray.MenuItem(
                'Enable Text Conversion',
                toggle_conversion,
                checked=lambda item: self.conversion_enabled
            ))

        menu_items.append(pystray.MenuItem('Exit', on_quit))
        menu = pystray.Menu(*menu_items)

        image = self._create_tray_image(self.current_color or DEFAULT_COLOR[0])
        self.tray_icon = pystray.Icon(
            'layout_indicator',
            image,
            f'Layout: {self.current_name or "?"}',
            menu
        )

        # Run tray in separate thread
        tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        tray_thread.start()
    
    def _update_tray_icon(self, color, name):
        """Update tray icon with new color."""
        if self.tray_icon:
            try:
                self.tray_icon.icon = self._create_tray_image(color)
                self.tray_icon.title = f'Layout: {name}'
            except Exception:
                pass  # Tray icon may be stopping
    
    def run(self):
        """Start the main loop."""
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            pass
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Clean up resources."""
        self.running = False
        with self._borders_lock:
            for border in self.borders:
                try:
                    border.destroy()
                except Exception:
                    pass
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass


def main():
    if sys.platform != 'win32':
        print("This script only works on Windows!")
        sys.exit(1)

    print("Layout Indicator Started")
    print(f"Border: {BORDER_THICKNESS}px, Opacity gradient: {BORDER_OPACITY_OUTER} -> {BORDER_OPACITY_INNER}")
    if ENABLE_TEXT_CONVERSION:
        print("Text conversion: Pause/Break or Settings key (select text first)")
    print("Right-click tray icon to exit" if HAS_TRAY else "Press Ctrl+C to exit")

    try:
        app = LayoutIndicator()
        app.run()
    except Exception as e:
        log_error(f"FATAL ERROR in main: {e}\n{traceback.format_exc()}")
        raise


if __name__ == '__main__':
    main()
