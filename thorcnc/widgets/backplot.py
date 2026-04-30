"""
3D Backplot using pyqtgraph OpenGL.

Color coding:
  Rapid (G0)  → red, dashed (alpha 0.4)
  Feed (G1)   → white
  Arc (G2/G3) → cyan

Tool position → yellow point

Fallback: if pyqtgraph/OpenGL is not available, a
hint label is displayed instead of an error.
"""
import os
# Force PySide6 for pyqtgraph before it's imported anywhere else
os.environ['PYQTGRAPH_QT_LIB'] = 'PySide6'

import numpy as np
import math
from PySide6.QtWidgets import QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QSurfaceFormat

# Global references for the backplot implementation
pg = None
gl = None
_HAS_GL = False
_GL_ERROR = ""

try:
    import pyqtgraph as _pg

    # Patch QOpenGLWidget BEFORE importing pyqtgraph.opengl — newer pyqtgraph
    # versions look it up at import time and crash if it's missing from QtWidgets.
    try:
        from PySide6.QtOpenGLWidgets import QOpenGLWidget as _QOGLWidget
        if hasattr(_pg, 'Qt') and hasattr(_pg.Qt, 'QtWidgets'):
            if not hasattr(_pg.Qt.QtWidgets, 'QOpenGLWidget'):
                _pg.Qt.QtWidgets.QOpenGLWidget = _QOGLWidget
    except Exception:
        pass

    import pyqtgraph.opengl as _gl

    pg = _pg
    gl = _gl
    _HAS_GL = True
except Exception as _e:
    _HAS_GL = False
    _GL_ERROR = str(_e)

from ..gcode_parser import Segment, RAPID, FEED, ARC, bounding_box
from ..i18n import _t


# ── Farben ────────────────────────────────────────────────────────────────
_COLOR_RAPID   = (1.0, 0.2, 0.2, 1.0)    # rot
_COLOR_FEED    = (0.9, 0.9, 0.9, 1.0)    # weiß
_COLOR_ARC     = (0.2, 0.9, 0.9, 1.0)    # cyan
_COLOR_TOOL    = (1.0, 0.9, 0.0, 1.0)    # gelb

# Standardfarben als Hex — werden via set_colors() überschrieben
DEFAULT_BACKPLOT_COLORS = {
    "rapid":      "#ff3333",
    "feed":       "#e5e5e5",
    "arc":        "#33e5e5",
    "tool":       "#e5cc33",
    "trail":      "#ff9900",
    "background": "#0d1117",
    "wcs_size":   28.0,   # WCS-Kreuz Armlänge in mm (float, kein Hex)
}

# WCS-Kreuz Farben: immer RGB wie Maschinenkoordinaten-Konvention
_WCS_COLORS = np.array([
    [1.0, 0.2, 0.2, 1], [1.0, 0.2, 0.2, 1],  # X = rot
    [0.2, 1.0, 0.2, 1], [0.2, 1.0, 0.2, 1],  # Y = grün
    [0.3, 0.5, 1.0, 1], [0.3, 0.5, 1.0, 1],  # Z = blau
], dtype=np.float32)

_CROSS_LEN = 40.0   # Length of axis cross arms (mm)


def _hex_to_rgba(hex_color: str, alpha: float = 1.0) -> tuple:
    """Convert '#rrggbb' hex string to (r, g, b, a) float tuple."""
    from PySide6.QtGui import QColor
    c = QColor(hex_color)
    if not c.isValid():
        return (1.0, 1.0, 1.0, alpha)
    return (c.redF(), c.greenF(), c.blueF(), alpha)


def _text_to_strokes(text: str, size: float = 80.0) -> list:
    """Convert text to a list of (N,2) numpy arrays (one per continuous stroke)."""
    try:
        from matplotlib.textpath import TextPath
        from matplotlib.font_manager import FontProperties
        from matplotlib.path import Path as MPath
        fp = FontProperties(family='sans-serif', weight='bold')
        tp = TextPath((0, 0), text, size=size, prop=fp)
        interp = MPath(tp.vertices, tp.codes).interpolated(steps=6)
        strokes, cur = [], []
        for v, c in zip(interp.vertices, interp.codes):
            if c == MPath.MOVETO:
                if len(cur) > 1:
                    strokes.append(np.array(cur, dtype=np.float32))
                cur = [v.tolist()]
            elif c == MPath.LINETO:
                cur.append(v.tolist())
            elif c == MPath.CLOSEPOLY:
                if cur:
                    cur.append(cur[0])
                if len(cur) > 1:
                    strokes.append(np.array(cur, dtype=np.float32))
                cur = []
        if len(cur) > 1:
            strokes.append(np.array(cur, dtype=np.float32))
        return strokes
    except Exception:
        return []


def _segments_to_array(segments: list[Segment], kind: int) -> np.ndarray | None:
    """Baut ein (N,3)-Array für einen Segmenttyp, NaN als Trennlinie."""
    pts = []
    for seg in segments:
        if seg.kind != kind:
            continue
        for p in seg.points:
            pts.append(p)
        pts.append((np.nan, np.nan, np.nan))  # Lücke zwischen Segmenten
    if not pts:
        return None
    return np.array(pts, dtype=np.float32)


_BackplotGL = None

if _HAS_GL:
    class _ThorGLView(gl.GLViewWidget):
        """GLViewWidget mit geänderter Maussteuerung:
        - Mittlere Taste          → Pan (XZ-Ebene, fühlt sich natürlich an)
        - Mittlere Taste + Strg   → Zoom (Distanz ändern)
        - Linke Taste             → Orbit (drehen)  — unverändert
        - Linke Taste + Strg      → Pan in View-Ebene — unverändert
        - Scrollrad               → Zoom — unverändert
        """

        def __init__(self, samples: int = 4, **kwargs):
            super().__init__(**kwargs)
            # Format direkt auf dem Widget setzen (vor show()) – das ist
            # zuverlässiger als nur QSurfaceFormat.setDefaultFormat().
            fmt = QSurfaceFormat()
            fmt.setSamples(max(0, samples))
            self.setFormat(fmt)

        def initializeGL(self):
            # Explizites Einschalten von Multisampling im GL-Kontext
            super().initializeGL()
            try:
                from OpenGL import GL
                GL.glEnable(GL.GL_MULTISAMPLE)
            except Exception:
                pass

        def mouseMoveEvent(self, ev):
            lpos = ev.position() if hasattr(ev, 'position') else ev.localPos()
            if not hasattr(self, 'mousePos'):
                self.mousePos = lpos
            diff = lpos - self.mousePos
            self.mousePos = lpos

            ctrl = bool(ev.modifiers() & Qt.KeyboardModifier.ControlModifier)

            if ev.buttons() == Qt.MouseButton.LeftButton:
                if ctrl:
                    self.pan(diff.x(), diff.y(), 0, relative='view')
                else:
                    self.orbit(-diff.x(), diff.y())
            elif ev.buttons() == Qt.MouseButton.MiddleButton:
                if ctrl:
                    # Strg + Mitte → Zoom
                    self.opts['distance'] *= 1.01 ** diff.y()
                    self.update()
                else:
                    # Center -> Pan (X + Z, no Y-world axis zoom effect)
                    self.pan(diff.x(), 0, diff.y(), relative='view-upright')


    class _BackplotGL(QWidget):
        """Interne Klasse: der eigentliche OpenGL-Viewport."""

        def __init__(self, parent=None, samples: int = 4):
            super().__init__(parent)
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)

            pg.setConfigOptions(antialias=True)
            self._view = _ThorGLView(samples=samples)
            _bg = "#1a1f2e" if os.environ.get("THORCNC_THEME") == "light" else "#0d1117"
            self._view.setBackgroundColor(_bg)

            # Standard-Werte setzen, damit es beim Start nicht winzig herangezoomt ist!
            self._view.opts['distance'] = 600.0
            self._view.opts['elevation'] = 35
            self._view.opts['azimuth'] = -45

            layout.addWidget(self._view)

            # Instanz-Farben (überschreibbar via set_colors) — vor _setup_static_items!
            self._color_rapid = _COLOR_RAPID
            self._color_feed  = _COLOR_FEED
            self._color_arc   = _COLOR_ARC
            self._color_tool  = (0.9, 0.8, 0.2, 1.0)
            self._color_trail = (1.0, 0.6, 0.0, 1.0)
            self._wcs_size    = 28.0   # Armlänge WCS-Kreuz in mm
            self._wcs_pos     = (0.0, 0.0, 0.0)

            self._setup_static_items()

            # Toolpath-Items (werden bei load_toolpath ersetzt)
            self._items: list = []
            self._items_data: list = []
            self._wcs_offset = (0.0, 0.0, 0.0)
            self._last_segments: list = []

            # Tool marker (End mill) - Cylinder
            self._tool_marker = gl.GLMeshItem(
                meshdata=self._capped_cylinder(1.0, 20.0, cols=40),
                color=self._color_tool,
                shader='shaded',
                smooth=True,
                glOptions='opaque',
                drawEdges=False
            )
            self._view.addItem(self._tool_marker)

            # Tool trail (History of movement)
            self._trail_pts = []
            self._trail_item = gl.GLLinePlotItem(
                pos=np.empty((0, 3), dtype=np.float32),
                color=self._color_trail,
                width=4,
                antialias=True,
                mode='line_strip',
                glOptions='opaque'
            )
            self._view.addItem(self._trail_item)

            # Splash animation state
            self._splash_item = None
            self._splash_pts = None
            self._splash_idx = 0
            self._splash_timer = QTimer()
            self._splash_timer.timeout.connect(self._splash_tick)
            self._env_cx = 300.0
            self._env_cy = 250.0
            self._env_cz = 0.0

        def start_splash(self, text: str = "ThorCNC"):
            strokes = _text_to_strokes(text, size=90.0)
            sub_lines = ["by Moshy", "for CNCchanges"]
            if not strokes:
                return
            all_xy = np.vstack(strokes)
            bx = (all_xy[:, 0].min() + all_xy[:, 0].max()) / 2
            by = (all_xy[:, 1].min() + all_xy[:, 1].max()) / 2
            text_h = all_xy[:, 1].max() - all_xy[:, 1].min()
            ox, oy, z = self._env_cx - bx, self._env_cy - by, self._env_cz
            pts = []
            for stroke in strokes:
                for xy in stroke:
                    pts.append([xy[0] + ox, xy[1] + oy, z])
                pts.append([np.nan, np.nan, np.nan])
            line_y = oy - text_h * 0.18
            for line_text in sub_lines:
                sub_strokes = _text_to_strokes(line_text, size=35.0)
                if not sub_strokes:
                    continue
                sub_xy = np.vstack(sub_strokes)
                sbx = (sub_xy[:, 0].min() + sub_xy[:, 0].max()) / 2
                sub_h = sub_xy[:, 1].max() - sub_xy[:, 1].min()
                sox = self._env_cx - sbx
                soy = line_y - sub_xy[:, 1].max()
                for stroke in sub_strokes:
                    for xy in stroke:
                        pts.append([xy[0] + sox, xy[1] + soy, z])
                    pts.append([np.nan, np.nan, np.nan])
                line_y = soy - sub_h * 0.3
            self._splash_pts = np.array(pts, dtype=np.float32)
            self._splash_idx = 0
            if self._splash_item is not None:
                self._view.removeItem(self._splash_item)
            self._splash_item = gl.GLLinePlotItem(
                pos=np.empty((0, 3), dtype=np.float32),
                color=(0.25, 0.75, 1.0, 0.9),
                width=3,
                antialias=True,
                mode='line_strip',
                glOptions='opaque'
            )
            self._view.addItem(self._splash_item)
            self._splash_timer.start(16)

        def _splash_tick(self):
            if self._splash_pts is None or self._splash_item is None:
                self._splash_timer.stop()
                return
            step = max(1, len(self._splash_pts) // 100)
            self._splash_idx = min(self._splash_idx + step, len(self._splash_pts))
            self._splash_item.setData(pos=self._splash_pts[:self._splash_idx])
            if self._splash_idx >= len(self._splash_pts):
                self._splash_timer.stop()

        def hide_splash(self):
            self._splash_timer.stop()
            if self._splash_item is not None:
                self._view.removeItem(self._splash_item)
                self._splash_item = None
            self._splash_pts = None
            self._splash_idx = 0

        def _setup_static_items(self):
            # ── Machine Zero (Fixed at 0,0,0) ─────────────────────────
            # helles Kreuz: X=rot, Y=grün, Z=blau
            L = _CROSS_LEN
            mach_pts = np.array([
                [0, 0, 0], [L, 0, 0],
                [0, 0, 0], [0, L, 0],
                [0, 0, 0], [0, 0, L],
            ], dtype=np.float32)
            mach_col = np.array([
                [1.0, 0.2, 0.2, 1], [1.0, 0.2, 0.2, 1],
                [0.2, 1.0, 0.2, 1], [0.2, 1.0, 0.2, 1],
                [0.3, 0.5, 1.0, 1], [0.3, 0.5, 1.0, 1],
            ], dtype=np.float32)
            self._view.addItem(gl.GLLinePlotItem(
                pos=mach_pts, color=mach_col, width=2.5,
                antialias=True, mode='lines'))

            # Machine Zero Marker (White point)
            self._mach_marker = gl.GLScatterPlotItem(
                pos=np.array([[0, 0, 0]], dtype=np.float32),
                color=np.array([[1.0, 1.0, 1.0, 1.0]], dtype=np.float32),
                size=8, pxMode=True)
            self._view.addItem(self._mach_marker)

            # ── WCS Origin (G54 etc., movable) — RGB wie Maschinenkonvention ─
            ws = self._wcs_size
            wcs_pts = np.array([
                [0, 0, 0], [ws, 0,  0],
                [0, 0, 0], [0,  ws, 0],
                [0, 0, 0], [0,  0,  ws],
            ], dtype=np.float32)
            self._wcs_cross = gl.GLLinePlotItem(
                pos=wcs_pts, color=_WCS_COLORS, width=2.0,
                antialias=True, mode='lines')
            self._view.addItem(self._wcs_cross)

            # WCS Origin Marker (weißer Punkt)
            self._wcs_marker = gl.GLScatterPlotItem(
                pos=np.array([[0, 0, 0]], dtype=np.float32),
                color=np.array([[1.0, 1.0, 1.0, 1.0]], dtype=np.float32),
                size=10, pxMode=True)
            self._view.addItem(self._wcs_marker)

        # ── Öffentliche API ──────────────────────────────────────────────────

        def load_toolpath(self, segments: list[Segment]):
            self._last_segments = segments
            # Alte Toolpath-Items entfernen
            for item in self._items:
                self._view.removeItem(item)
            self._items.clear()
            self._items_data.clear()

            def add(kind, color, width):
                arr = _segments_to_array(segments, kind)
                if arr is None:
                    return
                ox, oy, oz = self._wcs_offset
                item = gl.GLLinePlotItem(
                    pos=arr + [ox, oy, oz],
                    color=color,
                    width=width,
                    antialias=True,
                    mode='line_strip',
                    glOptions='opaque',
                )
                self._view.addItem(item)
                self._items.append(item)
                self._items_data.append((item, arr))

            add(RAPID, self._color_rapid, 1)
            add(FEED,  self._color_feed,  1)
            add(ARC,   self._color_arc,   1)

        def _capped_cylinder(self, r: float, length: float, cols: int=40):
            md = gl.MeshData.cylinder(rows=1, cols=cols, radius=[r, r], length=length)
            v = md.vertexes()
            f = list(md.faces())

            bc_idx = len(v)
            tc_idx = len(v) + 1
            new_v = np.vstack([v, [[0, 0, 0], [0, 0, length]]])

            for i in range(cols):
                nxt = (i + 1) % cols
                f.append([bc_idx, nxt, i])
                f.append([tc_idx, cols + i, cols + nxt])

            return gl.MeshData(vertexes=new_v, faces=np.array(f, dtype=np.int32))

        def set_tool_geometry(self, dia: float, length: float):
            r = dia / 2.0
            if r < 0.1: r = 0.5
            l = length if length > 0.1 else 20.0
            md = self._capped_cylinder(r, l, cols=40)
            self._tool_marker.setMeshData(meshdata=md)

        def set_tool_position(self, x: float, y: float, z: float):
            if any(math.isnan(v) for v in (x, y, z)):
                # Nicht gereferenciert → Marker verstecken
                self._tool_marker.hide()
            else:
                self._tool_marker.show()
                self._tool_marker.resetTransform()
                self._tool_marker.translate(x, y, z)

                # Trail aktualisieren
                if len(self._trail_pts) == 0 or self._trail_pts[-1] != (x, y, z):
                    self._trail_pts.append((x, y, z))
                    # Begrenzen auf die letzten N punkte gegen Speicher/Lag (z.b. 10000)
                    if len(self._trail_pts) > 10000:
                        self._trail_pts.pop(0)

                    arr = np.array(self._trail_pts, dtype=np.float32)
                    self._trail_item.setData(pos=arr)

        def clear_trail(self):
            self._trail_pts.clear()
            self._trail_item.setData(pos=np.empty((0, 3), dtype=np.float32))

        def set_colors(self, colors: dict):
            """Apply color/size settings to backplot elements live.
            Hex strings for colors, float for 'wcs_size'."""
            path_changed = False
            for key in ("rapid", "feed", "arc"):
                if key in colors:
                    rgba = _hex_to_rgba(colors[key])
                    setattr(self, f"_color_{key}", rgba)
                    path_changed = True
            if "tool" in colors:
                self._color_tool = _hex_to_rgba(colors["tool"])
                self._tool_marker.setColor(self._color_tool)
            if "trail" in colors:
                self._color_trail = _hex_to_rgba(colors["trail"])
                self._trail_item.setData(color=self._color_trail)
            if "background" in colors:
                self._view.setBackgroundColor(colors["background"])
            if "wcs_size" in colors:
                self._wcs_size = float(colors["wcs_size"])
                self.set_wcs_origin(*self._wcs_pos)
            if path_changed and self._last_segments:
                self.load_toolpath(self._last_segments)

        def set_wcs_origin(self, x: float, y: float, z: float):
            """Moves the WCS axis cross (RGB) to the new position."""
            self._wcs_offset = (x, y, z)
            self._wcs_pos = (x, y, z)
            ws = self._wcs_size
            wcs_pts = np.array([
                [x,    y,    z   ], [x+ws, y,    z   ],
                [x,    y,    z   ], [x,    y+ws, z   ],
                [x,    y,    z   ], [x,    y,    z+ws],
            ], dtype=np.float32)
            self._wcs_cross.setData(pos=wcs_pts, color=_WCS_COLORS)
            self._wcs_marker.setData(pos=np.array([[x, y, z]], dtype=np.float32))

            for item, arr in self._items_data:
                item.setData(pos=arr + [x, y, z])

        def set_antialiasing(self, enabled: bool):
            """Aktiviert/Deaktiviert das Linien-Smoothing aller Items live."""
            pg.setConfigOptions(antialias=enabled)
            # Alle Linien-Items durchgehen
            for item in self._view.items:
                if isinstance(item, gl.GLLinePlotItem):
                    item.setData(antialias=enabled)
                elif isinstance(item, gl.GLScatterPlotItem):
                     # ScatterPlotItems haben oft kein explizites setAntialiasing in pyqtgraph-opengl
                     # aber die globalen pg-options helfen ggf.
                     pass
            self._view.update()

        def set_machine_envelope(self,
                                 x_min: float, x_max: float,
                                 y_min: float, y_max: float,
                                 z_min: float, z_max: float):
            """Draws the machine work area as a wireframe."""
            self._env_cx = (x_min + x_max) / 2
            self._env_cy = (y_min + y_max) / 2
            self._env_cz = z_max
            if hasattr(self, "_envelope_item") and self._envelope_item:
                self._view.removeItem(self._envelope_item)

            # 8 Ecken des Quaders
            c = [
                [x_min, y_min, z_min], [x_max, y_min, z_min],
                [x_max, y_max, z_min], [x_min, y_max, z_min],
                [x_min, y_min, z_max], [x_max, y_min, z_max],
                [x_max, y_max, z_max], [x_min, y_max, z_max],
            ]
            # 12 Edges as line pairs
            edges = [
                c[0],c[1], c[1],c[2], c[2],c[3], c[3],c[0],  # Boden
                c[4],c[5], c[5],c[6], c[6],c[7], c[7],c[4],  # Deckel
                c[0],c[4], c[1],c[5], c[2],c[6], c[3],c[7],  # Seiten
            ]
            pts = np.array(edges, dtype=np.float32)
            col = np.full((len(pts), 4), [0.4, 0.8, 1.0, 0.35], dtype=np.float32)

            self._envelope_item = gl.GLLinePlotItem(
                pos=pts, color=col, width=1.0, antialias=True, mode='lines')
            self._view.addItem(self._envelope_item)

        def _fit_view(self, segments: list[Segment] = None):
            if not segments:
                ox, oy, oz = self._wcs_offset
                self._view.opts['center'] = pg.Vector(ox, oy, oz)
                self._view.opts['distance'] = 200.0  # Default zoom level
                self.set_view_iso()
                return

            mn_x, mx_x, mn_y, mx_y, mn_z, mx_z = bounding_box(segments)
            ox, oy, oz = self._wcs_offset
            cx = (mn_x + mx_x) / 2 + ox
            cy = (mn_y + mx_y) / 2 + oy
            cz = (mn_z + mx_z) / 2 + oz
            span = max(mx_x - mn_x, mx_y - mn_y, mx_z - mn_z, 1.0)

            self._view.opts['center'] = pg.Vector(cx, cy, cz)
            self._view.opts['distance'] = span * 2.5
            self.set_view_iso()

        def set_view_iso(self):
            """ISO (Vogelperspektive schräg)"""
            self._view.opts['elevation'] = 35
            self._view.opts['azimuth'] = -45
            self._view.update()

        def set_view_z(self):
            """Top View (Z) - Vogelperspektive flach"""
            self._view.opts['elevation'] = 90
            self._view.opts['azimuth'] = -90
            self._view.update()

        def set_view_y(self):
            """Front View (Y)"""
            self._view.opts['elevation'] = 0
            self._view.opts['azimuth'] = -90
            self._view.update()

        def set_view_x(self):
            """Side View (X)"""
            self._view.opts['elevation'] = 0
            self._view.opts['azimuth'] = 0
            self._view.update()

        def get_view_opts(self) -> dict:
            o = self._view.opts
            c = o.get('center')
            return {
                "distance": o.get('distance', 600.0),
                "elevation": o.get('elevation', 35),
                "azimuth": o.get('azimuth', -45),
                "center": [c.x(), c.y(), c.z()] if c else [0, 0, 0]
            }

        def set_view_opts(self, opts: dict):
            self._view.opts['distance'] = opts.get("distance", 600.0)
            self._view.opts['elevation'] = opts.get("elevation", 35)
            self._view.opts['azimuth'] = opts.get("azimuth", -45)
            c = opts.get("center", [0, 0, 0])
            self._view.opts['center'] = pg.Vector(c[0], c[1], c[2])
            self._view.update()


# ── Öffentliche Klasse ────────────────────────────────────────────────────

class BackplotWidget(QFrame):
    """
    Wrapper um _BackplotGL.
    Bei fehlendem pyqtgraph/OpenGL wird ein Fallback-Label gezeigt.
    """

    def __init__(self, parent=None, msaa_samples: int = 4):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)

        # Toolbar – wird von außen befüllt via toolbar_layout()
        toolbar_widget = QFrame(self)
        toolbar_widget.setObjectName("backplotToolbar")
        toolbar_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        toolbar_widget.setFixedHeight(40)
        self._toolbar_lay = QHBoxLayout(toolbar_widget)
        self._toolbar_lay.setContentsMargins(6, 2, 6, 2)
        self._toolbar_lay.setSpacing(4)
        outer.addWidget(toolbar_widget)

        if _HAS_GL:
            self._impl = _BackplotGL(self, samples=msaa_samples)
            outer.addWidget(self._impl)
        else:
            _err_detail = f"\n\nFehler: {_GL_ERROR}" if _GL_ERROR else ""
            lbl = QLabel(
                _t("pyqtgraph / OpenGL nicht verfügbar.\n\n"
                "Mögliche Lösungen:\n"
                "1. In VM: '3D-Beschleunigung' aktivieren\n"
                "2. Debian/Ubuntu: sudo apt install python3-pyqtgraph python3-opengl libgl1-mesa-dri\n"
                "3. Pip: pip install pyqtgraph PyOpenGL\n"
                "4. Software-Renderer: LIBGL_ALWAYS_SOFTWARE=1 thorcnc") + _err_detail,
                self,
            )
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setObjectName("backplot_unavailable_label")
            outer.addWidget(lbl)
            self._impl = None

    def toolbar_layout(self) -> "QHBoxLayout":
        """Gibt das QHBoxLayout der Toolbar zurück (links einfügen, rechts ist Stretch)."""
        return self._toolbar_lay

    def load_toolpath(self, segments: list[Segment]):
        if self._impl:
            self._impl.load_toolpath(segments)

    def fit_view(self, segments: list[Segment] = None):
        """Calculates center and distance to fit the segments in view.
        If segments is None, centers on the WCS origin."""
        if self._impl:
            self._impl._fit_view(segments)

    def set_tool_position(self, x: float, y: float, z: float):
        if self._impl:
            self._impl.set_tool_position(x, y, z)

    def set_wcs_origin(self, x: float, y: float, z: float):
        if self._impl:
            self._impl.set_wcs_origin(x, y, z)

    def set_tool_geometry(self, dia: float, length: float):
        if self._impl:
            self._impl.set_tool_geometry(dia, length)

    def set_machine_envelope(self, x_min, x_max, y_min, y_max, z_min, z_max):
        if self._impl:
            self._impl.set_machine_envelope(x_min, x_max, y_min, y_max, z_min, z_max)

    def start_splash(self, text: str = "ThorCNC"):
        if self._impl:
            self._impl.start_splash(text)

    def hide_splash(self):
        if self._impl:
            self._impl.hide_splash()

    def set_view_iso(self):
        if self._impl:
            self._impl.set_view_iso()

    def set_view_z(self):
        if self._impl:
            self._impl.set_view_z()

    def set_view_y(self):
        if self._impl:
            self._impl.set_view_y()

    def set_view_x(self):
        if self._impl:
            self._impl.set_view_x()

    def clear_trail(self):
        if self._impl:
            self._impl.clear_trail()

    def get_view_opts(self) -> dict:
        if self._impl:
            return self._impl.get_view_opts()
        return {}

    def set_view_opts(self, opts: dict):
        if self._impl:
            self._impl.set_view_opts(opts)

    def set_colors(self, colors: dict):
        if self._impl:
            self._impl.set_colors(colors)

    def set_antialiasing(self, enabled: bool):
        if self._impl:
            self._impl.set_antialiasing(enabled)

    def get_actual_samples(self) -> int:
        """Returns the MSAA samples actually provided by the driver."""
        if self._impl and hasattr(self._impl, "_view"):
            return self._impl._view.format().samples()
        return 0
