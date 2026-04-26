import os
import linuxcnc
from PySide6.QtCore import Qt, QObject, QByteArray, QEvent
from PySide6.QtWidgets import (QLabel, QFrame, QPushButton,
                               QWidget, QVBoxLayout, QSplitter,
                               QSizePolicy, QComboBox, QApplication)
from PySide6.QtUiTools import QUiLoader

from .status_poller import StatusPoller
from .i18n import TranslationManager, _t
from .modules import (FileManagerModule, ToolTableModule, OffsetsModule,
                        MotionModule, ProbingTabModule, NavigationModule, SettingsTabModule, DROModule, SpindleModule, SimpleViewModule, GCodeViewModule, MDIModule, HALModule, ControlPanelModule, BackplotModule,
                        ProgramControlModule, StatusModule, SurfaceMapModule)
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
        self.backplot_mod = BackplotModule(self)
        self.program_control = ProgramControlModule(self)
        self.status_mod = StatusModule(self)
        self.surface_map = SurfaceMapModule(self)
        
        # i18n
        self.i18n = TranslationManager(self.settings.get("language", "Deutsch"))

        self._load_ui()

        # Backplot needs to be setup before _replace_custom_widgets() can use it
        self.backplot_mod.setup()

        self._replace_custom_widgets()

        self._restore_window_state()
        self.hal_mod.setup()
        self.status_mod.setup()
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
        self.gcode_view_mod.setup_widget()
        self.motion._update_goto_home_style(all_homed=False)
        self.navigation.setup_flyouts()
        self.backplot_mod.replace_vtk_placeholder()
        self.surface_map.setup_widget()






    def _apply_ini_settings(self):
        """Apply INI settings to UI (machine name in window title)."""
        name = "ThorCNC"
        if self.ini:
            name = self.ini.find("EMC", "MACHINE") or name
        self.ui.setWindowTitle(name)
        # Machine envelope is set by backplot_mod.setup()

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

        # Arrow-key jog — intercept before any focused widget consumes the event
        if event.type() == QEvent.Type.KeyPress:
            if self._handle_arrow_jog_key(event, pressed=True):
                return True
        elif event.type() == QEvent.Type.KeyRelease:
            if self._handle_arrow_jog_key(event, pressed=False):
                return True

        # Delegate to NavigationManager for light-dismiss
        if self.navigation.handle_event(event):
            return True

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

    # ── Arrow-key jog ──────────────────────────────────────────────────────
    _ARROW_JOG_MAP = {
        Qt.Key.Key_Right:    (0, +1),
        Qt.Key.Key_Left:     (0, -1),
        Qt.Key.Key_Up:       (1, +1),
        Qt.Key.Key_Down:     (1, -1),
        Qt.Key.Key_PageUp:   (2, +1),
        Qt.Key.Key_PageDown: (2, -1),
    }

    def _handle_arrow_jog_key(self, event, pressed: bool) -> bool:
        if not self.settings.get("arrow_key_jog", False):
            return False
        mapping = self._ARROW_JOG_MAP.get(event.key())
        if mapping is None:
            return False
        if event.isAutoRepeat():
            return True
        if not self._is_machine_on:
            return True
        import linuxcnc as _lc
        if self._interp_state not in (_lc.INTERP_IDLE,):
            return True
        joint, direction = mapping
        if pressed:
            self.motion._jog_start(joint, direction)
        else:
            self.motion._jog_stop(joint)
        return True









    def _connect_signals(self):
        p = self.poller
        ui = self.ui

        p.g5x_index_changed.connect(self.dro._on_g5x_index)
        p.g5x_offset_changed.connect(self.dro._on_g5x_offset)
        p.gcodes_changed.connect(self.gcode_view_mod._on_gcodes)
        p.mcodes_changed.connect(self.gcode_view_mod._on_mcodes)
        p.file_loaded.connect(self.file_manager._on_file_loaded)

        # ── Machine Buttons (probe_basic widget names) ──────────────────────
        from PySide6.QtWidgets import QPushButton, QSlider
        def btn(name):
            return ui.findChild(QPushButton, name)
        def sld(name):
            return ui.findChild(QSlider, name)

        if b := btn("power_button"):
            b.clicked.connect(self.program_control.toggle_power)
        if b := btn("stop_button"):
            b.clicked.connect(self.program_control.stop_program)
        if b := btn("btn_opt"):
            b.clicked.connect(self.control_panel_mod._on_opt_clicked)
        if b := btn("btn_run"):
            b.clicked.connect(self.program_control.run_program)
        if b := btn("manual_mode_button"):
            b.clicked.connect(lambda: self.cmd.mode(linuxcnc.MODE_MANUAL))
        if b := btn("mdi_mode_button"):
            b.clicked.connect(lambda: self.cmd.mode(linuxcnc.MODE_MDI))
        if b := btn("auto_mode_button"):
            b.clicked.connect(lambda: self.cmd.mode(linuxcnc.MODE_AUTO))
        if b := btn("go_to_home_button"):
            b.clicked.connect(self.motion._home_all)
        if b := btn("estop_button"):
            b.clicked.connect(self.program_control.toggle_estop)

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
            b.clicked.connect(self.program_control.pause_program)
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

        # Module signal connections
        self.navigation.connect_signals()
        self.file_manager.connect_signals()
        self.tool_table.connect_signals()
        self.offsets.connect_signals()
        self.motion.connect_signals()
        self.probing_tab.connect_signals()
        self.spindle.connect_signals()
        self.gcode_view_mod.connect_signals()
        self.mdi_mod.connect_signals()
        self.control_panel_mod.connect_signals()
        self.backplot_mod.connect_signals()
        self.program_control.connect_signals()
        self.status_mod.connect_signals()

        # Simple View — fullscreen overlay, opened by clicking the status bar


    # ── Slots ─────────────────────────────────────────────────────────────────

    def _w(self, cls, name):
        return self.ui.findChild(cls, name)

    # _on_estop / _on_machine_on / _on_mode / _on_interp / _on_position / _on_program_line
    # → delegated to ProgramControlModule.connect_signals()

    def _update_run_buttons(self):
        self.program_control._update_run_buttons()

    def _setup_highlight_settings(self):
        self.gcode_view_mod._setup_highlight_settings()



    def _set_hal_pin(self, name: str, val):
        if self._hal_comp:
            try:
                self._hal_comp[name] = val
            except Exception:
                pass

    def _status(self, msg: str, error: bool = False):
        self.status_mod.status(msg, error)

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
        self.status_mod.drain_startup_errors()


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


