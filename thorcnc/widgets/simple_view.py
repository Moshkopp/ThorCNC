import os
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton
from PySide6.QtUiTools import QUiLoader

from .backplot import BackplotWidget

_DIR = os.path.dirname(__file__)

# DRO font sizes (point)
_PT_BIG  = 72   # WCS / DTG values  +  X/Y/Z row labels
_PT_MED  = 42   # MACH values
_PT_INFO = 32   # FEED / RPM
_PT_HDR  = 20   # WCS / MACH / DTG column headers

_MONO = "Ubuntu Mono"

# Colors matching the main DRO (dark.qss)
_COL_WCS  = "#00dd55"        # green
_COL_MACH = "#aaaaaa"        # gray
_COL_DTG  = "#e67e22"        # orange
_COL_BG   = "rgb(25,28,30)"  # dark cell background

def _dro_style(pt, color, family=_MONO):
    return (
        f"font-family: '{family}';"
        f"font-size: {pt}pt;"
        f"font-weight: bold;"
        f"color: {color};"
        f"background-color: {_COL_BG};"
        f"border-radius: 3px;"
        f"padding: 2px 6px;"
    )

def _hdr_style(color="white", pt=_PT_HDR):
    return f"font-size: {pt}pt; font-weight: bold; color: {color};"

def _axis_style(pt=_PT_BIG):
    """Style for the X / Y / Z row-label column."""
    return f"font-size: {pt}pt; font-weight: bold;"


class SimpleView(QWidget):
    """
    High-visibility fullscreen DRO overlay.
    Loaded from simple_view.ui; fonts applied programmatically after load
    so the global QSS cannot override them.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._load_ui()
        self._apply_fonts()
        self._setup_backplot()

    # ── UI loading ────────────────────────────────────────────────────────────

    def _load_ui(self):
        loader = QUiLoader()
        ui_path = os.path.join(_DIR, "simple_view.ui")
        self.ui = loader.load(ui_path, self)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.ui)

        def _w(name):
            return self.ui.findChild(QWidget, name)

        # WCS row
        self.lbl_wcs_x = _w("lbl_wcs_x")
        self.lbl_wcs_y = _w("lbl_wcs_y")
        self.lbl_wcs_z = _w("lbl_wcs_z")
        # MACH row
        self.lbl_mach_x = _w("lbl_mach_x")
        self.lbl_mach_y = _w("lbl_mach_y")
        self.lbl_mach_z = _w("lbl_mach_z")
        # DTG row
        self.lbl_dtg_x = _w("lbl_dtg_x")
        self.lbl_dtg_y = _w("lbl_dtg_y")
        self.lbl_dtg_z = _w("lbl_dtg_z")
        # Feed / RPM
        self.lbl_feed = _w("lbl_simple_feed")
        self.lbl_rpm  = _w("lbl_simple_rpm")
        # Buttons
        self.btn_back  = self.ui.findChild(QPushButton, "btn_simple_back")
        self.btn_start = self.ui.findChild(QPushButton, "btn_simple_start")
        self.btn_pause = self.ui.findChild(QPushButton, "btn_simple_pause")
        self.btn_stop  = self.ui.findChild(QPushButton, "btn_simple_stop")
        self.btn_estop = self.ui.findChild(QPushButton, "btn_simple_estop")

    def _apply_fonts(self):
        """Set fonts+colors via setStyleSheet — higher specificity than global QSS."""
        wcs_style  = _dro_style(_PT_BIG, _COL_WCS)
        mach_style = _dro_style(_PT_MED, _COL_MACH)
        dtg_style  = _dro_style(_PT_BIG, _COL_DTG)
        info_style = f"font-size: {_PT_INFO}pt; font-weight: bold;"
        axis_style = _axis_style()

        for lbl in (self.lbl_wcs_x, self.lbl_wcs_y, self.lbl_wcs_z):
            if lbl: lbl.setStyleSheet(wcs_style)

        for lbl in (self.lbl_mach_x, self.lbl_mach_y, self.lbl_mach_z):
            if lbl: lbl.setStyleSheet(mach_style)

        for lbl in (self.lbl_dtg_x, self.lbl_dtg_y, self.lbl_dtg_z):
            if lbl: lbl.setStyleSheet(dtg_style)

        for lbl in (self.lbl_feed, self.lbl_rpm):
            if lbl: lbl.setStyleSheet(info_style)

        btn_style = "font-size: 22pt; font-weight: bold;"
        for b in (self.btn_start, self.btn_pause, self.btn_stop, self.btn_estop, self.btn_back):
            if b: b.setStyleSheet(btn_style)

        # X / Y / Z row labels — same size as the big values
        for n in ("lbl_row_x", "lbl_row_y", "lbl_row_z"):
            lbl = self.ui.findChild(QWidget, n)
            if lbl: lbl.setStyleSheet(axis_style)

        # Column headers colored to match their column
        for name, color in (
            ("lbl_hdr_wcs",  _COL_WCS),
            ("lbl_hdr_mach", _COL_MACH),
            ("lbl_hdr_dtg",  _COL_DTG),
        ):
            lbl = self.ui.findChild(QWidget, name)
            if lbl: lbl.setStyleSheet(_hdr_style(color))

    def _setup_backplot(self):
        frame = self.ui.findChild(QWidget, "frame_simple_backplot")
        if frame and frame.layout():
            self.backplot = BackplotWidget(msaa_samples=4)
            frame.layout().addWidget(self.backplot)
        else:
            self.backplot = None

    # ── DRO setters ───────────────────────────────────────────────────────────

    def set_wcs(self, x, y, z):
        if self.lbl_wcs_x: self.lbl_wcs_x.setText(f"{x:+.3f}")
        if self.lbl_wcs_y: self.lbl_wcs_y.setText(f"{y:+.3f}")
        if self.lbl_wcs_z: self.lbl_wcs_z.setText(f"{z:+.3f}")

    def set_machine(self, x, y, z):
        if self.lbl_mach_x: self.lbl_mach_x.setText(f"{x:+.3f}")
        if self.lbl_mach_y: self.lbl_mach_y.setText(f"{y:+.3f}")
        if self.lbl_mach_z: self.lbl_mach_z.setText(f"{z:+.3f}")

    def set_dtg(self, x, y, z):
        if self.lbl_dtg_x: self.lbl_dtg_x.setText(f"{x:+.3f}")
        if self.lbl_dtg_y: self.lbl_dtg_y.setText(f"{y:+.3f}")
        if self.lbl_dtg_z: self.lbl_dtg_z.setText(f"{z:+.3f}")

    # backward compat
    def set_pos(self, x, y, z):
        self.set_wcs(x, y, z)

    def set_feed_rpm(self, feed, rpm):
        if self.lbl_feed: self.lbl_feed.setText(f"FEED: {int(feed)}")
        if self.lbl_rpm:  self.lbl_rpm.setText(f"RPM: {int(rpm)}")
