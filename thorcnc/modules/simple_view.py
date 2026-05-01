"""SimpleView module for ThorCNC — manages the fullscreen overlay."""

import linuxcnc
from PySide6.QtCore import Qt, QTimer, QPoint, QEvent
from PySide6.QtWidgets import QPushButton, QLabel, QWidget, QHBoxLayout, QApplication
from PySide6.QtGui import QShortcut, QKeySequence

from .base import ThorModule
from ..widgets.simple_view import SimpleView

class SimpleViewModule(ThorModule):
    """Manages the SimpleView fullscreen overlay and its status bar indicator."""

    def __init__(self, thorc):
        super().__init__(thorc)
        self.simple_view = None
        self._lbl_simple_view_indicator = None
        self._sb_for_filter = None
        self._pre_simple_window_state = Qt.WindowState.WindowMaximized

    def setup(self):
        """Initializes the overlay and status bar integration."""
        self._setup_simple_overlay()

    def connect_signals(self):
        self._t.poller.simple_view_toggle.connect(self._hal_toggle)
        self._t.poller.simple_view_state.connect(self._hal_state)

    def _hal_toggle(self):
        if self.simple_view and self.simple_view.isVisible():
            self.hide()
        else:
            self.show()

    def _hal_state(self, active: bool):
        if active:
            self.show()
        else:
            self.hide()

    def _setup_simple_overlay(self):
        """Create SimpleView as a child overlay of the central widget."""
        cw = self._t.ui.centralWidget() or self._t.ui
        self.simple_view = SimpleView(parent=cw)
        self.simple_view.setGeometry(cw.rect())
        self.simple_view.hide()

        # Gespeicherte Backplot-Farben anwenden
        saved_colors = self._t.settings.get("backplot_colors", {})
        if saved_colors and getattr(self.simple_view, "backplot", None):
            self.simple_view.backplot.set_colors(saved_colors)

        # ESC shortcut scoped to the overlay
        esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self.simple_view)
        esc.activated.connect(self.hide)

        # Zurück button
        if self.simple_view.btn_back:
            self.simple_view.btn_back.clicked.connect(self.hide)

        # Machine control buttons - delegate to MainWindow or other modules
        if self.simple_view.btn_start:
            self.simple_view.btn_start.clicked.connect(self._t.program_control.run_program)
        if self.simple_view.btn_pause:
            self.simple_view.btn_pause.clicked.connect(self._t.program_control.pause_program)
        if self.simple_view.btn_stop:
            self.simple_view.btn_stop.clicked.connect(self._t.program_control.stop_program)
        if self.simple_view.btn_estop:
            self.simple_view.btn_estop.clicked.connect(self._t.program_control.toggle_estop)

        # Sync initial backplot state
        self.refresh_backplot()

        # Status Bar integration
        if sb := self._t.ui.statusBar():
            sb.setVisible(True)
            sb.setMinimumHeight(28)
            sb.clearMessage()

            # Single container fills the whole bar — centers the Simple View indicator.
            # showMessage() is never called (StatusModule uses the label directly),
            # so this container is never hidden.
            container = QWidget()
            layout = QHBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            # Left: status message
            self._t._lbl_status_msg = QLabel("")
            self._t._lbl_status_msg.setObjectName("persistent_status_msg")
            self._t._lbl_status_msg.setMinimumWidth(300)
            layout.addWidget(self._t._lbl_status_msg)

            # Center: Simple View indicator
            layout.addStretch()
            self._lbl_simple_view_indicator = QLabel(" SIMPLE VIEW ")
            self._lbl_simple_view_indicator.setObjectName("simple_view_indicator")
            self._lbl_simple_view_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self._lbl_simple_view_indicator)
            layout.addStretch()

            # Right: CPU/RAM monitor
            self._t._lbl_resource_monitor = QLabel("")
            self._t._lbl_resource_monitor.setObjectName("resource_monitor_label")
            self._t._lbl_resource_monitor.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._t._lbl_resource_monitor.setMinimumWidth(160)
            self._t._lbl_resource_monitor.setVisible(False)
            layout.addWidget(self._t._lbl_resource_monitor)

            sb.addWidget(container, 1)

            sb.setCursor(Qt.CursorShape.PointingHandCursor)
            sb.installEventFilter(self._t)
            self._lbl_simple_view_indicator.installEventFilter(self._t)
            self._sb_for_filter = sb

    def show(self):
        """Displays the fullscreen overlay."""
        if not self.simple_view:
            return
        cw = self._t.ui.centralWidget() or self._t.ui
        self.simple_view.setGeometry(cw.rect())
        
        # Save current state to restore it later
        self._pre_simple_window_state = self._t.ui.windowState()
        # Go fullscreen
        self._t.ui.showFullScreen()
        
        # Hide the main backplot so it doesn't render while overlay is up
        if hasattr(self._t, "backplot") and self._t.backplot:
            self._t.backplot.hide()

        # Hide underlying main UI widgets to prevent layout overhead
        from PySide6.QtWidgets import QWidget
        if tw := self._t._w(QWidget, "tabWidget"): tw.hide()
        if rp := self._t._w(QWidget, "rightPanel"): rp.hide()
        if lp := self._t._w(QWidget, "runControlsPanel"): lp.hide()
        
        self.refresh_backplot()
        if self._t._user_program:
            self.simple_view.load_gcode(self._t._user_program)
            s = self._t.poller.stat
            line = s.motion_line if s.motion_line > 0 else s.current_line
            self.simple_view.set_gcode_line(line)

        self.simple_view.show()
        self.simple_view.raise_()
        self.simple_view.setFocus()

    def hide(self):
        """Hides the overlay and restores window state."""
        if self.simple_view:
            self.simple_view.hide()

            # Restore the main backplot
            if hasattr(self._t, "backplot") and self._t.backplot:
                self._t.backplot.show()

            # Restore underlying main UI widgets
            from PySide6.QtWidgets import QWidget
            if tw := self._t._w(QWidget, "tabWidget"): tw.show()
            if rp := self._t._w(QWidget, "rightPanel"): rp.show()
            if lp := self._t._w(QWidget, "runControlsPanel"): lp.show()

            # Optional: restore window state if desired, 
            # though usually F11 or the Back button handles this.
            if self._t.ui.isFullScreen():
                 self._t.ui.setWindowState(self._pre_simple_window_state)

    def refresh_backplot(self):
        """Syncs the overlay backplot with the main backplot state."""
        if not self.simple_view or not self.simple_view.backplot:
            return
        
        if hasattr(self._t, "_backplot_envelope"):
            self.simple_view.backplot.set_machine_envelope(**self._t._backplot_envelope)
        if hasattr(self._t, "_last_wcs_origin"):
            self.simple_view.backplot.set_wcs_origin(*self._t._last_wcs_origin)
        if hasattr(self._t, "_last_toolpath") and self._t._last_toolpath is not None:
            self.simple_view.backplot.load_toolpath(self._t._last_toolpath)
        self.simple_view.backplot.set_view_iso()

    def set_gcode_line(self, line):
        if self.simple_view and self.simple_view.isVisible():
            self.simple_view.set_gcode_line(line)

    def handle_event(self, watched, event):
        """Processes resize and click events for the overlay."""
        if watched in (self._sb_for_filter, self._lbl_simple_view_indicator):
            if event.type() == QEvent.Type.MouseButtonPress:
                self.show()
                return True
        
        if watched is self._t.ui:
            if event.type() == QEvent.Type.Resize:
                if self.simple_view:
                    cw = self._t.ui.centralWidget()
                    self.simple_view.setGeometry(cw.rect() if cw else self._t.ui.rect())
        return False
