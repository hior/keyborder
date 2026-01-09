# Keyboard Layout Border Indicator

## Overview

Simple Windows utility that shows a colored border around the screen based on the current keyboard layout. **Does NOT use keyboard hooks** — won't break dead keys for US International and other layouts with diacritics.

Also includes text conversion feature (like Punto Switcher) via `Pause/Break` key — converts selected text between EN↔RU layouts and switches keyboard layout. Uses `RegisterHotKey` (not a keyboard hook).

## Main file

`layout_indicator_tray.py` — version with system tray icon.

## Dependencies

```
pip install pystray pillow
```

## Running

```bash
pythonw layout_indicator_tray.py  # no console window
python layout_indicator_tray.py   # with console for debugging
```

## Current layout configuration

HKL values obtained from user's machine:

```python
KLID_COLORS = {
    0xF0010409: ('#8B008B', 'US-Intl'),    # US International - purple
    0x04090409: ('#00CED1', 'US'),          # US standard - cyan
    0x04190419: ('#DC143C', 'RU'),          # Russian - red
}
```

Border appearance:

```python
BORDER_THICKNESS = 6         # Border width in pixels
BORDER_OPACITY_OUTER = 0.8   # Opacity at outer edge (screen edge)
BORDER_OPACITY_INNER = 0.05  # Opacity at inner edge (fades inward)
```

## Architecture

- `get_keyboard_layout()` — gets HKL of active layout via `GetKeyboardLayout()` for foreground window
- `get_all_monitors()` — enumerates all monitors via `EnumDisplayMonitors` + `GetMonitorInfo`
- `BorderLayer` — single 1px tkinter window with specific opacity (one layer of gradient)
- `BorderWindow` — manages multiple `BorderLayer` objects to create gradient effect for one edge
- `LayoutIndicator` — main class, creates borders for all monitors + tray icon
- Layout check every 150ms via `root.after()`

## Key features

1. **Multi-monitor support** — border is drawn on all connected monitors, each with its own work area

2. **Gradient opacity** — border fades from outer edge (0.8) to inner edge (0.05), created by stacking multiple 1px layers with different alpha values

3. **Respects work area** — border is drawn within work area bounds (excluding taskbar) via `GetMonitorInfo(rcWork)`

4. **Click-through windows** — uses styles `WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE`

5. **Tray icon** — changes color with the border, right-click for menu (Toggle Borders / Exit)

6. **Text conversion** (`Pause/Break` key) — converts selected text between EN↔RU layouts:
   - Select text in any application (or place cursor after a word)
   - Press `Pause/Break`
   - If text is selected: copies, converts, pastes back
   - If nothing selected: automatically selects last word (Ctrl+Shift+Left), then converts
   - Auto-detects source layout (predominantly EN or RU characters)
   - Switches keyboard layout after conversion (EN→RU or RU→EN)
   - Uses `RegisterHotKey` API (not a keyboard hook) — doesn't interfere with dead keys
   - **Note:** Disabled in terminal windows (cmd, PowerShell, Windows Terminal)

## Text conversion configuration

```python
ENABLE_TEXT_CONVERSION = True  # Set to False to disable

# Hotkey
VK_PAUSE = 0x13  # Pause/Break key

# Target layouts for switching after conversion
HKL_EN = 0x04090409  # US standard (change to 0xF0010409 for US-Intl)
HKL_RU = 0x04190419  # Russian

# Character mapping (QWERTY ↔ ЙЦУКЕН)
EN_CHARS = r"""`qwertyuiop[]asdfghjkl;'zxcvbnm,./~QWERTYUIOP{}ASDFGHJKL:"ZXCVBNM<>?@#$^&"""
RU_CHARS = r"""ёйцукенгшщзхъфывапролджэячсмитьбю.ЁЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮ,"№;:?"""
```

## Known issues / TODO

- [ ] **Click-through may not work** — latest fix uses `wm_frame()` to get HWND, needs verification
- [ ] Add Windows autostart (shortcut in `shell:startup`)
- [ ] Border doesn't recalculate on monitor/taskbar changes (requires restart)

## Debugging

To view HKL values for layouts, add to `get_keyboard_layout()`:
```python
print(f"HKL: 0x{hkl_value:08X}")
```

## Autostart

Create `start_indicator.bat`:
```bat
@echo off
cd /d "%~dp0"
start "" pythonw layout_indicator_tray.py
```

Place a shortcut to this bat file in `shell:startup` (Win+R → `shell:startup`).
