"""Spindle module for ThorCNC — Spindle and Coolant management."""

import os
import re
import linuxcnc
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QPushButton, QLabel, QProgressBar, QMessageBox

from .base import ThorModule
from ..i18n import _t


def _probe_tool_number(thorc) -> int:
    """Tool number considered a touch-probe (must never be spun)."""
    try:
        return int(thorc.settings.get("safety_probe_tool_number", 99))
    except (TypeError, ValueError):
        return 99

class SpindleModule(ThorModule):
    """Manages spindle (CW/CCW/Stop), RPM displays, load bar, and Coolant."""

    def __init__(self, thorc):
        super().__init__(thorc)
        self._is_spindle_running = False
        self._spindle_at_speed = False
        self._last_gui_rpm = 0.0
        self._last_gui_load = 0.0

    def setup(self):
        # Initialize button states
        self._update_spindle_buttons()

    def connect_signals(self):
        p = self._t.poller
        p.spindle_at_speed.connect(self._on_spindle_at_speed)
        p.spindle_speed_actual.connect(self._on_spindle_actual)
        p.spindle_load.connect(self._on_spindle_load)
        p.spindle_speed_cmd.connect(self._on_spindle_speed)
        p.file_loaded.connect(self._on_file_loaded_probe_check)

    @Slot(float)
    def _on_spindle_speed(self, rpm: float):
        """Called when the COMMANDED/TARGET spindle speed changes."""
        self._is_spindle_running = (abs(rpm) > 0.1)
        if lbl := self._t._w(QLabel, "lbl_spindle_soll"):
            lbl.setText(f"CMD: {abs(rpm):.0f} RPM")
        self._t._update_run_buttons()
        self._update_spindle_buttons()

    @Slot(float)
    def _on_spindle_actual(self, rpm: float):
        """Called when the ACTUAL (Feedback) spindle speed changes (from HAL)."""
        if abs(rpm - self._last_gui_rpm) < 5.0 and abs(rpm) > 0.1:
            return
        self._last_gui_rpm = rpm
             
        if lbl := self._t._w(QLabel, "lbl_spindle_ist"):
            lbl.setText(f"{abs(rpm):.0f} RPM")
            
        # Real-time update for Simple View if visible
        # Real-time update for Simple View if visible
        sv = self._t.simple_view_mod.simple_view
        if sv and sv.isVisible():
            sv.set_feed_rpm(None, rpm)

    @Slot(float)
    def _on_spindle_load(self, load: float):
        if abs(load - self._last_gui_load) < 1.0:
            return
        self._last_gui_load = load
            
        if bar := self._t._w(QProgressBar, "spindle_load_bar"):
            val = int(max(0, min(100, load)))
            bar.setValue(val)
            
            if val >= 80:
                state = "critical"
            elif val >= 60:
                state = "warning"
            else:
                state = "normal"
                
            if bar.property("loadState") != state:
                bar.setProperty("loadState", state)
                bar.style().unpolish(bar)
                bar.style().polish(bar)

    @Slot(bool)
    def _on_spindle_at_speed(self, at_speed: bool):
        self._spindle_at_speed = at_speed
        self._update_spindle_buttons()

    def _update_spindle_buttons(self):
        direction = self._t.poller.stat.spindle[0]['direction']  # 1=fwd, -1=rev, 0=stop
        at_speed  = self._spindle_at_speed
        running   = direction != 0

        _base = "QPushButton { border-radius: 4px; font-weight: bold; padding: 4px 8px; "

        fwd_style = ""
        rev_style = ""
        stop_style = ""

        if running and at_speed:
            # Vollflächig grün: Solldrehzahl erreicht
            style = _base + "background-color: #27ae60; color: white; }"
            if direction > 0: # CW
                rev_style = style
            else: # CCW
                fwd_style = style
            # Stop-Button rot, wenn Spindel läuft (aktive Aktion verfügbar)
            stop_style = _base + "background-color: #c0392b; color: white; }"
        elif running:
            # Grüner Rahmen: läuft, aber noch nicht auf Drehzahl
            style = _base + "border: 2px solid #27ae60; color: #27ae60; }"
            if direction > 0: # CW
                rev_style = style
            else: # CCW
                fwd_style = style
            # Stop-Button rot, wenn Spindel läuft
            stop_style = _base + "background-color: #c0392b; color: white; }"
        else:
            # Grau mit Rot-Rahmen, wenn Spindel aus (inaktiv)
            stop_style = _base + "border: 2px solid #c0392b; color: #c0392b; }"

        if b := self._t._w(QPushButton, "btn_spindle_fwd"):
            b.setStyleSheet(fwd_style)
        if b := self._t._w(QPushButton, "btn_spindle_rev"):
            b.setStyleSheet(rev_style)
        if b := self._t._w(QPushButton, "btn_spindle_stop"):
            b.setStyleSheet(stop_style)

    def start_spindle(self, direction):
        """Starts the spindle in the given direction with the current speed."""
        # Safety check: machine must be powered on (not estop)
        if self._t.poller.stat.estop:
            self._t._status(_t("Machine is in estop!"), error=True)
            return

        # Safety: never spin a touch probe (T99 by default)
        probe_t = _probe_tool_number(self._t)
        if self._t.poller.stat.tool_in_spindle == probe_t:
            self._block_spindle_for_probe(probe_t)
            return

        speed = abs(self._t.poller.stat.spindle[0]['speed'])
        if speed < 1:
            speed = 6000
            if self._t.ini:
                try:
                    val = self._t.ini.find("DISPLAY", "DEFAULT_SPINDLE_SPEED")
                    if val:
                        speed = float(val)
                except:
                    pass
        self._t.cmd.mode(linuxcnc.MODE_MANUAL)
        self._t.cmd.spindle(direction, speed)

    def stop_spindle(self):
        # Safety check: machine must be powered on (not estop)
        if self._t.poller.stat.estop:
            self._t._status(_t("Machine is in estop!"), error=True)
            return
        self._t.cmd.spindle(linuxcnc.SPINDLE_OFF)

    def toggle_coolant(self):
        """Toggles Flood Coolant (M8/M9)."""
        curr_stat = self._t.poller.stat.flood
        new_state = 1 if curr_stat == 0 else 0
        
        c = linuxcnc.command()
        
        # If we are in AUTO and running, we MUST use flood()
        # If we are IDLE, we can also try MDI as a fallback
        c.flood(new_state)
        
        # Update UI immediately
        self._t.gcode_view_mod._update_active_codes_display()
        
        state_text = _t("ON") if new_state == 1 else _t("OFF")
        self._t._status("Coolant: " + state_text)

    # ── Probe-Tool Safety ─────────────────────────────────────────────────────

    @Slot(str)
    def _on_file_loaded_probe_check(self, path: str):
        """When a G-code file is loaded, scan once for the probe tool number.
        If found (and not inside a comment), warn the operator with a modal."""
        if not path or not os.path.isfile(path):
            return
        probe_t = _probe_tool_number(self._t)
        try:
            with open(path, "r", errors="ignore") as f:
                content = f.read()
        except OSError:
            return

        pattern = re.compile(r'\bT0*' + str(probe_t) + r'\b', re.IGNORECASE)
        for i, raw in enumerate(content.splitlines(), start=1):
            clean = re.sub(r'\(.*?\)|;.*', '', raw)
            if pattern.search(clean):
                self._warn_probe_in_program(probe_t, i, raw.strip())
                return  # one warning per file is enough

    def _warn_probe_in_program(self, probe_t: int, line_num: int, line_text: str):
        text = _t(
            "The loaded program references the probe tool T{n}:\n\n"
            "Line {ln}:  {txt}\n\n"
            "Make sure the spindle never runs while T{n} is in the spindle.\n"
            "A tool change (M6) to a real cutter must precede any M3/M4."
        ).format(n=probe_t, ln=line_num, txt=line_text)
        QMessageBox.warning(self._t.ui, _t("Probe-Tool in Program"), text)
        self._t._status(
            _t("Probe tool T{n} referenced in program (line {ln})").format(
                n=probe_t, ln=line_num),
            error=True,
        )

    def _block_spindle_for_probe(self, probe_t: int):
        """Modal + status when the user tries to start the spindle manually
        while the probe tool is in the spindle."""
        self._t._status(
            _t("BLOCKED: T{n} (probe) loaded — spindle disabled").format(n=probe_t),
            error=True,
        )
        text = _t(
            "Touch probe T{n} is loaded.\n\n"
            "Manual spindle start is blocked to protect the probe.\n"
            "Unload T{n} first (e.g. M6 T<cutter>)."
        ).format(n=probe_t)
        QMessageBox.critical(self._t.ui, _t("Probe-Tool Safety"), text)

    def sync_buttons(self):
        """Syncs the coolant button highlight with machine status."""
        is_on = not self._t.poller.stat.estop and self._t.poller.stat.enabled
        if not hasattr(self, "_btn_coolant_cached"):
            self._btn_coolant_cached = self._t._w(QPushButton, "btn_opt_coolant")
        btn_coolant = self._btn_coolant_cached
        if btn_coolant:
            flood_active = (self._t.poller.stat.flood > 0)
            if btn_coolant.isChecked() != flood_active:
                btn_coolant.blockSignals(True)
                btn_coolant.setChecked(flood_active)
                btn_coolant.blockSignals(False)
                self._t.gcode_view_mod._update_active_codes_display()
            if btn_coolant.isEnabled() != is_on:
                btn_coolant.setEnabled(is_on)
