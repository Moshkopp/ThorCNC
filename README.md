# ThorCNC

> [!CAUTION]
> **PRE-PRE-PRE-ALPHA VERSION — WORK IN PROGRESS**
>
> This project is a **pre-pre-pre-alpha** version and **not intended for productive or machine use** on real CNC machines. 
> 
> **Use at your own risk.** The author takes no responsibility for any damage to hardware, software, or persons. This software should currently be used **only in simulation (Sim) for testing and experimentation**.

---

A modern LinuxCNC graphical interface (VCP) for 3-axis milling machines, built with PySide6 and no additional framework overhead.

![License](https://img.shields.io/badge/license-GPL--2.0--or--later-blue)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![LinuxCNC](https://img.shields.io/badge/LinuxCNC-2.9%2B-orange)

---

![ThorCNC Screenshot](thorcnc/images/screen_main.png)
![Tool Change Dialog](thorcnc/images/screen_toolchange.png)

---

## Features

- **Industrial M6 Dialog** — Premium, touch-optimized manual tool change interface with automatic tool data lookup (Comment, Diameter, Offset).
- **Smart Spindle Load** — Real-time load bar with dynamic color feedback (Green: 0-60%, Yellow: 60-80%, Red: >80%).
- **3D Backplot** — OpenGL-accelerated toolpath visualization via pyqtgraph, with real-time tool position, live trail, and machine envelope display.
  - View presets: ISO, TOP, FRONT, SIDE
  - Clear trail button in toolbar
  - Mouse: left drag = orbit, middle drag = pan, Ctrl+middle drag = zoom
- **GO TO HOME** — Toolbar button with color feedback: red = not homed / machine off, green = homed + machine on, gray = AUTO mode.
- **Machine Mode** — Combobox in the left panel to switch between MANUAL / AUTO / MDI.
- **G-Code / MDI Panel** — Toggle between G-code viewer and MDI input with persistent command history.
- **DRO** — Digital readout for work (G54–G59.3) and machine coordinates, with per-axis zero and reference buttons.
- **OFFSETS Tab** — Full WCS table (G54–G59.3) with X/Y/Z values read live from the `.var` file.
- **Tool Table** — Editable tool table with diameter and length, live-updated after M6 tool changes.
- **M6 Remap Support** — Full integration with custom NGC measurement routines and ThorCNC's own manual fallback dialog.
- **Spindle Control** — Forward/reverse/stop, speed and override display, load indicator.
- **Jog Panel** — Continuous and incremental jog for X/Y/Z with configurable velocity and step sizes.
- **HAL Integration** — Reads and writes HAL pins directly; compatible with standard LinuxCNC HAL components.
- **INI-Driven Defaults** — Automatically synchronizes spindle start speeds, increments, and file paths.
- **Splash Screen** — Support for custom industrial startup graphics via `INTRO_GRAPHIC` and `INTRO_TIME`.
- **WCS Selector** — Quick switch between G54–G59.3 via dropdown in the DRO panel.
- **Settings** — Four sub-tabs: Toolsetter, UI (live theme + language switching), Maschine, Erweitert.
- **Themes** — Dark (default), light, dark_green, dark_orange — switchable at runtime.

---

## Requirements

| Dependency | Version |
|---|---|
| Python | ≥ 3.11 |
| LinuxCNC | ≥ 2.9 (with Python bindings) |
| PySide6 | ≥ 6.5 |
| pyqtgraph | ≥ 0.13 *(optional, for 3D backplot)* |
| PyOpenGL | ≥ 3.1 *(optional, for 3D backplot)* |

Supported distributions: **Debian 13 Trixie**, **Arch Linux**, **CachyOS**, **EndeavourOS**, **Manjaro**

---

## Installation

### Automatic (recommended)

```bash
git clone https://github.com/Moshkopp/thorcnc.git
cd thorcnc
./install.sh
```

For development (editable install — changes take effect immediately):

```bash
./install.sh --dev
```

Uninstall:

```bash
./install.sh --uninstall
```

### Update

Pull the latest changes and reinstall without deleting the folder:

```bash
./update.sh
```

In development mode:

```bash
./update.sh --dev
```

### Manual

```bash
pip install "PySide6>=6.5" pyqtgraph PyOpenGL
pip install .
```

---

## Usage

```bash
thorcnc --ini /path/to/machine.ini
```

With theme:

```bash
thorcnc --theme dark_green --ini /path/to/machine.ini
```

For development against the simulation config included in this repo:

```bash
linuxcnc configs/sim/thorcnc_sim.ini
```

---

## INI Configuration

ThorCNC is set as the display in your LinuxCNC INI file:

```ini
[DISPLAY]
DISPLAY = thorcnc
```

### Optional: M6 tool measurement remap

If you have a tool length sensor, you can enable automatic tool measurement on every tool change by adding the remap to `[RS274NGC]`:

```ini
[RS274NGC]
REMAP = M6 modalgroup=6 ngc=messe
SUBROUTINE_PATH = /path/to/subroutines
```

Without the remap, ThorCNC falls back to the standard `hal_manualtoolchange` dialog and reads tool geometry directly from the tool table.

---

## Project Structure

```
thorcnc/
├── main.py             # Entry point, argument parsing
├── mainwindow.py       # Main controller — connects UI to LinuxCNC
├── thorcnc.ui          # Qt Designer UI layout
├── status_poller.py    # QTimer-based LinuxCNC stat polling, emits Qt signals
├── gcode_parser.py     # Lightweight G-code parser for backplot preview
├── settings.py         # Persistent settings (JSON)
├── widgets/
│   ├── backplot.py     # 3D OpenGL backplot widget (pyqtgraph)
│   └── gcode_view.py   # Syntax-highlighted G-code viewer
configs/
└── sim/                # Ready-to-run simulation configuration
```

---

## Architecture

ThorCNC connects directly to LinuxCNC via the official Python bindings (`linuxcnc.stat`, `linuxcnc.command`, `linuxcnc.ini`) without any intermediate framework. A `QTimer`-based poller detects state changes and emits Qt signals, keeping the UI fully decoupled from the polling logic.

The backplot uses a `GLViewWidget` subclass (`_ThorGLView`) to implement custom mouse behaviour, and exposes a `toolbar_layout()` API so the main window can inject buttons directly into the widget — avoiding Qt's OpenGL context destruction that occurs when re-parenting a `QOpenGLWidget`.

---

## License

GPL-2.0-or-later — see [LICENSE](LICENSE)
