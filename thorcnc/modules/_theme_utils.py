"""Theme-aware color helper.

Zentrale Palette für die wenigen Stellen, an denen Farben dynamisch aus
Python gesetzt werden (z.B. setStyleSheet/setForeground/QColor). Alles
andere gehört in die QSS-Dateien unter thorcnc/themes/.

Verwendung:
    from ._theme_utils import theme_color
    col = theme_color(self._t, "accent")
"""

DARK = {
    "bg.main":        "#1e1e1e",
    "bg.panel":       "#2a2a2a",
    "bg.bar":         "#252525",
    "bg.elevated":    "#3a3a3a",
    "border":         "#444444",
    "border.strong":  "#3a7abf",
    "text.primary":   "#d0d0d0",
    "text.secondary": "#cccccc",
    "text.dim":       "#999999",
    "accent":         "#3a7abf",
    "accent.hover":   "#4d9de0",
    "accent.pressed": "#2d6099",
    "success":        "#27ae60",
    "success.bg":     "#2a4a2a",
    "warning":        "#e67e00",
    "warning.bg":     "#7a3000",
    "warning.text":   "#ffcc88",
    "error":          "#cc0000",
    "error.border":   "#ff4444",
    "error.text":     "#ff5555",
    "dro.work":       "#2ecc71",
    "dro.machine":    "#cccccc",
    "dro.dtg":        "#e67e00",
    "row.active.bg":  "#194a82",
    "row.idle.bg":    "#252525",
    "row.active.fg":  "#3db2ff",
    "row.idle.fg":    "#999999",
    "marker.gcode":   "#4ec9b0",
    "marker.probe":   "#e67e00",
    "title.section":  "#3a7abf",
    "title.label":    "#eee",
}

LIGHT = {
    "bg.main":        "#fdf6e3",
    "bg.panel":       "#eee8d5",
    "bg.bar":         "#e4dcc4",
    "bg.elevated":    "#fbf3d8",
    "border":         "#d3cbb1",
    "border.strong":  "#a39e84",
    "text.primary":   "#073642",
    "text.secondary": "#586e75",
    "text.dim":       "#93a1a1",
    "accent":         "#00838f",
    "accent.hover":   "#00acc1",
    "accent.pressed": "#006064",
    "success":        "#2e7d32",
    "success.bg":     "#c8e6c9",
    "warning":        "#ef6c00",
    "warning.bg":     "#ffe0b2",
    "warning.text":   "#bf360c",
    "error":          "#c62828",
    "error.border":   "#c62828",
    "error.text":     "#b71c1c",
    "dro.work":       "#00695c",
    "dro.machine":    "#455a64",
    "dro.dtg":        "#bf360c",
    "row.active.bg": "#b2dfdb",
    "row.idle.bg":   "#fdf6e3",
    "row.active.fg": "#00695c",
    "row.idle.fg":   "#93a1a1",
    "marker.gcode":   "#00695c",
    "marker.probe":   "#00838f",
    "title.section":  "#00838f",
    "title.label":    "#073642",
}


def _palette(thorc) -> dict:
    name = "dark"
    try:
        name = thorc.settings.get("theme", "dark")
    except Exception:
        pass
    return LIGHT if name == "light" else DARK


def theme_color(thorc, token: str, fallback: str = "#000000") -> str:
    """Returns the hex color for `token` in the currently active theme."""
    return _palette(thorc).get(token, fallback)


def current_theme(thorc) -> str:
    """Returns 'light' or 'dark' for the active theme."""
    try:
        return thorc.settings.get("theme", "dark")
    except Exception:
        return "dark"
