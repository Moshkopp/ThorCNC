"""Control Panel Module.

Handles:
- OPT (Options) Panel UI with expandable animation
- Single Block and M1 (Optional Stop) toggle controls
- Machine control button state synchronization
- Z-safety checks for G53 shortcuts
"""

import linuxcnc
from PySide6.QtCore import Slot
from PySide6.QtWidgets import QPushButton, QFrame
from PySide6.QtCore import QPropertyAnimation, QEasingCurve

from .base import ThorModule


class ControlPanelModule(ThorModule):
    """Manages machine control panel (OPT Panel) UI and logic."""

    def setup(self):
        """Initialize OPT panel UI and animations."""
        self._setup_opt_jalousie()

    def connect_signals(self):
        """Connect control panel signals to poller updates."""
        self._btn_sb: QPushButton | None = None
        self._btn_m1: QPushButton | None = None
        self._t.poller.periodic.connect(self._sync_opt_buttons)

    def _setup_opt_jalousie(self):
        """Initialize OPT Panel with expand/collapse animation."""
        self._opt_panel = self._t.ui.findChild(QFrame, "optExpandPanel")
        if not self._opt_panel:
            print("[ThorCNC] WARNUNG: optExpandPanel nicht in UI gefunden.")
            return

        # Create expand/collapse animation
        self._opt_anim = QPropertyAnimation(self._opt_panel, b"maximumHeight")
        self._opt_anim.setDuration(300)
        self._opt_anim.setEasingCurve(QEasingCurve.Type.InOutQuart)

        # Find and connect panel buttons — gecacht für _sync_opt_buttons
        self._btn_sb = self._t.ui.findChild(QPushButton, "btn_opt_sb")
        self._btn_m1 = self._t.ui.findChild(QPushButton, "btn_opt_m1")

        if self._btn_sb:
            self._btn_sb.clicked.connect(self._toggle_sb_internal)
        if self._btn_m1:
            self._btn_m1.clicked.connect(self._toggle_m1_internal)

        # Coolant button connects to spindle module
        btn_coolant = self._t.ui.findChild(QPushButton, "btn_opt_coolant")
        if btn_coolant:
            btn_coolant.clicked.connect(self._t.spindle.toggle_coolant)

    def _sync_opt_buttons(self):
        """Synchronize panel button states with machine status (called by poller)."""
        if self._btn_sb:
            self._btn_sb.setChecked(self._t.is_single_block)
        if self._btn_m1:
            self._btn_m1.setChecked(bool(self._t.poller.stat.optional_stop))

        # Update enable state for motion buttons based on machine idle/ready
        is_idle = self._t.poller.stat.interp_state == linuxcnc.INTERP_IDLE
        is_on = not self._t.poller.stat.estop and self._t.poller.stat.enabled
        can_mdi = is_idle and is_on

        # Sync spindle buttons
        self._t.spindle.sync_buttons()

        # Z-Safety: G53 X/Y shortcuts only if Z is at machine zero
        homed = getattr(self._t.poller, "_homed", [])
        enable_g53 = self._t.settings.get("homing_g53_conversion", False)
        z_mach = getattr(self._t, "_last_pos", [0, 0, -999])[2]
        z_safe = abs(z_mach) < 0.1

        def _set_enabled(btn, state: bool):
            if btn and btn.isEnabled() != state:
                btn.setEnabled(state)

        _set_enabled(self._t.dro._btn_ref_all, can_mdi)

        for i, axis in enumerate(("X", "Y", "Z")):
            if axis in self._t.dro._dro_ref_btn:
                btn = self._t.dro._dro_ref_btn[axis]
                is_homed = i < len(homed) and homed[i]
                btn_enabled = can_mdi
                if axis in ("X", "Y") and enable_g53 and is_homed and not z_safe:
                    btn_enabled = False
                _set_enabled(btn, btn_enabled)

        if hasattr(self._t, "_btn_find_m6") and self._t._btn_find_m6:
            _set_enabled(self._t._btn_find_m6, is_idle)
        if hasattr(self._t, "_btn_run_from_line") and self._t._btn_run_from_line:
            _set_enabled(self._t._btn_run_from_line, is_idle)

    @Slot()
    def _toggle_sb_internal(self):
        """Toggle Single Block mode."""
        self._t.is_single_block = not self._t.is_single_block
        self._t._status(f"Single Block: {'AN' if self._t.is_single_block else 'AUS'}")

    @Slot()
    def _toggle_m1_internal(self):
        """Toggle M1 (Optional Stop) mode."""
        curr = bool(self._t.poller.stat.optional_stop)
        self._t.cmd.set_optional_stop(not curr)
        self._t._status(f"M1 Optional Stop: {'AN' if not curr else 'AUS'}")

    @Slot()
    def _on_opt_clicked(self):
        """Toggle expand/collapse animation for OPT panel."""
        if not hasattr(self, "_opt_panel") or not self._opt_panel:
            return

        is_expanded = self._opt_panel.maximumHeight() > 0

        if is_expanded:
            self._opt_anim.setStartValue(175)
            self._opt_anim.setEndValue(0)
        else:
            self._opt_anim.setStartValue(0)
            self._opt_anim.setEndValue(175)  # Height for 3 buttons + spacing + margins

        self._opt_anim.start()
