import os
import linuxcnc
from PySide6.QtWidgets import QColorDialog, QMessageBox
from PySide6.QtGui import QColor
from PySide6.QtCore import QTimer

from ..i18n import _t

class ProbingManager:
    """Manages probe-related state and helper methods for ThorCNC."""



    def __init__(self, thorc):
        """Initialize ProbingManager with reference to ThorCNC."""
        self._t = thorc

        # Probe Warning State
        self._probe_warning_enabled = thorc.settings.get("probe_warning_enabled", True)
        self._probe_warning_pins_str = str(thorc.settings.get("probe_warning_pins", "0"))
        self._probe_warning_color = thorc.settings.get("probe_warning_color", "#8b1a1a")
        self._probe_warning_pins = []
        self._last_probe_warning_state = None
        self._probe_active = False
        self._parse_probe_warning_pins(self._probe_warning_pins_str)

        print(f"[ThorCNC] Probe Warning: {'ENABLED' if self._probe_warning_enabled else 'DISABLED'} on pins {self._probe_warning_pins}")

    def setup(self):
        """Setup probing after initialization. Register deferred calls."""
        # Schedule marker repositioning
        QTimer.singleShot(500, self.reposition_marker)

    def connect_settings_widgets(self, cb_warn, le_pins, btn_color):
        """Connect settings tab widgets (called from _setup_settings_tab)."""
        cb_warn.setChecked(self._probe_warning_enabled)
        cb_warn.toggled.connect(self._on_probe_warning_enabled_changed)
        le_pins.setText(self._probe_warning_pins_str)
        le_pins.textChanged.connect(self._on_probe_warning_pins_changed)
        btn_color.clicked.connect(self._pick_probe_warning_color)
        self._btn_probe_color = btn_color
        self._update_probe_color_button()

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

            if not hasattr(self, "_last_probe_warning_state") or self._last_probe_warning_state != is_active:
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

    def reposition_marker(self):
        """Reposition probe marker (delegates to ProbingTabModule)."""
        if hasattr(self._t, "probing_tab"):
            self._t.probing_tab.update_marker_pos()

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
        if not hasattr(self, "_btn_probe_color"):
            return
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
        initial = QColor(self._probe_warning_color)
        color = QColorDialog.getColor(initial, self._t.ui, _t("Pick Probe Warning Color"))
        if color.isValid():
            self._probe_warning_color = color.name()
            self._t.settings.set("probe_warning_color", self._probe_warning_color)
            self._t.settings.save()
            self._update_probe_color_button()
            self.update_probe_warning(self._t._last_dout if hasattr(self._t, "_last_dout") else [])


