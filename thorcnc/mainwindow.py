"""
ThorCNC Main Window
Loads the UI converted from probe_basic.ui and connects all widgets
directly to LinuxCNC via custom implementations (no qtpyvcp).
"""
import os
import re
import linuxcnc
from PySide6.QtWidgets import QMainWindow, QHBoxLayout, QLabel, QFrame, QPushButton, QTableWidgetItem
from PySide6.QtCore import Qt, QObject, Slot, QTimer, QPropertyAnimation, QEasingCurve, QByteArray
from PySide6.QtUiTools import QUiLoader

from .status_poller import StatusPoller
from .gcode_parser import parse_file
from .widgets.gcode_view import GCodeView
from .widgets.backplot import BackplotWidget
from .widgets.tool_dialog import ToolSelectionDialog
from .widgets.simple_view import SimpleView
# from .widgets.opt_options import OptOptionsDialog

_DIR = os.path.dirname(__file__)

class NumericTableWidgetItem(QTableWidgetItem):
    def __lt__(self, other):
        try:
            return float(self.text()) < float(other.text())
        except (ValueError, TypeError):
            return super().__lt__(other)

class ThorCNC(QObject):
    """
    Controller class. The loaded QMainWindow from probe_basic.ui IS the window.
    """

    def __init__(self, ini_path: str = "", parent=None):
        super().__init__(parent)

        self.ini_path = ini_path or os.environ.get("INI_FILE_NAME", "")
        self.ini = linuxcnc.ini(self.ini_path) if self.ini_path else None
        self.stat = linuxcnc.stat()
        self.cmd = linuxcnc.command()
        self.is_single_block = False
        
        self._jog_velocity = 100.0  # mm/min or inch/min default
        self._jog_increment = 0.0   # 0.0 means continuous
        
        # State tracking for dynamic run buttons
        self._is_machine_on = False
        self._has_file = False
        self._last_toolpath = None
        self._last_wcs_origin = (0.0, 0.0, 0.0)
        self._interp_state = linuxcnc.INTERP_IDLE
        self._is_spindle_running = False
        self._user_program = ""   # User loaded main program
        self._current_gcodes = ()
        self._current_mcodes = ()
        self._probe_center_inside = False
        self._load_settings()
        
        # Probe Warning Settings
        self._probe_warning_enabled = self.settings.get("probe_warning_enabled", True)
        self._probe_warning_pins_str = str(self.settings.get("probe_warning_pins", "0"))
        self._probe_warning_color = self.settings.get("probe_warning_color", "#8b1a1a")
        self._parse_probe_warning_pins(self._probe_warning_pins_str)
        
        print(f"[ThorCNC] Probe Warning: {'ENABLED' if self._probe_warning_enabled else 'DISABLED'} on pins {self._probe_warning_pins}")
        self._load_ui()
        self._replace_custom_widgets()
        self._restore_window_state()
        self._setup_dro()
        self._hal_comp = None
        self._setup_hal()
        self._setup_poller()
        self._setup_file_manager()
        self._setup_tool_table()
        self._setup_offsets_tab()
        self._setup_probing_tab()
        self._setup_html_tab()
        self._setup_settings_tab()
        self._connect_signals()
        self._setup_opt_jalousie()
        
        # Performance/Throttle state
        self._last_gui_pos = [0.0, 0.0, 0.0]
        self._last_gui_rpm = 0.0
        self._last_gui_load = -1.0
        
        # Tool-Change Handler
        self.poller.tool_change_request.connect(self._on_tool_change_request)
        
        self._apply_ini_settings()
        
        # Start in MAIN tab
        from PySide6.QtWidgets import QTabWidget
        if tab := self._w(QTabWidget, "tabWidget"):
            tab.setCurrentIndex(0)

    def _add_class(self, widget, class_name: str):
        """Helper to add a QSS class and ensure it's applied."""
        if not widget: return
        widget.setProperty("class", class_name)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
    # ── Settings & State ──────────────────────────────────────────────────────
    
    def _load_settings(self):
        from .settings import SettingsManager
        prefs_file = "thorcnc.prefs"
        ini_dir = os.path.dirname(self.ini_path) if self.ini_path else os.path.expanduser("~")
        if self.ini:
            p = self.ini.find("DISPLAY", "PREFS_FILE")
            if p:
                prefs_file = p
        
        prefs_path = os.path.expanduser(prefs_file)
        if not os.path.isabs(prefs_path):
            prefs_path = os.path.abspath(os.path.join(ini_dir, prefs_path))
            
        self.settings = SettingsManager(prefs_path)
        
        if self.settings.is_new:
            self._warn_missing_prefs = True
        else:
            self._warn_missing_prefs = False

    def _restore_window_state(self):
        from PySide6.QtCore import QByteArray
        geom = self.settings.get("window_geometry")
        state = self.settings.get("window_state")
        
        if geom:
            self.ui.restoreGeometry(QByteArray.fromHex(geom.encode()))
        if state:
            self.ui.restoreState(QByteArray.fromHex(state.encode()))
            
        # Splitter main
        ms_state = self.settings.get("main_splitter")
        if ms_state:
            from PySide6.QtWidgets import QSplitter
            sp = self._w(QSplitter, "mainSplitter")
            if sp: sp.restoreState(QByteArray.fromHex(ms_state.encode()))
            
        fs_state = self.settings.get("file_splitter")
        if fs_state:
            from PySide6.QtWidgets import QSplitter
            sp = self._w(QSplitter, "fileSplitter")
            if sp: sp.restoreState(QByteArray.fromHex(fs_state.encode()))
            
        if not geom and not state:
            self.ui.showMaximized()

    # ── UI laden ──────────────────────────────────────────────────────────────

    def _load_ui(self):
        loader = QUiLoader()
        ui_file = os.path.join(_DIR, "thorcnc.ui")
        # Kein Parent → QMainWindow bleibt eigenständig, kein Doppel-Wrap
        self.ui = loader.load(ui_file)
        
        # Load modular status bar
        from PySide6.QtWidgets import QWidget, QVBoxLayout
        status_ui_file = os.path.join(_DIR, "widgets", "status_bar.ui")
        if os.path.exists(status_ui_file):
            status_container = self.ui.findChild(QWidget, "statusBarContainer")
            if status_container:
                container_layout = QVBoxLayout(status_container)
                container_layout.setContentsMargins(0, 0, 0, 0)
                self.status_bar = loader.load(status_ui_file, status_container)
                container_layout.addWidget(self.status_bar)
            else:
                self.status_bar = self.ui
        else:
            self.status_bar = self.ui

        # Load Sidebar Modules (Split between Left and Right)
        from PySide6.QtWidgets import QFrame, QSizePolicy, QVBoxLayout
        right_panel = self.ui.findChild(QFrame, "rightPanel")
        left_panel  = self.ui.findChild(QFrame, "runControlsPanel")
        
        if right_panel:
            r_lay = right_panel.layout()
            if not r_lay: r_lay = QVBoxLayout(right_panel)
            r_lay.setContentsMargins(10, 0, 10, 0)
            r_lay.setSpacing(10)
            
            # Use left layout for run_controls if present
            l_lay = None
            if left_panel:
                l_lay = left_panel.layout()
                if not l_lay:
                    # Fallback lookup by name
                    l_lay = left_panel.findChild(QVBoxLayout, "runControlsLayout")
                
                if not l_lay:
                    l_lay = QVBoxLayout(left_panel)
                
                l_lay.setContentsMargins(0, 0, 0, 0)
                l_lay.setSpacing(0)

            for m_name in ["jog_panel", "spindle_panel", "run_controls"]:
                mod_file = os.path.join(_DIR, "widgets", f"{m_name}.ui")
                if os.path.exists(mod_file):
                    sub_w = loader.load(mod_file, self.ui)
                    if sub_w:
                        sub_w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
                        if hasattr(sub_w, 'layout') and sub_w.layout():
                            sub_w.layout().setContentsMargins(0, 0, 0, 0)
                                
                        if m_name == "run_controls":
                            sub_w.setObjectName("runControls")
                            from PySide6.QtCore import Qt
                            sub_w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                            sub_w.setFixedHeight(230)
                            if l_lay:
                                l_lay.addWidget(sub_w)
                            else:
                                r_lay.addWidget(sub_w)
                        else:
                            r_lay.addWidget(sub_w)
                        
                        if m_name == "spindle_panel":
                            r_lay.addStretch()
            
            # Ensure E-Stop/Power is at the bottom of the right panel
            estop_grp = self.ui.findChild(QFrame, "estopPowerGroup")
            if estop_grp and r_lay:
                r_lay.addWidget(estop_grp)

    def _replace_custom_widgets(self):
        """Replace GCodeEditor and VTKBackPlot with custom implementations."""
        from PySide6.QtWidgets import (QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
                                       QPushButton, QStackedWidget, QLineEdit,
                                       QListWidget, QSizePolicy)

        # ── GCode-Panel: Buttons sind fix in der UI (gcodeToggleBar)
        #    Hier nur den gcodeEditor-Placeholder durch QStackedWidget ersetzen
        old_gcode = self.ui.findChild(QWidget, "gcodeEditor")
        parent_gc = old_gcode.parent() if old_gcode else None

        # Delete redundant buttons from the loaded UI to avoid duplication and save resources
        for btn_name in ["btn_find_m6", "btn_main_zoom_in", "btn_main_zoom_out"]:
            if btn := self.ui.findChild(QPushButton, btn_name):
                if btn.parent() and btn.parent().layout():
                    btn.parent().layout().removeWidget(btn)
                btn.deleteLater()

        # Stack: Seite 0 = GCodeView, Seite 1 = MDI-Page
        self._gcode_mdi_stack = QStackedWidget()
        self._gcode_mdi_stack.setObjectName("gcodeEditor")

        # Seite 0: GCode-Editor mit Header
        gcode_container = QWidget()
        gcode_lay = QVBoxLayout(gcode_container)
        gcode_lay.setContentsMargins(0, 0, 0, 0)
        gcode_lay.setSpacing(0)

        # ── GCode Header ──
        self._gcode_header = QFrame()
        self._gcode_header.setObjectName("gcodeHeader")
        h_lay = QHBoxLayout(self._gcode_header)
        h_lay.setContentsMargins(4, 4, 4, 4)
        h_lay.setSpacing(6)

        # Find M6
        self._btn_find_m6 = QPushButton("FIND M6")
        self._btn_find_m6.setObjectName("btn_find_m6")
        self._btn_find_m6.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_find_m6.clicked.connect(self._find_next_m6)
        h_lay.addWidget(self._btn_find_m6)

        h_lay.addStretch()

        # Edit Toggle
        self._btn_edit_gcode = QPushButton("EDIT")
        self._btn_edit_gcode.setCheckable(True)
        self._btn_edit_gcode.setObjectName("btn_edit_gcode")
        self._btn_edit_gcode.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_edit_gcode.clicked.connect(self._on_toggle_gcode_edit)
        h_lay.addWidget(self._btn_edit_gcode)

        # Save Button
        self._btn_save_gcode = QPushButton("SAVE")
        self._btn_save_gcode.setObjectName("btn_save_gcode")
        self._btn_save_gcode.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_save_gcode.clicked.connect(self._on_save_gcode)
        self._btn_save_gcode.setEnabled(False) # Only if edited? Or always?
        h_lay.addWidget(self._btn_save_gcode)

        # Zoom Buttons
        self._btn_main_zoom_out = QPushButton("-")
        self._btn_main_zoom_out.setObjectName("btn_main_zoom_out")
        self._btn_main_zoom_out.clicked.connect(lambda: self.gcode_view.zoomOut(1))
        h_lay.addWidget(self._btn_main_zoom_out)

        self._btn_main_zoom_in = QPushButton("+")
        self._btn_main_zoom_in.setObjectName("btn_main_zoom_in")
        self._btn_main_zoom_in.clicked.connect(lambda: self.gcode_view.zoomIn(1))
        h_lay.addWidget(self._btn_main_zoom_in)

        gcode_lay.addWidget(self._gcode_header)

        # GCodeView
        self.gcode_view = GCodeView()
        self.gcode_view.zoom_changed.connect(
            lambda s: (self.settings.set("viewer_gcode_font_size", s), self.settings.save()))

        v_size = self.settings.get("viewer_gcode_font_size", 30)
        self.gcode_view.set_font_size(v_size)
        
        # Modification tracking
        self.gcode_view.document().modificationChanged.connect(self._on_gcode_modification_changed)
        
        gcode_lay.addWidget(self.gcode_view)
        
        self._gcode_mdi_stack.addWidget(gcode_container)

        # Seite 1: MDI-Page
        mdi_page = QWidget()
        mdi_page_lay = QVBoxLayout(mdi_page)
        mdi_page_lay.setContentsMargins(4, 4, 4, 4)
        mdi_page_lay.setSpacing(6)

        self._mdi_input = QLineEdit()
        self._mdi_input.setObjectName("mdiEntry")
        self._mdi_input.setPlaceholderText("MDI COMMAND...")
        self._mdi_input.setMinimumHeight(40)
        self._mdi_input.returnPressed.connect(
            lambda: self._send_mdi(self._mdi_input.text(), self._mdi_input))

        self._mdi_history_widget = QListWidget()
        self._mdi_history_widget.setObjectName("mdiHistory")
        self._mdi_history_widget.itemDoubleClicked.connect(
            lambda item: self._mdi_input.setText(item.text()))

        mdi_page_lay.addWidget(self._mdi_input)
        mdi_page_lay.addWidget(self._mdi_history_widget)
        self._gcode_mdi_stack.addWidget(mdi_page)

        # UI-Buttons verdrahten (aus der UI-Datei) - Sidebar Nav
        self._btn_show_gcode = self.ui.findChild(QPushButton, "btn_gcode_view")
        self._btn_show_mdi   = self.ui.findChild(QPushButton, "btn_mdi_view")
        if self._btn_show_gcode:
            self._btn_show_gcode.clicked.connect(lambda: self._switch_gcode_panel(0))
        if self._btn_show_mdi:
            self._btn_show_mdi.clicked.connect(lambda: self._switch_gcode_panel(1))

        self._setup_highlight_settings()

        # Replace placeholder with stack (Stack is in a QVBoxLayout)
        if parent_gc and parent_gc.layout():
            lay = parent_gc.layout()
            idx = lay.indexOf(old_gcode)
            lay.removeWidget(old_gcode)
            old_gcode.deleteLater()
            lay.insertWidget(idx, self._gcode_mdi_stack)

        # Load MDI history from settings
        for entry in self.settings.get("mdi_history", []):
            self._mdi_history_widget.addItem(entry)

        self._switch_gcode_panel(0)

        # ── Backplot mit View-Toolbar ─────────────────────────────────────────
        old_vtk = self.ui.findChild(QWidget, "vtk")
        parent_vtk = old_vtk.parent() if old_vtk else None

        _aa_on = self.settings.get("backplot_antialiasing", True)
        _msaa  = self.settings.get("backplot_msaa_samples", 4) if _aa_on else 0
        self.backplot = BackplotWidget(msaa_samples=_msaa)
        self.backplot.setObjectName("vtk")

        # Buttons direkt in BackplotWidget's eingebaute Toolbar einfügen
        # (kein Wrapper-Widget → kein GLViewWidget-Reparenting-Problem)
        tb_lay = self.backplot.toolbar_layout()
        # View-Buttons links (vor dem Stretch)
        tb_lay.takeAt(0)   # den initialen Stretch kurz rausnehmen (wird unten neu eingefügt)
        for label, fn in (("ISO",        self.backplot.set_view_iso),
                          ("TOP",        self.backplot.set_view_z),
                          ("FRONT",      self.backplot.set_view_y),
                          ("SIDE",       self.backplot.set_view_x),
                          ("CLR TRAIL",  self.backplot.clear_trail)):
            b = QPushButton(label)
            b.setObjectName("btn_backplot_view")
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(fn)
            tb_lay.addWidget(b)
        tb_lay.addStretch()   # Stretch wieder einfügen (trennt links von rechts)

        self._btn_go_to_home = QPushButton("GO TO HOME")
        self._btn_go_to_home.setObjectName("btn_go_to_home")
        self._btn_go_to_home.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_go_to_home.clicked.connect(self._go_to_home)
        self._update_goto_home_style(all_homed=False)
        tb_lay.addWidget(self._btn_go_to_home)
        
        # Move mode combobox to top toolbar (Reorganization)
        from PySide6.QtWidgets import QComboBox
        combo = self.ui.findChild(QComboBox, "combo_machine_mode")
        if combo:
            # Remove from old layout (leftPanel)
            if combo.parent() and combo.parent().layout():
                combo.parent().layout().removeWidget(combo)
            # Add to top toolbar
            combo.setMinimumWidth(120)
            combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            tb_lay.insertWidget(tb_lay.indexOf(self._btn_go_to_home), combo)
            self.combo_machine_mode = combo

        if parent_vtk:
            if isinstance(parent_vtk, QSplitter):
                idx = parent_vtk.indexOf(old_vtk)
                parent_vtk.replaceWidget(idx, self.backplot)
            elif parent_vtk.layout():
                lay = parent_vtk.layout()
                idx = lay.indexOf(old_vtk)
                lay.removeWidget(old_vtk)
                lay.insertWidget(idx, self.backplot)
            old_vtk.deleteLater()

        bpm = self.settings.get("backplot_view")
        if bpm:
            self.backplot.set_view_opts(bpm)

    def _switch_gcode_panel(self, idx: int):
        self._gcode_mdi_stack.setCurrentIndex(idx)
        for b, active_idx in ((self._btn_show_gcode, 0), (self._btn_show_mdi, 1)):
            if b is None:
                continue
            b.setChecked(idx == active_idx)

    def _update_goto_home_style(self, all_homed: bool):
        if not hasattr(self, "_btn_go_to_home"):
            return
        in_auto = getattr(self, "_current_mode", None) == linuxcnc.MODE_AUTO
        btn = self._btn_go_to_home
        
        if in_auto:
            btn.setEnabled(False)
            self._add_class(btn, "") # Clear specific color classes
        elif all_homed:
            btn.setEnabled(True)
            self._add_class(btn, "btn-green")
        else:
            btn.setEnabled(True)
            self._add_class(btn, "btn-red")

    def _setup_dro(self):
        """DRO panel in probe_basic style: Axis | WORK | MACHINE | REF button."""
        from PySide6.QtWidgets import (QHBoxLayout, QVBoxLayout, QWidget, QGridLayout,
                                       QFrame, QPushButton, QSizePolicy, QComboBox)

        container = self.ui.findChild(QHBoxLayout, "dro_display_layout")
        if not container:
            return

        self._dro_work    = {}   # axis → QLabel (relative/work)
        self._dro_machine = {}   # axis → QLabel (absolute/machine)
        self._dro_ref_btn = {}   # axis → QPushButton

        # Rahmen-Widget, füllt den ganzen DRO-Frame
        wrapper = QWidget()
        wrapper.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        glay = QGridLayout(wrapper)
        glay.setContentsMargins(8, 6, 8, 6)
        glay.setSpacing(6)
        
        # Define consistent widths
        btn_width = 85
        axis_width = 50
        val_width = 120 # Slightly slimmer to fit 3 columns

        # ── Row 0: Header ───────────────────────────────────────────────────
        
        # ZERO ALL button
        btn_zero_all = QPushButton("ZERO\nALL")
        btn_zero_all.setFixedSize(btn_width, 44)
        btn_zero_all.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._add_class(btn_zero_all, "btn-blue")
        btn_zero_all.clicked.connect(lambda: self._zero_axis("ALL"))
        glay.addWidget(btn_zero_all, 0, 0)

        # AXIS header
        lbl_axis_hdr = QLabel("AXIS")
        self._add_class(lbl_axis_hdr, "dro-header")
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

        # MACHINE header
        lbl_mach_hdr = QLabel("MACHINE")
        self._add_class(lbl_mach_hdr, "dro-header")
        lbl_mach_hdr.setFixedWidth(val_width)
        lbl_mach_hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        glay.addWidget(lbl_mach_hdr, 0, 3)

        # DTG header (Distance to Go)
        lbl_dtg_hdr = QLabel("DTG")
        self._add_class(lbl_dtg_hdr, "dro-header")
        lbl_dtg_hdr.setFixedWidth(val_width)
        lbl_dtg_hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        glay.addWidget(lbl_dtg_hdr, 0, 4)

        # REF ALL button
        self._btn_ref_all = QPushButton("REF ALL")
        self._btn_ref_all.setFixedSize(btn_width, 44)
        self._btn_ref_all.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._add_class(self._btn_ref_all, "btn-green")
        self._btn_ref_all.clicked.connect(self._home_all)
        glay.addWidget(self._btn_ref_all, 0, 5)

        # ── Row 1: Separator ─────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(2)
        glay.addWidget(sep, 1, 0, 1, 6)

        # ── Rows 2-4: Axis Rows ──────────────────────────────────────────────
        self._dro_dtg = {}   # axis → QLabel (DTG)

        for i, (axis, joint) in enumerate([("X", 0), ("Y", 1), ("Z", 2)], start=2):
            # ZERO button
            btn_zero = QPushButton(f"ZERO\n{axis}")
            btn_zero.setObjectName("dro_zero_btn")
            btn_zero.setFixedSize(btn_width, 52)
            btn_zero.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._add_class(btn_zero, "btn-blue")
            btn_zero.clicked.connect(lambda _=False, a=axis: self._zero_axis(a))
            glay.addWidget(btn_zero, i, 0)

            # Axis label
            lbl_axis = QLabel(axis)
            self._add_class(lbl_axis, "dro-axis-label")
            lbl_axis.setFixedWidth(axis_width)
            lbl_axis.setAlignment(Qt.AlignmentFlag.AlignCenter)
            glay.addWidget(lbl_axis, i, 1)

            # WORK position
            lbl_work = QLabel("+0.000")
            self._add_class(lbl_work, "dro-value")
            lbl_work.setFixedWidth(val_width)
            lbl_work.setFixedHeight(52)
            lbl_work.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            glay.addWidget(lbl_work, i, 2)

            # MACHINE position
            lbl_mach = QLabel("+0.000")
            self._add_class(lbl_mach, "dro-value")
            self._add_class(lbl_mach, "dro-machine") # Multiple classes are supported by space separated string if handled by QSS, but property "class" usually takes one. Actually QSS can match parts.
            # Wait, Qt property "class" usually is a single string. To match multiple, we use space.
            lbl_mach.setProperty("class", "dro-value dro-machine")
            lbl_mach.setFixedWidth(val_width)
            lbl_mach.setFixedHeight(52)
            lbl_mach.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            glay.addWidget(lbl_mach, i, 3)

            # DTG position
            lbl_dtg = QLabel("+0.000")
            self._add_class(lbl_dtg, "dro-value")
            self._add_class(lbl_dtg, "dro-dtg")
            lbl_dtg.setProperty("class", "dro-value dro-dtg")
            lbl_dtg.setFixedWidth(val_width)
            lbl_dtg.setFixedHeight(52)
            lbl_dtg.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            glay.addWidget(lbl_dtg, i, 4)

            # REF button
            btn_ref = QPushButton(f"REF {axis}")
            btn_ref.setObjectName("dro_ref_btn")
            btn_ref.setFixedSize(btn_width, 52)
            btn_ref.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._add_class(btn_ref, "btn-green")
            glay.addWidget(btn_ref, i, 5)
            btn_ref.clicked.connect(lambda _=False, j=joint: self._home_joint(j))

            self._dro_work[axis]    = lbl_work
            self._dro_machine[axis] = lbl_mach
            self._dro_dtg[axis]     = lbl_dtg
            self._dro_ref_btn[axis] = btn_ref

        glay.setColumnStretch(2, 1)
        glay.setColumnStretch(3, 1)
        
        container.addWidget(wrapper)

    @Slot(list)
    def _on_g5x_offset(self, g5x: list):
        """WCS-Offset geändert → DRO neu berechnen + Backplot-Kreuz verschieben.
        G59.3 (Index 9) wird im Backplot ignoriert – wird nur für Messroutinen
        verwendet und soll den Backplot des Hauptprogramms nicht verschieben."""
        self._refresh_dro()
        if self.poller.stat.g5x_index != 9:
            self.backplot.set_wcs_origin(g5x[0], g5x[1], g5x[2])
            self._last_wcs_origin = (g5x[0], g5x[1], g5x[2])
            
            # Wenn noch kein Programm geladen ist, zentriere auf den neuen Nullpunkt
            if not getattr(self, "_has_file", False):
                self.backplot.fit_view(None)

            if hasattr(self, "simple_view") and self.simple_view.backplot:
                self.simple_view.backplot.set_wcs_origin(g5x[0], g5x[1], g5x[2])
                if not getattr(self, "_has_file", False):
                    self.simple_view.backplot.fit_view(None)

    @Slot(int)
    def _on_g5x_index(self, g5x_index: int):
        """LinuxCNC WCS geändert → Combo synchronisieren (ohne Signal-Loop)."""
        combo = getattr(self, "_wcs_combo", None)
        if combo is None:
            return
        for i in range(combo.count()):
            if combo.itemData(i) == g5x_index:
                combo.blockSignals(True)
                combo.setCurrentIndex(i)
                combo.blockSignals(False)
                break

    def _zero_axis(self, axis: str):
        """Sets the WCS zero for the axis/axes based on the ComboBox selection."""
        g5x_index = self._wcs_combo.currentData()  # 1=G54, 2=G55, …
        axis_map = {"X": "X0", "Y": "Y0", "Z": "Z0", "ALL": "X0 Y0 Z0"}
        coords = axis_map.get(axis, "X0 Y0 Z0")
        wcs_name = self._wcs_combo.currentText()
        try:
            self.cmd.mode(linuxcnc.MODE_MDI)
            self.cmd.wait_complete()
            self.cmd.mdi(f"G10 L20 P{g5x_index} {coords}")
            self.cmd.wait_complete()
            self.cmd.mode(linuxcnc.MODE_MANUAL)
            self._status(f"ZERO {axis} → {wcs_name}")
        except Exception:
            pass

    def _on_wcs_combo_changed(self, index):
        """WCS-Auswahl → G54..G59.3 per MDI senden."""
        wcs = self._wcs_combo.itemText(index)
        try:
            self.cmd.mode(linuxcnc.MODE_MDI)
            self.cmd.wait_complete()
            self.cmd.mdi(wcs)
            self.cmd.wait_complete()
            self.cmd.mode(linuxcnc.MODE_MANUAL)
        except Exception:
            pass

    def _apply_ini_settings(self):
        name = "ThorCNC"
        if self.ini:
            name = self.ini.find("EMC", "MACHINE") or name
        self.ui.setWindowTitle(name)
        self._setup_jog_display()
        self._apply_machine_envelope()

    def _apply_machine_envelope(self):
        if not self.ini:
            return
        def lim(axis, key, default):
            v = self.ini.find(f"AXIS_{axis}", key)
            return float(v) if v else default

        # Envelope zeigt nutzbaren Arbeitsbereich (0 bis MAX bzw. MIN bis 0)
        # nicht die technischen Soft-Limits mit Homing-Überfahrt
        envelope = dict(
            x_min=lim("X", "MIN_LIMIT", 0), x_max=lim("X", "MAX_LIMIT", 600),
            y_min=lim("Y", "MIN_LIMIT", 0), y_max=lim("Y", "MAX_LIMIT", 500),
            z_min=lim("Z", "MIN_LIMIT", -200), z_max=lim("Z", "MAX_LIMIT", 0),
        )
        self.backplot.set_machine_envelope(**envelope)
        # SimpleView overlay backplot gets the same envelope (created later via singleShot)
        self._backplot_envelope = envelope

    def _setup_jog_display(self):
        """Jog-Display-Page aus INI setzen, Icons auf Buttons legen."""
        from PySide6.QtWidgets import QStackedWidget, QPushButton

        # ── Richtige Seite im jogDisplay ──────────────────────────────────────
        coords = ""
        if self.ini:
            coords = (self.ini.find("TRAJ", "COORDINATES") or
                      self.ini.find("DISPLAY", "GEOMETRY") or "XYZ").upper().replace(" ", "")

        page_map = {"XYZ": 0, "XYZA": 1, "XYZAB": 2, "XYZAC": 3, "XYZBC": 4, "XYZABC": 5}
        page = page_map.get(coords, 0)

        jog_stack = self.ui.findChild(QStackedWidget, "jogDisplay")
        if jog_stack:
            jog_stack.setCurrentIndex(page)

        # ── Icons auf XYZ-Buttons (_3 Suffix = jog_xyz Seite) ─────────────────
        btn_icons = {
            "z_plus_jogbutton_3":  ("Z", "up"),
            "z_minus_jogbutton_3": ("Z", "down"),
            "y_plus_jogbutton_3":  ("Y", "up"),
            "y_minus_jogbutton_3": ("Y", "down"),
            "x_plus_jogbutton_3":  ("X", "right"),
            "x_minus_jogbutton_3": ("X", "left"),
        }
        for btn_name, (axis, direction) in btn_icons.items():
            b = self.ui.findChild(QPushButton, btn_name)
            if b:
                b.setIcon(self._make_jog_icon(axis, direction))
                b.setIconSize(b.minimumSize())
                b.setText("")

    @staticmethod
    def _make_jog_icon(axis: str, direction: str, size: int = 42):
        """Zeichnet ein Jog-Button-Icon: farbiger Ring + Chevron-Pfeil + Achsbeschriftung."""
        from PySide6.QtGui import (QPixmap, QPainter, QColor,
                                   QFont, QPen, QBrush, QRadialGradient)
        from PySide6.QtCore import QPointF, QRectF

        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx, cy = size / 2.0, size / 2.0
        r = size / 2.0 - 1.5

        # Achsfarben (passend zum Backplot-Koordinatensystem)
        axis_colors = {
            "X": QColor(210, 55,  55),   # rot
            "Y": QColor(45,  190, 75),   # grün
            "Z": QColor(55,  120, 215),  # blau
        }
        ac = axis_colors.get(axis, QColor(160, 160, 160))

        # ── Background: subtle radial gradient ─────────────────────────
        bg = QRadialGradient(cx, cy, r)
        bg.setColorAt(0.0, QColor(52, 57, 62))
        bg.setColorAt(1.0, QColor(28, 31, 34))
        p.setBrush(QBrush(bg))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), r, r)

        # ── Farbiger Ring (Achsfarbe, halb-transparent) ───────────────────
        ring_pen = QPen(ac, 2.2)
        ring_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(ring_pen)
        p.drawEllipse(QPointF(cx, cy), r, r)

        # ── Axis + Sign centered ──────────────────────────────────
        sign = "+" if direction in ("up", "right") else "-"
        font = QFont("Bebas Kai", max(8, size // 3))
        font.setBold(True)
        p.setFont(font)
        label_color = ac.lighter(160)
        label_color.setAlpha(230)
        p.setPen(QPen(label_color))
        p.drawText(QRectF(0, 0, size, size),
                   Qt.AlignmentFlag.AlignCenter, f"{axis}{sign}")

        p.end()
        from PySide6.QtGui import QIcon
        return QIcon(pix)

    # ── StatusPoller ──────────────────────────────────────────────────────────

    def _setup_poller(self):
        # Wir übergeben die HAL-Komponente, damit der Poller direkt auf die Pins zugreifen kann
        self.poller = StatusPoller(interval_ms=100, hal_comp=self._hal_comp, parent=self)

    def _setup_file_manager(self):
        from PySide6.QtWidgets import QTreeView, QTextBrowser, QPushButton, QFileSystemModel, QLabel, QWidget
        from PySide6.QtCore import QDir
        import os

        tree = self._w(QTreeView, "fileManagerView")
        
        # Replace filePreviewArea placeholder with GCodeView (editable)
        old_preview = self.ui.findChild(QWidget, "filePreviewArea")
        if old_preview:
            parent = old_preview.parent()
            lay = parent.layout()
            idx = lay.indexOf(old_preview)
            lay.removeWidget(old_preview)
            old_preview.deleteLater()
            
            self._file_preview = GCodeView(editable=True)
            self._file_preview.setObjectName("filePreviewArea")
            e_size = self.settings.get("editor_gcode_font_size", 22)
            self._file_preview.set_font_size(e_size)
            self._file_preview.zoom_changed.connect(
                lambda s: (self.settings.set("editor_gcode_font_size", s), self.settings.save()))
            lay.insertWidget(idx, self._file_preview)
        else:
            self._file_preview = self._w(GCodeView, "filePreviewArea")

        self._btn_load = self._w(QPushButton, "load_gcode_button")
        self._btn_save = self._w(QPushButton, "btn_save_file")
        self._btn_save_as = self._w(QPushButton, "btn_save_as_file")
        self._btn_cancel = self._w(QPushButton, "btn_cancel_edit")
        
        self._btn_zoom_in = self._w(QPushButton, "btn_zoom_in")
        self._btn_zoom_out = self._w(QPushButton, "btn_zoom_out")
        if self._btn_zoom_in: self._btn_zoom_in.clicked.connect(lambda: self._file_preview.zoomIn(1))
        if self._btn_zoom_out: self._btn_zoom_out.clicked.connect(lambda: self._file_preview.zoomOut(1))

        self._btn_nav_up = self._w(QPushButton, "btn_nav_up")
        self._btn_nav_home = self._w(QPushButton, "btn_nav_home")
        
        # UI Polish: Narrower buttons with icons instead of text
        from PySide6.QtGui import QIcon
        if self._btn_nav_up:
            self._btn_nav_up.setText("")
            self._btn_nav_up.setFixedWidth(60)
            self._btn_nav_up.setToolTip("Übergeordnetes Verzeichnis")
            
        if self._btn_nav_home:
            self._btn_nav_home.setText("")
            self._btn_nav_home.setFixedWidth(60)
            self._btn_nav_home.setToolTip("Home-Verzeichnis")

        self._update_nav_icons()

        self._breadcrumb_container = self._w(QWidget, "breadcrumb_container")
        self._breadcrumb_layout = None
        if self._breadcrumb_container:
            self._breadcrumb_layout = QHBoxLayout(self._breadcrumb_container)
            self._breadcrumb_layout.setContentsMargins(0, 0, 0, 0)
            self._breadcrumb_layout.setSpacing(2)

        if not tree or not self._file_preview or not self._btn_load:
            return

        # Start directory from INI or default fallback
        start_dir = os.path.expanduser("~/linuxcnc/nc_files")
        if self.ini and self.ini_path:
            cfg_dir = self.ini.find("DISPLAY", "PROGRAM_PREFIX")
            if cfg_dir:
                cfg_dir = os.path.expanduser(cfg_dir)
                if not os.path.isabs(cfg_dir):
                    ini_dir = os.path.dirname(self.ini_path)
                    cfg_dir = os.path.abspath(os.path.join(ini_dir, cfg_dir))
                start_dir = cfg_dir
        
        if not os.path.exists(start_dir):
            try:
                os.makedirs(start_dir, exist_ok=True)
            except Exception:
                start_dir = os.path.expanduser("~/linuxcnc/nc_files")

        self._file_home_dir = start_dir

        self._fs_model = QFileSystemModel()
        self._fs_model.setRootPath(start_dir)
        self._fs_model.setFilter(QDir.AllDirs | QDir.Files | QDir.NoDotAndDotDot)

        tree.setModel(self._fs_model)
        
        # Hide unneeded columns for cleaner look
        tree.setColumnWidth(0, 300)
        tree.hideColumn(1) # size
        tree.hideColumn(2) # type
        tree.hideColumn(3) # date

        tree.selectionModel().selectionChanged.connect(self._on_file_selected)
        tree.doubleClicked.connect(self._on_file_double_clicked)
        
        if self._btn_nav_up:
            self._btn_nav_up.clicked.connect(self._nav_up)
        if self._btn_nav_home:
            self._btn_nav_home.clicked.connect(self._nav_home)
        
        self._selected_filepath = None
        self._btn_load.clicked.connect(self._load_selected_file)
        self._btn_load.setEnabled(False)

        if self._btn_save:
            self._btn_save.clicked.connect(self._save_file)
            self._btn_save.setEnabled(False)
        if self._btn_save_as:
            self._btn_save_as.clicked.connect(self._save_as_file)
            self._btn_save_as.setEnabled(False)
        if self._btn_cancel:
            self._btn_cancel.clicked.connect(self._cancel_edit)
            self._btn_cancel.setEnabled(False)
        
        last_dir = self.settings.get("last_file_dir")
        if last_dir and os.path.exists(last_dir):
            self._nav_set_dir(last_dir)
        else:
            self._nav_set_dir(start_dir)

    def _nav_set_dir(self, path: str):
        import os
        from PySide6.QtWidgets import QTreeView
        tree = self._w(QTreeView, "fileManagerView")
        if tree and os.path.isdir(path):
            tree.setRootIndex(self._fs_model.index(path))
            self._current_dir = path
            if hasattr(self, "_breadcrumb_container") and self._breadcrumb_container:
                self._update_breadcrumbs(path)

    def _update_breadcrumbs(self, path: str):
        """Erstellt interaktive Breadcrumb-Buttons für den aktuellen Pfad."""
        if not self._breadcrumb_layout:
            return

        # Layout leeren
        while self._breadcrumb_layout.count():
            item = self._breadcrumb_layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()
        
        # Pfad normalisieren und aufteilen
        path = os.path.normpath(path)
        parts = [p for p in path.split(os.sep) if p]
        
        # Root Button (/)
        self._add_breadcrumb_button("/", os.sep)
        
        # Segmente hinzufügen
        current_acc = os.sep
        for part in parts:
            # Separator
            sep = QLabel("›")
            sep.setObjectName("breadcrumb_sep")
            self._breadcrumb_layout.addWidget(sep)
            
            current_acc = os.path.join(current_acc, part)
            self._add_breadcrumb_button(part, current_acc)
            
        self._breadcrumb_layout.addStretch()

    def _add_breadcrumb_button(self, text, path):
        btn = QPushButton(text)
        btn.setObjectName("breadcrumb_item")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda: self._nav_set_dir(path))
        self._breadcrumb_layout.addWidget(btn)

    def _nav_up(self):
        import os
        if hasattr(self, "_current_dir"):
            parent_dir = os.path.dirname(self._current_dir)
            if parent_dir and parent_dir != self._current_dir:
                self._nav_set_dir(parent_dir)

    def _nav_home(self):
        if hasattr(self, "_file_home_dir"):
            self._nav_set_dir(self._file_home_dir)
            
    def _on_file_double_clicked(self, idx):
        import os
        path = self._fs_model.filePath(idx)
        if os.path.isdir(path):
            self._nav_set_dir(path)
        else:
            self._selected_filepath = path
            self._load_selected_file()

    def _on_file_selected(self):
        from PySide6.QtWidgets import QTreeView
        import os
        tree = self._w(QTreeView, "fileManagerView")
        idx = tree.currentIndex()
        if not idx.isValid():
            return
            
        path = self._fs_model.filePath(idx)
        if os.path.isdir(path):
            self.settings.set("last_file_dir", path)
            self._selected_filepath = None
            self._btn_load.setEnabled(False)
            self._file_preview.setPlainText("[ORDNER AUSGEWÄHLT]")
        else:
            self.settings.set("last_file_dir", os.path.dirname(path))
            self._selected_filepath = path
            self._btn_load.setEnabled(True)
            if self._btn_save: self._btn_save.setEnabled(True)
            if self._btn_save_as: self._btn_save_as.setEnabled(True)
            if self._btn_cancel: self._btn_cancel.setEnabled(True)
            
            try:
                # Load FULL file for editing
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                self._file_preview.setPlainText(content)
            except Exception as e:
                self._file_preview.setPlainText(f"Error loading:\n{e}")

    def _save_file(self):
        if not self._selected_filepath:
            return
        
        try:
            content = self._file_preview.toPlainText()
            with open(self._selected_filepath, "w", encoding="utf-8") as f:
                f.write(content)
            self._status(f"Datei gespeichert: {os.path.basename(self._selected_filepath)}")
        except Exception as e:
            self._status(f"Error saving file: {e}", error=True)

    def _save_as_file(self):
        from PySide6.QtWidgets import QFileDialog
        import os
        
        start_dir = self._current_dir if hasattr(self, "_current_dir") else os.path.expanduser("~")
        path, _ = QFileDialog.getSaveFileName(self.ui, "Speichern unter...", start_dir, "G-Code (*.ngc *.tap *.txt);;All Files (*)")
        
        if path:
            try:
                content = self._file_preview.toPlainText()
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                self._selected_filepath = path
                self._status(f"Datei gespeichert unter: {os.path.basename(path)}")
                # Refresh file tree if possible - fs_model updates automatically usually
            except Exception as e:
                self._status(f"Error saving file: {e}", error=True)

    def _cancel_edit(self):
        if self._selected_filepath:
            self._on_file_selected()
        else:
            self._file_preview.clear()

    def _load_selected_file(self):
        if self._selected_filepath:
            self._user_program = self._selected_filepath
            # Tell linuxcnc to open the program
            self.cmd.mode(linuxcnc.MODE_AUTO)
            self.cmd.wait_complete()
            self.cmd.program_open(self._selected_filepath)
            
            # Switch view back to MAIN
            from PySide6.QtWidgets import QTabWidget
            if tab := self._w(QTabWidget, "tabWidget"):
                tab.setCurrentIndex(0)


    def _setup_tool_table(self):
        from PySide6.QtWidgets import QTableWidget, QPushButton
        
        self.tool_table = self._w(QTableWidget, "toolTable")
        self.btn_add_tool = self._w(QPushButton, "btn_add_tool")
        self.btn_delete_tool = self._w(QPushButton, "btn_delete_tool")
        self.btn_reload_tools = self._w(QPushButton, "btn_reload_tools")
        self.btn_save_tools = self._w(QPushButton, "btn_save_tools")

        if not self.tool_table:
            return

        # UI Cleanup for tool table
        self.tool_table.verticalHeader().setVisible(False)
        self.tool_table.setSortingEnabled(True)

        # Path resolvieren
        self._tool_tbl_path = None
        if self.ini and self.ini_path:
            tbl_name = self.ini.find("EMCIO", "TOOL_TABLE")
            if tbl_name:
                import os
                if not os.path.isabs(tbl_name):
                    self._tool_tbl_path = os.path.abspath(os.path.join(os.path.dirname(self.ini_path), tbl_name))
                else:
                    self._tool_tbl_path = tbl_name

        if self.btn_add_tool:
            self.btn_add_tool.clicked.connect(self._add_tool)
        if self.btn_delete_tool:
            self.btn_delete_tool.clicked.connect(self._delete_tool)
        if self.btn_reload_tools:
            self.btn_reload_tools.clicked.connect(self._load_tool_table)
        if self.btn_save_tools:
            self.btn_save_tools.clicked.connect(self._save_tool_table)

        # Context Menu
        self.tool_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tool_table.customContextMenuRequested.connect(self._show_tool_table_context_menu)

        self._load_tool_table()
        
        # Restore tool table column widths
        tt_state = self.settings.get("tool_table_state")
        if tt_state:
            from PySide6.QtCore import QByteArray
            self.tool_table.horizontalHeader().restoreState(QByteArray.fromHex(tt_state.encode()))

    def _load_tool_table(self):
        import os, re
        from PySide6.QtWidgets import QTableWidgetItem
        from PySide6.QtCore import Qt
        if not self._tool_tbl_path or not os.path.exists(self._tool_tbl_path):
            return

        self.tool_table.setSortingEnabled(False)
        self.tool_table.setRowCount(0)
        try:
            with open(self._tool_tbl_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith(";"): 
                        continue
                    
                    parts = line.split(";", 1)
                    data = parts[0].strip()
                    comment = parts[1].strip() if len(parts) > 1 else ""
                    
                    t = re.search(r'T(\d+)', data)
                    p = re.search(r'P(\d+)', data)
                    d = re.search(r'D([+-]?\d*\.\d+|\d+)', data)
                    z = re.search(r'Z([+-]?\d*\.\d+|\d+)', data)
                    
                    dia_str = d.group(1) if d else ""
                    if dia_str.startswith("+"):
                        dia_str = dia_str[1:]
                    
                    row = self.tool_table.rowCount()
                    self.tool_table.insertRow(row)
                    
                    self.tool_table.setItem(row, 0, NumericTableWidgetItem(t.group(1) if t else ""))
                    self.tool_table.setItem(row, 1, NumericTableWidgetItem(p.group(1) if p else ""))
                    self.tool_table.setItem(row, 2, NumericTableWidgetItem(dia_str))
                    self.tool_table.setItem(row, 3, NumericTableWidgetItem(z.group(1) if z else ""))
                    self.tool_table.setItem(row, 4, QTableWidgetItem(comment))
            
            # Sort by Tool Number initially
            self.tool_table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        except Exception as e:
            self._status(f"Error loading tool table: {e}", error=True)
        finally:
            self.tool_table.setSortingEnabled(True)

    def _delete_tool(self):
        """Löscht die ausgewählten Zeilen aus der Werkzeugliste."""
        if not self.tool_table: return
        rows = set()
        for item in self.tool_table.selectedItems():
            rows.add(item.row())
        
        if not rows and self.tool_table.currentRow() >= 0:
            rows.add(self.tool_table.currentRow())

        if not rows:
            return

        # Von unten nach oben löschen, damit die Indizes gültig bleiben
        for row in sorted(list(rows), reverse=True):
            self.tool_table.removeRow(row)

    def _show_tool_table_context_menu(self, pos):
        """Zeigt das Kontextmenü für die Werkzeugliste an."""
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self.tool_table)
        delete_action = menu.addAction("- Ausgewähltes Werkzeug löschen")
        delete_action.triggered.connect(self._delete_tool)
        menu.exec(self.tool_table.mapToGlobal(pos))

    def _add_tool(self):
        from PySide6.QtWidgets import QTableWidgetItem
        if not self.tool_table: return
        row = self.tool_table.rowCount()
        self.tool_table.insertRow(row)
        for c in range(5):
            self.tool_table.setItem(row, c, QTableWidgetItem(""))

    def _save_tool_table(self):
        if not self._tool_tbl_path or not self.tool_table:
            return
            
        lines = []
        for row in range(self.tool_table.rowCount()):
            t = self.tool_table.item(row, 0)
            p = self.tool_table.item(row, 1)
            d = self.tool_table.item(row, 2)
            z = self.tool_table.item(row, 3)
            c = self.tool_table.item(row, 4)
            
            ts = t.text().strip() if t and t.text().strip() else ""
            ps = p.text().strip() if p and p.text().strip() else ""
            ds = d.text().strip().replace(",", ".") if d and d.text().strip() else ""
            zs = z.text().strip().replace(",", ".") if z and z.text().strip() else ""
            cs = c.text().strip() if c and c.text().strip() else ""
            
            if not ts: continue # T is required
            
            # Format nicely
            parts = [f"T{ts}"]
            if ps: parts.append(f"P{ps}")
            if ds: parts.append(f"D{ds}")
            if zs: parts.append(f"Z{zs}")
            
            line = " ".join(parts)
            if cs:
                line += f" ;{cs}"
            lines.append(line)
            
        try:
            with open(self._tool_tbl_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
                
            # Reload tool table in LinuxCNC
            self.cmd.load_tool_table()
            self._status("Tool table saved and reloaded!")
        except Exception as e:
            self._status(f"Error saving tool table: {e}", error=True)

    # ── Settings Tab ──────────────────────────────────────────────────────────

    # Mapping: (spinbox_name, prefs_key, default_value)
    _TOOLSENSOR_FIELDS = [
        ("dsb_ts_wechsel_x",    "ts_wechsel_x",    0.0),
        ("dsb_ts_wechsel_y",    "ts_wechsel_y",    0.0),
        ("dsb_ts_wechsel_z",    "ts_wechsel_z",    0.0),
        ("dsb_ts_x",            "ts_x",            0.0),
        ("dsb_ts_y",            "ts_y",            0.0),
        ("dsb_ts_z",            "ts_z",            0.0),
        ("dsb_ts_spindle_zero", "ts_spindle_zero", 0.0),
        ("dsb_ts_max_probe",    "ts_max_probe",   50.0),
        ("dsb_ts_retract",      "ts_retract",      2.0),
        ("dsb_ts_search_vel",   "ts_search_vel", 100.0),
        ("dsb_ts_probe_vel",    "ts_probe_vel",   10.0),
    ]

    def _setup_hal(self):
        """Initialisiert die HAL-Komponente so früh wie möglich (Timing-Fix)."""
        try:
            import hal
            from PySide6.QtCore import QTimer
            self._hal_comp = hal.component("thorcnc")
            
            # Pins für Tool-Sensor (aus Settings/VCP-Style)
            for _, key, _ in self._TOOLSENSOR_FIELDS:
                pin_name = key.replace("_", "-")
                self._hal_comp.newpin(pin_name, hal.HAL_FLOAT, hal.HAL_OUT)
            
            # Standard pins for status & control
            self._hal_comp.newpin("probe-sim",          hal.HAL_BIT,   hal.HAL_OUT)
            self._hal_comp.newpin("spindle-atspeed",    hal.HAL_BIT,   hal.HAL_IN)
            print(f"[HAL] Erzeuge Pins für Komponente 'thorcnc'...")
            self._hal_comp.newpin("spindle-speed-actual", hal.HAL_FLOAT, hal.HAL_IN)
            self._hal_comp.newpin("spindle-load",       hal.HAL_FLOAT, hal.HAL_IN)

            # Pins für Manuellen Werkzeugwechsler (M6)
            self._hal_comp.newpin("tool-change-request", hal.HAL_BIT,   hal.HAL_IN)
            self._hal_comp.newpin("tool-number",         hal.HAL_S32,   hal.HAL_IN)
            self._hal_comp.newpin("tool-changed-confirm", hal.HAL_BIT,  hal.HAL_OUT)
            
            # Pins für TsHW / Handrad Integration (falls gewünscht)
            self._hal_comp.newpin("jog-vel-final",      hal.HAL_FLOAT, hal.HAL_OUT)
            
            self._hal_comp.ready()
            print(f"[HAL] Komponente 'thorcnc' ist READY.")
            self._status("HAL component 'thorcnc' ready.")
            
            # LinuxCNC Core lädt keine Post-GUI Dateien. Dies ist Aufgabe der GUI!
            self._load_postgui_hal()
            
            
            # Sim-Parameter + Net-Verbindung per halcmd (nur Simulation)
            if "sim" in self.ini_path.lower():
                import subprocess
                _hc = lambda *args: subprocess.run(["halcmd"] + list(args), capture_output=True)
                _hc("setp", "limit_speed.maxv", "600.0")
                _hc("setp", "spindle_mass.gain", "0.002")
                _hc("net", "spindle-at-speed",    "thorcnc.spindle-atspeed")
                _hc("net", "spindle-rpm-filtered", "thorcnc.spindle-speed-actual")
                
        except Exception as e:
            print(f"[ThorCNC] HAL-Initialisierung übersprungen: {e}")
            self._hal_comp = None

    def _load_postgui_hal(self):
        """Liest alle POSTGUI_HALFILE Einträge aus der INI und führt sie aus."""
        if not self.ini:
            return
            
        postgui_files = self.ini.findall("HAL", "POSTGUI_HALFILE")
        if not postgui_files:
            return
            
        import subprocess
        ini_dir = os.path.dirname(self.ini_path) if self.ini_path else ""
        if not ini_dir:
            ini_dir = os.getcwd()
            
        for pfile in postgui_files:
            hal_path = os.path.join(ini_dir, pfile)
            print(f"[HAL] Lade Post-GUI Datei: {hal_path}")
            if os.path.exists(hal_path):
                # Nutzen von -i um die ini an das halcmd weiterzugeben (für [ ] variablen)
                res = subprocess.run(["halcmd", "-i", self.ini_path, "-f", hal_path], capture_output=True, text=True)
                if res.returncode != 0:
                    print(f"[HAL] Fehler beim Laden von {pfile}:\n{res.stderr}")
                else:
                    print(f"[HAL] {pfile} erfolgreich geladen.")
            else:
                print(f"[HAL] FEHLER: Post-GUI Datei nicht gefunden: {hal_path}")

    # ── WCS Offset Table ────────────────────────────────────────────────────

    # Parameter-Nummern: G54=5221, G55=5241 ... (je +20, X/Y/Z = +0/+1/+2)
    _WCS_LIST = [
        ("G54", 1, 5221), ("G55", 2, 5241), ("G56", 3, 5261),
        ("G57", 4, 5281), ("G58", 5, 5301), ("G59", 6, 5321),
        ("G59.1", 7, 5341), ("G59.2", 8, 5361), ("G59.3", 9, 5381),
    ]

    def _var_file_path(self) -> str | None:
        if not self.ini:
            return None
        name = self.ini.find("RS274NGC", "PARAMETER_FILE")
        if not name:
            return None
        p = os.path.join(os.path.dirname(self.ini_path), name)
        return p if os.path.exists(p) else None

    def _read_var_file(self) -> dict[int, float]:
        """Liest die LinuxCNC .var-Datei und gibt {param_nr: wert} zurück."""
        path = self._var_file_path()
        if not path:
            return {}
        params: dict[int, float] = {}
        try:
            with open(path, "r") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            params[int(parts[0])] = float(parts[1])
                        except ValueError:
                            pass
        except OSError:
            pass
        return params

    def _setup_offsets_tab(self):
        from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                                       QTableWidget, QTableWidgetItem,
                                       QPushButton, QHeaderView, QLabel,
                                       QAbstractItemView)
        from PySide6.QtCore import Qt as _Qt
        from PySide6.QtGui import QColor, QFont

        tab = self._w(QWidget, "tab_offsets")
        if not tab:
            return

        outer = QVBoxLayout(tab)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        # Titel
        title = QLabel("Work Coordinate Offsets (G54 – G59.3)")
        title.setObjectName("section_title")
        outer.addWidget(title)

        # Table
        cols = ["WCS", "X", "Y", "Z", "R", ""]
        tbl = QTableWidget(len(self._WCS_LIST), len(cols))
        tbl.setObjectName("offsetTable")
        tbl.setHorizontalHeaderLabels(cols)
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tbl.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        tbl.setObjectName("offsetsTable")
        tbl.setFocusPolicy(_Qt.FocusPolicy.NoFocus)

        hdr = tbl.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        tbl.setColumnWidth(0, 100)
        tbl.setColumnWidth(5, 110)
        tbl.verticalHeader().setDefaultSectionSize(48)

        _bold = QFont()
        _bold.setBold(True)
        _bold.setPointSize(14)

        for row, (label, p_idx, base_param) in enumerate(self._WCS_LIST):
            # WCS-Name
            name_item = QTableWidgetItem(label)
            name_item.setTextAlignment(_Qt.AlignmentFlag.AlignCenter)
            name_item.setFont(_bold)
            tbl.setItem(row, 0, name_item)
            # X / Y / Z (Platzhalter – werden per _refresh_offsets_table befüllt)
            for col in range(1, 5):
                it = QTableWidgetItem("–")
                it.setTextAlignment(_Qt.AlignmentFlag.AlignRight | _Qt.AlignmentFlag.AlignVCenter)
                tbl.setItem(row, col, it)
            # Clear-Button
            btn = QPushButton("CLEAR")
            btn.setObjectName("wcs_clear_btn")
            btn.setFocusPolicy(_Qt.FocusPolicy.NoFocus)
            btn.setFixedSize(80, 30)
            btn.clicked.connect(lambda _=False, n=p_idx: self._clear_wcs(n))
            tbl.setCellWidget(row, 5, btn)

        outer.addWidget(tbl)
        # Removed stretch to allow table to fill the space


        self._offset_table = tbl
        self._offset_active_row = 0
        self._offset_var_mtime = 0.0

        # Erste Befüllung + Signal-Verbindung
        self._refresh_offsets_table()
        self.poller.periodic.connect(self._refresh_offsets_table)
        self.poller.g5x_index_changed.connect(self._on_offset_wcs_changed)

    def _refresh_offsets_table(self):
        """Reads the .var file (only if mtime changed) and updates the table."""
        path = self._var_file_path()
        if not hasattr(self, "_offset_table"):
            return
        mtime = os.path.getmtime(path) if path else 0.0
        if mtime == self._offset_var_mtime:
            return
        self._offset_var_mtime = mtime

        from PySide6.QtGui import QColor
        params = self._read_var_file()
        tbl = self._offset_table

        for row, (_, _, base) in enumerate(self._WCS_LIST):
            for col, offset in enumerate((0, 1, 2, 9)):
                val = params.get(base + offset, 0.0)
                it = tbl.item(row, col + 1)
                if it:
                    it.setText(f"{val:+.4f}")
                    it.setForeground(QColor("#3db2ff" if val != 0.0 else "#999999"))

    def _on_offset_wcs_changed(self, index: int):
        """Hebt die aktive WCS-Zeile hervor."""
        if not hasattr(self, "_offset_table"):
            return
        from PySide6.QtGui import QColor
        tbl = self._offset_table
        for row, (_, p_idx, _) in enumerate(self._WCS_LIST):
            active = p_idx == index
            bg = QColor("#194a82") if active else QColor("#252525")
            for col in range(6):
                it = tbl.item(row, col)
                if it:
                    it.setBackground(bg)

    def _clear_wcs(self, p_idx: int):
        """Setzt alle Offsets des angegebenen WCS auf 0 via G10 L2."""
        try:
            self.cmd.mode(linuxcnc.MODE_MDI)
            self.cmd.wait_complete()
            self.cmd.mdi(f"G10 L2 P{p_idx} X0 Y0 Z0 R0")
            self.cmd.wait_complete()
            self.cmd.mode(linuxcnc.MODE_MANUAL)
            self._status(f"WCS G{53 + p_idx if p_idx <= 6 else '59.' + str(p_idx - 6)} → X0 Y0 Z0 R0")
            self._offset_var_mtime = 0.0   # mtime invalidieren → sofortiger Refresh
        except Exception as e:
            self._status(f"Offset clear error: {e}")

    # ── Probing Tab ───────────────────────────────────────────────────────────

    def _setup_probing_tab(self):
        """Lädt SVG-Icons, verbindet Override-Slider und baut probe-DRO."""
        from PySide6.QtWidgets import (QPushButton, QButtonGroup, QLineEdit,
                                       QSlider, QToolButton, QMenu, QFrame,
                                       QWidget, QStackedWidget, QGridLayout,
                                       QVBoxLayout, QHBoxLayout, QLabel)
        from PySide6.QtGui import QIcon, QAction
        from PySide6.QtCore import QSize, Qt

        self._probe_img_dir = os.path.join(_DIR, "images", "probe")

        # ── Mode Selection Buttons ──────────────────────────────────────────
        from PySide6.QtWidgets import QButtonGroup
        self._probe_mode_grp = QButtonGroup(self)
        self._probe_mode_grp.setExclusive(True)

        for obj_name, mode in [
            ("btn_mode_outside", "OUTSIDE CORNERS"),
            ("btn_mode_inside",  "INSIDE CORNERS"),
            ("btn_mode_center",  "CENTER FINDER"),
            ("btn_mode_angle",  "EDGE ANGLE")
        ]:
            if btn := self._w(QPushButton, obj_name):
                self._probe_mode_grp.addButton(btn)
                btn.clicked.connect(lambda _=False, m=mode: self._probe_set_mode(m))

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
            "corner_tl": "Top-Left Corner",
            "edge_top":  "Top Edge",
            "corner_tr": "Top-Right Corner",
            "edge_left": "Left Edge",
            "center":    "Z Probe (Surface)",
            "edge_right":"Right Edge",
            "corner_bl": "Bottom-Left Corner",
            "edge_bottom":"Bottom Edge",
            "corner_br": "Bottom-Right Corner",
        }

        def make_grid_page(subfolder, cells):
            """cells: list of (row, col, ngc_name, svg_file)"""
            page = QWidget()
            gl = QGridLayout(page)
            gl.setSpacing(6)
            gl.setContentsMargins(0, 0, 0, 0)
            grp = QButtonGroup(page)
            grp.setExclusive(True)
            for row, col, ngc, svgf in cells:
                btn = make_btn(f"{subfolder}_{ngc}", grp)
                btn.setIcon(svg(subfolder, svgf))
                
                # Set Tooltip
                prefix = subfolder.capitalize() if "angle" not in subfolder else "Measure Angle at"
                if subfolder == "outside": prefix = "Probe Outside"
                if subfolder == "inside":  prefix = "Probe Inside"
                
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
        self._btn_probe_center_mode = QPushButton("MODE: OUTSIDE")
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
            (0, 1, "angle_edge_top",    "edge_top.svg"),
            (1, 0, "angle_edge_left",   "edge_left.svg"),
            (1, 2, "angle_edge_right",  "edge_right.svg"),
            (2, 1, "angle_edge_bottom", "edge_bottom.svg"),
        ]
        p_angle = make_grid_page("outside", ANGLE_CELLS)
        
        # Reparent Edge Width to this page
        lay_angle = p_angle.layout()
        from PySide6.QtWidgets import QLabel, QDoubleSpinBox, QHBoxLayout
        lbl_ew = self._w(QLabel, "lbl_probe_param_edge_width")
        dsb_ew = self._w(QDoubleSpinBox, "dsb_probe_edge_width")
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
        frm = self._w(QFrame, "frm_probe_grid")
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
            self._probe_marker = QLabel("⌂", self.ui.tab_probing)
            self._probe_marker.setFixedSize(self._probe_marker_sz, self._probe_marker_sz)
            self._probe_marker.setAlignment(Qt.AlignCenter)
            self._probe_marker.setStyleSheet(
                f"background:#e67e00;color:white;border-radius:{self._probe_marker_sz//2}px;"
                "font-size:8pt;font-weight:bold;")
            self._probe_marker.setToolTip("Machine Zero")

            # Orange Corner Accent
            from PySide6.QtWidgets import QFrame
            self._probe_home_accent = QFrame(self.ui.tab_probing)
            self._probe_home_accent.setFixedSize(14, 14)
            self._probe_home_accent.setStyleSheet("background:#e67e00; border-radius:3px;")
            self._probe_home_accent.lower() # Place behind icon
            
            # L-Shaped Corner Accent (inside the frame)
            self._probe_corner_accent = QFrame(frm)
            self._probe_corner_accent.setFixedSize(20, 20)
            self._probe_corner_accent.setAttribute(Qt.WA_TransparentForMouseEvents)
            
            # Install event filter to handle resize
            self._probe_grid_frm = frm
            self._probe_grid_frm.installEventFilter(self)
            
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
            if btn := self._w(QPushButton, btn_name):
                btn.clicked.connect(
                    lambda _=False, flds=fields: self._probe_clear_fields(flds))

        # ── AUTO ZERO ────────────────────────────────────────────────────────
        self._btn_probe_auto_zero = self.ui.findChild(QPushButton, "btn_auto_zero_master")
        if self._btn_probe_auto_zero:
            self._btn_probe_auto_zero.setCheckable(True)
            # Loading of Auto Zero is now handled within _probe_prefs_load()

        # ── Load and Connect Prefs ───────────────────────────────────────────
        self._probe_prefs_load()
        self._probe_prefs_connect()

        # ── Setup Probe DRO ────────────────────────────────────────────────
        self._setup_probe_dro()

    def _on_probe_center_mode_toggled(self, inside: bool):
        """Umschaltung zwischen OUTSIDE und INSIDE."""
        self._probe_center_inside = inside
        self._btn_probe_center_mode.setText("MODE: INSIDE" if inside else "MODE: OUTSIDE")
        
        # Helper for SVGs
        def svg(filename):
            p = os.path.join(self._probe_img_dir, "center_finder", filename)
            from PySide6.QtGui import QIcon
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
        from PySide6.QtCore import QPoint
        if hasattr(self, "_probe_marker") and hasattr(self, "_probe_grid_frm"):
            w = self._probe_grid_frm.width()
            h = self._probe_grid_frm.height()
            sz = self._probe_marker_sz
            
            # Absolute position relative to the tab
            pos_in_tab = self._probe_grid_frm.mapTo(self.ui.tab_probing, QPoint(0, 0))
            
            # Sit exactly on the border (half icon size)
            badge_offset = - (sz // 2)
            
            # Default: Bottom-Left
            x = pos_in_tab.x() + badge_offset
            y = pos_in_tab.y() + h + badge_offset

            # Try to detect from INI
            if self.ini:
                try:
                    # X Axis
                    h_x = float(self.ini.find("JOINT_0", "HOME") or 0.0)
                    min_x = float(self.ini.find("AXIS_X", "MIN_LIMIT") or 0.0)
                    max_x = float(self.ini.find("AXIS_X", "MAX_LIMIT") or 1000.0)
                    if abs(h_x - max_x) < abs(h_x - min_x):
                        x = pos_in_tab.x() + w + badge_offset # Right

                    # Y Axis
                    h_y = float(self.ini.find("JOINT_1", "HOME") or 0.0)
                    min_y = float(self.ini.find("AXIS_Y", "MIN_LIMIT") or 0.0)
                    max_y = float(self.ini.find("AXIS_Y", "MAX_LIMIT") or 1000.0)
                    if abs(h_y - max_y) < abs(h_y - min_y):
                        y = pos_in_tab.y() + badge_offset # Top
                except:
                    pass

            self._probe_marker.move(x, y)
            self._probe_marker.raise_()
            self._probe_marker.show()
            
            # Position the L-accent inside the frame corner
            if hasattr(self, "_probe_corner_accent"):
                # Determine which borders to color based on position
                is_right = x > pos_in_tab.x() + (w/2)
                is_bottom = y > pos_in_tab.y() + (h/2)
                
                # Create a CSS that colors only the corner borders
                border_x = "right" if is_right else "left"
                border_y = "bottom" if is_bottom else "top"
                
                style = f"background: transparent; border-{border_x}: 4px solid #e67e00; border-{border_y}: 4px solid #e67e00;"
                self._probe_corner_accent.setStyleSheet(style)
                
                # Move to the absolute corner of the frame
                ax = w - 20 if is_right else 0
                ay = h - 20 if is_bottom else 0
                self._probe_corner_accent.move(ax, ay)
                self._probe_corner_accent.show()
                self._probe_corner_accent.raise_()

    def eventFilter(self, watched, event):
        from PySide6.QtCore import QEvent
        if watched == getattr(self, "_probe_grid_frm", None):
            if event.type() == QEvent.Resize:
                self._update_probe_marker_pos()
        # Status bar click or Simple View label click → open simple overlay
        if watched in (getattr(self, "_sb_for_filter", None), getattr(self, "_lbl_simple_view_indicator", None)):
            if event.type() == QEvent.Type.MouseButtonPress:
                self._show_simple_overlay()
        # Main window resize → keep overlay covering the full window
        if watched is self.ui:
            if event.type() == QEvent.Type.Resize:
                if hasattr(self, "simple_view"):
                    cw = self.ui.centralWidget()
                    self.simple_view.setGeometry(cw.rect() if cw else self.ui.rect())
            
            elif event.type() == QEvent.Type.Close:
                # Safe-Exit: Confirm always to prevent accidental shutdowns
                from PySide6.QtWidgets import QMessageBox
                res = QMessageBox.question(
                    self.ui, 
                    "ThorCNC beenden?", 
                    "Die Maschinen-Steuerung wirklich beenden?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if res == QMessageBox.StandardButton.No:
                    event.ignore()
                    return True # Event handled

            elif event.type() == QEvent.Type.KeyPress:
                if event.key() == Qt.Key.Key_F11:
                    if self.ui.isFullScreen():
                        self.ui.setWindowState(getattr(self, "_pre_simple_window_state", Qt.WindowState.WindowMaximized))
                        # Fallback falls state nicht da war
                        if self.ui.isFullScreen(): self.ui.showNormal()
                    else:
                        self._pre_simple_window_state = self.ui.windowState()
                        self.ui.showFullScreen()
                    return True

        return super().eventFilter(watched, event)

    def _setup_probe_dro(self):
        """Builds compact (read-only) DRO in Probing tab bottom bar."""
        from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout,
                                       QLabel, QFrame, QSizePolicy)

        container = self.ui.findChild(QHBoxLayout, "probe_dro_display_layout")
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

    # Mapping: pref-key → (widget-name, widget-type)
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

    def _probe_prefs_load(self):
        from PySide6.QtWidgets import QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QLineEdit, QPushButton
        for key, wname, wtype in self._PROBE_PREFS:
            val = self.settings.get(key)
            if val is None:
                continue
            if wtype == "SpinBox":
                if w := self._w(QSpinBox, wname):
                    w.setValue(int(val))
            elif wtype == "DoubleSpinBox":
                if w := self._w(QDoubleSpinBox, wname):
                    w.setValue(float(val))
            elif wtype == "ComboBox":
                if w := self._w(QComboBox, wname):
                    idx = w.findText(str(val))
                    if idx >= 0:
                        w.setCurrentIndex(idx)
            elif wtype == "TextEdit":
                if w := self._w(QTextEdit, wname):
                    w.setPlainText(str(val))
            elif wtype == "LineEdit":
                if w := self._w(QLineEdit, wname):
                    w.setText(str(val))
            elif wtype == "CheckButton":
                if w := self._w(QPushButton, wname):
                    # For Auto-Zero, default to True if pref is missing
                    is_on = (val.lower() == 'true') if isinstance(val, str) else bool(val)
                    w.setChecked(is_on)
                    self._on_probe_auto_zero_toggled(is_on)

    def _probe_prefs_connect(self):
        """Verbindet alle Probe-Widgets mit autosave."""
        from PySide6.QtWidgets import QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QLineEdit, QPushButton
        for key, wname, wtype in self._PROBE_PREFS:
            if wtype == "SpinBox":
                if w := self._w(QSpinBox, wname):
                    w.valueChanged.connect(
                        lambda v, k=key: self._probe_pref_save(k, v))
            elif wtype == "DoubleSpinBox":
                if w := self._w(QDoubleSpinBox, wname):
                    w.valueChanged.connect(
                        lambda v, k=key: self._probe_pref_save(k, v))
            elif wtype == "ComboBox":
                if w := self._w(QComboBox, wname):
                    w.currentTextChanged.connect(
                        lambda v, k=key: self._probe_pref_save(k, v))
            elif wtype == "TextEdit":
                if w := self._w(QTextEdit, wname):
                    w.textChanged.connect(
                        lambda k=key, wn=wname:
                            self._probe_pref_save(
                                k, self._w(QTextEdit, wn).toPlainText()))
            elif wtype == "LineEdit":
                if w := self._w(QLineEdit, wname):
                    w.textChanged.connect(
                        lambda v, k=key: self._probe_pref_save(k, v))
            elif wtype == "CheckButton":
                if w := self._w(QPushButton, wname):
                    w.toggled.connect(
                        lambda v, k=key: self._probe_pref_save(k, v))

        
    def _on_probe_auto_zero_toggled(self, on: bool):
        """Handler für den Master Auto-Zero Button: (Zusatzlogik falls nötig)."""
        # Falls später noch Logik nötig ist, hier einfügen.
        # Das eigentliche Speichern wird jetzt über _probe_prefs_connect() via 'CheckButton' erledigt.
        pass

    def _probe_pref_save(self, key: str, value):
        self.settings.set(key, value)
        self.settings.save()

    def _probe_clear_fields(self, field_names: list):
        from PySide6.QtWidgets import QLineEdit
        for name in field_names:
            if le := self._w(QLineEdit, name):
                le.setText("0")

    def _on_probe_v_override_changed(self, val: int):
        from PySide6.QtWidgets import QLabel
        if lbl := self._w(QLabel, "probe_v_override_status"):
            lbl.setText(f"V {val}%")
        self.cmd.feedrate(val / 100.0)
        self.cmd.spindleoverride(val / 100.0)

    def _on_probe_v_override_to_100(self):
        from PySide6.QtWidgets import QSlider, QLabel
        if s := self._w(QSlider, "probe_v_override_slider"):
            s.setValue(100)
        if lbl := self._w(QLabel, "probe_v_override_status"):
            lbl.setText("V 100%")
        self.cmd.feedrate(1.0)
        self.cmd.spindleoverride(1.0)

    def _probe_set_mode(self, mode: str):
        from PySide6.QtWidgets import QLabel, QPushButton
        if lbl := self._w(QLabel, "lbl_probe_section_title"):
            lbl.setText(mode)

        # Update button highlights
        btn_map = {
            "OUTSIDE CORNERS": "btn_mode_outside",
            "INSIDE CORNERS":  "btn_mode_inside",
            "CENTER FINDER":   "btn_mode_center",
            "EDGE ANGLE":      "btn_mode_angle"
        }
        if mode in btn_map:
            if btn := self._w(QPushButton, btn_map[mode]):
                btn.setChecked(True)

        if hasattr(self, "_probe_pages") and mode in self._probe_pages:
            self._probe_stack.setCurrentWidget(self._probe_pages[mode])

    def _probe_ngc_dir(self) -> str:
        """
        Gibt das NGC-Verzeichnis für Probing zurück.
        Priorität:
        1. 'subroutines/probing' relativ zur INI
        2. PROGRAM_PREFIX aus der INI
        """
        if self.ini_path:
            ini_dir = os.path.dirname(os.path.abspath(self.ini_path))
            sub_probing = os.path.join(ini_dir, "subroutines", "probing")
            if os.path.isdir(sub_probing):
                return sub_probing

        d = os.path.expanduser("~/linuxcnc/nc_files")
        if self.ini:
            cfg = self.ini.find("DISPLAY", "PROGRAM_PREFIX")
            if cfg:
                cfg = os.path.expanduser(cfg)
                if not os.path.isabs(cfg):
                    cfg = os.path.abspath(
                        os.path.join(os.path.dirname(self.ini_path), cfg))
                d = cfg
        return d

    def _probe_run_sequence(self, ngc_name: str):
        """
        Schreibt before_probe.ngc / after_probe.ngc und erzeugt
        probe_run.ngc, das die drei Dateien der Reihe nach aufruft,
        dann lädt und startet es.

        Ablauf:  before_probe.ngc → <ngc_name>.ngc → after_probe.ngc
        """
        from PySide6.QtWidgets import QTextEdit
        ngc_dir = self._probe_ngc_dir()

        # Safety check: Is a tool loaded and is it the correct probe tool?
        current_tool = self.poller.stat.tool_in_spindle
        from PySide6.QtWidgets import QSpinBox
        probe_tool_sb = self._w(QSpinBox, "spb_probe_tool")
        target_probe_tool = probe_tool_sb.value() if probe_tool_sb else 0

        if current_tool == 0:
            self._status("Probing canceled: No tool loaded (T0)", error=True)
            return

        if current_tool != target_probe_tool:
            self._status(f"Probing canceled: Tool T{current_tool} is not the configured probe tool T{target_probe_tool}!", error=True)
            return

        before_te = self._w(QTextEdit, "te_probe_before")
        after_te  = self._w(QTextEdit, "te_probe_after")
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
            self._status(f"Probe NGC not found: {ngc_name}.ngc")
            return

        # Parameter für Center Finder und Corners/Edges sammeln
        params = ""
        is_corner_edge = ngc_name.startswith("outside_") or ngc_name.startswith("inside_") or ngc_name.startswith("angle_")
        if ngc_name.startswith("center_") or is_corner_edge:
            from PySide6.QtWidgets import QLineEdit, QDoubleSpinBox
            def val(name, default="0.0"):
                if w := self._w(QLineEdit, name): return w.text() or default
                if w := self._w(QDoubleSpinBox, name): return str(w.value())
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
            self.cmd.mode(1)   # MANUAL → AUTO benötigt erst MANUAL
            self.cmd.wait_complete()
            self.cmd.mode(2)   # AUTO
            self.cmd.wait_complete()
            self.cmd.program_open(run_path)
            self.cmd.auto(0, 0)   # AUTO_RUN from line 0
            self._status(f"Probe: {ngc_name}")
        except Exception as e:
            self._status(f"Probe error: {e}")

    def _setup_html_tab(self):
        """Baut den HTML-Tab auf: links Dateiliste, rechts Viewer."""
        from PySide6.QtWidgets import QWidget, QSplitter, QListWidget, QVBoxLayout, QLabel
        from PySide6.QtCore import Qt

        tab = self._w(QWidget, "tab_html")
        if not tab:
            return

        lay = QVBoxLayout(tab)
        lay.setContentsMargins(4, 4, 4, 4)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        lay.addWidget(splitter)

        # ── Links: Dateiliste ────────────────────────────────────────────
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(2)
        left_lay.addWidget(QLabel("HTML / PDF im NGC-Ordner:"))
        self._html_list = QListWidget()
        self._html_list.setObjectName("html_doc_list")
        left_lay.addWidget(self._html_list)
        left.setMinimumWidth(160)
        splitter.addWidget(left)

        # ── Rechts: HTML-Viewer ──────────────────────────────────────────
        self._html_viewer = None
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)

        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from PySide6.QtWebEngineCore import QWebEngineSettings
            viewer = QWebEngineView()
            s = viewer.settings()
            s.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, True)
            s.setAttribute(QWebEngineSettings.WebAttribute.PdfViewerEnabled, True)
            self._html_viewer = viewer
            self._html_viewer_type = "web"
        except ImportError:
            from PySide6.QtWidgets import QTextBrowser
            viewer = QTextBrowser()
            viewer.setOpenExternalLinks(False)
            self._html_viewer = viewer
            self._html_viewer_type = "text"

        right_lay.addWidget(self._html_viewer)
        splitter.addWidget(right)

        splitter.setSizes([200, 700])
        self._html_splitter = splitter

        self._html_list.currentItemChanged.connect(self._on_html_item_changed)

    def _refresh_html_list(self, ngc_path: str):
        """Sucht HTML- und PDF-Dateien im Ordner der geladenen NGC-Datei."""
        import os
        self._html_list.clear()
        if not ngc_path:
            return
        folder = os.path.dirname(ngc_path)
        try:
            files = sorted(
                f for f in os.listdir(folder)
                if f.lower().endswith((".html", ".htm", ".pdf"))
            )
        except OSError:
            return
        for name in files:
            from PySide6.QtWidgets import QListWidgetItem
            item = QListWidgetItem(name)
            item.setData(256, os.path.join(folder, name))  # Qt.UserRole = 256
            self._html_list.addItem(item)

    def _on_html_item_changed(self, current, _previous):
        if not current or not self._html_viewer:
            return
        path = current.data(256)
        if not path:
            return
        if self._html_viewer_type == "web":
            from PySide6.QtCore import QUrl
            self._html_viewer.setUrl(QUrl.fromLocalFile(path))
        else:
            # QTextBrowser-Fallback: PDFs können nicht angezeigt werden
            if path.lower().endswith(".pdf"):
                self._html_viewer.setHtml(
                    "<p style='color:#aaa;padding:16px'>"
                    "PDF-Ansicht erfordert PySide6-WebEngine.<br>"
                    f"Datei: {path}</p>")
            else:
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        self._html_viewer.setHtml(f.read())
                except OSError:
                    pass

    def _setup_settings_tab(self):
        """Verbindet alle Settings-Sub-Tabs."""
        from PySide6.QtWidgets import (QDoubleSpinBox, QPushButton, QComboBox, QCheckBox, 
                                       QGroupBox, QVBoxLayout, QWidget, QLineEdit, QHBoxLayout, QLabel, QTextEdit)

        # ── UI Tab: Theme & Language ───────────────────────────────────────────
        if cb := self._w(QComboBox, "combo_theme"):
            # Gespeichertes Theme vorauswählen und sofort anwenden
            saved = self.settings.get("theme", "dark")
            idx = cb.findText(saved)
            if idx >= 0:
                cb.setCurrentIndex(idx)
            cb.currentTextChanged.connect(self._apply_theme)
            self._apply_theme(saved)

        if cb := self._w(QComboBox, "combo_language"):
            saved_lang = self.settings.get("language", "Deutsch")
            idx = cb.findText(saved_lang)
            if idx >= 0:
                cb.setCurrentIndex(idx)
            cb.currentTextChanged.connect(
                lambda lang: self.settings.set("language", lang))

        # ── Backplot Antialiasing ──
        if ui_tab := self._w(QWidget, "settings_tab_ui"):
            layout = ui_tab.layout()
            gb_gfx = QGroupBox("Grafik / Performance")
            # Wir suchen uns einen Platz vor dem vertikalen Spacer
            gl_gfx = QVBoxLayout(gb_gfx)
            self._cb_aa = QCheckBox("Backplot Antialiasing (Glättung)")
            self._cb_aa.setToolTip("Verbessert die Linienqualität (MSAA). Erfordert Neustart für volle Wirkung.")
            
            active = self.settings.get("backplot_antialiasing", True)
            self._cb_aa.setChecked(active)
            self._cb_aa.toggled.connect(self._on_aa_toggled)

            gl_gfx.addWidget(self._cb_aa)
            lay_msaa = QHBoxLayout()
            lay_msaa.addWidget(QLabel("MSAA Samples:"))
            self._cb_msaa = QComboBox()
            for x in [2, 4, 8, 16]:
                self._cb_msaa.addItem(f"{x}x", userData=x)
            
            saved_msaa = self.settings.get("backplot_msaa_samples", 4)
            idx = self._cb_msaa.findData(saved_msaa)
            if idx >= 0: self._cb_msaa.setCurrentIndex(idx)
            
            self._cb_msaa.setEnabled(active)
            self._cb_msaa.currentIndexChanged.connect(self._on_msaa_changed)
            
            lay_msaa.addWidget(self._cb_msaa)
            gl_gfx.addLayout(lay_msaa)

            gl_gfx.addWidget(self._cb_aa)
            layout.insertWidget(layout.count() - 1, gb_gfx)

            # ── Navigation / Tabs ──
            gb_nav = QGroupBox("Navigation")
            gl_nav = QVBoxLayout(gb_nav)
            self._cb_html_tab = QCheckBox("HTML-Tab anzeigen")
            self._cb_html_tab.setToolTip(
                "Blendet den HTML/PDF-Dokumenten-Tab in der Navigation ein oder aus.")
            self._cb_html_tab.setChecked(self.settings.get("show_html_tab", True))
            self._cb_html_tab.toggled.connect(self._on_html_tab_visibility)
            gl_nav.addWidget(self._cb_html_tab)
            layout.insertWidget(layout.count() - 1, gb_nav)

            # ── Werkzeugliste ──
            gb_tools = QGroupBox("Werkzeugliste")
            gl_tools = QVBoxLayout(gb_tools)
            self._cb_show_pocket = QCheckBox("Pocket-Spalte anzeigen")
            self._cb_show_pocket.setToolTip("Zeigt oder verbirgt die Pocket-Spalte (P) in der Werkzeugliste.")
            show_pocket = self.settings.get("show_pocket_column", True)
            self._cb_show_pocket.setChecked(show_pocket)
            self._cb_show_pocket.toggled.connect(self._on_show_pocket_column_changed)
            gl_tools.addWidget(self._cb_show_pocket)
            layout.insertWidget(layout.count() - 1, gb_tools)
            
            # Initiale Sichtbarkeit anwenden
            self._on_show_pocket_column_changed(show_pocket)

        # Initiale Sichtbarkeit anwenden (nach dem UI-Aufbau)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._on_html_tab_visibility(
            self.settings.get("show_html_tab", True)))


        # ── Machine Tab Cleanup & Probe Warning Settings ──────────────────────
        if mach_tab := self._w(QWidget, "settings_tab_machine"):
            # Robustly clear existing layout and its widgets
            if old_layout := mach_tab.layout():
                while old_layout.count():
                    item = old_layout.takeAt(0)
                    if w := item.widget():
                        w.setParent(None)
                        w.deleteLater()
                # Detach layout from widget by parenting it to a dummy
                QWidget().setLayout(old_layout)
            
            # Set a horizontal layout for the machine tab
            main_layout = QHBoxLayout(mach_tab)
            main_layout.setContentsMargins(10, 10, 10, 10)
            main_layout.setSpacing(15)
            
            # --- Column 1: Machine Safety / Warnings (Left) ---
            col_safety = QVBoxLayout()
            
            # Wrap Safety in a styled Frame
            f_safety = QFrame()
            f_safety.setFrameShape(QFrame.Shape.StyledPanel)
            f_safety.setObjectName("safetyFrame")
            
            fl_safety = QVBoxLayout(f_safety)
            gb_safety = QGroupBox("Maschinensicherheit / Warnungen")
            gl_safety = QVBoxLayout(gb_safety)
            
            # Description
            lbl_desc = QLabel("<b>Visuelle Taster-Warnung:</b><br>"
                              "Färbt die Statuszeile auffällig ein, wenn digitale "
                              "Ausgänge (M64) aktiv sind (z.B. für 3D-Taster).")
            lbl_desc.setWordWrap(True)
            lbl_desc.setObjectName("settings_desc_label")
            gl_safety.addWidget(lbl_desc)
            
            # Enable Checkbox
            self._cb_probe_warn = QCheckBox("Visuelle Warnung aktivieren")
            self._cb_probe_warn.setChecked(self._probe_warning_enabled)
            self._cb_probe_warn.toggled.connect(self._on_probe_warning_enabled_changed)
            gl_safety.addWidget(self._cb_probe_warn)
            
            # Pins Input
            lay_pins = QHBoxLayout()
            lay_pins.addWidget(QLabel("M64 P... (Index):"))
            self._le_probe_pins = QLineEdit(self._probe_warning_pins_str)
            self._le_probe_pins.setPlaceholderText("z.B. 0, 2")
            self._le_probe_pins.textChanged.connect(self._on_probe_warning_pins_changed)
            lay_pins.addWidget(self._le_probe_pins)
            gl_safety.addLayout(lay_pins)
            
            # Color Selector
            lay_color = QHBoxLayout()
            lay_color.addWidget(QLabel("Warnfarbe:"))
            self._btn_probe_color = QPushButton("WÄHLEN")
            self._btn_probe_color.setFixedWidth(120)
            self._update_probe_color_button()
            self._btn_probe_color.clicked.connect(self._pick_probe_warning_color)
            lay_color.addWidget(self._btn_probe_color)
            lay_color.addStretch()
            gl_safety.addLayout(lay_color)
            
            gl_safety.addSpacing(10)
            sep2 = QFrame()
            sep2.setFrameShape(QFrame.Shape.HLine)
            sep2.setObjectName("settings_separator")
            gl_safety.addWidget(sep2)
            gl_safety.addSpacing(5)

            # Homing conversion
            self._cb_homing_g53 = QCheckBox("Homing-Buttons umfunktionieren (Ref -> G53 X0)")
            self._cb_homing_g53.setToolTip("Ersetzt den REF-Button durch G53 X0, sobald die Achse homed ist.")
            self._cb_homing_g53.setChecked(self.settings.get("homing_g53_conversion", False))
            self._cb_homing_g53.toggled.connect(
                lambda checked: (self.settings.set("homing_g53_conversion", checked), 
                                 self.settings.save(), 
                                 self._on_homed(getattr(self.poller, "_homed", [])))
            )
            gl_safety.addWidget(self._cb_homing_g53)
            
            fl_safety.addWidget(gb_safety)
            fl_safety.addStretch() # Push safety up
            
            col_safety.addWidget(f_safety)
            main_layout.addLayout(col_safety, 1) # Stretch 1
            
            # --- Column 2: Abort Handler (Middle) ---
            col_abort = QVBoxLayout()
            gb_abort = QGroupBox("Abort Handler (STOP/Fehler)")
            gl_abort = QVBoxLayout(gb_abort)
            
            lbl_abort_desc = QLabel("<b>G-Code bei Abbruch:</b><br>"
                                     "Dieser Code wird ausgeführt, wenn das Programm gestoppt wird.<br>"
                                     "<font color='#aaa'>INI [RS274NGC] ON_ABORT_COMMAND = O&lt;on_abort&gt; call</font>")
            lbl_abort_desc.setWordWrap(True)
            gl_abort.addWidget(lbl_abort_desc)
            
            self._te_abort_gcode = QTextEdit()
            self._te_abort_gcode.setPlaceholderText("z.B. M5 M9\nG54\nG90\nG40")
            self._te_abort_gcode.setMinimumHeight(200)
            
            # GUI hat Vorrang: Immer aus den Prefs laden
            saved_abort = self.settings.get("abort_gcode", "M5 M9\nG54\nG90\nG40")
            self._te_abort_gcode.setPlainText(saved_abort)
            
            gl_abort.addWidget(self._te_abort_gcode)
            
            btn_save_abort = QPushButton("SPEICHERN & ANWENDEN")
            btn_save_abort.setMinimumHeight(45)
            btn_save_abort.clicked.connect(self._save_abort_handler)
            gl_abort.addWidget(btn_save_abort)
            
            col_abort.addWidget(gb_abort)
            main_layout.addLayout(col_abort, 2) # Give it more space
            
            # --- Column 2: Diagnostics & Components (Right) ---
            col_diag = QVBoxLayout()
            gb_diag = QGroupBox("Diagnose & Komponenten")
            gl_diag = QVBoxLayout(gb_diag)
            
            # List of diagnostics tools
            diag_tools = [
                ("HAL Show (Pins & Signale)", self._run_halshow),
                ("HAL Scope (Oszilloskop)", self._run_halscope),
                ("LinuxCNC Status (Detail-Infos)", self._run_linuxcnc_status)
            ]
            
            for text, func in diag_tools:
                b = QPushButton(text)
                b.setMinimumHeight(45)
                b.clicked.connect(func)
                gl_diag.addWidget(b)
            
            # Probe Sim Button (Sim only) - move here if present
            if b_sim := self._w(QPushButton, "btn_probe_sim"):
                gl_diag.addWidget(b_sim)
            
            gl_diag.addStretch()
            col_diag.addWidget(gb_diag)
            main_layout.addLayout(col_diag, 1) # Stretch 1

        # ── Toolsetter Settings Initialization (RESTORED) ─────────────────────
        # Spinboxen laden & verbinden
        for widget_name, prefs_key, default in self._TOOLSENSOR_FIELDS:
            dsb = self._w(QDoubleSpinBox, widget_name)
            if not dsb:
                continue

            # Wert aus Prefs laden (oder Default)
            val = self.settings.get(prefs_key, default)
            dsb.blockSignals(True)
            dsb.setValue(float(val))
            dsb.blockSignals(False)

            # HAL-Pin initial setzen
            self._hal_set(prefs_key, float(val))

            # Jede Änderung → Prefs speichern + HAL aktualisieren
            dsb.valueChanged.connect(
                lambda v, k=prefs_key: self._on_toolsensor_changed(k, v)
            )

        # "Aktuelle Position" Buttons
        if b := self._w(QPushButton, "btn_set_wechsel_pos"):
            b.clicked.connect(self._set_wechsel_pos_from_machine)
            
    def _save_abort_handler(self):
        """Speichert den G-Code für den Abort-Handler und aktualisiert die .ngc Datei."""
        import os
        gcode = self._te_abort_gcode.toPlainText()
        self.settings.set("abort_gcode", gcode)
        self.settings.save()
        
        # Pfad zur on_abort.ngc finden
        ini_dir = os.path.dirname(self.ini_path) if self.ini_path else os.getcwd()
        ngc_filename = "on_abort.ngc"
        target_path = None
        
        # 1. Priorität: Lokaler subroutines Ordner im INI-Verzeichnis
        local_sub = os.path.join(ini_dir, "subroutines", ngc_filename)
        if os.path.exists(local_sub):
            target_path = local_sub
        
        # 2. Suche in SUBROUTINE_PATH aus INI falls lokal nicht gefunden
        if not target_path and self.ini:
            sub_paths = self.ini.find("RS274NGC", "SUBROUTINE_PATH")
            if sub_paths:
                for p in sub_paths.split(":"):
                    p = p.strip()
                    if not p: continue
                    full_p = os.path.expanduser(p)
                    if not os.path.isabs(full_p):
                        full_p = os.path.join(ini_dir, full_p)
                    
                    test_path = os.path.join(full_p, ngc_filename)
                    if os.path.exists(test_path):
                        target_path = test_path
                        break
        
        # 3. Fallback: Erstelle sie lokal
        if not target_path:
            target_path = local_sub
            
        # Datei schreiben
        try:
            # Ordner sicherstellen
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            
            with open(target_path, "w", encoding="utf-8") as f:
                f.write("(--- Dynamically generated by ThorCNC ---)\n")
                f.write("(--- Settings -> Machine -> Abort Handler ---)\n\n")
                f.write("o<on_abort> sub\n")
                # User Code einrücken
                for line in gcode.splitlines():
                    f.write(f"  {line}\n")
                f.write("o<on_abort> endsub\n")
                f.write("M2\n")
            
            self._status(f"Abort-Handler aktualisiert: {target_path}")
        except Exception as e:
            self._status(f"Fehler beim Speichern des Abort-Handlers: {e}", error=True)
        if b := self._w(QPushButton, "btn_set_taster_pos"):
            b.clicked.connect(self._set_taster_pos_from_machine)

        # Before / After Toolsetter TextEdits
        from PySide6.QtWidgets import QTextEdit
        for key, wname in (("ts_before", "te_ts_before"), ("ts_after", "te_ts_after")):
            if te := self._w(QTextEdit, wname):
                val = self.settings.get(key, "")
                te.blockSignals(True)
                te.setPlainText(str(val) if val else "")
                te.blockSignals(False)
                te.textChanged.connect(
                    lambda k=key, widget=te: self._on_ts_text_save(k, widget)
                )
        self._write_ts_before_after()

    def _parse_probe_warning_pins(self, text: str):
        """Parses comma-separated string of pins into self._probe_warning_pins list."""
        self._probe_warning_pins = []
        try:
            parts = text.split(",")
            for p in parts:
                p = p.strip()
                if p.isdigit():
                    self._probe_warning_pins.append(int(p))
        except:
            self._probe_warning_pins = [0]
        if not self._probe_warning_pins:
            self._probe_warning_pins = [0]

    def _update_probe_color_button(self):
        """Updates the color button background to show current color."""
        c = self._probe_warning_color
        # Get a contrast color (white or black) for the text
        self._btn_probe_color.setStyleSheet(
            f"QPushButton {{ background-color: {c}; color: white; "
            f"border: 1px solid #444; font-weight: bold; padding: 4px; }}"
        )

    def _on_probe_warning_enabled_changed(self, enabled: bool):
        self._probe_warning_enabled = enabled
        self.settings.set("probe_warning_enabled", enabled)
        self.settings.save()
        # Trigger refresh if active
        if hasattr(self, "_last_dout"):
            self._on_digital_out_changed(self._last_dout)

    def _on_probe_warning_pins_changed(self, text: str):
        self._probe_warning_pins_str = text
        self._parse_probe_warning_pins(text)
        self.settings.set("probe_warning_pins", text)
        self.settings.save()
        # Trigger refresh
        if hasattr(self, "_last_dout"):
            self._on_digital_out_changed(self._last_dout)

    def _pick_probe_warning_color(self):
        from PySide6.QtWidgets import QColorDialog
        from PySide6.QtGui import QColor
        initial = QColor(self._probe_warning_color)
        color = QColorDialog.getColor(initial, self.ui, "Warnfarbe wählen")
        if color.isValid():
            hex_color = color.name() # #RRGGBB
            self._probe_warning_color = hex_color
            self.settings.set("probe_warning_color", hex_color)
            self.settings.save()
            self._update_probe_color_button()
            # Trigger refresh
            if hasattr(self, "_last_dout"):
                self._on_digital_out_changed(self._last_dout)

    def _get_brighter_color(self, hex_color, factor=1.2):
        """Helper to get a brighter version for the border."""
        from PySide6.QtGui import QColor
        c = QColor(hex_color)
        h, s, v, a = c.getHsv()
        # Make it brighter and slightly less saturated for "neon" effect
        v = min(255, int(v * factor))
        s = int(s * 0.9)
        return QColor.fromHsv(h, s, v, a).name()

    def _set_sim_probe(self, state: bool):
        """Setzt den simulierten Probe-Pin über die HAL-Komponente."""
        if self._hal_comp:
            try:
                self._hal_comp["probe-sim"] = state
                self._status(f"PROBE SIM: {'[ AKTIV ]' if state else '[ INAKTIV ]'}")
            except Exception as e:
                self._status(f"PROBE SIM error: {e}")

    def _hal_set(self, prefs_key: str, value: float):
        """Setzt einen HAL-Pin, wenn der HAL-Comp verfügbar ist."""
        if not self._hal_comp:
            return
        try:
            pin_name = prefs_key.replace("_", "-")
            self._hal_comp[pin_name] = value
        except Exception:
            pass

    def _on_toolsensor_changed(self, key: str, value: float):
        """Callback: Spinbox geändert → Prefs speichern + HAL-Pin setzen."""
        self.settings.set(key, value)
        self.settings.save()
        self._hal_set(key, value)

    def _on_ts_text_save(self, key: str, widget):
        """Callback: Before/After-Toolsetter TextEdit geändert → Prefs speichern + NGC schreiben."""
        self.settings.set(key, widget.toPlainText())
        self.settings.save()
        self._write_ts_before_after()
        from PySide6.QtWidgets import QTextEdit
        before = self.settings.get("ts_before", "") or ""
        after  = self.settings.get("ts_after",  "") or ""
        before_str = before.strip() or "—"
        after_str  = after.strip()  or "—"
        self._status(f"Toolsetter  BEFORE: [{before_str}]  |  AFTER: [{after_str}]")

    def _ts_ngc_dir(self) -> str:
        """Gibt das NGC-Verzeichnis für Toolsetter-Subroutinen zurück."""
        if self.ini_path:
            ini_dir = os.path.dirname(os.path.abspath(self.ini_path))
            sub_tools = os.path.join(ini_dir, "subroutines", "tools")
            if os.path.isdir(sub_tools):
                return sub_tools
        d = os.path.expanduser("~/linuxcnc/nc_files")
        if self.ini:
            cfg = self.ini.find("DISPLAY", "PROGRAM_PREFIX")
            if cfg:
                cfg = os.path.expanduser(cfg)
                if not os.path.isabs(cfg):
                    cfg = os.path.abspath(
                        os.path.join(os.path.dirname(self.ini_path), cfg))
                d = cfg
        return d

    def _write_ts_before_after(self):
        """Schreibt before_toolsetter.ngc und after_toolsetter.ngc ins Tools-Verzeichnis."""
        from PySide6.QtWidgets import QTextEdit
        ngc_dir = self._ts_ngc_dir()
        before_code = ""
        after_code = ""
        if te := self._w(QTextEdit, "te_ts_before"):
            before_code = te.toPlainText().strip()
        if te := self._w(QTextEdit, "te_ts_after"):
            after_code = te.toPlainText().strip()
        try:
            before_path = os.path.join(ngc_dir, "before_toolsetter.ngc")
            with open(before_path, "w") as f:
                f.write("O<before_toolsetter> sub\n")
                if before_code:
                    f.write(f"  {before_code}\n")
                f.write("O<before_toolsetter> endsub\n")
                f.write("M2\n")
            after_path = os.path.join(ngc_dir, "after_toolsetter.ngc")
            with open(after_path, "w") as f:
                f.write("O<after_toolsetter> sub\n")
                if after_code:
                    f.write(f"  {after_code}\n")
                f.write("O<after_toolsetter> endsub\n")
                f.write("M2\n")
        except Exception as e:
            self._status(f"Could not write toolsetter NGC files: {e}", error=True)

    def _on_aa_toggled(self, enabled: bool):
        """Callback: Antialiasing Checkbox geändert."""
        self.settings.set("backplot_antialiasing", enabled)
        self.settings.save()
        self.backplot.set_antialiasing(enabled)
        if hasattr(self, "_cb_msaa"):
            self._cb_msaa.setEnabled(enabled)
        self._status("Antialiasing-Master-Schalter geändert. (MSAA-Level braucht Neustart)")

    def _on_msaa_changed(self, index: int):
        """MSAA Samples (2x, 4x, etc) geändert."""
        val = self._cb_msaa.itemData(index)
        self.settings.set("backplot_msaa_samples", val)
        self.settings.save()
        self._status(f"MSAA auf {val}x gesetzt. Ein Neustart ist nötig.")

    def _on_html_tab_visibility(self, visible: bool):
        """Blendet den HTML-Tab-Button ein/aus."""
        self.settings.set("show_html_tab", visible)
        self.settings.save()
        from PySide6.QtWidgets import QPushButton, QTabWidget
        if btn := self._w(QPushButton, "nav_html"):
            btn.setVisible(visible)
        # If HTML tab is currently active, switch back to Main
        if not visible:
            if tab := self._w(QTabWidget, "tabWidget"):
                html_idx = self._html_tab_index()
                if tab.currentIndex() == html_idx:
                    tab.setCurrentIndex(0)

    def _on_show_pocket_column_changed(self, visible: bool):
        """Blendet die Pocket-Spalte in der Werkzeugliste ein/aus."""
        if self.tool_table:
            self.tool_table.setColumnHidden(1, not visible)
        self.settings.set("show_pocket_column", visible)
        self.settings.save()

    def _html_tab_index(self) -> int:
        """Gibt den tabWidget-Index von tab_html zurück."""
        from PySide6.QtWidgets import QTabWidget, QWidget
        tab = self._w(QTabWidget, "tabWidget")
        if not tab:
            return 5
        for i in range(tab.count()):
            if tab.widget(i) and tab.widget(i).objectName() == "tab_html":
                return i
        return 5

    def _set_wechsel_pos_from_machine(self):
        """Sets the current machine position as Change Position X/Y/Z."""
        from PySide6.QtWidgets import QDoubleSpinBox, QMessageBox
        
        # Sicherheitsabfrage
        res = QMessageBox.question(self.ui, "Position übernehmen", 
                                  "Möchtest du die aktuelle Maschinenposition wirklich als neue WECHSELPOSITION übernehmen?",
                                  QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if res != QMessageBox.StandardButton.Yes:
            return

        pos = getattr(self, "_last_pos", None)
        if pos is None:
            self._status("Keine Positionsdaten verfügbar!", error=True)
            return
        mapping = [
            ("dsb_ts_wechsel_x", "ts_wechsel_x", 0),
            ("dsb_ts_wechsel_y", "ts_wechsel_y", 1),
            ("dsb_ts_wechsel_z", "ts_wechsel_z", 2),
        ]
        for widget_name, prefs_key, axis_idx in mapping:
            dsb = self._w(QDoubleSpinBox, widget_name)
            if dsb:
                dsb.setValue(pos[axis_idx])
        self._status("Change position set from current machine position.")

    def _set_taster_pos_from_machine(self):
        """Sets the current machine position as Probe Position X/Y/Z."""
        from PySide6.QtWidgets import QDoubleSpinBox, QMessageBox
        
        # Sicherheitsabfrage
        res = QMessageBox.question(self.ui, "Position übernehmen", 
                                  "Möchtest du die aktuelle Maschinenposition wirklich als neue MESSPOSITION übernehmen?",
                                  QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if res != QMessageBox.StandardButton.Yes:
            return

        pos = getattr(self, "_last_pos", None)
        if pos is None:
            self._status("Keine Positionsdaten verfügbar!", error=True)
            return
        mapping = [
            ("dsb_ts_x", "ts_x", 0),
            ("dsb_ts_y", "ts_y", 1),
            ("dsb_ts_z", "ts_z", 2),
        ]
        for widget_name, prefs_key, axis_idx in mapping:
            dsb = self._w(QDoubleSpinBox, widget_name)
            if dsb:
                dsb.setValue(pos[axis_idx])
        self._status("Probe position set from current machine position.")

    def _setup_opt_jalousie(self):
        """Initialisiert die Animation für das OPT-Panel."""
        self._opt_panel = self.ui.findChild(QFrame, "optExpandPanel")
        if not self._opt_panel:
            print("[ThorCNC] WARNUNG: optExpandPanel nicht in UI gefunden.")
            return
            
        self._opt_anim = QPropertyAnimation(self._opt_panel, b"maximumHeight")
        self._opt_anim.setDuration(300)
        self._opt_anim.setEasingCurve(QEasingCurve.Type.InOutQuart)
        
        # Buttons im Panel verbinden
        btn_sb = self.ui.findChild(QPushButton, "btn_opt_sb")
        btn_m1 = self.ui.findChild(QPushButton, "btn_opt_m1")
        
        if btn_sb:
            btn_sb.clicked.connect(self._toggle_sb_internal)
        if btn_m1:
            btn_m1.clicked.connect(self._toggle_m1_internal)
            
        # Status-Sync für die neuen Buttons
        self.poller.periodic.connect(self._sync_opt_buttons)

    def _sync_opt_buttons(self):
        """Synchronisiert die Sidebar-Buttons mit dem Maschinenstatus."""
        btn_sb = self.ui.findChild(QPushButton, "btn_opt_sb")
        btn_m1 = self.ui.findChild(QPushButton, "btn_opt_m1")
        
        if btn_sb:
            btn_sb.setChecked(self.is_single_block)
        if btn_m1:
            btn_m1.setChecked(bool(self.poller.stat.optional_stop))
        
        # Homing / G53 Buttons sperren wenn Maschine läuft
        is_idle = self.poller.stat.interp_state == linuxcnc.INTERP_IDLE
        can_mdi = is_idle and not self.poller.stat.estop and self.poller.stat.enabled

        # Z-Safety: G53 X/Y shortcuts only if Z is at machine zero
        homed = getattr(self.poller, "_homed", [])
        enable_g53 = self.settings.get("homing_g53_conversion", False)
        z_mach = getattr(self, "_last_pos", [0,0,-999])[2]
        z_safe = abs(z_mach) < 0.1 # 0.1mm Toleranz

        if hasattr(self, "_btn_ref_all") and self._btn_ref_all:
            self._btn_ref_all.setEnabled(can_mdi)
            
        for i, axis in enumerate(("X", "Y", "Z")):
            if axis in self._dro_ref_btn:
                btn = self._dro_ref_btn[axis]
                is_homed = i < len(homed) and homed[i]
                
                btn_enabled = can_mdi
                # Wenn G53-Modus für X/Y aktiv ist, prüfen wir Z-Sicherheit
                if axis in ("X", "Y") and enable_g53 and is_homed:
                    if not z_safe:
                        btn_enabled = False
                
                btn.setEnabled(btn_enabled)

        # Find M6 Button sperren
        if hasattr(self, "_btn_find_m6") and self._btn_find_m6:
            self._btn_find_m6.setEnabled(is_idle)

    def _toggle_sb_internal(self):
        self.is_single_block = not self.is_single_block
        self._status(f"Single Block: {'AN' if self.is_single_block else 'AUS'}")

    def _toggle_m1_internal(self):
        curr = bool(self.poller.stat.optional_stop)
        self.cmd.set_optional_stop(not curr)
        self._status(f"M1 Optional Stop: {'AN' if not curr else 'AUS'}")

    def _on_opt_clicked(self):
        """Toggle-Logik für das Jalousie-Panel."""
        if not hasattr(self, "_opt_panel") or not self._opt_panel:
            return
            
        is_expanded = self._opt_panel.maximumHeight() > 0
        
        if is_expanded:
            self._opt_anim.setStartValue(100)
            self._opt_anim.setEndValue(0)
        else:
            self._opt_anim.setStartValue(0)
            self._opt_anim.setEndValue(105) # Höhe für 2 Buttons + Spacing
            
        self._opt_anim.start()

    def _on_toggle_gcode_edit(self):
        """Schaltet den G-Code Viewer in den Editiermodus um."""
        if not self.gcode_view:
            return
        
        is_edit = self._btn_edit_gcode.isChecked()
        self.gcode_view.setReadOnly(not is_edit)
        self._btn_save_gcode.setEnabled(is_edit)
        
        # Style-Update via Property (optional)
        self._btn_edit_gcode.setProperty("active", is_edit)
        self._btn_edit_gcode.style().unpolish(self._btn_edit_gcode)
        self._btn_edit_gcode.style().polish(self._btn_edit_gcode)
        
        if is_edit:
            self._status("G-CODE EDIT MODE ENABLED")
            # Update save button state based on current modification
            self._on_gcode_modification_changed(self.gcode_view.document().isModified())
        else:
            self._status("G-CODE EDIT MODE DISABLED")
            self._btn_save_gcode.setEnabled(False)

    @Slot(bool)
    def _on_gcode_modification_changed(self, modified: bool):
        """Wird aufgerufen, wenn sich der Änderungsstatus des G-Codes ändert."""
        if not self.gcode_view:
            return
            
        # Button nur aktivieren, wenn wir auch im Edit-Modus sind
        is_edit = self._btn_edit_gcode.isChecked()
        self._btn_save_gcode.setEnabled(is_edit and modified)
        
        # Property für das Styling
        self._btn_save_gcode.setProperty("modified", modified)
        self._btn_save_gcode.style().unpolish(self._btn_save_gcode)
        self._btn_save_gcode.style().polish(self._btn_save_gcode)

    def _on_save_gcode(self):
        """Speichert den aktuell editierten G-Code zurück in die Datei."""
        if not self._user_program or not os.path.exists(self._user_program):
            self._status("SAVE FAILED: NO FILE LOADED")
            return
            
        try:
            content = self.gcode_view.toPlainText()
            with open(self._user_program, 'w') as f:
                f.write(content)
            
            self.gcode_view.document().setModified(False)
            self._status(f"G-CODE SAVED: {os.path.basename(self._user_program)}")
            
            # Neu parsen für Backplot
            tp = parse_file(self._user_program)
            self._last_toolpath = tp
            self.backplot.load_toolpath(tp)
            
            # Wenn wir fertig sind mit Speichern, Edit-Mode verlassen?
            # Der User entscheidet das meist selbst. Wir lassen ihn drin.
        except Exception as e:
            self._status(f"SAVE ERROR: {str(e)}")

    def _find_next_m6(self):
        """Sucht nach dem nächsten M6 Werkzeugwechsel im G-Code."""
        if not self.gcode_view:
            return

        text = self.gcode_view.toPlainText()
        if not text:
            return
            
        lines = text.split('\n')
        total_lines = len(lines)
        
        # Aktuelle Zeile (0-basiert)
        cursor = self.gcode_view.textCursor()
        start_line = cursor.blockNumber()
        
        # Regex für M6 (G-Code konform: ignoriert Kommentare)
        m6_ptrn = re.compile(r'(?<!\()(?:\bM6\b)', re.IGNORECASE)

        # 1. Suche ab der nächsten Zeile bis zum Dateiende
        found_idx = -1
        for i in range(start_line + 1, total_lines):
            line_clean = re.sub(r'\(.*?\)|;.*', '', lines[i])
            if m6_ptrn.search(line_clean):
                found_idx = i
                break
        
        # 2. Zyklische Suche: Falls nichts gefunden, vom Dateianfang bis zur aktuellen Zeile
        if found_idx == -1:
            for i in range(0, start_line + 1):
                line_clean = re.sub(r'\(.*?\)|;.*', '', lines[i])
                if m6_ptrn.search(line_clean):
                    found_idx = i
                    break
        
        if found_idx != -1:
            # Zeile hervorheben und Statusmeldung
            # Wir erzwingen den Cursor-Sprung (move_cursor=True), damit der User sieht wo das M6 ist
            self.gcode_view.set_current_line(found_idx + 1, move_cursor=True)
            self._status(f"M6 gefunden in Zeile {found_idx + 1}")
        else:
            self._status("Kein M6 im Programm gefunden.")

    def _connect_signals(self):
        p = self.poller
        ui = self.ui

        p.estop_changed.connect(self._on_estop)
        p.machine_on_changed.connect(self._on_machine_on)
        p.mode_changed.connect(self._on_mode)
        p.interp_changed.connect(self._on_interp)
        p.position_changed.connect(self._on_position)
        p.tool_in_spindle.connect(self._on_tool)
        p.tool_offset_changed.connect(self._on_tool_offset_changed)
        p.spindle_at_speed.connect(self._on_spindle_at_speed)
        p.spindle_speed_actual.connect(self._on_spindle_actual)
        p.spindle_load.connect(self._on_spindle_load)
        p.feed_override.connect(self._on_feed_override)
        p.spindle_override.connect(self._on_spindle_override)
        if hasattr(p, 'rapid_override'):
            p.rapid_override.connect(self._on_rapid_override)
        p.spindle_speed_cmd.connect(self._on_spindle_speed)
        p.homed_changed.connect(self._on_homed)
        p.g5x_index_changed.connect(self._on_g5x_index)
        p.g5x_offset_changed.connect(self._on_g5x_offset)
        p.gcodes_changed.connect(self._on_gcodes)
        p.mcodes_changed.connect(self._on_mcodes)
        p.file_loaded.connect(self._on_file_loaded)
        p.program_line.connect(self._on_program_line)
        p.error_message.connect(self._on_error)
        p.info_message.connect(self._on_info)
        p.digital_outputs_changed.connect(self._on_digital_out_changed)

        # ── Machine Buttons (probe_basic widget names) ──────────────────────
        from PySide6.QtWidgets import QPushButton, QSlider
        def btn(name):
            return ui.findChild(QPushButton, name)
        def sld(name):
            return ui.findChild(QSlider, name)

        if b := btn("power_button"):
            b.clicked.connect(self._toggle_power)
        if b := btn("stop_button"):
            b.clicked.connect(self._stop_program)
        if b := btn("btn_opt"):
            b.clicked.connect(self._on_opt_clicked)
        if b := btn("btn_run"):
            b.clicked.connect(self._run_program)
        if b := btn("manual_mode_button"):
            b.clicked.connect(lambda: self.cmd.mode(linuxcnc.MODE_MANUAL))
        if b := btn("mdi_mode_button"):
            b.clicked.connect(lambda: self.cmd.mode(linuxcnc.MODE_MDI))
        if b := btn("auto_mode_button"):
            b.clicked.connect(lambda: self.cmd.mode(linuxcnc.MODE_AUTO))
        if b := btn("go_to_home_button"):
            b.clicked.connect(self._home_all)
        if b := btn("estop_button"):
            b.clicked.connect(self._toggle_estop)

        # Spindle Controls
        def _start_spindle(direction):
            # Get current programmed speed (S value)
            speed = abs(self.poller.stat.spindle[0]['speed'])
            # Fallback if no speed was ever set
            if speed < 1:
                # Versuche Standardwert aus INI zu lesen, sonst 1000
                speed = 6000
                if self.ini:
                    try:
                        val = self.ini.find("DISPLAY", "DEFAULT_SPINDLE_SPEED")
                        if val:
                            speed = float(val)
                    except:
                        pass
            self.cmd.mode(linuxcnc.MODE_MANUAL)
            self.cmd.spindle(direction, speed)

        if b := btn("btn_spindle_fwd"):
            b.clicked.connect(lambda: _start_spindle(linuxcnc.SPINDLE_FORWARD))
        if b := btn("btn_spindle_rev"):
            b.clicked.connect(lambda: _start_spindle(linuxcnc.SPINDLE_REVERSE))
        if b := btn("btn_spindle_stop"):
            b.clicked.connect(lambda: self.cmd.spindle(linuxcnc.SPINDLE_OFF))

        # ── Compact Layout Spacing & Perfect Alignment ─────────────────────
        from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QComboBox
        for grp_name in ("spindleGroup", "jogBox"):
            if g := self._w(QGroupBox, grp_name):
                if lay := g.layout():
                    lay.setSpacing(1) # Even tighter
                    lay.setContentsMargins(4, 4, 4, 4)

        # Align Left Sidebar (Mode, Estop, Power)
        cb_mode = ui.findChild(QComboBox, "combo_machine_mode")
        btn_estop = ui.findChild(QPushButton, "estop_button")
        if cb_mode and btn_estop:
            # Force same width to align left/right edges
            target_w = 110 # approx width from UI
            cb_mode.setFixedWidth(target_w)
            # Find their layout and tighten it
            if lay := cb_mode.parent().layout():
                lay.setSpacing(4)
                lay.setContentsMargins(0, 0, 0, 0)
        
        # Align Right Sidebar (Run, Pause, Stop)
        btn_run = ui.findChild(QPushButton, "btn_run")
        if btn_run:
            if lay := btn_run.parent().layout():
                lay.setSpacing(4)
                # Flush to right and bottom (0 margins)
                lay.setContentsMargins(0, 0, 0, 0)
        if b := btn("btn_m6_change"):
            b.clicked.connect(self._send_m6)
        if b := btn("ref_all_button"):
            b.clicked.connect(self._home_all)
        if b := btn("ref_x_button"):
            b.clicked.connect(lambda: self._home_joint(0))
        if b := btn("ref_y_button"):
            b.clicked.connect(lambda: self._home_joint(1))
        if b := btn("ref_z_button"):
            b.clicked.connect(lambda: self._home_joint(2))
        if b := btn("btn_pause_mdi"):
            b.clicked.connect(self._pause_program)
        if b := btn("feed_override_to_100_button"):
            b.clicked.connect(lambda: self.cmd.feedrate(1.0))
        if b := btn("spindle_override_to_100_button"):
            b.clicked.connect(lambda: self.cmd.spindleoverride(1.0))
        if b := btn("rapid_override_to_100_button"):
            b.clicked.connect(lambda: self.cmd.rapidrate(1.0))
        if b := btn("v_override_to_100_button"):
            b.clicked.connect(self._on_v_override_to_100)
        
        # HAL Show
        if b := btn("btn_halshow"):
            b.clicked.connect(self._run_halshow)

        # Go to Home
        if b := btn("btn_go_to_home"):
            b.clicked.connect(self._go_to_home)

        # Jog buttons (Suffix _3 = jog_xyz page, 3-axis)
        for axis, joint in (("x", 0), ("y", 1), ("z", 2)):
            for dirn, sign in (("plus", 1), ("minus", -1)):
                if b := btn(f"{axis}_{dirn}_jogbutton_3"):
                    b.pressed.connect(
                        lambda a=joint, s=sign: self._jog_start(a, s))
                    b.released.connect(
                        lambda a=joint: self._jog_stop(a))

        # Machine mode combobox (MANUAL / AUTO / MDI)
        _MODE_MAP = [linuxcnc.MODE_MANUAL, linuxcnc.MODE_AUTO, linuxcnc.MODE_MDI]
        from PySide6.QtWidgets import QComboBox
        if cb := ui.findChild(QComboBox, "combo_machine_mode"):
            cb.activated.connect(lambda idx: self.cmd.mode(_MODE_MAP[idx]))

        # Overrides & Jog Slider
        from PySide6.QtWidgets import QLabel
        from PySide6.QtCore import Qt
        for lbl_name in ["feed_override_status", "spindle_override_status", "rapid_override_status", "v_override_status", "jog_vel_label"]:
            if lbl := self._w(QLabel, lbl_name):
                lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        if s := sld("feed_override_slider"):
            s.valueChanged.connect(lambda v: self.cmd.feedrate(v / 100.0))
        if s := sld("spindle_override_slider"):
            s.valueChanged.connect(lambda v: self.cmd.spindleoverride(v / 100.0))
        if s := sld("rapid_override_slider"):
            s.valueChanged.connect(lambda v: self.cmd.rapidrate(v / 100.0))
        if s := sld("v_override_slider"):
            s.valueChanged.connect(self._on_v_override_changed)
        if s := sld("jog_vel_slider"):
            s.valueChanged.connect(self._on_jog_vel_changed)

        # Jog Increment Buttons (Exclusive)
        if b := btn("btn_jog_cont"):
            b.clicked.connect(lambda: self._set_jog_increment(0.0))
        if b := btn("btn_jog_1_0"):
            b.clicked.connect(lambda: self._set_jog_increment(1.0))
        if b := btn("btn_jog_0_1"):
            b.clicked.connect(lambda: self._set_jog_increment(0.1))
        if b := btn("btn_jog_0_01"):
            b.clicked.connect(lambda: self._set_jog_increment(0.01))

        # Nav-Buttons → tabWidget
        from PySide6.QtWidgets import QTabWidget, QButtonGroup
        tab = ui.findChild(QTabWidget, "tabWidget")
        if tab:
            self.nav_group = QButtonGroup(self)
            self.nav_group.setExclusive(True)

            nav_names = ["nav_main", "nav_file", "nav_tool", "nav_offsets",
                         "nav_probing", "nav_html", "nav_settings", "nav_status", "nav_quit"]

            for idx, name in enumerate(nav_names):
                b = btn(name)

                if b:
                    b.setMinimumHeight(38)
                    b.setCursor(Qt.CursorShape.PointingHandCursor)
                    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                    
                    if name == "nav_quit":
                        b.setCheckable(False)
                        b.clicked.connect(self.ui.close)
                    else:
                        b.setCheckable(True)
                        self.nav_group.addButton(b, idx)
                        b.clicked.connect(lambda _, i=idx, t=tab: t.setCurrentIndex(i))
            
            tab.currentChanged.connect(self._sync_nav_buttons)
            # Initial sync (Wait a bit for machine state)
            from PySide6.QtCore import QTimer
            QTimer.singleShot(500, lambda: self._sync_nav_buttons(tab.currentIndex()))

        # Simple View — fullscreen overlay, opened by clicking the status bar
        self._setup_simple_overlay()

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _w(self, cls, name):
        return self.ui.findChild(cls, name)

    @Slot(bool)
    def _on_estop(self, active: bool):
        self._status(f"ESTOP {'AKTIV' if active else 'ZURÜCKGESETZT'}")
        from PySide6.QtWidgets import QPushButton
        _base = "border-radius: 6px; font-weight: bold; font-size: 14pt; min-height: 70px;"
        # Main Tab
        if b := self._w(QPushButton, "estop_button"):
            if active:
                b.setStyleSheet(f"QPushButton {{ border: 2px solid #ff4444; color: #cc0000; {_base} }}")
            else:
                b.setStyleSheet(f"QPushButton {{ background-color: #cc0000; color: white; {_base} }}")
        
        # Simple View
        sv = getattr(self, "simple_view", None)
        if sv and (b_s := getattr(sv, "btn_estop", None)):
             if active:
                 b_s.setStyleSheet(f"QPushButton {{ border: 2px solid #ff4444; color: #cc0000; {_base} }}")
             else:
                 b_s.setStyleSheet(f"QPushButton {{ background-color: #cc0000; color: white; {_base} }}")

    @Slot(bool)
    def _on_machine_on(self, on: bool):
        from PySide6.QtWidgets import QPushButton
        self._is_machine_on = on
        if b := self._w(QPushButton, "power_button"):
            _base = "border-radius: 6px; font-weight: bold; font-size: 14pt; min-height: 70px;"
            if on:
                b.setStyleSheet(f"QPushButton {{ background-color: #27ae60; color: white; {_base} }}")
            else:
                b.setStyleSheet(f"QPushButton {{ border: 2px solid #27ae60; color: #27ae60; {_base} }}")
        self._update_run_buttons()
        # GO TO HOME: only green if machine is ON AND all joints are homed
        self._update_goto_home_style(on and getattr(self, "_all_joints_homed", False))

    @Slot(int)
    def _on_mode(self, mode: int):
        from PySide6.QtWidgets import QPushButton, QComboBox
        self._current_mode = mode
        for name, m in (("manual_mode_button", linuxcnc.MODE_MANUAL),
                        ("mdi_mode_button",    linuxcnc.MODE_MDI),
                        ("auto_mode_button",   linuxcnc.MODE_AUTO)):
            if b := self._w(QPushButton, name):
                b.setChecked(mode == m)
        _IDX = {linuxcnc.MODE_MANUAL: 0, linuxcnc.MODE_AUTO: 1, linuxcnc.MODE_MDI: 2}
        if cb := self._w(QComboBox, "combo_machine_mode"):
            cb.blockSignals(True)
            cb.setCurrentIndex(_IDX.get(mode, 0))
            cb.blockSignals(False)
        # MDI-Modus → automatisch MDI-Seite zeigen
        # (not if _silent_mdi is set – e.g. during M6 tool change)
        if hasattr(self, "_gcode_mdi_stack"):
            if mode == linuxcnc.MODE_MDI:
                if not getattr(self, "_silent_mdi", False):
                    self._switch_gcode_panel(1)
            else:
                self._silent_mdi = False
                self._switch_gcode_panel(0)
        # GO TO HOME im AUTO-Modus deaktivieren
        self._update_goto_home_style(self._is_machine_on and getattr(self, "_all_joints_homed", False))

    @Slot(int)
    def _on_interp(self, state: int):
        from PySide6.QtWidgets import QPushButton
        self._interp_state = state
        running = state in (linuxcnc.INTERP_READING, linuxcnc.INTERP_WAITING)
        paused  = state == linuxcnc.INTERP_PAUSED
        if b := self._w(QPushButton, "stop_button"):
            b.setEnabled(running or paused)
        if b := self._w(QPushButton, "btn_pause_mdi"):
            b.setEnabled(running)
            
        self._update_run_buttons()

    def _update_run_buttons(self):
        from PySide6.QtWidgets import QPushButton
        btn_run = self._w(QPushButton, "btn_run")
        btn_pause = self._w(QPushButton, "btn_pause_mdi")
        btn_stop = self._w(QPushButton, "stop_button")
        
        # Simple View buttons
        sv = getattr(self, "simple_view", None)
        s_run   = getattr(sv, "btn_start", None) if sv else None
        s_pause = getattr(sv, "btn_pause", None) if sv else None
        s_stop  = getattr(sv, "btn_stop", None) if sv else None
        
        def set_status(w, status):
            if w and w.property("status") != status:
                w.setProperty("status", status)
                # Use individual widget style to ensure polishing works correctly across overlays
                w.style().unpolish(w)
                w.style().polish(w)

        if not self._is_machine_on:
            for btn in (btn_run, btn_pause, btn_stop, s_run, s_pause, s_stop):
                set_status(btn, "disabled")
            return

        is_running = self._interp_state in (linuxcnc.INTERP_READING, linuxcnc.INTERP_WAITING)
        is_paused = self._interp_state == linuxcnc.INTERP_PAUSED
        is_idle = self._interp_state == linuxcnc.INTERP_IDLE

        # Cycle Start
        if is_running:
            set_status(btn_run, "running")
            set_status(s_run, "running")
        elif (is_idle or is_paused) and self._has_file:
            set_status(btn_run, "ready")
            set_status(s_run, "ready")
        else:
            set_status(btn_run, "idle")
            set_status(s_run, "idle")

        # Feedhold
        if is_paused:
            set_status(btn_pause, "paused")
            set_status(s_pause, "paused")
        elif is_running:
            set_status(btn_pause, "running")
            set_status(s_pause, "running")
        else:
            set_status(btn_pause, "idle")
            set_status(s_pause, "idle")

        # Stop
        if is_running or is_paused:
            set_status(btn_stop, "active")
            set_status(s_stop, "active")
        else:
            set_status(btn_stop, "idle")
            set_status(s_stop, "idle")

    @Slot(list)
    def _on_position(self, pos: list):
        # ── Performance Throttling ─────────────────────────────────────────
        # Only update GUI if the move is significant (> 0.005mm)
        # or if the machine has stopped (interp idle) to ensure final precision.
        significant = False
        if hasattr(self, "_last_gui_pos"):
            for i in range(min(3, len(pos))):
                if abs(pos[i] - self._last_gui_pos[i]) > 0.005:
                    significant = True
                    break
        
        # Always update if machine transitions to IDLE to settle the display
        if self.poller.stat.interp_state == linuxcnc.INTERP_IDLE:
             significant = True
             
        if not significant:
            return
            
        self._last_gui_pos = list(pos[:3])
        self._last_pos = pos
        self._refresh_dro()

    def _refresh_dro(self, _=None):
        pos = getattr(self, "_last_pos", None)
        if pos is None:
            return
        g5x   = getattr(self.poller, "_g5x_offset", None) or [0.0, 0.0, 0.0]
        try:
            t_off = self.poller.stat.tool_offset or [0.0, 0.0, 0.0]
        except AttributeError:
            t_off = [0.0, 0.0, 0.0]
            
        homed = getattr(self.poller, "_homed", []) or []

        all_homed = True
        for i, axis in enumerate(("X", "Y", "Z")):
            is_homed = i < len(homed) and homed[i]
            if not is_homed:
                all_homed = False
            work = pos[i] - g5x[i] - t_off[i]
            mach = pos[i]
            dtg  = self.poller.stat.dtg[i] if hasattr(self.poller.stat, 'dtg') else 0.0

            if axis in self._dro_work:
                self._dro_work[axis].setText(f"{work:+.3f}")
            if axis in self._dro_machine:
                self._dro_machine[axis].setText(f"{mach:+.3f}")
            if axis in getattr(self, "_dro_dtg", {}):
                self._dro_dtg[axis].setText(f"{dtg:+.3f}")

            # probe-DRO mitsyncen
            probe_dro_work = getattr(self, "_probe_dro_work", {})
            probe_dro_mach = getattr(self, "_probe_dro_machine", {})
            if axis in probe_dro_work:
                probe_dro_work[axis].setText(f"{work:+.3f}")
            if axis in probe_dro_mach:
                probe_dro_mach[axis].setText(f"{mach:+.3f}")

        # Tool marker only visible if all axes are homed
        if all_homed:
            self.backplot.set_tool_position(pos[0] - t_off[0], pos[1] - t_off[1], pos[2] - t_off[2])
            if hasattr(self, "simple_view") and self.simple_view.backplot:
                self.simple_view.backplot.set_tool_position(pos[0] - t_off[0], pos[1] - t_off[1], pos[2] - t_off[2])
        else:
            self.backplot.set_tool_position(float('nan'), float('nan'), float('nan'))
            if hasattr(self, "simple_view") and self.simple_view.backplot:
                self.simple_view.backplot.set_tool_position(float('nan'), float('nan'), float('nan'))

        # Simple View overlay DRO sync (only when visible to save work)
        if hasattr(self, "simple_view") and self.simple_view.isVisible():
            w_coords = [pos[i] - g5x[i] - t_off[i] for i in range(3)]
            m_coords = [pos[i] for i in range(3)]
            dtg_vals = [
                self.poller.stat.dtg[i] if hasattr(self.poller.stat, "dtg") else 0.0
                for i in range(3)
            ]
            self.simple_view.set_wcs(*w_coords)
            self.simple_view.set_machine(*m_coords)
            self.simple_view.set_dtg(*dtg_vals)
            # Actual feed velocity (mm/min) instead of feedrate override factor
            feed = self.poller.stat.current_vel * 60.0
            # Prefer HAL actual RPM, fall back to commanded speed
            rpm = getattr(self.poller, '_spindle_actual', 0.0)
            if rpm is None or rpm <= 0:
                rpm = abs(self.poller.stat.spindle[0]['speed'])
            self.simple_view.set_feed_rpm(feed, rpm)

    @Slot(int)
    def _on_tool(self, tool: int):
        from PySide6.QtWidgets import QLineEdit, QTableWidget, QLabel
        if tool == 0:
            return  # Tool 0 = no/unknown tool, do not overwrite display

        # Update modular status bar label
        lbl = self.status_bar.findChild(QLabel, "label_tool_nr")
        if lbl:
            lbl.setText(f"T{tool}")
            
        if entry := self._w(QLineEdit, "mdi_m6_entry"):
            # Nur aktualisieren wenn der User gerade nicht tippt
            if not entry.hasFocus():
                entry.setText(str(tool))

        # Tool-Tabelle neu einlesen (Messung kann .tbl Datei geändert haben)
        self._load_tool_table()

        # Geometrie aus dem gerade neu geladenen Widget lesen
        from PySide6.QtWidgets import QTableWidget
        table = self._w(QTableWidget, "toolTable")
        dia, length, comment = "0.000", "0.000", "-"
        if table:
            for r in range(table.rowCount()):
                t_item = table.item(r, 0)
                if t_item and t_item.text().strip() == str(tool):
                    d_item = table.item(r, 2)
                    len_item = table.item(r, 3)
                    c_item = table.item(r, 4)
                    if d_item: dia = d_item.text()
                    if len_item: length = len_item.text()
                    if c_item: comment = c_item.text()
                    break

        def _fmt3(val: str) -> str:
            try:
                return f"{float(val):.3f}"
            except ValueError:
                return val

        if dia_lbl := self._w(QLabel, "tool_dia_label"):
            dia_lbl.setText(_fmt3(dia))
        if len_lbl := self._w(QLabel, "tool_len_label"):
            len_lbl.setText(_fmt3(length))
        if c_lbl := self._w(QLabel, "tool_comment_label"):
            c_lbl.setText(comment)
        # Probe-Statusbar mitsyncen
        if nr_lbl := self._w(QLabel, "probe_tool_nr_label"):
            nr_lbl.setText(f"T{tool}")
        if dia_lbl := self._w(QLabel, "probe_tool_dia_label"):
            dia_lbl.setText(_fmt3(dia))
        if len_lbl := self._w(QLabel, "probe_tool_len_label"):
            len_lbl.setText(_fmt3(length))
        if c_lbl := self._w(QLabel, "probe_tool_comment_label"):
            c_lbl.setText(comment)
            
        try:
            fdia = float(dia) if dia.strip() else 0.0
        except ValueError:
            fdia = 0.0
        try:
            flen = float(length) if length.strip() else 0.0
        except ValueError:
            flen = 0.0
        self.backplot.set_tool_geometry(fdia, flen)
        # Sync to Simple View if present
        sv = getattr(self, "simple_view", None)
        if sv and hasattr(sv, "backplot") and sv.backplot:
            sv.backplot.set_tool_geometry(fdia, flen)

    @Slot(list)
    def _on_tool_offset_changed(self, _):
        """Tool offset has changed (e.g. after measurement) -> update tool display."""
        tool = self.poller.stat.tool_in_spindle
        if tool > 0:
            self._on_tool(tool)

    @Slot(tuple)
    def _on_gcodes(self, gcodes: tuple):
        self._current_gcodes = gcodes
        self._update_active_codes_display()
        self._sync_wcs_from_gcodes(gcodes)

    def _sync_wcs_from_gcodes(self, gcodes: tuple):
        """Extrahiert das WCS aus den aktiven G-Codes und synchronisiert die Combo."""
        # WCS ist in Modale Gruppe 6: G54=540, G55=550, ..., G59.3=593
        for g in gcodes:
            if 540 <= g <= 593:
                # Berechne den Index (1-9)
                idx = 0
                if g <= 590: # G54..G59
                    idx = (g - 540) // 10 + 1
                else: # G59.1..G59.3
                    idx = (g - 590) + 6
                
                # Jetzt die Combo synchronisieren
                combo = getattr(self, "_wcs_combo", None)
                if combo:
                    for i in range(combo.count()):
                        if int(combo.itemData(i) or 0) == idx:
                            if combo.currentIndex() != i:
                                # print(f"[ThorCNC] WCS-Sync via G-Code: G{g/10.0:g} -> Index {idx}")
                                combo.blockSignals(True)
                                combo.setCurrentIndex(i)
                                combo.blockSignals(False)
                            break
                break

    @Slot(tuple)
    def _on_mcodes(self, mcodes: tuple):
        self._current_mcodes = mcodes
        self._update_active_codes_display()

    def _update_active_codes_display(self):
        from PySide6.QtWidgets import QLabel
        from PySide6.QtCore import Qt
        lbl = self._w(QLabel, "active_gcodes_label")
        if not lbl:
            return

        # Lade Einstellungen
        s = self.settings
        imp_list = set(s.get("hlight_gc_imp_list", "").replace(",", " ").upper().split())
        warn_list = set(s.get("hlight_gc_warn_list", "").replace(",", " ").upper().split())
        m_list = set(s.get("hlight_mc_list", "").replace(",", " ").upper().split())
        
        col_imp = s.get("hlight_gc_imp_color", "#ffffff")
        col_warn = s.get("hlight_gc_warn_color", "#ffffff")
        col_m = s.get("hlight_mc_color", "#ffffff")
        col_def = "#cccccc" # Standardfarbe für nicht-markierte Codes

        active_g = []
        # Format G-codes
        for g in self._current_gcodes[1:]:
            if g == -1: continue
            val = g / 10.0
            g_str = f"G{val:g}".upper()
            
            color = col_def
            weight = "normal"
            
            if g_str in warn_list:
                color = col_warn
                weight = "bold"
            elif g_str in imp_list:
                color = col_imp
                weight = "bold"
            
            active_g.append(f'<span style="color: {color}; font-weight: {weight};">{g_str}</span>')

        # Format M-codes
        active_m = []
        for m in self._current_mcodes[1:]:
            if m == -1: continue
            m_str = f"M{m}".upper()
            
            color = col_def
            weight = "normal"
            
            if m_str in m_list:
                color = col_m
                weight = "bold"
            
            active_m.append(f'<span style="color: {color}; font-weight: {weight};">{m_str}</span>')
            
        all_codes = "<br>".join(active_g + active_m)
        lbl.setText(f'<html><body>{all_codes}</body></html>')

    def _setup_highlight_settings(self):
        from PySide6.QtWidgets import QLineEdit, QPushButton
        s = self.settings
        for prefix, le_name, btn_name in [
            ("hlight_gc_imp", "le_gc_important", "btn_gc_color_important"),
            ("hlight_gc_warn", "le_gc_warning", "btn_gc_color_warning"),
            ("hlight_mc", "le_mc_highlights", "btn_mc_color"),
        ]:
            le = self.ui.findChild(QLineEdit, le_name)
            btn = self.ui.findChild(QPushButton, btn_name)
            
            if le:
                le.setText(s.get(f"{prefix}_list", ""))
                le.textChanged.connect(lambda text, p=prefix: self._on_hlight_text_changed(p, text))
            
            if btn:
                color = s.get(f"{prefix}_color", "#ffffff")
                self._update_color_btn_style(btn, color)
                btn.clicked.connect(lambda checked=False, p=prefix, b=btn: self._on_hlight_color_clicked(p, b))

    def _on_hlight_text_changed(self, prefix, text):
        self.settings.set(f"{prefix}_list", text)
        self.settings.save()
        self._update_active_codes_display()

    def _on_hlight_color_clicked(self, prefix, btn):
        from PySide6.QtWidgets import QColorDialog
        from PySide6.QtGui import QColor
        
        current = self.settings.get(f"{prefix}_color", "#ffffff")
        color = QColorDialog.getColor(QColor(current), self.ui, "Farbe wählen")
        
        if color.isValid():
            hex_color = color.name()
            self.settings.set(f"{prefix}_color", hex_color)
            self.settings.save()
            self._update_color_btn_style(btn, hex_color)
            self._update_active_codes_display()

    def _update_color_btn_style(self, btn, color):
        btn.setStyleSheet(f"background-color: {color}; color: {'#000000' if self._is_light(color) else '#ffffff'}; border: 1px solid #5d6d7e; font-weight: bold;")

    def _is_light(self, hex_color):
        """Prüft ob eine Farbe hell oder dunkel ist (für Kontrast-Text)."""
        hex_color = hex_color.lstrip('#')
        if len(hex_color) != 6: return True
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        # Luminanz-Formel
        brightness = (r * 0.299 + g * 0.587 + b * 0.114)
        return brightness > 128

    @Slot(list)
    def _on_homed(self, homed: list):
        self._all_joints_homed = all(i < len(homed) and homed[i] for i in range(3))
        self._update_goto_home_style(self._is_machine_on and self._all_joints_homed)
        
        # Update REF ALL button text
        if hasattr(self, "_btn_ref_all"):
            self._btn_ref_all.setText("HOMED" if self._all_joints_homed else "REF ALL")
            cls = "btn-green btn-homed" if self._all_joints_homed else "btn-green"
            self._btn_ref_all.setProperty("class", cls)
            self._btn_ref_all.style().unpolish(self._btn_ref_all)
            self._btn_ref_all.style().polish(self._btn_ref_all)

        enable_g53 = self.settings.get("homing_g53_conversion", False)

        for i, axis in enumerate(("X", "Y", "Z")):
            is_homed = i < len(homed) and homed[i]
            # DRO work label: Status via property
            if axis in self._dro_work:
                lbl = self._dro_work[axis]
                lbl.setProperty("homed", str(is_homed).lower())
                lbl.style().unpolish(lbl)
                lbl.style().polish(lbl)
            
            # REF button: Status via property
            if axis in self._dro_ref_btn:
                btn = self._dro_ref_btn[axis]
                
                if enable_g53 and is_homed:
                    btn.setText(f"G53 {axis} 0")
                    btn.setProperty("class", "btn-blue btn-homed")
                else:
                    btn.setText(f"REF {axis}")
                    btn.setProperty("class", "btn-green btn-homed" if is_homed else "btn-green")
                
                btn.style().unpolish(btn)
                btn.style().polish(btn)
                btn.update()

    @Slot(float)
    def _on_feed_override(self, val: float):
        from PySide6.QtWidgets import QLabel, QSlider
        pct = f"F {val*100:.0f}%"
        ival = int(val * 100)
        for lbl_name, sld_name in [
            ("feed_override_status",       "feed_override_slider"),
            ("probe_feed_override_status", "probe_feed_override_slider"),
        ]:
            if lbl := self._w(QLabel, lbl_name):
                lbl.setText(pct)
            if s := self._w(QSlider, sld_name):
                s.blockSignals(True); s.setValue(ival); s.blockSignals(False)

    @Slot(float)
    def _on_spindle_override(self, val: float):
        from PySide6.QtWidgets import QLabel, QSlider
        pct = f"S {val*100:.0f}%"
        ival = int(val * 100)
        for lbl_name, sld_name in [
            ("spindle_override_status",       "spindle_override_slider"),
            ("probe_spindle_override_status", "probe_spindle_override_slider"),
        ]:
            if lbl := self._w(QLabel, lbl_name):
                lbl.setText(pct)
            if s := self._w(QSlider, sld_name):
                s.blockSignals(True); s.setValue(ival); s.blockSignals(False)

    @Slot(float)
    def _on_rapid_override(self, val: float):
        from PySide6.QtWidgets import QLabel, QSlider
        pct = f"R {val*100:.0f}%"
        ival = int(val * 100)
        for lbl_name, sld_name in [
            ("rapid_override_status",       "rapid_override_slider"),
            ("probe_rapid_override_status", "probe_rapid_override_slider"),
        ]:
            if lbl := self._w(QLabel, lbl_name):
                lbl.setText(pct)
            if s := self._w(QSlider, sld_name):
                s.blockSignals(True); s.setValue(ival); s.blockSignals(False)

    def _on_v_override_changed(self, val: int):
        from PySide6.QtWidgets import QLabel
        if lbl := self._w(QLabel, "v_override_status"):
            lbl.setText(f"V {val}%")
        self.cmd.feedrate(val / 100.0)
        self.cmd.spindleoverride(val / 100.0)
        
    def _on_v_override_to_100(self):
        from PySide6.QtWidgets import QSlider, QLabel
        if s := self._w(QSlider, "v_override_slider"):
            s.setValue(100)
        if lbl := self._w(QLabel, "v_override_status"):
            lbl.setText(f"V 100%")
        self.cmd.feedrate(1.0)
        self.cmd.spindleoverride(1.0)

    @Slot(float)
    def _on_spindle_speed(self, rpm: float):
        """Called when the COMMANDED/TARGET spindle speed changes."""
        from PySide6.QtWidgets import QLabel
        self._is_spindle_running = (abs(rpm) > 0.1)
        if lbl := self._w(QLabel, "lbl_spindle_soll"):
            lbl.setText(f"CMD: {abs(rpm):.0f} RPM")
        self._update_run_buttons()
        self._update_spindle_buttons()

    @Slot(float)
    def _on_spindle_actual(self, rpm: float):
        """Called when the ACTUAL (Feedback) spindle speed changes (from HAL)."""
        # Throttled update to save CPU
        if hasattr(self, "_last_gui_rpm"):
            if abs(rpm - self._last_gui_rpm) < 5.0 and abs(rpm) > 0.1:
                return
        self._last_gui_rpm = rpm
             
        from PySide6.QtWidgets import QLabel
        if lbl := self._w(QLabel, "lbl_spindle_ist"):
            lbl.setText(f"{abs(rpm):.0f} RPM")
            
        # Real-time update for Simple View if visible
        sv = getattr(self, "simple_view", None)
        if sv and sv.isVisible():
            sv.set_feed_rpm(None, rpm)

    @Slot(float)
    def _on_spindle_load(self, load: float):
        # Throttled update
        if hasattr(self, "_last_gui_load"):
            if abs(load - self._last_gui_load) < 1.0:
                return
        self._last_gui_load = load
            
        from PySide6.QtWidgets import QProgressBar
        if bar := self._w(QProgressBar, "spindle_load_bar"):
            val = int(max(0, min(100, load)))
            bar.setValue(val)
            
            # Dynamische Farbe basierend auf Auslastung ändern (via Style-Property)
            if val >= 80:
                state = "critical"
            elif val >= 60:
                state = "warning"
            else:
                state = "normal"
                
            if bar.property("loadState") != state:
                bar.setProperty("loadState", state)
                # Aktualisiert das Styling der ProgressBar zur Laufzeit!
                bar.style().unpolish(bar)
                bar.style().polish(bar)


    @Slot(bool)
    def _on_spindle_at_speed(self, at_speed: bool):
        self._spindle_at_speed = at_speed
        self._update_spindle_buttons()

    def _update_spindle_buttons(self):
        from PySide6.QtWidgets import QPushButton
        direction = self.poller.stat.spindle[0]['direction']  # 1=fwd, -1=rev, 0=stop
        at_speed  = getattr(self, '_spindle_at_speed', False)
        running   = direction != 0

        _base = "QPushButton { border-radius: 4px; font-weight: bold; padding: 4px 8px; "

        if running and at_speed:
            # Vollflächig grün: Solldrehzahl erreicht
            fwd_style = _base + "background-color: #27ae60; color: white; }"
            rev_style = _base + "background-color: #27ae60; color: white; }"
        elif running:
            # Grüner Rahmen: läuft, aber noch nicht auf Drehzahl
            fwd_style = _base + "border: 2px solid #27ae60; color: #27ae60; }"
            rev_style = _base + "border: 2px solid #27ae60; color: #27ae60; }"
        else:
            fwd_style = ""
            rev_style = ""

        if b := self._w(QPushButton, "btn_spindle_fwd"):
            b.setStyleSheet(fwd_style if direction == 1 else "")
        if b := self._w(QPushButton, "btn_spindle_rev"):
            b.setStyleSheet(rev_style if direction == -1 else "")

    def _set_hal_pin(self, name: str, val):
        if self._hal_comp:
            try:
                self._hal_comp[name] = val
            except Exception:
                pass

    @Slot(int)
    def _on_tool_change_request(self, tool_nr: int):
        """Called via HAL tool-change-request pin."""
        from thorcnc.widgets.m6_dialog import M6Dialog
        
        # Alle Tool-Daten aus der Tabelle suchen
        tool_data = {'id': tool_nr, 'comment': '', 'diameter': 0.0, 'zoffset': 0.0}
        try:
            for t in self.poller.stat.tool_table:
                if t.id == tool_nr:
                    tool_data['comment'] = getattr(t, 'comment', "").strip()
                    tool_data['diameter'] = getattr(t, 'diameter', 0.0)
                    tool_data['zoffset'] = getattr(t, 'zoffset', 0.0)
                    break
            
            # FALLBACK: Falls LinuxCNC keinen Kommentar liefert, direkt aus der Datei lesen
            if not tool_data['comment'] and self.ini:
                tbl_path = self.ini.find("EMCIO", "TOOL_TABLE")
                if tbl_path:
                    # Pfad korrigieren falls relativ
                    if not os.path.isabs(tbl_path):
                        tbl_path = os.path.join(os.path.dirname(self.ini_path), tbl_path)
                    
                    if os.path.exists(tbl_path):
                        with open(tbl_path, 'r') as f:
                            for line in f:
                                # Suche Zeile die mit T<nummer> startet
                                if line.strip().startswith(f"T{tool_nr} "):
                                    if ";" in line:
                                        tool_data['comment'] = line.split(";", 1)[1].strip()
                                        break
        except Exception as e:
            print(f"[M6] Fehler beim Laden der Werkzeug-Details: {e}")

        dlg = M6Dialog(tool_nr, tool_data, self.ui)
        
        # Bestätigung an HAL senden, wenn der User den Button klickt
        if dlg.exec():
            if self._hal_comp:
                self._hal_comp["tool-changed-confirm"] = True
                # Nach kurzer Zeit wieder auf False, damit der nächste Wechsel sauber triggert
                from PySide6.QtCore import QTimer
                QTimer.singleShot(1000, lambda: self._set_hal_pin("tool-changed-confirm", False))

    @Slot(str)
    def _on_file_loaded(self, path: str):
        if not path or not os.path.isfile(path):
            return
        # Subroutinen (messe.ngc etc.) ignorieren – nur das User-Hauptprogramm anzeigen
        if path != self._user_program:
            return
        self._has_file = True
        self.gcode_view.load_file(path)
        tp = parse_file(path)
        self._last_toolpath = tp
        self.backplot.load_toolpath(tp)
        self.backplot.fit_view(tp)
        
        if hasattr(self, "simple_view"):
            if self.simple_view.backplot:
                self.simple_view.backplot.load_toolpath(tp)
                self.simple_view.backplot.fit_view(tp)
            self.simple_view.load_gcode(path)
        self._update_run_buttons()
        if hasattr(self, "_html_list"):
            self._refresh_html_list(path)

    @Slot(tuple)
    def _on_digital_out_changed(self, dout: tuple):
        """React to M64/M65 on specific pins to show a visual warning."""
        self._last_dout = dout # Store for settings refresh
        
        if not self._probe_warning_enabled:
            # If function is disabled, ensure property is false and reset style
            if hasattr(self, "status_bar") and self.status_bar:
                if self.status_bar.property("probe_active"):
                    self.status_bar.setProperty("probe_active", False)
                    self.status_bar.setStyleSheet("")
                    self.status_bar.style().unpolish(self.status_bar)
                    self.status_bar.style().polish(self.status_bar)
            return
            
        is_active = False
        try:
            # Check if ANY of the configured pins are high
            for idx in self._probe_warning_pins:
                if 0 <= idx < len(dout):
                    if dout[idx] == 1:
                        is_active = True
                        break
            
            # Print debug on state change
            if not hasattr(self, "_last_probe_warning_state") or self._last_probe_warning_state != is_active:
                print(f"[DEBUG] Probe Warning state changed: {is_active} (Pins: {self._probe_warning_pins})")
                self._last_probe_warning_state = is_active
        except Exception as e:
            print(f"[DEBUG] Error in _on_digital_out_changed: {e}")
            pass

        self._probe_active = is_active
        
        # Update property on the bottom status bar (bottomBarFrame)
        if hasattr(self, "status_bar") and self.status_bar:
            frame = self.status_bar
            if frame.property("probe_active") != is_active:
                frame.setProperty("probe_active", is_active)
                
                if is_active:
                    # Apply dynamic user-defined color ONLY as border
                    color = self._probe_warning_color
                    # We override the QSS colors via inline stylesheet when active
                    # Use a thick border for visibility
                    frame.setStyleSheet(
                        f"QFrame#bottomBarFrame {{ border: 6px solid {color} !important; }}"
                    )
                else:
                    # Reset to QSS defaults
                    frame.setStyleSheet("")
                
                frame.style().unpolish(frame)
                frame.style().polish(frame)
                frame.update()

    @Slot(int)
    def _on_program_line(self, line: int):
        self.gcode_view.set_current_line(line)
        if hasattr(self, "simple_view") and self.simple_view.isVisible():
            self.simple_view.set_gcode_line(line)
            
        # GUI-side Single Block: Pause immediately after line change
        if getattr(self, "is_single_block", False):
            # If we are running (READING/WAITING/EXEC), send pause
            if self._interp_state in (linuxcnc.INTERP_READING, linuxcnc.INTERP_WAITING):
                print(f"[DIAGNOSTIC] Single Block Auto-Pause triggered at line {line}")
                self.cmd.auto(linuxcnc.AUTO_PAUSE)

    @Slot(str)
    def _on_error(self, msg: str):
        self._status(f"ERROR: {msg}", error=True)

    @Slot(str)
    def _on_info(self, msg: str):
        self._status(msg)

    def _status(self, msg: str, error: bool = False):
        if hasattr(self, "_lbl_status_msg") and self._lbl_status_msg:
            self._lbl_status_msg.setText(msg)
            self._lbl_status_msg.setStyleSheet(
                f"color: {'#ff5555' if error else '#cccccc'}; font-weight: bold; margin-left: 10px;"
            )
            # Timer to clear the message after 10 seconds
            if not hasattr(self, "_status_timer"):
                from PySide6.QtCore import QTimer
                self._status_timer = QTimer()
                self._status_timer.setSingleShot(True)
                self._status_timer.timeout.connect(lambda: self._lbl_status_msg.setText(""))
            self._status_timer.start(10000)
        elif sb := self.ui.statusBar():
            sb.showMessage(msg, 10000)
            
        self._append_status_log(msg, error=error)

    def _append_status_log(self, msg: str, error: bool = False):
        from PySide6.QtWidgets import QListWidget, QListWidgetItem
        from PySide6.QtGui import QColor
        from PySide6.QtCore import QDateTime
        log: QListWidget = self.ui.findChild(QListWidget, "status_log")
        if log is None:
            return
        # Ensure alternating rows are disabled (sometimes UI file setting is overridden)
        log.setAlternatingRowColors(False)
        ts = QDateTime.currentDateTime().toString("HH:mm:ss")
        item = QListWidgetItem(f"[{ts}]  {msg}")
        if error:
            item.setForeground(QColor("#ff5555"))
        else:
            theme = self.settings.get("theme", "dark")
            if theme == "light":
                item.setForeground(QColor("#1a2332"))
            else:
                item.setForeground(QColor("#d0d0d0"))
        log.addItem(item)
        log.scrollToBottom()

    # ── Simple View Overlay ───────────────────────────────────────────────────

    def _setup_simple_overlay(self):
        """Create SimpleView as a child overlay of the central widget."""
        cw = self.ui.centralWidget() or self.ui
        self.simple_view = SimpleView(parent=cw)
        self.simple_view.setGeometry(cw.rect())
        self.simple_view.hide()

        # ESC shortcut scoped to the overlay
        from PySide6.QtGui import QShortcut, QKeySequence
        esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self.simple_view)
        esc.activated.connect(self._hide_simple_overlay)

        # Zurück button
        if self.simple_view.btn_back:
            self.simple_view.btn_back.clicked.connect(self._hide_simple_overlay)

        # Machine control buttons
        if self.simple_view.btn_start:
            self.simple_view.btn_start.clicked.connect(self._run_program)
        if self.simple_view.btn_pause:
            self.simple_view.btn_pause.clicked.connect(self._pause_program)
        if self.simple_view.btn_stop:
            self.simple_view.btn_stop.clicked.connect(self._stop_program)
        if self.simple_view.btn_estop:
            self.simple_view.btn_estop.clicked.connect(self._toggle_estop)

        # Sync backplot state from main backplot
        if self.simple_view.backplot:
            if hasattr(self, "_backplot_envelope"):
                self.simple_view.backplot.set_machine_envelope(**self._backplot_envelope)
            if hasattr(self, "_last_wcs_origin"):
                self.simple_view.backplot.set_wcs_origin(*self._last_wcs_origin)
            if hasattr(self, "_last_toolpath") and self._last_toolpath is not None:
                self.simple_view.backplot.load_toolpath(self._last_toolpath)
            self.simple_view.backplot.set_view_iso()

        # Make status bar clickable & add persistent Simple View indicator
        if sb := self.ui.statusBar():
            from PySide6.QtCore import Qt as _Qt
            from PySide6.QtWidgets import QLabel, QWidget, QHBoxLayout
            
            # 1. Custom Status Message Label (Left)
            self._lbl_status_msg = QLabel("")
            self._lbl_status_msg.setObjectName("persistent_status_msg")
            self._lbl_status_msg.setMinimumWidth(300)
            
            # 2. Centered Simple View Indicator
            self._lbl_simple_view_indicator = QLabel(" SIMPLE VIEW ")
            self._lbl_simple_view_indicator.setObjectName("simple_view_indicator")
            self._lbl_simple_view_indicator.setAlignment(_Qt.AlignmentFlag.AlignCenter)
            # Subtle styling: Blue border instead of solid background
            # Styling via QSS: QLabel#simple_view_indicator
            
            # Create a container to hold and center everything
            container = QWidget()
            layout = QHBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            
            layout.addWidget(self._lbl_status_msg)
            layout.addStretch()
            layout.addWidget(self._lbl_simple_view_indicator)
            layout.addStretch()
            # Placeholder for right-side alignment symmetry if needed
            right_spacer = QLabel("")
            right_spacer.setMinimumWidth(300)
            layout.addWidget(right_spacer)
            
            # Configure status bar
            sb.setVisible(True)
            sb.setMinimumHeight(28)
            # Styling via QSS: QStatusBar
            sb.clearMessage()
            sb.addWidget(container, 1)
            
            sb.setCursor(_Qt.CursorShape.PointingHandCursor)
            sb.installEventFilter(self)
            self._lbl_simple_view_indicator.installEventFilter(self)
            self._sb_for_filter = sb

        # Track main window resize
        self.ui.installEventFilter(self)

    def _show_simple_overlay(self):
        if not hasattr(self, "simple_view"):
            return
        cw = self.ui.centralWidget() or self.ui
        self.simple_view.setGeometry(cw.rect())
        self.simple_view.show()
        
        # Save current state (maximized/normal) to restore it later
        self._pre_simple_window_state = self.ui.windowState()
        # Go fullscreen to prevent accidental GUI closure (clicking the X)
        self.ui.showFullScreen()
        if self.simple_view.backplot:
            if hasattr(self, "_backplot_envelope"):
                self.simple_view.backplot.set_machine_envelope(**self._backplot_envelope)
            if hasattr(self, "_last_wcs_origin"):
                self.simple_view.backplot.set_wcs_origin(*self._last_wcs_origin)
            if self._last_toolpath is not None:
                self.simple_view.backplot.load_toolpath(self._last_toolpath)
            if self._user_program:
                self.simple_view.load_gcode(self._user_program)
                s = self.poller.stat
                line = s.motion_line if s.motion_line > 0 else s.current_line
                self.simple_view.set_gcode_line(line)

        self.simple_view.show()
        self.simple_view.raise_()
        self.simple_view.setFocus()

    def _hide_simple_overlay(self):
        if hasattr(self, "simple_view"):
            self.simple_view.hide()

    def _sync_nav_buttons(self, index: int):
        """Nav-Buttons an den Tab-Zustand anpassen und LinuxCNC-Modus umschalten."""
        if hasattr(self, "nav_group"):
            if b := self.nav_group.button(index):
                b.blockSignals(True)
                b.setChecked(True)
                b.blockSignals(False)

        # Modus-Umschaltung basierend auf Tab (Auto vs Manual)
        # Tab 0: Main (Auto), Tab 1: File (Auto), Rest: Manual
        try:
            current_mode = self.poller.stat.task_mode
            target_mode = linuxcnc.MODE_MANUAL
            if index in (0, 1):
                target_mode = linuxcnc.MODE_AUTO
            
            if current_mode != target_mode:
                # Only switch if the machine is in IDLE
                if self._interp_state == linuxcnc.INTERP_IDLE:
                    self.cmd.mode(target_mode)
                    self.cmd.wait_complete()
        except Exception:
            pass

    # ── Machine Actions ────────────────────────────────────────────────────

    def _toggle_power(self):
        s = self.poller.stat
        if s.task_state == linuxcnc.STATE_ESTOP:
            self.cmd.state(linuxcnc.STATE_ESTOP_RESET)
        elif s.task_state == linuxcnc.STATE_ON:
            self.cmd.state(linuxcnc.STATE_OFF)
        else:
            self.cmd.state(linuxcnc.STATE_ON)

    def _toggle_estop(self):
        s = self.poller.stat
        if s.task_state == linuxcnc.STATE_ESTOP:
            self.cmd.state(linuxcnc.STATE_ESTOP_RESET)
        else:
            self.cmd.state(linuxcnc.STATE_ESTOP)

    def _run_program(self):
        s = self.poller.stat
        current_mode = s.task_mode
        interp_state = self._interp_state
        is_sb = getattr(self, "is_single_block", False)

        # In Automatik-Modus wechseln falls nötig
        if current_mode != linuxcnc.MODE_AUTO:
            self.cmd.mode(linuxcnc.MODE_AUTO)
            self.cmd.wait_complete()

        # Falls pausiert, prüfen ob wir steppen oder fortsetzen
        if interp_state == linuxcnc.INTERP_PAUSED:
            if is_sb:
                print("[DIAGNOSTIC] Step click (Paused): Sending AUTO_STEP")
                self.cmd.auto(linuxcnc.AUTO_STEP)
            else:
                print("[DIAGNOSTIC] Resume click: Sending AUTO_RESUME")
                self.cmd.auto(linuxcnc.AUTO_RESUME)
        else:
            # Wenn nicht pausiert, entweder Steppen oder normal Starten
            if is_sb:
                print("[DIAGNOSTIC] Step click (Start): Sending AUTO_STEP")
                self.cmd.auto(linuxcnc.AUTO_STEP)
            else:
                # Normaler Start von Zeile 0 (oder aktueller Zeile falls Idle in Mitte)
                line = s.motion_line if (s.motion_line and s.motion_line > 0) else 0
                print(f"[DIAGNOSTIC] Start click: Sending AUTO_RUN from line {line}")
                self.cmd.auto(linuxcnc.AUTO_RUN, line)

    def _run_halshow(self):
        """Startet halshow als externen Prozess."""
        import subprocess
        try:
            subprocess.Popen(["halshow"], start_new_session=True)
            self._status("HAL Show gestartet.")
        except Exception as e:
            self._status(f"Konnte halshow nicht starten: {e}", error=True)

    def _run_halscope(self):
        """Startet halscope als externen Prozess."""
        import subprocess
        try:
            subprocess.Popen(["halscope"], start_new_session=True)
            self._status("HAL Scope gestartet.")
        except Exception as e:
            self._status(f"Konnte halscope nicht starten: {e}", error=True)

    def _run_linuxcnc_status(self):
        """Startet linuxcnctop als externen Prozess."""
        import subprocess
        try:
            # linuxcnctop runs in a terminal usually, but here we try to launch it.
            # If it's a CLI tool, it might need a terminal emulator.
            # But we'll try launching it directly first as the user requested it.
            subprocess.Popen(["linuxcnctop"], start_new_session=True)
            self._status("LinuxCNC Status (top) gestartet.")
        except Exception as e:
            self._status(f"Konnte linuxcnctop nicht starten: {e}", error=True)

    def _go_to_home(self):
        """Move to machine zero via O<go_to_home> subroutine."""
        try:
            # Merken des alten Modus
            old_mode = self.poller.stat.task_mode
            self.cmd.mode(linuxcnc.MODE_MDI)
            self.cmd.wait_complete()
            
            # Subroutine aufrufen
            self.cmd.mdi("O<go_to_home> CALL")
            self.cmd.wait_complete()
            
            # Warten bis die Fahrt wirklich beendet ist (Interpreter IDLE)
            # Das verhindert das Ruckeln am Ende, wenn ThorCNC den Modus zu früh umschaltet
            import time
            from PySide6.QtWidgets import QApplication
            start_t = time.time()
            timeout = 60.0 # Sekunden
            
            self._status("Fahrt auf Home-Position (G53) läuft...")
            
            while time.time() - start_t < timeout:
                # Wir geben der GUI Zeit zum Atmen und Aktualisieren
                QApplication.processEvents()
                
                # Check ob Interpreter fertig ist
                # Wir greifen direkt auf den Status zu
                if self.poller.stat.interp_state == linuxcnc.INTERP_IDLE:
                    break
                time.sleep(0.05)
            
            self.cmd.mode(old_mode)
            self.cmd.wait_complete()
            self._status("Home-Position erreicht.")
        except Exception as e:
            self._status(f"Homing error: {e}", error=True)

    def _home_all(self):
        self.cmd.mode(linuxcnc.MODE_MANUAL)
        self.cmd.wait_complete()
        self.cmd.home(-1)

    def _home_joint(self, joint: int):
        # Check if we should do G53 instead
        is_homed = False
        homed_status = getattr(self.poller, "_homed", [])
        if 0 <= joint < len(homed_status):
            is_homed = homed_status[joint]
            
        enable_g53 = self.settings.get("homing_g53_conversion", False)
        
        if enable_g53 and is_homed:
            # G53 Move
            axis_map = {0: "X", 1: "Y", 2: "Z"}
            axis = axis_map.get(joint)
            if axis:
                self._send_mdi(f"G53 G0 {axis}0")
            return

        self.cmd.mode(linuxcnc.MODE_MANUAL)
        self.cmd.wait_complete()
        self.cmd.home(joint)

    def _pause_program(self):
        self.cmd.auto(linuxcnc.AUTO_PAUSE)

    def _stop_program(self):
        self.cmd.abort()

    def _send_mdi(self, text: str, widget=None):
        text = text.strip()
        if not text:
            return
        try:
            self.cmd.mode(linuxcnc.MODE_MDI)
            self.cmd.wait_complete()
            self.cmd.mdi(text)
            # Modus bleibt MDI — Poller aktualisiert Combobox automatisch.
            # User switches back to MANUAL/AUTO via combobox.
            if widget:
                widget.clear()
            self._status(f"MDI: {text}")
            # History eintragen (kein Duplikat direkt oben)
            if hasattr(self, "_mdi_history_widget"):
                hw = self._mdi_history_widget
                if hw.count() == 0 or hw.item(0).text() != text:
                    hw.insertItem(0, text)
                    if hw.count() > 50:
                        hw.takeItem(hw.count() - 1)
        except Exception as e:
            self._status(f"MDI error: {e}")
        
    def _send_m6(self):
        # Prepare tool data from current table
        tool_data = []
        if self.tool_table:
            for row in range(self.tool_table.rowCount()):
                try:
                    nr_item = self.tool_table.item(row, 0)
                    dia_item = self.tool_table.item(row, 2)
                    comment_item = self.tool_table.item(row, 4)
                    
                    if nr_item:
                        nr_str = nr_item.text().strip()
                        if nr_str:
                            tool_data.append({
                                'nr': int(nr_str),
                                'dia': float(dia_item.text()) if dia_item and dia_item.text().strip() else 0.0,
                                'comment': comment_item.text() if comment_item else ""
                            })
                except Exception:
                    continue

        dialog = ToolSelectionDialog(tool_data, self.ui)
        if dialog.exec():
            val = dialog.get_selected_tool()
            if val is not None:
                self._send_mdi(f"T{val} M6 G43")

    def _set_jog_increment(self, inc: float):
        self._jog_increment = inc
        from PySide6.QtWidgets import QPushButton
        # Radio-button like behavior
        for name, val in [("btn_jog_cont", 0.0), ("btn_jog_1_0", 1.0), ("btn_jog_0_1", 0.1), ("btn_jog_0_01", 0.01)]:
            if b := self._w(QPushButton, name):
                b.setChecked(abs(inc - val) < 0.0001)

    def _on_jog_vel_changed(self, val: int):
        self._jog_velocity = float(val)
        from PySide6.QtWidgets import QLabel
        if lbl := self._w(QLabel, "jog_vel_label"):
            lbl.setText(f"Velocity: {val}")

    def _jog_start(self, joint: int, direction: int):
        self.cmd.mode(linuxcnc.MODE_MANUAL)
        self.cmd.wait_complete()
        if self._jog_increment <= 0.0:
            # Continuous
            self.cmd.jog(linuxcnc.JOG_CONTINUOUS, False, joint, direction * self._jog_velocity)
        else:
            # Incremental
            self.cmd.jog(linuxcnc.JOG_INCREMENT, False, joint, direction * self._jog_velocity, self._jog_increment)

    def _jog_stop(self, joint: int):
        if self._jog_increment <= 0.0:
            self.cmd.jog(linuxcnc.JOG_STOP, False, joint)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def show(self):
        self.ui.show()
        if hasattr(self, "_warn_missing_prefs") and self._warn_missing_prefs:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self.ui, 
                "Neue Konfigurationsdatei", 
                "Es wurde automatisch eine neue 'thorcnc.prefs' Datei im Config-Programmverzeichnis angelegt.\n"
                "In dieser speichern wir von nun an Fensterpositionen, Kameraperspektive und ausgewählte Dateipfade.\n\n"
                "Optional: Füge 'PREFS_FILE = thorcnc.prefs' im [DISPLAY] Abschnitt deiner INI hinzu, um den Ort explizit festzulegen!"
            )
            self._warn_missing_prefs = False

    def _apply_theme(self, name: str):
        from PySide6.QtWidgets import QApplication
        from .main import load_theme
        load_theme(QApplication.instance(), name)
        self.settings.set("theme", name)
        self._update_nav_icons()

    def _update_nav_icons(self):
        theme = self.settings.get("theme", "dark")
        color = "#1a2332" if theme == "light" else "#ffffff"
        
        up_svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="18 15 12 9 6 15"></polyline></svg>"""
        home_svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><polyline points="9 22 9 12 15 12 15 22"></polyline></svg>"""
        
        from PySide6.QtGui import QPixmap, QIcon
        from PySide6.QtCore import QByteArray
        
        def svg_to_icon(svg_str):
            pixmap = QPixmap()
            # Try loading as SVG format explicitly
            if not pixmap.loadFromData(QByteArray(svg_str.encode('utf-8')), "SVG"):
                # Fallback or debug print could go here
                pass
            return QIcon(pixmap)

        if hasattr(self, "_btn_nav_up") and self._btn_nav_up:
            self._btn_nav_up.setIcon(svg_to_icon(up_svg))
            self._btn_nav_up.setIconSize(self._btn_nav_up.size() * 0.7)
        if hasattr(self, "_btn_nav_home") and self._btn_nav_home:
            self._btn_nav_home.setIcon(svg_to_icon(home_svg))
            self._btn_nav_home.setIconSize(self._btn_nav_home.size() * 0.7)

    def _drain_startup_errors(self):
        """Liest den LinuxCNC Error-Channel einmalig beim Start aus und loggt alle Meldungen."""
        self._append_status_log("── Session gestartet ──")
        try:
            ec = self.poller.error_channel
            msg = ec.poll()
            while msg:
                kind, text = msg
                is_err = kind in (linuxcnc.NML_ERROR, linuxcnc.OPERATOR_ERROR)
                self._append_status_log(text, error=is_err)
                msg = ec.poll()
        except Exception:
            pass

    def start(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance().aboutToQuit.connect(self._on_close)
        
        if hasattr(self, "_auto_load_file") and self._auto_load_file:
            self.load_file(self._auto_load_file)
        self._drain_startup_errors()
        if hasattr(self, "backplot"):
             s = self.backplot.get_actual_samples()
             self._status(f"Graphics system ready (Antialiasing: {s}x MSAA)")
        self.poller.start()

    def _on_close(self):
        # Remove event filters to prevent crashes during destruction
        if hasattr(self, "_sb_for_filter") and self._sb_for_filter:
            try:
                self._sb_for_filter.removeEventFilter(self)
            except Exception: pass
        try:
            self.ui.removeEventFilter(self)
        except Exception: pass

        self.poller.stop()
        
        # Save settings
        geom = self.ui.saveGeometry().toHex().data().decode()
        state = self.ui.saveState().toHex().data().decode()
        self.settings.set("window_geometry", geom)
        self.settings.set("window_state", state)
        
        from PySide6.QtWidgets import QSplitter
        sp_main = self._w(QSplitter, "mainSplitter")
        if sp_main:
            self.settings.set("main_splitter", sp_main.saveState().toHex().data().decode())
            
        sp_file = self._w(QSplitter, "fileSplitter")
        if sp_file:
            self.settings.set("file_splitter", sp_file.saveState().toHex().data().decode())
            
        from PySide6.QtWidgets import QTableWidget
        tw = self._w(QTableWidget, "toolTable")
        if tw:
            self.settings.set("tool_table_state", tw.horizontalHeader().saveState().toHex().data().decode())
        
        if hasattr(self, "backplot") and hasattr(self.backplot, "get_view_opts"):
            self.settings.set("backplot_view", self.backplot.get_view_opts())

        if hasattr(self, "_mdi_history_widget"):
            hw = self._mdi_history_widget
            self.settings.set("mdi_history",
                              [hw.item(i).text() for i in range(hw.count())])

        self.settings.save()
