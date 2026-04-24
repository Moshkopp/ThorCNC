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
                        MotionModule, ProbingTabModule, NavigationModule, SettingsTabModule, DROModule, SpindleModule, SimpleViewModule, GCodeViewModule, MDIModule, HALModule, ControlPanelModule)
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
        self.settings_tab = SettingsTabModule(self)
        self.dro = DROModule(self)
        self.spindle = SpindleModule(self)
        self.simple_view_mod = SimpleViewModule(self)
        self.gcode_view_mod = GCodeViewModule(self)
        self.mdi_mod = MDIModule(self)
        self.hal_mod = HALModule(self)
        self.control_panel_mod = ControlPanelModule(self)
        
        # i18n
        self.i18n = TranslationManager(self.settings.get("language", "Deutsch"))
        
        self._load_ui()
        
        self._replace_custom_widgets()

        self._restore_window_state()
        self.hal_mod.setup()
        self._setup_poller()
        self.file_manager.setup()
        self.tool_table.setup()
        self.offsets.setup()
        self.motion.setup()
        self.probing_tab.setup()
        self.settings_tab.setup()
        self.dro.setup()
        self.spindle.setup()
        self.simple_view_mod.setup()
        self.gcode_view_mod.setup()
        self.mdi_mod.setup()
        self.control_panel_mod.setup()
        self._connect_signals()
        
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
        self._btn_find_m6.clicked.connect(self.gcode_view_mod._find_next_m6)
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
        self._btn_edit_gcode.clicked.connect(self.gcode_view_mod._on_toggle_gcode_edit)
        h_lay.addWidget(self._btn_edit_gcode)

        # Save Button
        self._btn_save_gcode = QPushButton(_t("SAVE"))
        self._btn_save_gcode.setObjectName("btn_save_gcode")
        self._btn_save_gcode.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_save_gcode.clicked.connect(self.gcode_view_mod._on_save_gcode)
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
        self.gcode_view.document().modificationChanged.connect(self.gcode_view_mod._on_gcode_modification_changed)
        
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
            lambda: self.mdi_mod._send_mdi(self._mdi_input.text(), self._mdi_input))

        self._mdi_history_widget = QListWidget()
        self._mdi_history_widget.setObjectName("mdiHistory")
        self._mdi_history_widget.itemDoubleClicked.connect(
            lambda item: self._mdi_input.setText(item.text()))
        # Also connect to MDI send when history item is double-clicked
        self._mdi_history_widget.itemDoubleClicked.connect(
            lambda item: self.mdi_mod._send_mdi(item.text()))

        mdi_page_lay.addWidget(self._mdi_input)
        mdi_page_lay.addWidget(self._mdi_history_widget)
        self._gcode_mdi_stack.addWidget(mdi_page)

        # UI-Buttons verdrahten (aus der UI-Datei) - Sidebar Nav
        self._btn_show_gcode = self.ui.findChild(QPushButton, "btn_gcode_view")
        self._btn_show_mdi   = self.ui.findChild(QPushButton, "btn_mdi_view")
        if self._btn_show_gcode:
            self._btn_show_gcode.clicked.connect(lambda: self.mdi_mod._switch_gcode_panel(0))
        if self._btn_show_mdi:
            self._btn_show_mdi.clicked.connect(lambda: self.mdi_mod._switch_gcode_panel(1))

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

        self.mdi_mod._switch_gcode_panel(0)

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
        # Delegate to SimpleViewModule
        if self.simple_view_mod.handle_event(watched, event):
            return True
        if watched is self.ui:
            if event.type() == QEvent.Type.Close:
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

        p.g5x_index_changed.connect(self.dro._on_g5x_index)
        p.g5x_offset_changed.connect(self.dro._on_g5x_offset)
        p.gcodes_changed.connect(self.gcode_view_mod._on_gcodes)
        p.mcodes_changed.connect(self.gcode_view_mod._on_mcodes)
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
            b.clicked.connect(self.control_panel_mod._on_opt_clicked)
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
        if b := btn("btn_spindle_fwd"):
            b.setText("CCW")
            b.clicked.connect(lambda: self.spindle.start_spindle(linuxcnc.SPINDLE_REVERSE))
        if b := btn("btn_spindle_rev"):
            b.setText("CW")
            b.clicked.connect(lambda: self.spindle.start_spindle(linuxcnc.SPINDLE_FORWARD))
        if b := btn("btn_spindle_stop"):
            b.clicked.connect(self.spindle.stop_spindle)

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
            b.clicked.connect(self.settings_tab.run_halshow)

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
        self.spindle.connect_signals()
        self.gcode_view_mod.connect_signals()
        self.mdi_mod.connect_signals()
        self.control_panel_mod.connect_signals()

        # Simple View — fullscreen overlay, opened by clicking the status bar


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
        sv = self.simple_view_mod.simple_view
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
                    self.mdi_mod._switch_gcode_panel(1)
            else:
                self._silent_mdi = False
                self.mdi_mod._switch_gcode_panel(0)
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
        sv = self.simple_view_mod.simple_view
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
        self.dro.refresh()




    @Slot(tuple)


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
        self.simple_view_mod.set_gcode_line(line)
            
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

