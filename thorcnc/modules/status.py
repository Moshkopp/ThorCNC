"""Status Module.

Handles:
- Status bar message display (with auto-clear timer)
- Status log list widget (timestamped entries)
- Error and info message routing
- Startup error channel drain
"""

import linuxcnc
from PySide6.QtCore import Slot, QTimer, QDateTime
from PySide6.QtWidgets import QListWidget, QListWidgetItem
from PySide6.QtGui import QColor

from .base import ThorModule
from ._theme_utils import theme_color


class StatusModule(ThorModule):
    """Manages status message display and logging."""

    def setup(self):
        from PySide6.QtWidgets import QLabel
        self._lbl_status_msg = self._t.ui.findChild(QLabel, "lbl_status_msg")
        self._status_timer = QTimer()
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self._clear_status)

        # Wire reference so other modules can still call self._t._lbl_status_msg
        self._t._lbl_status_msg = self._lbl_status_msg

    def connect_signals(self):
        self._t.poller.error_message.connect(self._on_error)
        self._t.poller.info_message.connect(self._on_info)

    def _clear_status(self):
        lbl = getattr(self._t, '_lbl_status_msg', None) or getattr(self, '_lbl_status_msg', None)
        if lbl:
            lbl.setText("")

    def status(self, msg: str, error: bool = False):
        # Prefer the persistent label created by SimpleViewModule; fall back to
        # the one found at setup time. Never use showMessage() — it hides
        # permanent widgets (simple_view_indicator, resource_monitor).
        lbl = getattr(self._t, '_lbl_status_msg', None) or getattr(self, '_lbl_status_msg', None)
        if lbl:
            lbl.setText(msg)
            col = theme_color(self._t, "error.text" if error else "text.primary")
            lbl.setStyleSheet(
                f"color: {col}; font-weight: bold; margin-left: 10px;"
            )
            self._status_timer.start(10000)

        self.append_log(msg, error=error)

    def append_log(self, msg: str, error: bool = False):
        log: QListWidget = self._t.ui.findChild(QListWidget, "status_log")
        if log is None:
            return
        log.setAlternatingRowColors(False)
        ts = QDateTime.currentDateTime().toString("HH:mm:ss")
        item = QListWidgetItem(f"[{ts}]  {msg}")
        col = theme_color(self._t, "error.text" if error else "text.primary")
        item.setForeground(QColor(col))
        log.addItem(item)
        log.scrollToBottom()

    def drain_startup_errors(self):
        self.append_log("── Session gestartet ──")
        try:
            ec = self._t.poller.error_channel
            msg = ec.poll()
            while msg:
                kind, text = msg
                is_err = kind in (linuxcnc.NML_ERROR, linuxcnc.OPERATOR_ERROR)
                self.append_log(text, error=is_err)
                msg = ec.poll()
        except Exception:
            pass

    @Slot(str)
    def _on_error(self, msg: str):
        self.status(f"ERROR: {msg}", error=True)

    @Slot(str)
    def _on_info(self, msg: str):
        self.status(msg)
