"""Probing tab module for ThorCNC — UI setup, probe sequences, preferences."""

import os
import linuxcnc
from PySide6.QtCore import Qt, QSize, QTimer, QPoint
from PySide6.QtWidgets import (
    QPushButton, QButtonGroup, QLineEdit, QSlider, QFrame,
    QWidget, QStackedWidget, QGridLayout, QVBoxLayout, QHBoxLayout,
    QLabel, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QSizePolicy,
)
from PySide6.QtGui import QIcon

from .base import ThorModule
from ..i18n import _t

_DIR = os.path.dirname(os.path.dirname(__file__))


class ProbingTabModule(ThorModule):
    """Manages the complete Probing tab: UI, sequences, preferences, DRO."""

    _PROBE_PREFS = [
        ("probe_tool",       "spb_probe_tool",        "SpinBox"),
        ("probe_step_off",   "dsb_probe_step_off",    "DoubleSpinBox"),
        ("probe_dia",        "dsb_probe_dia",          "DoubleSpinBox"),
        ("probe_max_xy",     "dsb_probe_max_xy",       "DoubleSpinBox"),
        ("probe_rapid",      "dsb_probe_rapid",        "DoubleSpinBox"),
        ("probe_max_z",      "dsb_probe_max_z",        "DoubleSpinBox"),
        ("probe_search",     "dsb_probe_search",       "DoubleSpinBox"),
        ("probe_xy_clear",   "dsb_probe_xy_clearance", "DoubleSpinBox"),
        ("probe_feed",       "dsb_probe_feed",         "DoubleSpinBox"),
        ("probe_z_clear",    "dsb_probe_z_clearance",  "DoubleSpinBox"),
        ("probe_extra_dep",  "dsb_probe_extra_depth",  "DoubleSpinBox"),
        ("probe_edge_w",     "dsb_probe_edge_width",   "DoubleSpinBox"),
        ("probe_motion",     "combo_probe_motion",     "ComboBox"),
        ("probe_before",     "te_probe_before",        "TextEdit"),
        ("probe_after",      "te_probe_after",         "TextEdit"),
        ("probe_auto_zero",  "btn_auto_zero_master",   "CheckButton"),
        ("probe_center_x",   "le_probe_center_x",      "LineEdit"),
        ("probe_center_y",   "le_probe_center_y",      "LineEdit"),
        ("probe_center_dia", "le_probe_center_diam",   "LineEdit"),
    ]

    def __init__(self, thorc):
        super().__init__(thorc)
        self._probe_center_inside = False
        self._probe_dro_work = {}
        self._probe_dro_machine = {}

        # ── Probe Warning State (from ProbingManager) ────────────────────────
        self._probe_warning_enabled = thorc.settings.get("probe_warning_enabled", True)
        self._probe_warning_pins_str = str(thorc.settings.get("probe_warning_pins", "0"))
        self._probe_warning_color = thorc.settings.get("probe_warning_color", "#8b1a1a")
        self._probe_warning_pins = []
        self._last_probe_warning_state = None
        self._probe_active = False
        self._parse_probe_warning_pins(self._probe_warning_pins_str)
        
        print(f"[ThorCNC] Probe Warning: {'ENABLED' if self._probe_warning_enabled else 'DISABLED'} on pins {self._probe_warning_pins}")

    def setup(self):
        self._setup_probing_tab()

    def connect_signals(self):
        pass  # All signals connected in _setup_probing_tab

    def update_marker_pos(self):
        """Public API for eventFilter delegation."""
        self._update_probe_marker_pos()

    def _setup_probing_tab(self):
        """Lädt SVG-Icons, verbindet Override-Slider und baut probe-DRO."""
        self._probe_img_dir = os.path.join(_DIR, "images", "probe")

        # ── Mode Selection Buttons ──────────────────────────────────────────
        self._probe_mode_grp = QButtonGroup(self._t)
        self._probe_mode_grp.setExclusive(True)

        for obj_name, mode_key in [
            ("btn_mode_outside", "OUTSIDE CORNERS"),
            ("btn_mode_inside",  "INSIDE CORNERS"),
            ("btn_mode_center",  "CENTER FINDER"),
            ("btn_mode_angle",   "EDGE ANGLE")
        ]:
            if btn := self._t._w(QPushButton, obj_name):
                self._probe_mode_grp.addButton(btn)
                btn.clicked.connect(lambda _=False, m=mode_key: self._probe_set_mode(m))

        # ── QStackedWidget Setup ───────────────────────────────────────────
        self._probe_stack = QStackedWidget()
        self._probe_pages = {}

        BTN_SZ  = QSize(130, 130)
        ICON_SZ = QSize(118, 108)

        def make_btn(ngc_name, btn_group):
            btn = QPushButton()
            btn.setObjectName("probe_grid_btn")
            btn.setMinimumSize(BTN_SZ)
            btn.setMaximumSize(BTN_SZ)
            btn.setIconSize(ICON_SZ)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, n=ngc_name: self._probe_run_sequence(n))
            btn_group.addButton(btn)
            return btn

        def svg(subfolder, filename):
            p = os.path.join(self._probe_img_dir, subfolder, filename)
            return QIcon(p) if os.path.exists(p) else QIcon()

        GRID_3x3 = [
            (0, 0, "corner_tl",   "corner_tl.svg"),
            (0, 1, "edge_top",    "edge_top.svg"),
            (0, 2, "corner_tr",   "corner_tr.svg"),
            (1, 0, "edge_left",   "edge_left.svg"),
            (1, 1, "center",      "center.svg"),
            (1, 2, "edge_right",  "edge_right.svg"),
            (2, 0, "corner_bl",   "corner_bl.svg"),
            (2, 1, "edge_bottom", "edge_bottom.svg"),
            (2, 2, "corner_br",   "corner_br.svg"),
        ]

        # Tooltip mapping
        TT_MAP = {
            "corner_tl": _t("Top-Left Corner"),
            "edge_top":  _t("Top Edge"),
            "corner_tr": _t("Top-Right Corner"),
            "edge_left": _t("Left Edge"),
            "center":    _t("Z Probe (Surface)"),
            "edge_right":_t("Right Edge"),
            "corner_bl": _t("Bottom-Left Corner"),
            "edge_bottom":_t("Bottom Edge"),
            "corner_br": _t("Bottom-Right Corner"),
        }

        def make_grid_page(subfolder, cells, icon_subfolder=None):
            """cells: list of (row, col, ngc_name, svg_file)"""
            if icon_subfolder is None: icon_subfolder = subfolder
            page = QWidget()
            gl = QGridLayout(page)
            gl.setSpacing(6)
            gl.setContentsMargins(0, 0, 0, 0)
            grp = QButtonGroup(page)
            grp.setExclusive(True)
            for row, col, ngc, svgf in cells:
                # Intelligently construct NGC name: don't double-prefix
                if subfolder and ngc.startswith(f"{subfolder}_"):
                    full_ngc = ngc
                else:
                    full_ngc = f"{subfolder}_{ngc}" if subfolder else ngc
                
                btn = make_btn(full_ngc, grp)
                btn.setIcon(svg(icon_subfolder, svgf))
                
                # Set Tooltip
                prefix = subfolder.capitalize() if "angle" not in subfolder else _t("Measure Angle at")
                if subfolder == "outside": prefix = _t("OUTSIDE")
                if subfolder == "inside":  prefix = _t("INSIDE")
                
                label = TT_MAP.get(ngc, ngc.replace("_", " ").title())
                btn.setToolTip(f"{prefix} {label}")
                
                gl.addWidget(btn, row, col)
            return page

        # Page 1 – Outside Corners (3×3)
        p = make_grid_page("outside", GRID_3x3)
        self._probe_stack.addWidget(p)
        self._probe_pages["OUTSIDE CORNERS"] = p

        # Page 2 – Inside Corners (3×3)
        p = make_grid_page("inside", GRID_3x3)
        self._probe_stack.addWidget(p)
        self._probe_pages["INSIDE CORNERS"] = p

        # Page 3 – Center Finder (2 Columns: Rectangular with X/Y, Round with Diam)
        p = QWidget()
        vl_cf_main = QVBoxLayout(p)
        vl_cf_main.setContentsMargins(0, 0, 0, 0)
        vl_cf_main.setSpacing(10)

        # Header: Inside/Outside Toggle
        hl_toggle = QHBoxLayout()
        self._btn_probe_center_mode = QPushButton(_t("MODE: OUTSIDE"))
        self._btn_probe_center_mode.setObjectName("btn_probe_center_mode")
        self._btn_probe_center_mode.setCheckable(True)
        self._btn_probe_center_mode.setMinimumHeight(45)
        self._btn_probe_center_mode.toggled.connect(self._on_probe_center_mode_toggled)
        hl_toggle.addStretch()
        hl_toggle.addWidget(self._btn_probe_center_mode)
        hl_toggle.addStretch()
        vl_cf_main.addLayout(hl_toggle)

        hl_cf = QHBoxLayout()
        hl_cf.setContentsMargins(0, 0, 0, 0)
        hl_cf.setSpacing(12)
        vl_cf_main.addLayout(hl_cf)

        grp_cf = QButtonGroup(p)
        grp_cf.setExclusive(True)

        # Column 1: Rectangular (Square)
        col_rect = QWidget()
        vl_rect = QVBoxLayout(col_rect)
        vl_rect.setContentsMargins(0, 0, 0, 0)
        vl_rect.setSpacing(6)
        
        # Btn X
        self._btn_rect_x = QPushButton()
        self._btn_rect_x.setMinimumSize(BTN_SZ); self._btn_rect_x.setMaximumSize(BTN_SZ)
        self._btn_rect_x.setIconSize(ICON_SZ); self._btn_rect_x.setCheckable(True); self._btn_rect_x.setObjectName("probe_grid_btn")
        self._btn_rect_x.clicked.connect(lambda: self._run_center_probe("rect_x"))
        grp_cf.addButton(self._btn_rect_x)
        vl_rect.addWidget(self._btn_rect_x, 0, Qt.AlignCenter)

        # X input
        lbl_x = QLabel("X LENGTH:"); lbl_x
        le_x = QLineEdit("0.0000"); le_x.setObjectName("le_probe_center_x")
        le_x.setAlignment(Qt.AlignCenter); le_x.setFixedWidth(130)
        le_x.setToolTip("Expected X size")
        vl_rect.addWidget(lbl_x, 0, Qt.AlignCenter)
        vl_rect.addWidget(le_x, 0, Qt.AlignCenter)

        # Btn Y
        self._btn_rect_y = QPushButton()
        self._btn_rect_y.setMinimumSize(BTN_SZ); self._btn_rect_y.setMaximumSize(BTN_SZ)
        self._btn_rect_y.setIconSize(ICON_SZ); self._btn_rect_y.setCheckable(True); self._btn_rect_y.setObjectName("probe_grid_btn")
        self._btn_rect_y.clicked.connect(lambda: self._run_center_probe("rect_y"))
        grp_cf.addButton(self._btn_rect_y)
        vl_rect.addWidget(self._btn_rect_y, 0, Qt.AlignCenter)

        # Y input
        lbl_y = QLabel("Y LENGTH:"); lbl_y
        le_y = QLineEdit("0.0000"); le_y.setObjectName("le_probe_center_y")
        le_y.setAlignment(Qt.AlignCenter); le_y.setFixedWidth(130)
        le_y.setToolTip("Expected Y size")
        vl_rect.addWidget(lbl_y, 0, Qt.AlignCenter)
        vl_rect.addWidget(le_y, 0, Qt.AlignCenter)

        vl_rect.addStretch()
        hl_cf.addWidget(col_rect)

        # Column 2: Round (Circular)
        col_round = QWidget()
        vl_round = QVBoxLayout(col_round)
        vl_round.setContentsMargins(0, 0, 0, 0)
        vl_round.setSpacing(6)
        
        self._btn_rect_round = QPushButton()
        self._btn_rect_round.setMinimumSize(BTN_SZ); self._btn_rect_round.setMaximumSize(BTN_SZ)
        self._btn_rect_round.setIconSize(ICON_SZ); self._btn_rect_round.setCheckable(True); self._btn_rect_round.setObjectName("probe_grid_btn")
        self._btn_rect_round.clicked.connect(lambda: self._run_center_probe("round"))
        grp_cf.addButton(self._btn_rect_round)
        vl_round.addWidget(self._btn_rect_round, 0, Qt.AlignCenter)

        # Diameter Input
        lbl_dia = QLabel("DIAMETER:"); lbl_dia
        le_dia = QLineEdit("0.0000")
        le_dia.setObjectName("le_probe_center_diam")
        le_dia.setAlignment(Qt.AlignCenter)
        le_dia.setFixedWidth(130)
        le_dia.setToolTip("Diameter of the round workpiece/pocket for safety")
        vl_round.addWidget(lbl_dia, 0, Qt.AlignCenter)
        vl_round.addWidget(le_dia, 0, Qt.AlignCenter)
        vl_round.addStretch()
        hl_cf.addWidget(col_round)

        # Update icons to initial (Outside) mode
        self._on_probe_center_mode_toggled(False)

        self._probe_stack.addWidget(p)
        self._probe_pages["CENTER FINDER"] = p

        # ANGLE FINDER page
        ANGLE_CELLS = [
            (0, 1, "edge_top",    "edge_top.svg"),
            (1, 0, "edge_left",   "edge_left.svg"),
            (1, 2, "edge_right",  "edge_right.svg"),
            (2, 1, "edge_bottom", "edge_bottom.svg"),
        ]
        p_angle = make_grid_page("angle", ANGLE_CELLS, icon_subfolder="outside")
        
        # Reparent Edge Width to this page
        lay_angle = p_angle.layout()
        from PySide6.QtWidgets import QDoubleSpinBox
        lbl_ew = self._t._w(QLabel, "lbl_probe_param_edge_width")
        dsb_ew = self._t._w(QDoubleSpinBox, "dsb_probe_edge_width")
        if lbl_ew and dsb_ew:
            lbl_ew.setText("MEASUREMENT DIST")
            # Create a horizontal layout for it
            hl = QHBoxLayout()
            hl.addWidget(lbl_ew)
            hl.addWidget(dsb_ew)
            lay_angle.addLayout(hl, 3, 0, 1, 3)
            lbl_ew.setVisible(True)
            dsb_ew.setVisible(True)
            # Set constraints
            dsb_ew.setMinimum(-9999)
            dsb_ew.setMaximum(9999)

        self._probe_stack.addWidget(p_angle)
        self._probe_pages["EDGE ANGLE"] = p_angle

        # ── Replace frm_probe_grid with stack ───────────────────────────────
        frm = self._t._w(QFrame, "frm_probe_grid")
        if frm:
            gl = frm.layout()
            while gl.count():
                item = gl.takeAt(0)
                if w := item.widget():
                    w.setParent(None)
            gl.setSpacing(0)
            gl.setContentsMargins(12, 12, 12, 12)
            gl.addWidget(self._probe_stack, 0, 0)
            # Fixed Home-Marker bottom-left (X=left, Y=bottom → origin)
            self._probe_marker_sz = 22
            self._probe_marker = QLabel("⌂", self._t.ui.tab_probing)
            self._probe_marker.setFixedSize(self._probe_marker_sz, self._probe_marker_sz)
            self._probe_marker.setAlignment(Qt.AlignCenter)
            self._probe_marker.setStyleSheet(
                f"background:#e67e00;color:white;border-radius:{self._probe_marker_sz//2}px;"
                "font-size:8pt;font-weight:bold;")
            self._probe_marker.setToolTip("Machine Zero")

            # Orange Corner Accent
            self._probe_home_accent = QFrame(self._t.ui.tab_probing)
            self._probe_home_accent.setFixedSize(14, 14)
            self._probe_home_accent.setStyleSheet("background:#e67e00; border-radius:3px;")
            self._probe_home_accent.lower() # Place behind icon
            
            # L-Shaped Corner Accent (inside the frame)
            self._probe_corner_accent = QFrame(frm)
            self._probe_corner_accent.setFixedSize(20, 20)
            self._probe_corner_accent.setAttribute(Qt.WA_TransparentForMouseEvents)
            
            # Install event filter to handle resize
            self._probe_grid_frm = frm
            self._probe_grid_frm.installEventFilter(self._t)
            
            # Remove the previous unsuccessful accent
            if hasattr(self, "_probe_home_accent"):
                self._probe_home_accent.deleteLater()
                del self._probe_home_accent
            
            # Initial placement
            QTimer.singleShot(100, self._update_probe_marker_pos)

        self._probe_set_mode("OUTSIDE CORNERS")

        # ── CLEAR Buttons ─────────────────────────────────────────────────────
        for btn_name, fields in [
            ("btn_probe_clear_x", ["le_probe_x_minus", "le_probe_x_ctr",
                                   "le_probe_x_plus",  "le_probe_x_width"]),
            ("btn_probe_clear_y", ["le_probe_y_minus", "le_probe_y_ctr",
                                   "le_probe_y_plus",  "le_probe_y_width"]),
            ("btn_probe_clear_all", ["le_probe_x_minus", "le_probe_x_ctr",
                                     "le_probe_x_plus",  "le_probe_x_width",
                                     "le_probe_y_minus", "le_probe_y_ctr",
                                     "le_probe_y_plus",  "le_probe_y_width",
                                     "le_probe_z", "le_probe_diam",
                                     "le_probe_delta", "le_probe_angle",
                                     "le_probe_center_x", "le_probe_center_y",
                                     "le_probe_center_diam"]),
        ]:
            if btn := self._t._w(QPushButton, btn_name):
                btn.clicked.connect(
                    lambda _=False, flds=fields: self._probe_clear_fields(flds))

        # ── AUTO ZERO ────────────────────────────────────────────────────────
        self._btn_probe_auto_zero = self._t.ui.findChild(QPushButton, "btn_auto_zero_master")
        if self._btn_probe_auto_zero:
            self._btn_probe_auto_zero.setCheckable(True)
            # Loading of Auto Zero is now handled within _probe_prefs_load()

        # ── Load and Connect Prefs ───────────────────────────────────────────
        self._probe_prefs_load()
        self._probe_prefs_connect()
        self._write_probe_before_after() # Synchronize NGC files at startup

        # ── Setup Probe DRO ────────────────────────────────────────────────
        self._setup_probe_dro()

    def _on_probe_center_mode_toggled(self, inside: bool):
        """Umschaltung zwischen OUTSIDE und INSIDE."""
        self._probe_center_inside = inside
        self._btn_probe_center_mode.setText(_t("MODE: INSIDE") if inside else _t("MODE: OUTSIDE"))
        
        # Helper for SVGs
        def svg(filename):
            p = os.path.join(self._probe_img_dir, "center_finder", filename)
            return QIcon(p) if os.path.exists(p) else QIcon()

        # Update icons
        if inside:
            self._btn_rect_x.setIcon(svg("inside_rect_x.svg"))
            self._btn_rect_y.setIcon(svg("inside_rect_y.svg"))
            self._btn_rect_round.setIcon(svg("inside_round.svg"))
            self._btn_rect_x.setToolTip("Find X center of internal Valley/Pocket")
            self._btn_rect_y.setToolTip("Find Y center of internal Valley/Pocket")
            self._btn_rect_round.setToolTip("Find center of circular Pocket")
        else:
            self._btn_rect_x.setIcon(svg("center_rect_x.svg"))
            self._btn_rect_y.setIcon(svg("center_rect_y.svg"))
            self._btn_rect_round.setIcon(svg("center_round.svg"))
            self._btn_rect_x.setToolTip("Find X center of rectangular Boss/Ridge")
            self._btn_rect_y.setToolTip("Find Y center of rectangular Boss/Ridge")
            self._btn_rect_round.setToolTip("Find center of circular Boss")

    def _run_center_probe(self, base_type: str):
        """NGC-Name basierend auf aktuellem Modus ermitteln und starten."""
        if base_type == "rect_x":
            name = "inside_rect_x" if self._probe_center_inside else "center_rect_x"
        elif base_type == "rect_y":
            name = "inside_rect_y" if self._probe_center_inside else "center_rect_y"
        else: # round
            name = "inside_round" if self._probe_center_inside else "center_round"
        
        self._probe_run_sequence(name)

    def _update_probe_marker_pos(self):
        """Reposition the Home marker based on INI limits. Badge-style on the edge."""
        if hasattr(self, "_probe_marker") and hasattr(self, "_probe_grid_frm"):
            w = self._probe_grid_frm.width()
            h = self._probe_grid_frm.height()
            sz = self._probe_marker_sz
            
            # Absolute position relative to the tab
            pos_in_tab = self._probe_grid_frm.mapTo(self._t.ui.tab_probing, QPoint(0, 0))
            
            # Sit exactly on the border (half icon size)
            badge_offset = - (sz // 2)
            
            # Default: Bottom-Left
            x = pos_in_tab.x() + badge_offset
            y = pos_in_tab.y() + h + badge_offset

            # Try to detect from INI
            if self._t.ini:
                try:
                    # X Axis (Joint 0)
                    h_x = float(self._t.ini.find("JOINT_0", "HOME") or 0.0)
                    max_x = float(self._t.ini.find("AXIS_X", "MAX_LIMIT") or 1000.0)
                    if abs(h_x - max_x) < 5.0:
                        x = pos_in_tab.x() + w + badge_offset # Right

                    # Y Axis (Joint 1)
                    h_y = float(self._t.ini.find("JOINT_1", "HOME") or 0.0)
                    max_y = float(self._t.ini.find("AXIS_Y", "MAX_LIMIT") or 1000.0)
                    if abs(h_y - max_y) < 5.0:
                        y = pos_in_tab.y() + badge_offset # Top
                except: pass

            self._probe_marker.move(x, y)
            self._probe_marker.raise_()
            self._probe_marker.show()
            
            # Position the L-accent inside the frame corner
            if hasattr(self, "_probe_corner_accent"):
                is_right = (x > pos_in_tab.x() + (w // 2))
                is_bottom = (y > pos_in_tab.y() + (h // 2))
                
                # Create a CSS that colors only the corner borders
                border_x = "right" if is_right else "left"
                border_y = "bottom" if is_bottom else "top"
                
                self._probe_corner_accent.setStyleSheet(
                    f"background: transparent; border-{border_x}: 4px solid #e67e00; border-{border_y}: 4px solid #e67e00;"
                )
                
                # Move to the absolute corner of the frame
                ax = w - 20 if is_right else 0
                ay = h - 20 if is_bottom else 0
                self._probe_corner_accent.move(ax, ay)
                self._probe_corner_accent.show()
                self._probe_corner_accent.raise_()

    def _setup_probe_dro(self):
        """Builds compact (read-only) DRO in Probing tab bottom bar."""
        container = self._t.ui.findChild(QHBoxLayout, "probe_dro_display_layout")
        if not container:
            return

        self._probe_dro_work    = {}
        self._probe_dro_machine = {}

        wrapper = QWidget()
        wrapper.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        vbox = QVBoxLayout(wrapper)
        vbox.setContentsMargins(8, 4, 8, 4)
        vbox.setSpacing(4)

        for axis in ("X", "Y", "Z"):
            row = QWidget()
            row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(6)

            lbl_axis = QLabel(axis)
            lbl_axis.setObjectName("dro_axis_label")
            lbl_axis.setFixedWidth(36)
            lbl_axis.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hl.addWidget(lbl_axis)

            lbl_work = QLabel("+0.000")
            lbl_work.setObjectName("dro_work")
            lbl_work.setFixedWidth(110)
            lbl_work.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            hl.addWidget(lbl_work)

            lbl_mach = QLabel("+0.000")
            lbl_mach.setObjectName("dro_machine")
            lbl_mach.setFixedWidth(110)
            lbl_mach.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            hl.addWidget(lbl_mach)

            hl.addStretch()
            vbox.addWidget(row)
            self._probe_dro_work[axis]    = lbl_work
            self._probe_dro_machine[axis] = lbl_mach

        container.addWidget(wrapper)

    def _probe_prefs_load(self):
        for key, wname, wtype in self._PROBE_PREFS:
            val = self._t.settings.get(key)
            if val is None:
                continue
            if wtype == "SpinBox":
                if w := self._t._w(QSpinBox, wname):
                    w.setValue(int(val))
            elif wtype == "DoubleSpinBox":
                if w := self._t._w(QDoubleSpinBox, wname):
                    w.setValue(float(val))
            elif wtype == "ComboBox":
                if w := self._t._w(QComboBox, wname):
                    idx = w.findText(str(val))
                    if idx >= 0:
                        w.setCurrentIndex(idx)
            elif wtype == "TextEdit":
                if w := self._t._w(QTextEdit, wname):
                    w.setPlainText(str(val))
            elif wtype == "LineEdit":
                if w := self._t._w(QLineEdit, wname):
                    w.setText(str(val))
            elif wtype == "CheckButton":
                if w := self._t._w(QPushButton, wname):
                    # For Auto-Zero, default to True if pref is missing
                    is_on = (val.lower() == 'true') if isinstance(val, str) else bool(val)
                    w.setChecked(is_on)
                    self._on_probe_auto_zero_toggled(is_on)

    def _probe_prefs_connect(self):
        """Verbindet alle Probe-Widgets mit autosave."""
        for key, wname, wtype in self._PROBE_PREFS:
            if wtype == "SpinBox":
                if w := self._t._w(QSpinBox, wname):
                    w.valueChanged.connect(
                        lambda v, k=key: self._probe_pref_save(k, v))
            elif wtype == "DoubleSpinBox":
                if w := self._t._w(QDoubleSpinBox, wname):
                    w.valueChanged.connect(
                        lambda v, k=key: self._probe_pref_save(k, v))
            elif wtype == "ComboBox":
                if w := self._t._w(QComboBox, wname):
                    w.currentTextChanged.connect(
                        lambda v, k=key: self._probe_pref_save(k, v))
            elif wtype == "TextEdit":
                if w := self._t._w(QTextEdit, wname):
                    w.textChanged.connect(
                        lambda k=key, wn=wname:
                            self._probe_pref_save(
                                k, self._t._w(QTextEdit, wn).toPlainText()))
            elif wtype == "LineEdit":
                if w := self._t._w(QLineEdit, wname):
                    w.textChanged.connect(
                        lambda v, k=key: self._probe_pref_save(k, v))
            elif wtype == "CheckButton":
                if w := self._t._w(QPushButton, wname):
                    w.toggled.connect(
                        lambda v, k=key: self._probe_pref_save(k, v))

        
    def _on_probe_auto_zero_toggled(self, on: bool):
        """Handler für den Master Auto-Zero Button: (Zusatzlogik falls nötig)."""
        # Falls später noch Logik nötig ist, hier einfügen.
        # Das eigentliche Speichern wird jetzt über _probe_prefs_connect() via 'CheckButton' erledigt.
        pass

    def _probe_pref_save(self, key: str, value):
        self._t.settings.set(key, value)
        self._t.settings.save()
        if key in ("probe_before", "probe_after"):
            self._write_probe_before_after()

    def _write_probe_before_after(self):
        """Schreibt before_probe.ngc und after_probe.ngc ins Probing-Verzeichnis."""
        ngc_dir = self._probe_ngc_dir()
        before_code = ""
        after_code = ""
        if te := self._t._w(QTextEdit, "te_probe_before"):
            before_code = te.toPlainText().strip()
        if te := self._t._w(QTextEdit, "te_probe_after"):
            after_code = te.toPlainText().strip()
        
        try:
            # before_probe.ngc schreiben
            before_path = os.path.join(ngc_dir, "before_probe.ngc")
            with open(before_path, "w", encoding="utf-8") as f:
                f.write("O<before_probe> sub\n")
                if before_code:
                    f.write(f"  {before_code}\n")
                f.write("O<before_probe> endsub\n")
                f.write("M2\n")

            # after_probe.ngc schreiben
            after_path = os.path.join(ngc_dir, "after_probe.ngc")
            with open(after_path, "w", encoding="utf-8") as f:
                f.write("O<after_probe> sub\n")
                if after_code:
                    f.write(f"  {after_code}\n")
                f.write("O<after_probe> endsub\n")
                f.write("M2\n")
        except Exception as e:
            self._t._status(f"Could not write probe NGC files: {e}", error=True)

    def _probe_clear_fields(self, field_names: list):
        for name in field_names:
            if le := self._t._w(QLineEdit, name):
                le.setText("0")

    def _on_probe_v_override_changed(self, val: int):
        if lbl := self._t._w(QLabel, "probe_v_override_status"):
            lbl.setText(f"V {val}%")
        self._t.cmd.feedrate(val / 100.0)
        self._t.cmd.spindleoverride(val / 100.0)

    def _on_probe_v_override_to_100(self):
        if s := self._t._w(QSlider, "probe_v_override_slider"):
            s.setValue(100)
        if lbl := self._t._w(QLabel, "probe_v_override_status"):
            lbl.setText("V 100%")
        self._t.cmd.feedrate(1.0)
        self._t.cmd.spindleoverride(1.0)

    def _probe_set_mode(self, mode: str):
        if lbl := self._t._w(QLabel, "lbl_probe_section_title"):
            lbl.setText(_t(mode))

        # Update button highlights
        btn_map = {
            "OUTSIDE CORNERS": "btn_mode_outside",
            "INSIDE CORNERS":  "btn_mode_inside",
            "CENTER FINDER":   "btn_mode_center",
            "EDGE ANGLE":      "btn_mode_angle"
        }
        if mode in btn_map:
            if btn := self._t._w(QPushButton, btn_map[mode]):
                btn.setChecked(True)

        if hasattr(self, "_probe_pages") and mode in self._probe_pages:
            self._probe_stack.setCurrentWidget(self._probe_pages[mode])

    def _probe_ngc_dir(self) -> str:
        """
        Gibt das NGC-Verzeichnis für Probing zurück.
        Priorität:
        1. 'subroutines/probing' relativ zur INI
        2. 'subroutines/probing' im PROGRAM_PREFIX
        3. PROGRAM_PREFIX aus der INI
        """
        search_dirs = []
        if self._t.ini_path:
            search_dirs.append(os.path.dirname(os.path.abspath(self._t.ini_path)))
            
        if self._t.ini:
            prefix = self._t.ini.find("DISPLAY", "PROGRAM_PREFIX")
            if prefix:
                prefix = os.path.expanduser(prefix)
                if not os.path.isabs(prefix) and self._t.ini_path:
                    prefix = os.path.abspath(os.path.join(os.path.dirname(self._t.ini_path), prefix))
                search_dirs.append(prefix)
        
        search_dirs.append(os.path.expanduser("~/linuxcnc/nc_files"))
        
        for base in search_dirs:
            sub = os.path.join(base, "subroutines", "probing")
            if os.path.isdir(sub):
                return sub
                
        # Fallback: Erster gefundener Basis-Ordner oder Default
        return search_dirs[1] if len(search_dirs) > 1 else search_dirs[0]

    def _probe_run_sequence(self, ngc_name: str):
        """
        Schreibt before_probe.ngc / after_probe.ngc und erzeugt
        probe_run.ngc, das die drei Dateien der Reihe nach aufruft,
        dann lädt und startet es.

        Ablauf:  before_probe.ngc → <ngc_name>.ngc → after_probe.ngc
        """
        ngc_dir = self._probe_ngc_dir()

        # Safety check: Is a tool loaded and is it the correct probe tool?
        current_tool = self._t.poller.stat.tool_in_spindle
        probe_tool_sb = self._t._w(QSpinBox, "spb_probe_tool")
        target_probe_tool = probe_tool_sb.value() if probe_tool_sb else 0

        if current_tool == 0:
            self._t._status(_t("Probing canceled: No tool loaded (T0)"), error=True)
            return

        if current_tool != target_probe_tool:
            self._t._status(f"Probing canceled: Tool T{current_tool} is not the configured probe tool T{target_probe_tool}!", error=True)
            return

        before_te = self._t._w(QTextEdit, "te_probe_before")
        after_te  = self._t._w(QTextEdit, "te_probe_after")
        before_code = before_te.toPlainText().strip() if before_te else ""
        after_code  = after_te.toPlainText().strip()  if after_te  else ""

        # before_probe.ngc schreiben
        before_path = os.path.join(ngc_dir, "before_probe.ngc")
        with open(before_path, "w") as f:
            f.write("O<before_probe> sub\n")
            if before_code:
                f.write(f"  {before_code}\n")
            f.write("O<before_probe> endsub\n")
            f.write("M2\n")

        # after_probe.ngc schreiben
        after_path = os.path.join(ngc_dir, "after_probe.ngc")
        with open(after_path, "w") as f:
            f.write("O<after_probe> sub\n")
            if after_code:
                f.write(f"  {after_code}\n")
            f.write("O<after_probe> endsub\n")
            f.write("M2\n")

        # Probe-NGC prüfen
        probe_path = os.path.join(ngc_dir, f"{ngc_name}.ngc")
        if not os.path.exists(probe_path):
            self._t._status(f"Probe NGC not found: {ngc_name}.ngc")
            return

        # Parameter für Center Finder und Corners/Edges sammeln
        params = ""
        is_corner_edge = ngc_name.startswith("outside_") or ngc_name.startswith("inside_") or ngc_name.startswith("angle_")
        if ngc_name.startswith("center_") or is_corner_edge:
            def val(name, default="0.0"):
                if w := self._t._w(QLineEdit, name): return w.text() or default
                if w := self._t._w(QDoubleSpinBox, name): return str(w.value())
                return default

            max_xy = val("dsb_probe_max_xy")
            max_z  = val("dsb_probe_max_z")
            s_vel  = val("dsb_probe_search")
            p_vel  = val("dsb_probe_feed")
            z_cl   = val("dsb_probe_z_clearance")
            dep    = val("dsb_probe_extra_depth")

            auto_zero = 0
            if btn := getattr(self, "_btn_probe_auto_zero", None):
                auto_zero = 1 if btn.isChecked() else 0

            dia    = val("dsb_probe_dia")

            rapid  = val("dsb_probe_rapid")
            xy_cl  = val("dsb_probe_xy_clearance")
            step_off = val("dsb_probe_step_off")

            if ngc_name in ("center_rect", "center_rect_x", "center_rect_y",
                            "inside_rect", "inside_rect_x", "inside_rect_y"):
                lx = val("le_probe_center_x")
                ly = val("le_probe_center_y")
                params = f" [{lx}] [{ly}] [{max_xy}] [{max_z}] [{s_vel}] [{p_vel}] [{z_cl}] [{dep}] [{auto_zero}] [{dia}] [{rapid}] [{xy_cl}] [{step_off}]"
            elif ngc_name in ("center_round", "inside_round"):
                cdia = val("le_probe_center_diam")
                params = f" [{cdia}] [0] [{max_xy}] [{max_z}] [{s_vel}] [{p_vel}] [{z_cl}] [{dep}] [{auto_zero}] [{dia}] [{rapid}] [{xy_cl}] [{step_off}]"
            elif is_corner_edge:
                # For corners and edges: #1 Width, #2-9 as usual, #10 Dia, #11 Rapid, #12 XY_Cl, #13 Step_Off
                ew = val("dsb_probe_edge_width")
                params = f" [{ew}] [0] [{max_xy}] [{max_z}] [{s_vel}] [{p_vel}] [{z_cl}] [{dep}] [{auto_zero}] [{dia}] [{rapid}] [{xy_cl}] [{step_off}]"

        # Wrapper-Datei erzeugen: ruft alle drei nacheinander auf
        run_path = os.path.join(ngc_dir, "probe_run.ngc")
        with open(run_path, "w") as f:
            f.write("; ThorCNC – Probe sequence\n")
            f.write(f"O<before_probe> call\n")
            f.write(f"O<{ngc_name}> call {params}\n")
            f.write(f"O<after_probe> call\n")
            f.write("M2\n")

        try:
            self._t.cmd.mode(1)   # MANUAL → AUTO benötigt erst MANUAL
            self._t.cmd.wait_complete()
            self._t.cmd.mode(2)   # AUTO
            self._t.cmd.wait_complete()
            self._t.cmd.program_open(run_path)
            self._t.cmd.auto(0, 0)   # AUTO_RUN from line 0
            self._t._status(f"Probe: {ngc_name}")
        except Exception as e:
            self._t._status(f"Probe error: {e}")

    def set_sim_probe(self, state: bool):
        """Setzt den simulierten Probe-Pin über die HAL-Komponente."""
        if self._t._hal_comp:
            try:
                self._t._hal_comp["probe-sim"] = state
                self._t._status(f"PROBE SIM: {'[ AKTIV ]' if state else '[ INAKTIV ]'}")
            except Exception as e:
                self._t._status(f"PROBE SIM error: {e}")

    # ── Probe Warning Logic (Merged from ProbingManager) ───────────────────

    def update_probe_warning(self, dout):
        """Update probe warning based on digital outputs (called from _on_digital_out_changed)."""
        if not self._probe_warning_enabled:
            return

        is_active = False
        try:
            for idx in self._probe_warning_pins:
                if 0 <= idx < len(dout):
                    if dout[idx] == 1:
                        is_active = True
                        break

            if self._last_probe_warning_state != is_active:
                print(f"[DEBUG] Probe Warning state changed: {is_active} (Pins: {self._probe_warning_pins})")
                self._last_probe_warning_state = is_active
        except Exception as e:
            print(f"[DEBUG] Error in update_probe_warning: {e}")
            return

        self._probe_active = is_active

        if hasattr(self._t, "status_bar") and self._t.status_bar:
            frame = self._t.status_bar
            if frame.property("probe_active") != is_active:
                frame.setProperty("probe_active", is_active)

                if is_active:
                    color = self._probe_warning_color
                    frame.setStyleSheet(
                        f"QFrame#bottomBarFrame {{ border: 6px solid {color} !important; }}"
                    )
                else:
                    frame.setStyleSheet("")

                frame.style().unpolish(frame)
                frame.style().polish(frame)
                frame.update()

    def connect_settings_widgets(self, cb_warn, le_pins, btn_color):
        """Connect settings tab widgets (called from _setup_settings_tab)."""
        cb_warn.setChecked(self._probe_warning_enabled)
        cb_warn.toggled.connect(self._on_probe_warning_enabled_changed)
        le_pins.setText(self._probe_warning_pins_str)
        le_pins.textChanged.connect(self._on_probe_warning_pins_changed)
        
        from PySide6.QtWidgets import QPushButton
        if isinstance(btn_color, QPushButton):
            btn_color.clicked.connect(self._pick_probe_warning_color)
            self._btn_probe_color = btn_color
            self._update_probe_color_button()

    def _parse_probe_warning_pins(self, text: str):
        """Parses comma-separated string of pins into self._probe_warning_pins list."""
        self._probe_warning_pins = []
        if text:
            try:
                parts = text.replace(" ", "").split(",")
                for p in parts:
                    if p.isdigit():
                        self._probe_warning_pins.append(int(p))
            except:
                self._probe_warning_pins = [0]
        if not self._probe_warning_pins:
            self._probe_warning_pins = [0]

    def _update_probe_color_button(self):
        """Updates the color button visual to match current warning color."""
        if hasattr(self, "_btn_probe_color"):
            c = self._probe_warning_color
            self._btn_probe_color.setStyleSheet(f"background-color: {c};")

    def _on_probe_warning_enabled_changed(self, enabled: bool):
        self._probe_warning_enabled = enabled
        self._t.settings.set("probe_warning_enabled", enabled)
        self._t.settings.save()
        if hasattr(self._t, "_last_dout"):
            self.update_probe_warning(self._t._last_dout)

    def _on_probe_warning_pins_changed(self, text: str):
        self._probe_warning_pins_str = text
        self._t.settings.set("probe_warning_pins", text)
        self._t.settings.save()
        self._parse_probe_warning_pins(text)
        if hasattr(self._t, "_last_dout"):
            self.update_probe_warning(self._t._last_dout)

    def _pick_probe_warning_color(self):
        """Opens color picker for probe warning color."""
        from PySide6.QtWidgets import QColorDialog
        from PySide6.QtGui import QColor
        initial = QColor(self._probe_warning_color)
        color = QColorDialog.getColor(initial, self._t.ui, _t("Pick Probe Warning Color"))
        if color.isValid():
            self._probe_warning_color = color.name()
            self._t.settings.set("probe_warning_color", self._probe_warning_color)
            self._t.settings.save()
            self._update_probe_color_button()
            self.update_probe_warning(self._t._last_dout if hasattr(self._t, "_last_dout") else [])

