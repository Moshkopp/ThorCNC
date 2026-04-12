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

import numpy as np
from PySide6.QtWidgets import QWidget, QFrame, QVBoxLayout, QLabel
from PySide6.QtCore import Qt

try:
    import pyqtgraph as pg
    
    # Kompatibilitäts-Fix für PySide6: QOpenGLWidget wurde in Qt6 verschoben.
    # Wir "patchen" es zurück an die Stelle, wo pyqtgraph es erwartet.
    if not hasattr(pg.Qt.QtWidgets, "QOpenGLWidget"):
        try:
            from PySide6.QtOpenGLWidgets import QOpenGLWidget
            pg.Qt.QtWidgets.QOpenGLWidget = QOpenGLWidget
        except ImportError:
            pass

    import pyqtgraph.opengl as gl
    _HAS_GL = True
except Exception:
    _HAS_GL = False

from ..gcode_parser import Segment, RAPID, FEED, ARC, bounding_box


# ── Farben ────────────────────────────────────────────────────────────────
_COLOR_RAPID   = (1.0, 0.2, 0.2, 1.0)    # rot
_COLOR_FEED    = (0.9, 0.9, 0.9, 1.0)    # weiß
_COLOR_ARC     = (0.2, 0.9, 0.9, 1.0)    # cyan
_COLOR_TOOL    = (1.0, 0.9, 0.0, 1.0)    # gelb

_CROSS_LEN = 40.0   # Length of axis cross arms (mm)


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
            from PySide6.QtGui import QSurfaceFormat
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
        self._view.setBackgroundColor("#1a1a1a")

        # Standard-Werte setzen, damit es beim Start nicht winzig herangezoomt ist!
        self._view.opts['distance'] = 600.0
        self._view.opts['elevation'] = 35
        self._view.opts['azimuth'] = -45

        layout.addWidget(self._view)

        self._setup_static_items()

        # Toolpath-Items (werden bei load_toolpath ersetzt)
        self._items: list = []
        self._items_data: list = []
        self._wcs_offset = (0.0, 0.0, 0.0)

        # Tool marker (End mill) - Cylinder
        self._tool_marker = gl.GLMeshItem(
            meshdata=self._capped_cylinder(1.0, 20.0, cols=40),
            color=(0.9, 0.8, 0.2, 1.0),   # Undurchsichtiges Titan-Gold
            shader='shaded',              # Echter 3D-Lichteffekt
            smooth=True,
            glOptions='opaque',           # Verhindert, dass Linien durch den Fräser durchscheinen!
            drawEdges=False
        )
        self._view.addItem(self._tool_marker)

        # Tool trail (History of movement)
        self._trail_pts = []
        self._trail_item = gl.GLLinePlotItem(
            pos=np.empty((0, 3), dtype=np.float32),
            color=(1.0, 0.6, 0.0, 1.0),  # Orange
            width=4,
            antialias=True,
            mode='line_strip',
            glOptions='opaque'
        )
        self._view.addItem(self._trail_item)

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

        # ── WCS Origin (G54 etc., movable) ────────────────────────
        # orange Kreuz, etwas kürzer
        ws = _CROSS_LEN * 0.7
        wcs_pts = np.array([
            [0, 0, 0], [ws, 0,  0],
            [0, 0, 0], [0,  ws, 0],
            [0, 0, 0], [0,  0,  ws],
        ], dtype=np.float32)
        wcs_col = np.array([
            [1.0, 0.5, 0.0, 1], [1.0, 0.5, 0.0, 1],
            [1.0, 0.5, 0.0, 1], [1.0, 0.5, 0.0, 1],
            [1.0, 0.5, 0.0, 1], [1.0, 0.5, 0.0, 1],
        ], dtype=np.float32)
        self._wcs_cross = gl.GLLinePlotItem(
            pos=wcs_pts, color=wcs_col, width=2.0,
            antialias=True, mode='lines')
        self._view.addItem(self._wcs_cross)

        # WCS Origin Marker (Orange point)
        self._wcs_marker = gl.GLScatterPlotItem(
            pos=np.array([[0, 0, 0]], dtype=np.float32),
            color=np.array([[1.0, 0.5, 0.0, 1.0]], dtype=np.float32),
            size=10, pxMode=True)
        self._view.addItem(self._wcs_marker)

    # ── Öffentliche API ──────────────────────────────────────────────────

    def load_toolpath(self, segments: list[Segment]):
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

        add(RAPID, _COLOR_RAPID, 1)
        add(FEED,  _COLOR_FEED,  1)
        add(ARC,   _COLOR_ARC,   1)

    def _capped_cylinder(self, r: float, length: float, cols: int=40):
        import numpy as np
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
        import math
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

    def set_wcs_origin(self, x: float, y: float, z: float):
        """Moves the WCS axis cross (orange) to the new position."""
        self._wcs_offset = (x, y, z)
        ws = _CROSS_LEN * 0.7
        wcs_pts = np.array([
            [x,    y,    z   ], [x+ws, y,    z   ],
            [x,    y,    z   ], [x,    y+ws, z   ],
            [x,    y,    z   ], [x,    y,    z+ws],
        ], dtype=np.float32)
        self._wcs_cross.setData(pos=wcs_pts)
        self._wcs_marker.setData(pos=np.array([[x, y, z]], dtype=np.float32))

        for item, arr in self._items_data:
            item.setData(pos=arr + [x, y, z])

    def set_antialiasing(self, enabled: bool):
        """Aktiviert/Deaktiviert das Linien-Smoothing aller Items live."""
        pg.setConfigOptions(antialias=enabled)
        # Alle Linien-Items durchgehen
        for item in self._view.items:
            if isinstance(item, gl.GLLinePlotItem):
                item.setAntialiasing(enabled)
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

    def _fit_view(self, segments: list[Segment]):
        if not segments:
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
        
        from PySide6.QtWidgets import QHBoxLayout
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
        self._toolbar_lay.addStretch()   # rechts ausrichten per default
        outer.addWidget(toolbar_widget)

        if _HAS_GL:
            self._impl = _BackplotGL(self, samples=msaa_samples)
            outer.addWidget(self._impl)
        else:
            lbl = QLabel(
                "pyqtgraph / OpenGL nicht verfügbar.\n\n"
                "Mögliche Lösungen:\n"
                "1. In VM: '3D-Beschleunigung' aktivieren\n"
                "2. Debian/Ubuntu: sudo apt install python3-pyqtgraph python3-opengl\n"
                "3. Pip: pip install pyqtgraph PyOpenGL",
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

    def set_antialiasing(self, enabled: bool):
        if self._impl:
            self._impl.set_antialiasing(enabled)

    def get_actual_samples(self) -> int:
        """Returns the MSAA samples actually provided by the driver."""
        if self._impl and hasattr(self._impl, "_view"):
            return self._impl._view.format().samples()
        return 0
