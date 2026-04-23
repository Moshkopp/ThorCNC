import os
import re
import linuxcnc
from PySide6.QtCore import Qt, QObject, Slot, QTimer, QPropertyAnimation, QEasingCurve, QByteArray, QPoint, QEvent
from PySide6.QtWidgets import (QMainWindow, QHBoxLayout, QLabel, QFrame, QPushButton, 
                               QTableWidgetItem, QWidget, QVBoxLayout, QSplitter, 
                               QStackedWidget, QLineEdit, QListWidget, QSizePolicy, 
                               QComboBox, QListView, QSpinBox, QApplication)
from PySide6.QtUiTools import QUiLoader

from .status_poller import StatusPoller
from .gcode_parser import parse_file
from .widgets.gcode_view import GCodeView
from .widgets.backplot import BackplotWidget
from .widgets.simple_view import SimpleView
from .i18n import TranslationManager, _t
from .modules import (FileManagerModule, ToolTableModule, OffsetsModule,
                        MotionModule, ProbingTabModule, NavigationModule)
# from .widgets.opt_options import OptOptionsDialog

_DIR = os.path.dirname(__file__)

class ThorCNC(QObject):


    def __init__(self, ini_path: str = "", parent=None):
        super().__init__(parent)

        # Managers will be initialized after settings are loaded

        self.ini_path = ini_path or os.environ.get("INI_FILE_NAME", "")
        self.ini = linuxcnc.ini(self.ini_path) if self.ini_path else None
        self.stat = linuxcnc.stat()
        self.cmd = linuxcnc.command()
        self.is_single_block = False

        # State tracking for dynamic run buttons
        self._is_machine_on = False
        self._has_file = False
        self._last_toolpath = None
        self._last_wcs_origin = (0.0, 0.0, 0.0)
        self._wcs_initialized = False
        self._view_restored = False
        self._interp_state = linuxcnc.INTERP_IDLE
        self._is_spindle_running = False
        self._user_program = ""   # User loaded main program
        self._current_gcodes = ()
        self._current_mcodes = ()

        self._load_settings()

        # Initialize managers (after settings loaded)

        self.navigation = NavigationModule(self)
        self.file_manager = FileManagerModule(self)
        self.tool_table = ToolTableModule(self)
        self.offsets = OffsetsModule(self)
        self.motion = MotionModule(self)
        self.probing_tab = ProbingTabModule(self)
        
        # i18n
        self.i18n = TranslationManager(self.settings.get("language", "Deutsch"))
        
        self._load_ui()
        
        self._replace_custom_widgets()

        self._restore_window_state()
        self._setup_dro()
        self._setup_hal()
        self._setup_poller()
        self.file_manager.setup()
        self.tool_table.setup()
        self.offsets.setup()
        self.motion.setup()
        self.probing_tab.setup()
        self._setup_html_tab()
        self._setup_settings_tab()
        self._connect_signals()
        self._setup_opt_jalousie()
        
        # Performance/Throttle state
        self._last_gui_pos = [0.0, 0.0, 0.0]
        self._last_gui_rpm = 0.0
        self._last_gui_load = -1.0

        self._apply_ini_settings()
        
        # Start in MAIN tab
        from PySide6.QtWidgets import QTabWidget
        if tab := self._w(QTabWidget, "tabWidget"):
            tab.setCurrentIndex(0)

        # Apply translations to ALL widgets (including dynamic ones)
        self.i18n.apply_to_widget(self.ui)

        # Setup navigation and install event filter (must be after all initialization)
        self.navigation.setup()
        QApplication.instance().installEventFilter(self)

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

        # Update probe marker on first show and subsequent resizes
        # (will be called from probing.setup())

    def resizeEvent(self, event):
        """Handle window resizing to update floating UI elements."""
        super().resizeEvent(event)
        # Update probing marker position as it depends on absolute tab coordinates
        if hasattr(self, 'probing_tab') and self.probing_tab:
            self.probing_tab.update_marker_pos()

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
        # Load Status Bar UI (if it exists)
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
        # Load Sidebar Modules (Split between Left and Right)
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
        # Determine sidebar layout
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
        # ── GCode-Panel: Buttons sind fix in der UI (gcodeToggleBar)

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
        self._btn_find_m6 = QPushButton(_t("FIND M6"))
        self._btn_find_m6.setObjectName("btn_find_m6")
        self._btn_find_m6.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_find_m6.clicked.connect(self._find_next_m6)
        h_lay.addWidget(self._btn_find_m6)

        # Run From Line Button
        self._btn_run_from_line = QPushButton(_t("START AT LINE"))
        self._btn_run_from_line.setObjectName("btn_run_from_line")
        self._btn_run_from_line.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_run_from_line.clicked.connect(self.navigation.toggle_line_queue_flyout)
        h_lay.addWidget(self._btn_run_from_line)

        # Create the mini-flyout for line selection
        self._line_queue_panel = QFrame(self.ui, Qt.WindowType.FramelessWindowHint | Qt.WindowType.ToolTip)
        self._line_queue_panel.setObjectName("line_queue_panel")
        self._line_queue_panel.setFixedWidth(220)
        self._line_queue_panel.setFixedHeight(170) # Taller for two buttons
        self._line_queue_panel.hide()
        
        lq_lay = QVBoxLayout(self._line_queue_panel)
        lq_lay.setContentsMargins(10, 10, 10, 10)
        lq_lay.setSpacing(8)
        
        lq_title = QLabel(_t("STARTZEILE WÄHLEN:"))
        lq_title.setStyleSheet("font-weight: bold; color: #3a7abf;")
        lq_lay.addWidget(lq_title)
        
        self._line_input = QSpinBox()
        self._line_input.setRange(1, 999999)
        self._line_input.setFixedHeight(40)
        self._line_input.setStyleSheet("font-size: 14pt; font-weight: bold;")
        lq_lay.addWidget(self._line_input)
        
        lq_ok_btn = QPushButton(_t("SET QUEUE"))
        lq_ok_btn.setFixedHeight(40)
        lq_ok_btn.setObjectName("btn_flyout_item")
        lq_ok_btn.clicked.connect(self.navigation.confirm_line_queue)
        lq_lay.addWidget(lq_ok_btn)

        lq_clear_btn = QPushButton(_t("CLEAR QUEUE"))
        lq_clear_btn.setFixedHeight(35)
        lq_clear_btn.setObjectName("btn_flyout_item_clear") # New style
        lq_clear_btn.clicked.connect(self.navigation.clear_line_queue)
        lq_lay.addWidget(lq_clear_btn)

        h_lay.addStretch()

        # Edit Toggle
        self._btn_edit_gcode = QPushButton(_t("EDIT"))
        self._btn_edit_gcode.setCheckable(True)
        self._btn_edit_gcode.setObjectName("btn_edit_gcode")
        self._btn_edit_gcode.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_edit_gcode.clicked.connect(self._on_toggle_gcode_edit)
        h_lay.addWidget(self._btn_edit_gcode)

        # Save Button
        self._btn_save_gcode = QPushButton(_t("SAVE"))
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
        self._mdi_input.setPlaceholderText(_t("MDI COMMAND..."))
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
        for label, fn in ((_t("ISO"),        self.backplot.set_view_iso),
                          (_t("TOP"),        self.backplot.set_view_z),
                          (_t("FRONT"),      self.backplot.set_view_y),
                          (_t("SIDE"),       self.backplot.set_view_x),
                          (_t("CLR TRAIL"),  self.backplot.clear_trail)):
            b = QPushButton(label)
            b.setObjectName("btn_backplot_view")
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(fn)
            tb_lay.addWidget(b)
        tb_lay.addStretch()   # Stretch wieder einfügen (trennt links von rechts)

        self.motion._update_goto_home_style(all_homed=False)
        
        # --- Flyout System Implementation ---
        # 1. Cleanup old elements
        for name in ("combo_machine_mode", "btn_opt", "optExpandPanel"):
            if w := self.ui.findChild(QWidget, name):
                w.hide()
                if w.parent() and w.parent().layout():
                    w.parent().layout().removeWidget(w)

        # 2. Create the Flyout Buttons in Sidebar
        self.cmd.set_block_delete(0)
        self.cmd.set_optional_stop(0)
        
        # Container for the sidebar buttons
        self.flyout_btn_group = QWidget()
        self.flyout_btn_group.setObjectName("flyout_btn_group")
        group_lay = QVBoxLayout(self.flyout_btn_group)
        group_lay.setContentsMargins(0, 50, 0, 0) # 50px spacing at the top
        group_lay.setSpacing(6)
        
        # Define the three musketeers
        self._flyout_configs = [
            ("MODE",   ["MANUAL", "AUTO", "MDI"]),
            ("SHORTS", ["GO TO HOME", "GOTO ZERO XY"]),
            ("OPT",    ["COOLANT", "M1 STOP", "SINGLE BLOCK", "BLOCK DELETE"])
        ]
        
        for name, items in self._flyout_configs:
            # Create the Sidebar Button
            btn = QPushButton(name)
            btn.setObjectName(f"btn_flyout_toggle_{name.lower()}")
            btn.setProperty("is_flyout_toggle", True)
            btn.setMinimumHeight(60)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            group_lay.addWidget(btn)
            
            # Create the Overlay Panel (Child of centralwidget for stacking)
            panel = QFrame(self.ui.centralwidget)
            panel.setWindowFlags(Qt.WindowType.FramelessWindowHint)
            panel.setObjectName(f"flyout_panel_{name.lower()}")
            panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            panel.stackUnder(self.ui.leftPanel) # Slide out from behind the sidebar
            panel.hide()
            
            p_lay = QVBoxLayout(panel) # Vertical layout now
            p_lay.setContentsMargins(5, 5, 5, 5)
            p_lay.setSpacing(5)
            
            # Add items to panel
            for item_text in items:
                i_btn = QPushButton(_t(item_text))
                i_btn.setObjectName("btn_flyout_item")
                i_btn.setMinimumHeight(60)
                i_btn.setMinimumWidth(180)
                i_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                p_lay.addWidget(i_btn)
                # Store for highlighting (e.g. MODE)
                self.navigation._flyout_item_buttons[f"{name}_{item_text}"] = i_btn
                # Logic connection
                i_btn.clicked.connect(lambda checked=False, t=item_text, n=name: self.navigation.handle_flyout_action(n, t))

            p_lay.addStretch() # Keep items to the left

            self.navigation._flyout_panels[name] = panel
            btn.clicked.connect(lambda checked=False, n=name, b=btn: self.navigation.toggle_flyout(n, b))
            
        # Add the group to the sidebar
        sidebar_lay = self.ui.leftPanel.layout()
        if sidebar_lay:
            # Insert right below the navigation (after QUIT button)
            sidebar_lay.insertWidget(9, self.flyout_btn_group)
        
        print(f"[ThorCNC] Registered Flyouts: {list(self.navigation._flyout_panels.keys())}")
        
        # Save references for direct access
        self.btn_mode_toggle = self.ui.findChild(QPushButton, "btn_flyout_toggle_mode")
        self._queued_start_line = None # For "Run from Line"

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
            self._view_restored = True
            # The flag prevents auto-fitting during startup signals (WCS, first file load)
            # We clear it after a short delay to allow normal auto-fitting later.
            QTimer.singleShot(1500, self._clear_view_restored_flag)

    def _switch_gcode_panel(self, idx: int):
        self._gcode_mdi_stack.setCurrentIndex(idx)
        for b, active_idx in ((self._btn_show_gcode, 0), (self._btn_show_mdi, 1)):
            if b is None:
                continue
            b.setChecked(idx == active_idx)

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
        btn_zero_all = QPushButton(_t("ZERO\nALL"))
        btn_zero_all.setFixedSize(btn_width, 44)
        btn_zero_all.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._add_class(btn_zero_all, "btn-blue")
        btn_zero_all.clicked.connect(lambda: self._zero_axis("ALL"))
        glay.addWidget(btn_zero_all, 0, 0)

        # AXIS header
        lbl_axis_hdr = QLabel(_t("AXIS"))
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
        lbl_mach_hdr = QLabel(_t("MACHINE"))
        self._add_class(lbl_mach_hdr, "dro-header")
        lbl_mach_hdr.setFixedWidth(val_width)
        lbl_mach_hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        glay.addWidget(lbl_mach_hdr, 0, 3)

        # DTG header (Distance to Go)
        lbl_dtg_hdr = QLabel(_t("DTG"))
        self._add_class(lbl_dtg_hdr, "dro-header")
        lbl_dtg_hdr.setFixedWidth(val_width)
        lbl_dtg_hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        glay.addWidget(lbl_dtg_hdr, 0, 4)

        # REF ALL button
        self._btn_ref_all = QPushButton(_t("REF ALL"))
        self._btn_ref_all.setFixedSize(btn_width, 44)
        self._btn_ref_all.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._add_class(self._btn_ref_all, "btn-green")
        self._btn_ref_all.clicked.connect(self.motion._home_all)
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
            btn_zero = QPushButton(_t("ZERO\n{}").format(axis))
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
            btn_ref = QPushButton(_t("REF {}").format(axis))
            btn_ref.setObjectName("dro_ref_btn")
            btn_ref.setFixedSize(btn_width, 52)
            btn_ref.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._add_class(btn_ref, "btn-green")
            glay.addWidget(btn_ref, i, 5)
            btn_ref.clicked.connect(lambda _=False, j=joint: self.motion._home_joint(j))

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
            new_origin = (g5x[0], g5x[1], g5x[2])
            is_initial = not self._wcs_initialized
            changed = not is_initial and new_origin != self._last_wcs_origin
            
            self.backplot.set_wcs_origin(*new_origin)
            self._last_wcs_origin = new_origin
            self._wcs_initialized = True
            
            # Wenn noch kein Programm geladen ist, zentriere auf den neuen Nullpunkt
            # Aber nur wenn wir nicht gerade die Ansicht aus den Settings wiederhergestellt haben
            # UND nur wenn es eine echte Änderung war (nicht beim allerersten Poller-Update)
            if not getattr(self, "_has_file", False) and changed:
                if not self._view_restored:
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
            self._status(_t("ZERO {} → {}").format(axis, wcs_name))
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

    # ── StatusPoller ──────────────────────────────────────────────────────────

    def _setup_poller(self):
        # Wir übergeben die HAL-Komponente, damit der Poller direkt auf die Pins zugreifen kann
        self.poller = StatusPoller(interval_ms=100, hal_comp=self._hal_comp, parent=self)



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
            self._status(_t("HAL component 'thorcnc' ready."))
            
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








    def eventFilter(self, watched, event):
        import shiboken6
        if not shiboken6.isValid(self) or not shiboken6.isValid(watched):
            return False
        if hasattr(self, "ui") and not shiboken6.isValid(self.ui):
            return False

        # Delegate to NavigationManager for light-dismiss
        if self.navigation.handle_event(event):
            return True

        from PySide6.QtCore import QEvent
        if watched == getattr(self.probing_tab, "_probe_grid_frm", None):
            if event.type() == QEvent.Resize:
                self.probing_tab.update_marker_pos()
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
            
            elif watched is self.ui and event.type() == QEvent.Type.Close:
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
                    return True 
                else:
                    # If Yes, we let it pass, but we must ensure we don't ask again
                    # We can remove the filter right here
                    QApplication.instance().removeEventFilter(self)
                    event.accept()
                    return True

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
        if cb_theme := self._w(QComboBox, "combo_theme"):
            # Set internal keys as userData before translation
            for i in range(cb_theme.count()):
                cb_theme.setItemData(i, cb_theme.itemText(i))
            
            valid_themes = ["dark", "light"]
            saved = self.settings.get("theme", "dark")
            if saved not in valid_themes:
                saved = "dark"
                
            idx = cb_theme.findData(saved)
            if idx >= 0:
                cb_theme.setCurrentIndex(idx)
            
            # Use blockSignals to avoid triggering apply_theme during translation later
            cb_theme.currentTextChanged.connect(
                lambda t, c=cb_theme: self.navigation.apply_theme(c.currentData() or t)
            )
            self.navigation.apply_theme(saved)

        if cb_lang := self._w(QComboBox, "combo_language"):
            # Set internal keys as userData before translation
            for i in range(cb_lang.count()):
                cb_lang.setItemData(i, cb_lang.itemText(i))
                
            saved_lang = self.settings.get("language", "Deutsch")
            idx = cb_lang.findData(saved_lang)
            if idx >= 0:
                cb_lang.setCurrentIndex(idx)
            cb_lang.currentIndexChanged.connect(lambda i, c=cb_lang: self._on_language_changed(c.itemData(i)))

        # ── UI Settings (Antialiasing, Tabs, etc) ──
        # ── Backplot Antialiasing ──
        if ui_tab := self._w(QWidget, "settings_tab_ui"):
            layout = ui_tab.layout()
            gb_gfx = QGroupBox(_t("Grafik / Performance"))
            # Wir suchen uns einen Platz vor dem vertikalen Spacer
            gl_gfx = QVBoxLayout(gb_gfx)
            self._cb_aa = QCheckBox(_t("Backplot Antialiasing (Glättung)"))
            self._cb_aa.setToolTip(_t("Verbessert die Linienqualität (MSAA). Erfordert Neustart für volle Wirkung."))
            
            active = self.settings.get("backplot_antialiasing", True)
            self._cb_aa.setChecked(active)
            self._cb_aa.toggled.connect(self._on_aa_toggled)

            gl_gfx.addWidget(self._cb_aa)
            lay_msaa = QHBoxLayout()
            lay_msaa.addWidget(QLabel(_t("MSAA Samples:")))
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
            gb_nav = QGroupBox(_t("Navigation"))
            gl_nav = QVBoxLayout(gb_nav)
            self._cb_html_tab = QCheckBox(_t("HTML-Tab anzeigen"))
            self._cb_html_tab.setToolTip(
                _t("Blendet den HTML/PDF-Dokumenten-Tab in der Navigation ein oder aus."))
            self._cb_html_tab.setChecked(self.settings.get("show_html_tab", True))
            self._cb_html_tab.toggled.connect(self._on_html_tab_visibility)
            gl_nav.addWidget(self._cb_html_tab)
            layout.insertWidget(layout.count() - 1, gb_nav)

            # ── Werkzeugliste ──
            gb_tools = QGroupBox(_t("Werkzeugliste"))
            gl_tools = QVBoxLayout(gb_tools)
            self._cb_show_pocket = QCheckBox(_t("Pocket-Spalte anzeigen"))
            self._cb_show_pocket.setToolTip(_t("Zeigt oder verbirgt die Pocket-Spalte (P) in der Werkzeugliste."))
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
            gb_safety = QGroupBox(_t("Maschinensicherheit / Warnungen"))
            gl_safety = QVBoxLayout(gb_safety)
            
            # Description
            lbl_desc = QLabel(_t("<b>Visuelle Taster-Warnung:</b><br>"
                              "Färbt die Statuszeile auffällig ein, wenn digitale "
                              "Ausgänge (M64) aktiv sind (z.B. für 3D-Taster)."))
            lbl_desc.setWordWrap(True)
            lbl_desc.setObjectName("settings_desc_label")
            gl_safety.addWidget(lbl_desc)
            
            # Enable Checkbox
            self._cb_probe_warn = QCheckBox(_t("Visuelle Warnung aktivieren"))
            gl_safety.addWidget(self._cb_probe_warn)

            # Pins Input
            lay_pins = QHBoxLayout()
            lay_pins.addWidget(QLabel(_t("M64 P... (Index):")))
            self._le_probe_pins = QLineEdit()
            self._le_probe_pins.setPlaceholderText(_t("z.B. 0, 2"))
            lay_pins.addWidget(self._le_probe_pins)
            gl_safety.addLayout(lay_pins)

            # Color Selector
            lay_color = QHBoxLayout()
            lay_color.addWidget(QLabel(_t("Warnfarbe:")))
            self._btn_probe_color = QPushButton(_t("WÄHLEN"))
            self._btn_probe_color.setFixedWidth(120)
            lay_color.addWidget(self._btn_probe_color)
            lay_color.addStretch()
            gl_safety.addLayout(lay_color)

            # Connect to ProbingManager
            self.probing_tab.connect_settings_widgets(
                self._cb_probe_warn,
                self._le_probe_pins,
                self._btn_probe_color
            )
            
            gl_safety.addSpacing(10)
            sep2 = QFrame()
            sep2.setFrameShape(QFrame.Shape.HLine)
            sep2.setObjectName("settings_separator")
            gl_safety.addWidget(sep2)
            gl_safety.addSpacing(5)

            # Homing conversion
            self._cb_homing_g53 = QCheckBox(_t("Homing-Buttons umfunktionieren (Ref -> G53 X0)"))
            self._cb_homing_g53.setToolTip(_t("Ersetzt den REF-Button durch G53 X0, sobald die Achse homed ist."))
            self._cb_homing_g53.setChecked(self.settings.get("homing_g53_conversion", False))
            self._cb_homing_g53.toggled.connect(
                lambda checked: (self.settings.set("homing_g53_conversion", checked),
                                 self.settings.save(),
                                 self.motion._on_homed(getattr(self.poller, "_homed", [])))
            )
            gl_safety.addWidget(self._cb_homing_g53)
            
            fl_safety.addWidget(gb_safety)
            fl_safety.addStretch() # Push safety up
            
            col_safety.addWidget(f_safety)
            main_layout.addLayout(col_safety, 1) # Stretch 1
            
            # --- Column 2: Abort Handler (Middle) ---
            col_abort = QVBoxLayout()
            gb_abort = QGroupBox(_t("Abort Handler (STOP/Fehler)"))
            gl_abort = QVBoxLayout(gb_abort)
            
            lbl_abort_desc = QLabel(_t("<b>G-Code bei Abbruch:</b><br>"
                                     "Dieser Code wird ausgeführt, wenn das Programm gestoppt wird.<br>"
                                     "<font color='#aaa'>INI [RS274NGC] ON_ABORT_COMMAND = O&lt;on_abort&gt; call</font>"))
            lbl_abort_desc.setWordWrap(True)
            gl_abort.addWidget(lbl_abort_desc)
            
            self._te_abort_gcode = QTextEdit()
            self._te_abort_gcode.setPlaceholderText(_t("z.B. M5 M9\nG54\nG90\nG40"))
            self._te_abort_gcode.setMinimumHeight(200)
            
            # GUI hat Vorrang: Immer aus den Prefs laden
            saved_abort = self.settings.get("abort_gcode", "M5 M9\nG54\nG90\nG40")
            self._te_abort_gcode.setPlainText(saved_abort)
            
            gl_abort.addWidget(self._te_abort_gcode)
            
            btn_save_abort = QPushButton(_t("SAVE & APPLY"))
            btn_save_abort.setMinimumHeight(45)
            btn_save_abort.clicked.connect(self._save_abort_handler)
            gl_abort.addWidget(btn_save_abort)
            
            col_abort.addWidget(gb_abort)
            main_layout.addLayout(col_abort, 2) # Give it more space
            
            # --- Column 2: Diagnostics & Components (Right) ---
            col_diag = QVBoxLayout()
            gb_diag = QGroupBox(_t("Diagnose & Komponenten"))
            gl_diag = QVBoxLayout(gb_diag)
            
            # List of diagnostics tools
            diag_tools = [
                (_t("HAL Show (Pins & Signale)"), self._run_halshow),
                (_t("HAL Scope (Oszilloskop)"), self._run_halscope),
                (_t("LinuxCNC Status (Detail-Infos)"), self._run_linuxcnc_status)
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

        # ── Abort Handler & Toolsetter Initialization (RESTORED) ──────────────
        self._write_on_abort_ngc()
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
        if b := self._w(QPushButton, "btn_set_taster_pos"):
            b.clicked.connect(self._set_taster_pos_from_machine)

        # Before / After Toolsetter TextEdits (RESTORED TO INIT)
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
            
    def _save_abort_handler(self):
        """Speichert den G-Code für den Abort-Handler und aktualisiert die .ngc Datei."""
        gcode = self._te_abort_gcode.toPlainText()
        self.settings.set("abort_gcode", gcode)
        self.settings.save()
        self._write_on_abort_ngc()

    def _write_on_abort_ngc(self):
        """Aktualisiert die on_abort.ngc Datei basierend auf dem aktuellen UI-Inhalt."""
        import os
        if not hasattr(self, "_te_abort_gcode"):
            return
            
        gcode = self._te_abort_gcode.toPlainText()
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
            
            self._status(f"Abort-Handler synchronisiert: {target_path}")
        except Exception as e:
            self._status(f"Fehler beim Schreiben des Abort-Handlers: {e}", error=True)




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
        """
        Gibt das NGC-Verzeichnis für Toolsetter-Subroutinen zurück.
        Priorität:
        1. 'subroutines/tools' relativ zur INI
        2. 'subroutines/tools' im PROGRAM_PREFIX
        3. PROGRAM_PREFIX aus der INI
        """
        search_dirs = []
        if self.ini_path:
            search_dirs.append(os.path.dirname(os.path.abspath(self.ini_path)))
            
        if self.ini:
            prefix = self.ini.find("DISPLAY", "PROGRAM_PREFIX")
            if prefix:
                prefix = os.path.expanduser(prefix)
                if not os.path.isabs(prefix) and self.ini_path:
                    prefix = os.path.abspath(os.path.join(os.path.dirname(self.ini_path), prefix))
                search_dirs.append(prefix)
        
        search_dirs.append(os.path.expanduser("~/linuxcnc/nc_files"))
        
        for base in search_dirs:
            sub = os.path.join(base, "subroutines", "tools")
            if os.path.isdir(sub):
                return sub
                
        # Fallback: Erster gefundener Basis-Ordner oder Default
        return search_dirs[1] if len(search_dirs) > 1 else search_dirs[0]

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
        self._status(_t("Antialiasing-Master-Schalter geändert. (MSAA-Level braucht Neustart)"))

    def _on_msaa_changed(self, index: int):
        """MSAA Samples (2x, 4x, etc) geändert."""
        val = self._cb_msaa.itemData(index)
        self.settings.set("backplot_msaa_samples", val)
        self.settings.save()
        self._status(_t("MSAA auf {}x gesetzt. Ein Neustart ist nötig.").format(val))

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
        from PySide6.QtWidgets import QTableWidget
        w = self._w(QTableWidget, "toolTable")
        if w:
            w.setColumnHidden(1, not visible)
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
        res = QMessageBox.question(self.ui, _t("Position übernehmen"), 
                                  _t("Möchtest du die aktuelle Maschinenposition wirklich als neue WECHSELPOSITION übernehmen?"),
                                  QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if res != QMessageBox.StandardButton.Yes:
            return

        pos = getattr(self, "_last_pos", None)
        if pos is None:
            self._status(_t("Keine Positionsdaten verfügbar!"), error=True)
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
        self._status(_t("Change position set from current machine position."))

    def _set_taster_pos_from_machine(self):
        """Sets the current machine position as Probe Position X/Y/Z."""
        from PySide6.QtWidgets import QDoubleSpinBox, QMessageBox
        
        # Sicherheitsabfrage
        res = QMessageBox.question(self.ui, _t("Position übernehmen"), 
                                  _t("Möchtest du die aktuelle Maschinenposition wirklich als neue MESSPOSITION übernehmen?"),
                                  QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if res != QMessageBox.StandardButton.Yes:
            return

        pos = getattr(self, "_last_pos", None)
        if pos is None:
            self._status(_t("Keine Positionsdaten verfügbar!"), error=True)
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
        self._status(_t("Probe position set from current machine position."))

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
        
        btn_coolant = self.ui.findChild(QPushButton, "btn_opt_coolant")
        if btn_coolant:
            btn_coolant.clicked.connect(self._toggle_coolant_internal)
            
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
        is_on = not self.poller.stat.estop and self.poller.stat.enabled
        can_mdi = is_idle and is_on
        
        btn_coolant = self.ui.findChild(QPushButton, "btn_opt_coolant")
        if btn_coolant:
            # Button Status NUR vom Poller setzen
            flood_active = (self.poller.stat.flood > 0)
            if btn_coolant.isChecked() != flood_active:
                btn_coolant.blockSignals(True)
                btn_coolant.setChecked(flood_active)
                btn_coolant.blockSignals(False)
                # Display ebenfalls aktualisieren
                self._update_active_codes_display()
            btn_coolant.setEnabled(is_on)

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
        if hasattr(self, "_btn_run_from_line") and self._btn_run_from_line:
            self._btn_run_from_line.setEnabled(is_idle)

    def _toggle_sb_internal(self):
        self.is_single_block = not self.is_single_block
        self._status(f"Single Block: {'AN' if self.is_single_block else 'AUS'}")

    def _toggle_m1_internal(self):
        curr = bool(self.poller.stat.optional_stop)
        self.cmd.set_optional_stop(not curr)
        self._status(f"M1 Optional Stop: {'AN' if not curr else 'AUS'}")

    def _toggle_coolant_internal(self):
        """Toggles flood coolant (M8/M9)."""
        curr_stat = self.poller.stat.flood
        new_state = 1 if curr_stat == 0 else 0
        
        print(f"[ThorCNC] Coolant Toggle. Current: {curr_stat} -> Target: {new_state}")
        
        # Fresh command object often helps in sim/remote environments
        c = linuxcnc.command()
        
        # If we are in AUTO and running, we MUST use flood()
        # If we are IDLE, we can also try MDI as a fallback
        if self.poller.stat.interp_state == linuxcnc.INTERP_IDLE:
            c.mode(linuxcnc.MODE_MDI)
            c.wait_complete()
            c.mdi("M8" if new_state == 1 else "M9")
        else:
            c.flood(new_state)
        
        # Update UI immediately
        self._update_active_codes_display()
        
        state_text = _t("AN") if new_state == 1 else _t("AUS")
        self._status(_t("KÜHLUNG: ") + state_text)

    def _on_opt_clicked(self):
        """Toggle-Logik für das Jalousie-Panel."""
        if not hasattr(self, "_opt_panel") or not self._opt_panel:
            return
            
        is_expanded = self._opt_panel.maximumHeight() > 0
        
        if is_expanded:
            self._opt_anim.setStartValue(175)
            self._opt_anim.setEndValue(0)
        else:
            self._opt_anim.setStartValue(0)
            self._opt_anim.setEndValue(175) # Höhe für 3 Buttons + Spacing + Margins
            
        self._opt_anim.start()

    def _run_mdi_command(self, cmd_text):
        """Helper to run MDI commands with robust mode switching."""
        if not self._is_machine_on: return
        
        import time
        # Switch to MDI and wait until it's really there (max 1s)
        self.cmd.mode(linuxcnc.MODE_MDI)
        for _ in range(10):
            if self.poller.stat.task_mode == linuxcnc.MODE_MDI:
                break
            time.sleep(0.05)
            
        self.cmd.mdi(cmd_text)


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
            self._status(_t("G-CODE EDIT MODE ENABLED"))
            # Update save button state based on current modification
            self._on_gcode_modification_changed(self.gcode_view.document().isModified())
        else:
            self._status(_t("G-CODE EDIT MODE DISABLED"))
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
            self._status(_t("SAVE FAILED: NO FILE LOADED"))
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
            self._status(_t("Kein M6 im Programm gefunden."))

    def _on_language_changed(self, lang: str):
        """Callback: Sprache geändert."""
        if lang == self.settings.get("language"):
            return
        self.settings.set("language", lang)
        self.settings.save()
        self._status(_t("Sprache geändert. Ein Neustart ist erforderlich."), error=True)

    def _connect_signals(self):
        p = self.poller
        ui = self.ui

        p.estop_changed.connect(self._on_estop)
        p.machine_on_changed.connect(self._on_machine_on)
        p.mode_changed.connect(self._on_mode)
        p.interp_changed.connect(self._on_interp)
        p.position_changed.connect(self._on_position)
        p.spindle_at_speed.connect(self._on_spindle_at_speed)
        p.spindle_speed_actual.connect(self._on_spindle_actual)
        p.spindle_load.connect(self._on_spindle_load)
        p.spindle_speed_cmd.connect(self._on_spindle_speed)
        p.g5x_index_changed.connect(self._on_g5x_index)
        p.g5x_offset_changed.connect(self._on_g5x_offset)
        p.gcodes_changed.connect(self._on_gcodes)
        p.mcodes_changed.connect(self._on_mcodes)
        p.file_loaded.connect(self.file_manager._on_file_loaded)
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
            b.clicked.connect(self.motion._home_all)
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
            b.setText("CCW")
            b.clicked.connect(lambda: _start_spindle(linuxcnc.SPINDLE_REVERSE))
        if b := btn("btn_spindle_rev"):
            b.setText("CW")
            b.clicked.connect(lambda: _start_spindle(linuxcnc.SPINDLE_FORWARD))
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
        if b := btn("btn_pause_mdi"):
            b.clicked.connect(self._pause_program)
        if b := btn("feed_override_to_100_button"):
            b.clicked.connect(lambda: self.cmd.feedrate(1.0))
        if b := btn("spindle_override_to_100_button"):
            b.clicked.connect(lambda: self.cmd.spindleoverride(1.0))
        if b := btn("rapid_override_to_100_button"):
            b.clicked.connect(lambda: self.cmd.rapidrate(1.0))

        # HAL Show
        if b := btn("btn_halshow"):
            b.clicked.connect(self._run_halshow)

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

        # Module signal connections
        self.file_manager.connect_signals()
        self.tool_table.connect_signals()
        self.offsets.connect_signals()
        self.motion.connect_signals()
        self.probing_tab.connect_signals()

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
        self.motion._update_goto_home_style(on and getattr(self, "_all_joints_homed", False))

    @Slot(int)
    def _on_mode(self, mode: int):
        from PySide6.QtWidgets import QPushButton, QComboBox
        self._current_mode = mode
        
        # Sync Sidebar Buttons (Classic)
        for name, m in (("manual_mode_button", linuxcnc.MODE_MANUAL),
                        ("mdi_mode_button",    linuxcnc.MODE_MDI),
                        ("auto_mode_button",   linuxcnc.MODE_AUTO)):
            if b := self._w(QPushButton, name):
                b.setChecked(mode == m)
                
        # Sync New Jalousie Buttons
        _MODES = {linuxcnc.MODE_MANUAL: "MANUAL", linuxcnc.MODE_AUTO: "AUTO", linuxcnc.MODE_MDI: "MDI"}
        if hasattr(self, "btn_mode_toggle"):
            txt = _MODES.get(mode, "MANUAL")
            self.btn_mode_toggle.setText(f"MODE: {txt}")
            # Color logic via style property
            self.btn_mode_toggle.setProperty("active_mode", txt)
            self.btn_mode_toggle.style().unpolish(self.btn_mode_toggle)
            self.btn_mode_toggle.style().polish(self.btn_mode_toggle)
            
            # Highlight items in Flyout
            _MODES = {linuxcnc.MODE_MANUAL: "MANUAL", linuxcnc.MODE_AUTO: "AUTO", linuxcnc.MODE_MDI: "MDI"}
            current_txt = _MODES.get(mode, "")
            for m_txt in ("MANUAL", "AUTO", "MDI"):
                if b := self.navigation._flyout_item_buttons.get(f"MODE_{m_txt}"):
                    b.setProperty("active", m_txt == current_txt)
                    b.style().unpolish(b)
                    b.style().polish(b)

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
        self.motion._update_goto_home_style(self._is_machine_on and getattr(self, "_all_joints_homed", False))

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
            
        # G-Code Edit Safety: Disable editing while not IDLE
        idle = state == linuxcnc.INTERP_IDLE
        if hasattr(self, "_btn_edit_gcode") and self._btn_edit_gcode:
            self._btn_edit_gcode.setEnabled(idle)
            if self.gcode_view:
                # Force read-only if not idle, otherwise follow button state
                self.gcode_view.setReadOnly(not idle or not self._btn_edit_gcode.isChecked())
        
        if hasattr(self, "_btn_save_gcode") and self._btn_save_gcode:
            # Save is only enabled if idle AND we were in edit mode AND file is modified
            is_edit = self._btn_edit_gcode.isChecked() if hasattr(self, "_btn_edit_gcode") else False
            is_modified = self.gcode_view.document().isModified() if self.gcode_view else False
            self._btn_save_gcode.setEnabled(idle and is_edit and is_modified)

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

        self.navigation.update_highlights()

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
            # G92 and G52 offsets are stored in g92_offset in modern LinuxCNC
            g92 = self.poller.stat.g92_offset[:3]
        except (AttributeError, TypeError):
            g92 = [0.0, 0.0, 0.0]

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
            # Work = Machine - WCS - G92 - Tool
            work = pos[i] - g5x[i] - g92[i] - t_off[i]
            mach = pos[i]
            
            # DTG is a tuple in LinuxCNC 2.9 (Axis-specific remaining distance)
            try:
                dtg_val = self.poller.stat.dtg[i]
            except (AttributeError, TypeError, IndexError):
                dtg_val = 0.0

            if axis in self._dro_work:
                self._dro_work[axis].setText(f"{work:+.3f}")
            if axis in self._dro_machine:
                self._dro_machine[axis].setText(f"{mach:+.3f}")
            if axis in getattr(self, "_dro_dtg", {}):
                self._dro_dtg[axis].setText(f"{dtg_val:+.3f}")

            # probe-DRO mitsyncen
            probe_dro_work = getattr(self.probing_tab, "_probe_dro_work", {})
            probe_dro_mach = getattr(self.probing_tab, "_probe_dro_machine", {})
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
            w_coords = [pos[i] - g5x[i] - g92[i] - t_off[i] for i in range(3)]
            m_coords = [pos[i] for i in range(3)]
            try:
                dtg_vals = list(self.poller.stat.dtg[:3])
            except (AttributeError, TypeError):
                dtg_vals = [0.0, 0.0, 0.0]

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
        
        # We handle M8/M9 (flood) and M7 (mist) based on REAL status,
        # because manual toggles bypass the interpreter's modal list.
        flood_active = (self.poller.stat.flood > 0)
        mist_active  = (self.poller.stat.mist > 0)
        
        for m in self._current_mcodes[1:]:
            if m == -1: continue
            
            # Skip interpreter's M7/M8/M9 - we insert our own based on real status
            if m in (7, 8, 9):
                continue
                
            m_str = f"M{m}".upper()
            color = col_def
            weight = "normal"
            if m_str in m_list:
                color = col_m
                weight = "bold"
            active_m.append(f'<span style="color: {color}; font-weight: {weight};">{m_str}</span>')
            
        # Insert real-time coolant codes
        if flood_active:
            active_m.append(f'<span style="color: {col_m if "M8" in m_list else col_def}; font-weight: bold;">M8</span>')
        else:
            active_m.append(f'<span style="color: {col_def};">M9</span>')
            
        if mist_active:
            active_m.append(f'<span style="color: {col_m if "M7" in m_list else col_def}; font-weight: bold;">M7</span>')
            
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
            # fwd button is now on the left and labeled CCW (direction -1)
            b.setStyleSheet(fwd_style if direction == -1 else "")
        if b := self._w(QPushButton, "btn_spindle_rev"):
            # rev button is now on the right and labeled CW (direction 1)
            b.setStyleSheet(rev_style if direction == 1 else "")

    def _set_hal_pin(self, name: str, val):
        if self._hal_comp:
            try:
                self._hal_comp[name] = val
            except Exception:
                pass

    @Slot(str)
    @Slot(tuple)
    def _on_digital_out_changed(self, dout: tuple):
        """React to M64/M65 on specific pins to show a visual warning."""
        self._last_dout = dout # Store for settings refresh

        # Delegate probe warning update to ProbingManager
        if hasattr(self, 'probing_tab') and self.probing_tab:
            self.probing_tab.update_probe_warning(dout)

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
        q_line = getattr(self, "_queued_start_line", None)

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
            # Wenn nicht pausiert, entweder Queued-Line, Steppen oder normal Starten
            if q_line:
                print(f"[DIAGNOSTIC] Queued Start: Preparing state for line {q_line}")
                
                # 1. Prepare Preamble (WCS and G43)
                # Get current WCS from status (540=G54, 550=G55, etc.)
                g5x_code = 54
                g43_active = False
                for g in s.gcodes:
                    if 540 <= g <= 590:
                        g5x_code = 54 + (g - 540) // 10
                    if g == 430 or g == 431: # G43 or G43.1
                        g43_active = True
                
                # Build preamble command
                pre_cmd = f"G{g5x_code}"
                if g43_active:
                    pre_cmd += " G43"
                
                # Send Preamble via MDI first
                self.cmd.mode(linuxcnc.MODE_MDI)
                self.cmd.wait_complete()
                self.cmd.mdi(pre_cmd)
                self.cmd.wait_complete()
                
                # 2. Switch back to AUTO and RUN
                self.cmd.mode(linuxcnc.MODE_AUTO)
                self.cmd.wait_complete()
                
                print(f"[DIAGNOSTIC] Queued Start: Sending AUTO_RUN from line {q_line}")
                self.cmd.auto(linuxcnc.AUTO_RUN, q_line)
                
                # Reset Queue
                self._queued_start_line = None
                if hasattr(self, "_btn_run_from_line"):
                    self._btn_run_from_line.setProperty("active", False)
                    self._btn_run_from_line.style().unpolish(self._btn_run_from_line)
                    self._btn_run_from_line.style().polish(self._btn_run_from_line)
                    self._btn_run_from_line.update()
            elif is_sb:
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
            self._status(_t("HAL Show gestartet."))
        except Exception as e:
            self._status(f"Konnte halshow nicht starten: {e}", error=True)

    def _run_halscope(self):
        """Startet halscope als externen Prozess."""
        import subprocess
        try:
            subprocess.Popen(["halscope"], start_new_session=True)
            self._status(_t("HAL Scope gestartet."))
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
            self._status(_t("LinuxCNC Status (top) gestartet."))
        except Exception as e:
            self._status(f"Konnte linuxcnctop nicht starten: {e}", error=True)

    def _pause_program(self):
        self.cmd.auto(linuxcnc.AUTO_PAUSE)

    def _stop_program(self):
        self.cmd.abort()
        self.cmd.wait_complete()
        self.cmd.mode(linuxcnc.MODE_MANUAL)
        self._status(_t("PROGRAMM ABGEBROCHEN"))

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
            from PySide6.QtWidgets import QApplication
            QApplication.instance().removeEventFilter(self)
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

    def _clear_view_restored_flag(self):
        self._view_restored = False

