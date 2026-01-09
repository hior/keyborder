# Keyboard Layout Border Indicator

Windows utility that shows a colored border around the screen based on the current keyboard layout. Includes Punto Switcher-like text conversion.

**No keyboard hooks** — safe for US International and other layouts with dead keys.

## Features

- **Colored screen border** — instantly see which keyboard layout is active
- **Multi-monitor support** — border appears on all connected monitors
- **Gradient effect** — border fades from edge inward for a subtle look
- **System tray icon** — colored icon matches current layout, right-click menu
- **Text conversion** (Pause/Break) — convert selected text between EN↔RU layouts
  - Works like Punto Switcher but without keyboard hooks
  - Auto-selects last word if nothing is selected
  - Automatically switches keyboard layout after conversion
- **Fullscreen-aware** — border hides in fullscreen apps

## Installation

### Requirements

- Windows 10/11
- Python 3.8+

### Setup

```bash
pip install pystray pillow
```

### Running

```bash
# Without console window (recommended)
pythonw layout_indicator_tray.py

# With console (for debugging)
python layout_indicator_tray.py
```

## Usage

### Border Indicator

The border color changes automatically when you switch keyboard layouts:

| Layout | Default Color |
|--------|---------------|
| US International | Purple |
| US Standard | Cyan |
| Russian | Red |

Right-click the tray icon to:
- Toggle border visibility
- Exit the application

### Text Conversion

1. Select text in any application (or just place cursor after a word)
2. Press `Pause/Break`
3. Text is converted and keyboard layout switches automatically

**Example:** Type `ghbdtn` (with EN layout) → press Pause → get `привет` (RU layout active)

**Terminal support:**
- **Windows Terminal:** Select text first (double-click on word), then press `Pause/Break`
- **Classic console (cmd):** Just press `Pause/Break` — reads last word from console buffer

## Configuration

Edit the top of `layout_indicator_tray.py`:

```python
# Colors by keyboard layout (HKL values)
KLID_COLORS = {
    0xF0010409: ('#8B008B', 'US-Intl'),  # Purple
    0x04090409: ('#00CED1', 'US'),        # Cyan
    0x04190419: ('#DC143C', 'RU'),        # Red
}

# Border appearance
BORDER_THICKNESS = 6         # Width in pixels
BORDER_OPACITY_OUTER = 0.8   # Opacity at screen edge
BORDER_OPACITY_INNER = 0.05  # Opacity at inner edge

# Text conversion
ENABLE_TEXT_CONVERSION = True
HKL_EN = 0x04090409  # Target EN layout after conversion
HKL_RU = 0x04190419  # Target RU layout after conversion
```

### Finding your HKL values

Add this to `get_keyboard_layout()` function to see HKL values for your layouts:

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

Place a shortcut to this file in `shell:startup` (Win+R → `shell:startup`).

## How it works

- Uses `GetKeyboardLayout()` Win32 API to detect current layout
- Creates transparent click-through windows using `WS_EX_LAYERED | WS_EX_TRANSPARENT`
- Text conversion uses `RegisterHotKey()` — not a keyboard hook, so it doesn't interfere with dead keys or other input methods
- Gradient effect achieved by stacking multiple 1px windows with varying opacity

## Why no keyboard hooks?

Many similar tools use low-level keyboard hooks (`SetWindowsHookEx`), which can:
- Break dead keys (like `'` + `e` = `é` in US International)
- Interfere with other input methods
- Cause input lag
- Trigger antivirus warnings

This tool uses only `RegisterHotKey()` for the conversion feature, which is a clean system API that doesn't intercept all keyboard input.

## License

MIT
