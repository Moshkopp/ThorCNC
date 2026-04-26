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
        if getattr(self, '_lbl_status_msg', None):
            self._lbl_status_msg.setText("")

    def status(self, msg: str, error: bool = False):
        if getattr(self, '_lbl_status_msg', None):
            self._lbl_status_msg.setText(msg)
            self._lbl_status_msg.setStyleSheet(
                f"color: {'#ff5555' if error else '#cccccc'}; font-weight: bold; margin-left: 10px;"
            )
            self._status_timer.start(10000)
        elif sb := self._t.ui.statusBar():
            sb.showMessage(msg, 10000)

        self.append_log(msg, error=error)

    def append_log(self, msg: str, error: bool = False):
        log: QListWidget = self._t.ui.findChild(QListWidget, "status_log")
        if log is None:
            return
        log.setAlternatingRowColors(False)
        ts = QDateTime.currentDateTime().toString("HH:mm:ss")
        item = QListWidgetItem(f"[{ts}]  {msg}")
        if error:
            item.setForeground(QColor("#ff5555"))
        else:
            theme = self._t.settings.get("theme", "dark")
            item.setForeground(QColor("#1a2332" if theme == "light" else "#d0d0d0"))
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
