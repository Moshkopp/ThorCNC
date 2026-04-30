"""DRO module for ThorCNC — Digital Read Out management."""

import linuxcnc

_TOOL_EPSILON = 0.001  # mm — minimum movement to trigger backplot redraw
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QHBoxLayout, QWidget, QGridLayout, QFrame, QPushButton, 
    QSizePolicy, QComboBox, QLabel
)

from .base import ThorModule
from ..i18n import _t

class DROModule(ThorModule):
    """Manages the DRO display: coordinates, WCS, and axis zeroing."""

    def __init__(self, thorc):
        super().__init__(thorc)
        self._dro_work = {}    # axis -> QLabel
        self._dro_machine = {} # axis -> QLabel
        self._dro_dtg = {}     # axis -> QLabel
        self._dro_ref_btn = {} # axis -> QPushButton
        self._wcs_combo = None
        self._btn_ref_all = None
        
        self._wcs_initialized = False
        self._last_wcs_origin = (0.0, 0.0, 0.0)
        self._last_tool_pos = None  # None = unhomed/unknown

    def setup(self):
        self._setup_dro()

    def connect_signals(self):
        # Already connected in _setup_dro or delegated from MainWindow
        pass

    def _setup_dro(self):
        """DRO panel in probe_basic style: Axis | WORK | MACHINE | REF button."""
        container = self._t._w(QHBoxLayout, "dro_display_layout")
        if not container:
            return

        wrapper = QWidget()
        wrapper.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        glay = QGridLayout(wrapper)
        glay.setContentsMargins(8, 6, 8, 6)
        glay.setSpacing(6)
        
        btn_width = 85
        axis_width = 50
        val_width = 120 

        # ZERO ALL
        btn_zero_all = QPushButton(_t("ZERO\nALL"))
        btn_zero_all.setObjectName("dro_zero_all_btn")
        btn_zero_all.setFixedSize(btn_width, 44)
        btn_zero_all.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._t._add_class(btn_zero_all, "btn-blue")
        btn_zero_all.clicked.connect(lambda: self._zero_axis("ALL"))
        glay.addWidget(btn_zero_all, 0, 0)

        lbl_axis_hdr = QLabel(_t("AXIS"))
        self._t._add_class(lbl_axis_hdr, "dro-header")
        lbl_axis_hdr.setFixedWidth(axis_width)
        lbl_axis_hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        glay.addWidget(lbl_axis_hdr, 0, 1)

        # WCS ComboBox
        self._wcs_combo = QComboBox()
        self._wcs_combo.setFixedWidth(val_width)
        self._wcs_combo.setFixedHeight(40)
        self._wcs_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for label, index in [("G54", 1), ("G55", 2), ("G56", 3), ("G57", 4),
                              ("G58", 5), ("G59", 6), ("G59.1", 7), ("G59.2", 8), ("G59.3", 9)]:
            self._wcs_combo.addItem(label, userData=index)
        self._wcs_combo.setObjectName("wcsCombo")
        self._wcs_combo.currentIndexChanged.connect(self._on_wcs_combo_changed)
        glay.addWidget(self._wcs_combo, 0, 2)

        lbl_mach_hdr = QLabel(_t("MACHINE"))
        self._t._add_class(lbl_mach_hdr, "dro-header")
        lbl_mach_hdr.setFixedWidth(val_width)
        lbl_mach_hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        glay.addWidget(lbl_mach_hdr, 0, 3)

        lbl_dtg_hdr = QLabel(_t("DTG"))
        self._t._add_class(lbl_dtg_hdr, "dro-header")
        lbl_dtg_hdr.setFixedWidth(val_width)
        lbl_dtg_hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        glay.addWidget(lbl_dtg_hdr, 0, 4)

        # REF ALL
        self._btn_ref_all = QPushButton(_t("REF ALL"))
        self._btn_ref_all.setFixedSize(btn_width, 44)
        self._btn_ref_all.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._t._add_class(self._btn_ref_all, "btn-green")
        self._btn_ref_all.clicked.connect(self._t.motion._home_all)
        glay.addWidget(self._btn_ref_all, 0, 5)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(2)
        glay.addWidget(sep, 1, 0, 1, 6)

        for i, (axis, joint) in enumerate([("X", 0), ("Y", 1), ("Z", 2)], start=2):
            btn_zero = QPushButton(_t("ZERO\n{}").format(axis))
            btn_zero.setObjectName("dro_zero_btn")
            btn_zero.setFixedSize(btn_width, 52)
            btn_zero.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._t._add_class(btn_zero, "btn-blue")
            btn_zero.clicked.connect(lambda _=False, a=axis: self._zero_axis(a))
            glay.addWidget(btn_zero, i, 0)

            lbl_axis = QLabel(axis)
            self._t._add_class(lbl_axis, "dro-axis-label")
            lbl_axis.setFixedWidth(axis_width)
            lbl_axis.setAlignment(Qt.AlignmentFlag.AlignCenter)
            glay.addWidget(lbl_axis, i, 1)

            lbl_work = QLabel("+0.000")
            self._t._add_class(lbl_work, "dro-value")
            lbl_work.setFixedWidth(val_width)
            lbl_work.setFixedHeight(52)
            lbl_work.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            glay.addWidget(lbl_work, i, 2)

            lbl_mach = QLabel("+0.000")
            lbl_mach.setProperty("class", "dro-value dro-machine")
            lbl_mach.setFixedWidth(val_width)
            lbl_mach.setFixedHeight(52)
            lbl_mach.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            glay.addWidget(lbl_mach, i, 3)

            lbl_dtg = QLabel("+0.000")
            lbl_dtg.setProperty("class", "dro-value dro-dtg")
            lbl_dtg.setFixedWidth(val_width)
            lbl_dtg.setFixedHeight(52)
            lbl_dtg.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            glay.addWidget(lbl_dtg, i, 4)

            btn_ref = QPushButton(_t("REF {}").format(axis))
            btn_ref.setObjectName("dro_ref_btn")
            btn_ref.setFixedSize(btn_width, 52)
            btn_ref.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._t._add_class(btn_ref, "btn-green")
            glay.addWidget(btn_ref, i, 5)
            btn_ref.clicked.connect(lambda _=False, j=joint: self._t.motion._home_joint(j))

            self._dro_work[axis]    = lbl_work
            self._dro_machine[axis] = lbl_mach
            self._dro_dtg[axis]     = lbl_dtg
            self._dro_ref_btn[axis] = btn_ref

        glay.setColumnStretch(2, 1)
        glay.setColumnStretch(3, 1)
        container.addWidget(wrapper)

    def refresh(self):
        """Updates the DRO displays."""
        pos = getattr(self._t, "_last_pos", None)
        if pos is None:
            return
        g5x   = getattr(self._t.poller, "_g5x_offset", None) or [0.0, 0.0, 0.0]
        try:
            g92 = self._t.poller.stat.g92_offset[:3]
        except (AttributeError, TypeError):
            g92 = [0.0, 0.0, 0.0]

        try:
            t_off = self._t.poller.stat.tool_offset or [0.0, 0.0, 0.0]
        except AttributeError:
            t_off = [0.0, 0.0, 0.0]
            
        homed = getattr(self._t.poller, "_homed", []) or []

        all_homed = True
        for i, axis in enumerate(("X", "Y", "Z")):
            is_homed = i < len(homed) and homed[i]
            if not is_homed:
                all_homed = False
                
            work = pos[i] - g5x[i] - g92[i] - t_off[i]
            mach = pos[i]
            
            try:
                dtg_val = self._t.poller.stat.dtg[i]
            except (AttributeError, TypeError, IndexError):
                dtg_val = 0.0

            if axis in self._dro_work:
                t = f"{work:+.3f}"
                if self._dro_work[axis].text() != t:
                    self._dro_work[axis].setText(t)
            if axis in self._dro_machine:
                t = f"{mach:+.3f}"
                if self._dro_machine[axis].text() != t:
                    self._dro_machine[axis].setText(t)
            if axis in self._dro_dtg:
                t = f"{dtg_val:+.3f}"
                if self._dro_dtg[axis].text() != t:
                    self._dro_dtg[axis].setText(t)

            # probe-DRO mitsyncen
            probe_dro_work = getattr(self._t.probing_tab, "_probe_dro_work", {})
            probe_dro_mach = getattr(self._t.probing_tab, "_probe_dro_machine", {})
            if axis in probe_dro_work:
                t = f"{work:+.3f}"
                if probe_dro_work[axis].text() != t:
                    probe_dro_work[axis].setText(t)
            if axis in probe_dro_mach:
                t = f"{mach:+.3f}"
                if probe_dro_mach[axis].text() != t:
                    probe_dro_mach[axis].setText(t)

        # Tool marker only visible if all axes are homed
        sv = self._t.simple_view_mod.simple_view
        if all_homed:
            new_tp = (pos[0] - t_off[0], pos[1] - t_off[1], pos[2] - t_off[2])
            last = self._last_tool_pos
            if last is None or any(abs(new_tp[i] - last[i]) > _TOOL_EPSILON for i in range(3)):
                self._last_tool_pos = new_tp
                self._t.backplot.set_tool_position(*new_tp)
                if sv and sv.backplot:
                    sv.backplot.set_tool_position(*new_tp)
        else:
            if self._last_tool_pos is not None:
                self._last_tool_pos = None
                self._t.backplot.set_tool_position(float('nan'), float('nan'), float('nan'))
                if sv and sv.backplot:
                    sv.backplot.set_tool_position(float('nan'), float('nan'), float('nan'))

        # Simple View overlay DRO sync
        if sv and sv.isVisible():
            w_coords = [pos[i] - g5x[i] - g92[i] - t_off[i] for i in range(3)]
            m_coords = [pos[i] for i in range(3)]
            try:
                dtg_vals = list(self._t.poller.stat.dtg[:3])
            except (AttributeError, TypeError):
                dtg_vals = [0.0, 0.0, 0.0]

            sv.set_wcs(*w_coords)
            sv.set_machine(*m_coords)
            sv.set_dtg(*dtg_vals)
            
            feed = self._t.poller.stat.current_vel * 60.0
            rpm = getattr(self._t.poller, '_spindle_actual', 0.0)
            if rpm is None or rpm <= 0:
                rpm = abs(self._t.poller.stat.spindle[0]['speed'])
            sv.set_feed_rpm(feed, rpm)

    @Slot(list)
    def _on_g5x_offset(self, g5x: list):
        """WCS-Offset geändert → DRO neu berechnen + Backplot-Kreuz verschieben."""
        self.refresh()
        if self._t.poller.stat.g5x_index != 9:
            new_origin = (g5x[0], g5x[1], g5x[2])
            is_initial = not self._wcs_initialized
            changed = not is_initial and new_origin != self._t._last_wcs_origin
            
            self._t.backplot.set_wcs_origin(*new_origin)
            self._t._last_wcs_origin = new_origin
            self._wcs_initialized = True
            
            sv = self._t.simple_view_mod.simple_view
            if sv and sv.backplot:
                sv.backplot.set_wcs_origin(g5x[0], g5x[1], g5x[2])

    @Slot(int)
    def _on_g5x_index(self, g5x_index: int):
        """LinuxCNC WCS geändert → Combo synchronisieren."""
        if self._wcs_combo is None:
            return
        for i in range(self._wcs_combo.count()):
            if self._wcs_combo.itemData(i) == g5x_index:
                self._wcs_combo.blockSignals(True)
                self._wcs_combo.setCurrentIndex(i)
                self._wcs_combo.blockSignals(False)
                break

    def _zero_axis(self, axis: str):
        """Sets the WCS zero for the axis/axes."""
        if not self._wcs_combo: return
        g5x_index = self._wcs_combo.currentData()
        axis_map = {"X": "X0", "Y": "Y0", "Z": "Z0", "ALL": "X0 Y0 Z0"}
        coords = axis_map.get(axis, "X0 Y0 Z0")
        wcs_name = self._wcs_combo.currentText()
        try:
            self._t.cmd.mode(linuxcnc.MODE_MDI)
            self._t.cmd.wait_complete()
            self._t.cmd.mdi(f"G10 L20 P{g5x_index} {coords}")
            self._t.cmd.wait_complete()
            self._t.cmd.mode(linuxcnc.MODE_MANUAL)
            self._t._status(_t("ZERO {} → {}").format(axis, wcs_name))
        except Exception:
            pass

    def _on_wcs_combo_changed(self, index):
        """WCS-Auswahl → G54..G59.3 per MDI senden."""
        wcs = self._wcs_combo.itemText(index)
        try:
            self._t.cmd.mode(linuxcnc.MODE_MDI)
            self._t.cmd.wait_complete()
            self._t.cmd.mdi(wcs)
            self._t.cmd.wait_complete()
            self._t.cmd.mode(linuxcnc.MODE_MANUAL)
        except Exception:
            pass

    def _sync_wcs_from_gcodes(self, gcodes: tuple):
        """Versucht das WCS aus den aktiven GCodes zu synchronisieren (G54-G59.3)."""
        wcs_codes = {
            540: 1, 550: 2, 560: 3, 570: 4, 580: 5, 590: 6,
            591: 7, 592: 8, 593: 9
        }
        for g in gcodes:
            if g in wcs_codes:
                idx = wcs_codes[g]
                self._on_g5x_index(idx)
                break
