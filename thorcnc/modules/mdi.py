"""MDI (Manual Data Input) Module.

Handles:
- MDI command execution and history
- Panel switching between GCode and MDI views
"""

import linuxcnc
import time
from PySide6.QtCore import Slot

from .base import ThorModule


class MDIModule(ThorModule):
    """Manages MDI input, history, and execution."""

    def setup(self):
        """Called after MainWindow initialization."""
        pass

    def connect_signals(self):
        """Connect MDI-related signals from MainWindow."""
        pass

    # ── Panel Switching ───────────────────────────────────────────────────────

    @Slot(int)
    def _switch_gcode_panel(self, idx: int):
        """Switch between GCode view (0) and MDI history (1)."""
        stack = self._t._gcode_mdi_stack
        if not stack:
            return

        stack.setCurrentIndex(idx)

        # Update button states
        for b, active_idx in ((self._t._btn_show_gcode, 0), (self._t._btn_show_mdi, 1)):
            if b is None:
                continue
            b.setChecked(idx == active_idx)

    # ── MDI Execution ─────────────────────────────────────────────────────────

    @Slot(str)
    def _send_mdi(self, text: str, widget=None):
        """Send MDI command and add to history."""
        text = text.strip()
        if not text:
            return

        try:
            self._t.cmd.mode(linuxcnc.MODE_MDI)
            self._t.cmd.wait_complete()
            self._t.cmd.mdi(text)

            if widget:
                widget.clear()

            self._t._status(f"MDI: {text}")

            # Add to history
            hist_widget = self._t._mdi_history_widget
            if hist_widget.count() == 0 or hist_widget.item(0).text() != text:
                hist_widget.insertItem(0, text)
                if hist_widget.count() > 50:
                    hist_widget.takeItem(hist_widget.count() - 1)

            # Save history to settings
            self._save_mdi_history()

        except Exception as e:
            self._t._status(f"MDI error: {e}")

    def _run_mdi_command(self, cmd_text):
        """Helper to run MDI commands with robust mode switching."""
        if not self._t._is_machine_on:
            return

        self._t.cmd.mode(linuxcnc.MODE_MDI)
        for _ in range(10):
            if self._t.poller.stat.task_mode == linuxcnc.MODE_MDI:
                break
            time.sleep(0.05)

        self._t.cmd.mdi(cmd_text)

    def _save_mdi_history(self):
        """Save current MDI history to settings."""
        history = []
        hist_widget = self._t._mdi_history_widget
        for i in range(hist_widget.count()):
            item = hist_widget.item(i)
            if item:
                history.append(item.text())

        self._t.settings.set("mdi_history", history)
        self._t.settings.save()
