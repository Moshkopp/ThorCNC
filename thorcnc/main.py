"""
ThorCNC entry point.

Usage:
    thorcnc [--ini INI_FILE] [--theme THEME]
    thorcnc -h | --help

Options:
    --ini INI_FILE   Path to LinuxCNC INI file (default: $INI_FILE_NAME)
    --theme THEME    Theme name: dark | light
                     [default: dark]
"""
import os
import sys
import argparse

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QSurfaceFormat, QIcon

from .mainwindow import ThorCNC

_DIR = os.path.dirname(__file__)
THEMES_DIR = os.path.join(_DIR, "themes")


def load_theme(app: QApplication, name: str):
    import re
    qss_file = os.path.join(THEMES_DIR, f"{name}.qss")
    if not os.path.isfile(qss_file):
        print(f"[ThorCNC] Theme '{name}' nicht gefunden, verwende 'dark'")
        qss_file = os.path.join(THEMES_DIR, "dark.qss")
    
    with open(qss_file, "r") as f:
        content = f.read()
    
    # Einfache Auflösung von @import "file.qss";
    def _resolve(match):
        filename = match.group(1)
        path = os.path.join(THEMES_DIR, filename)
        if os.path.isfile(path):
            with open(path, "r") as f_imp:
                return f_imp.read()
        return f"/* Import failed: {filename} */"
    
    content = re.sub(r'@import\s+"([^"]+)";', _resolve, content)
    app.setStyleSheet(content)


def main():
    parser = argparse.ArgumentParser(description="ThorCNC – LinuxCNC VCP")
    parser.add_argument("--ini",   default="", help="Pfad zur INI-Datei")
    parser.add_argument("--theme", default="",
                        choices=["dark", "light", ""],
                        help="UI-Theme")
    # parse_known_args: LinuxCNC übergibt ggf. extra Argumente (z.B. -ini, Pfad),
    # die wir ignorieren – INI_FILE_NAME aus der Umgebung reicht.
    args, _ = parser.parse_known_args()

    # Theme: CLI > Env > Prefs-JSON > INI-Datei > Fallback "dark"
    ini_path = args.ini or os.environ.get("INI_FILE_NAME", "")

    # Anti-Aliasing (MSAA) Setting laden (muss VOR QApplication passieren!)
    msaa_samples = _get_msaa_setting(ini_path)
    if msaa_samples > 0:
        fmt = QSurfaceFormat()
        fmt.setSamples(msaa_samples)
        QSurfaceFormat.setDefaultFormat(fmt)

    theme = (args.theme
             or os.environ.get("THORCNC_THEME", "")
             or _theme_from_prefs(ini_path)
             or _theme_from_ini(ini_path)
             or "dark")

    # Konsistente HiDPI Skalierung erzwingen (MUSS vor QApplication passieren)
    if hasattr(Qt, "HighDpiScaleFactorRoundingPolicy"):
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    _icon_path = os.path.join(_DIR, "images", "icon.svg")
    if os.path.isfile(_icon_path):
        app.setWindowIcon(QIcon(_icon_path))

    os.environ.setdefault("THORCNC_THEME", theme)
    load_theme(app, theme)

    win = ThorCNC(ini_path=ini_path)
    win.show()
    win.start()

    sys.exit(app.exec())


def _theme_from_prefs(ini_path: str) -> str:
    """Liest das gespeicherte Theme aus der JSON-Prefs-Datei."""
    try:
        prefs_file = "thorcnc.prefs"
        ini_dir = os.path.dirname(ini_path) if ini_path else os.path.expanduser("~")
        if ini_path and os.path.isfile(ini_path):
            import linuxcnc
            ini = linuxcnc.ini(ini_path)
            p = ini.find("DISPLAY", "PREFS_FILE")
            if p:
                prefs_file = p
        prefs_path = os.path.expanduser(prefs_file)
        if not os.path.isabs(prefs_path):
            prefs_path = os.path.join(ini_dir, prefs_file)
        if os.path.isfile(prefs_path):
            import json
            with open(prefs_path, "r", encoding="utf-8") as f:
                prefs = json.load(f)
            t = prefs.get("theme", "")
            if t in ("dark", "light"):
                return t
    except Exception:
        pass
    return ""


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


def _get_antialiasing_setting(ini_path: str) -> bool:
    """Liest das Antialiasing-Setting direkt aus den Prefs (für QSurfaceFormat)."""
    try:
        prefs_file = "thorcnc.prefs"
        ini_dir = os.path.dirname(ini_path) if ini_path else os.path.expanduser("~")
        
        if ini_path and os.path.isfile(ini_path):
            import linuxcnc
            ini = linuxcnc.ini(ini_path)
            p = ini.find("DISPLAY", "PREFS_FILE")
            if p: prefs_file = p
            
        prefs_path = os.path.expanduser(prefs_file)
        if not os.path.isabs(prefs_path):
            prefs_path = os.path.join(ini_dir, prefs_path)
            
        if os.path.isfile(prefs_path):
            import json
            with open(prefs_path, "r") as f:
                prefs = json.load(f)
                # Wenn global aus, dann 0, sonst den gespeicherten Wert (default 4)
                if not prefs.get("backplot_antialiasing", True):
                    return 0
                return prefs.get("backplot_msaa_samples", 4)
    except Exception:
        pass
    return 4


def _get_msaa_setting(ini_path: str) -> int:
    """Liest die gewünschten MSAA-Samples aus den Prefs (0 = deaktiviert)."""
    return _get_antialiasing_setting(ini_path)


if __name__ == "__main__":
    main()
