"""
ThorCNC entry point.

Usage:
    thorcnc [--ini INI_FILE] [--theme THEME]
    thorcnc -h | --help

Options:
    --ini INI_FILE   Path to LinuxCNC INI file (default: $INI_FILE_NAME)
    --theme THEME    Theme name: dark | light | dark_green | dark_orange
                     [default: dark]
"""
import os
import sys
import argparse

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from .mainwindow import ThorCNC

_DIR = os.path.dirname(__file__)
THEMES_DIR = os.path.join(_DIR, "themes")


def load_theme(app: QApplication, name: str):
    qss_file = os.path.join(THEMES_DIR, f"{name}.qss")
    if not os.path.isfile(qss_file):
        print(f"[ThorCNC] Theme '{name}' nicht gefunden, verwende 'dark'")
        qss_file = os.path.join(THEMES_DIR, "dark.qss")
    with open(qss_file, "r") as f:
        app.setStyleSheet(f.read())


def main():
    parser = argparse.ArgumentParser(description="ThorCNC – LinuxCNC VCP")
    parser.add_argument("--ini",   default="", help="Pfad zur INI-Datei")
    parser.add_argument("--theme", default="",
                        choices=["dark", "light", "dark_green", "dark_orange", ""],
                        help="UI-Theme")
    # parse_known_args: LinuxCNC übergibt ggf. extra Argumente (z.B. -ini, Pfad),
    # die wir ignorieren – INI_FILE_NAME aus der Umgebung reicht.
    args, _ = parser.parse_known_args()

    # Theme: CLI > Env > INI-Datei > Fallback "dark"
    ini_path = args.ini or os.environ.get("INI_FILE_NAME", "")
    theme = (args.theme
             or os.environ.get("THORCNC_THEME", "")
             or _theme_from_ini(ini_path)
             or "dark")

    app = QApplication.instance() or QApplication(sys.argv)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    load_theme(app, theme)

    win = ThorCNC(ini_path=ini_path)
    win.show()
    win.start()

    sys.exit(app.exec())


def _theme_from_ini(ini_path: str) -> str:
    """Liest optionales THEME aus [DISPLAY] in der INI-Datei."""
    if not ini_path or not os.path.isfile(ini_path):
        return ""
    try:
        import linuxcnc
        ini = linuxcnc.ini(ini_path)
        return ini.find("DISPLAY", "THEME") or ""
    except Exception:
        return ""


if __name__ == "__main__":
    main()
