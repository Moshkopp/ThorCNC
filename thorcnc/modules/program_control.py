"""Program Control Module.

Handles:
- Machine power/estop state management
- Program run/pause/stop/step logic
- Mode switching (MANUAL/AUTO/MDI)
- Interpreter state tracking and button updates
- Position updates and single block logic
- Program line tracking
"""

import linuxcnc
from PySide6.QtCore import Slot
from PySide6.QtWidgets import QPushButton, QComboBox, QTableWidget, QTabWidget

from .base import ThorModule
from ..i18n import _t


class ProgramControlModule(ThorModule):
    """Manages machine program execution, state transitions, and control buttons."""

    def setup(self):
        pass

    def connect_signals(self):
        p = self._t.poller
        p.estop_changed.connect(self._on_estop)
        p.machine_on_changed.connect(self._on_machine_on)
        p.mode_changed.connect(self._on_mode)
        p.interp_changed.connect(self._on_interp)
        p.position_changed.connect(self._on_position)
        p.program_line.connect(self._on_program_line)

    # ── Estop / Power ─────────────────────────────────────────────────────────

    @Slot(bool)
    def _on_estop(self, active: bool):
        self._t._status(f"ESTOP {'AKTIV' if active else 'ZURÜCKGESETZT'}")
        _base = "border-radius: 6px; font-weight: bold; font-size: 14pt; min-height: 70px;"
        if b := self._t._w(QPushButton, "estop_button"):
            if active:
                b.setStyleSheet(f"QPushButton {{ border: 2px solid #ff4444; color: #cc0000; {_base} }}")
            else:
                b.setStyleSheet(f"QPushButton {{ background-color: #cc0000; color: white; {_base} }}")

        sv = self._t.simple_view_mod.simple_view
        if sv and (b_s := getattr(sv, "btn_estop", None)):
            if active:
                b_s.setStyleSheet(f"QPushButton {{ border: 2px solid #ff4444; color: #cc0000; {_base} }}")
            else:
                b_s.setStyleSheet(f"QPushButton {{ background-color: #cc0000; color: white; {_base} }}")

    @Slot(bool)
    def _on_machine_on(self, on: bool):
        self._t._is_machine_on = on
        _base = "border-radius: 6px; font-weight: bold; font-size: 14pt; min-height: 70px;"
        if b := self._t._w(QPushButton, "power_button"):
            if on:
                b.setStyleSheet(f"QPushButton {{ background-color: #27ae60; color: white; {_base} }}")
            else:
                b.setStyleSheet(f"QPushButton {{ border: 2px solid #27ae60; color: #27ae60; {_base} }}")
        self._update_run_buttons()
        self._t.motion._update_goto_home_style(on and getattr(self._t, "_all_joints_homed", False))

    # ── Mode ──────────────────────────────────────────────────────────────────

    @Slot(int)
    def _on_mode(self, mode: int):
        self._t._current_mode = mode

        for name, m in (("manual_mode_button", linuxcnc.MODE_MANUAL),
                        ("mdi_mode_button",    linuxcnc.MODE_MDI),
                        ("auto_mode_button",   linuxcnc.MODE_AUTO)):
            if b := self._t._w(QPushButton, name):
                b.setChecked(mode == m)

        _MODES = {linuxcnc.MODE_MANUAL: "MANUAL", linuxcnc.MODE_AUTO: "AUTO", linuxcnc.MODE_MDI: "MDI"}
        if hasattr(self._t, "btn_mode_toggle"):
            txt = _MODES.get(mode, "MANUAL")
            self._t.btn_mode_toggle.setText(f"MODE: {txt}")
            self._t.btn_mode_toggle.setProperty("active_mode", txt)
            self._t.btn_mode_toggle.style().unpolish(self._t.btn_mode_toggle)
            self._t.btn_mode_toggle.style().polish(self._t.btn_mode_toggle)

            current_txt = _MODES.get(mode, "")
            for m_txt in ("MANUAL", "AUTO", "MDI"):
                if b := self._t.navigation._flyout_item_buttons.get(f"MODE_{m_txt}"):
                    b.setProperty("active", m_txt == current_txt)
                    b.style().unpolish(b)
                    b.style().polish(b)

        if cb := self._t._w(QComboBox, "combo_machine_mode"):
            _IDX = {linuxcnc.MODE_MANUAL: 0, linuxcnc.MODE_AUTO: 1, linuxcnc.MODE_MDI: 2}
            cb.blockSignals(True)
            cb.setCurrentIndex(_IDX.get(mode, 0))
            cb.blockSignals(False)

        if hasattr(self._t, "_gcode_mdi_stack"):
            if mode == linuxcnc.MODE_MDI:
                if not getattr(self._t, "_silent_mdi", False):
                    self._t.mdi_mod._switch_gcode_panel(1)
            else:
                self._t._silent_mdi = False
                self._t.mdi_mod._switch_gcode_panel(0)

        self._t.motion._update_goto_home_style(
            self._t._is_machine_on and getattr(self._t, "_all_joints_homed", False))

    # ── Interpreter ───────────────────────────────────────────────────────────

    @Slot(int)
    def _on_interp(self, state: int):
        self._t._interp_state = state
        running = state in (linuxcnc.INTERP_READING, linuxcnc.INTERP_WAITING)
        paused  = state == linuxcnc.INTERP_PAUSED

        if b := self._t._w(QPushButton, "stop_button"):
            b.setEnabled(running or paused)
        if b := self._t._w(QPushButton, "btn_pause_mdi"):
            b.setEnabled(running)
        if b := self._t._w(QPushButton, "nav_quit"):
            b.setEnabled(not running and not paused)

        idle = state == linuxcnc.INTERP_IDLE
        if hasattr(self._t, "_btn_edit_gcode") and self._t._btn_edit_gcode:
            self._t._btn_edit_gcode.setEnabled(idle)
            if self._t.gcode_view:
                self._t.gcode_view.setReadOnly(
                    not idle or not self._t._btn_edit_gcode.isChecked())

        if hasattr(self._t, "_btn_save_gcode") and self._t._btn_save_gcode:
            is_edit = self._t._btn_edit_gcode.isChecked() if hasattr(self._t, "_btn_edit_gcode") else False
            is_modified = self._t.gcode_view.document().isModified() if self._t.gcode_view else False
            self._t._btn_save_gcode.setEnabled(idle and is_edit and is_modified)

        self._update_tab_locks(running, paused)
        self._update_run_buttons()

    def _update_tab_locks(self, running: bool, paused: bool):
        locked = running or paused

        # Fully disabled nav buttons while locked
        for nav_name in ("nav_file", "nav_probing", "nav_surface_map"):
            if b := self._t._w(QPushButton, nav_name):
                b.setEnabled(not locked)

        # Tool table — disable all action buttons, make cells non-editable
        for btn_name in ("btn_add_tool", "btn_delete_tool", "btn_reload_tools", "btn_save_tools"):
            if b := self._t._w(QPushButton, btn_name):
                b.setEnabled(not locked)
        if tw := self._t._w(QTableWidget, "toolTable"):
            tw.setEditTriggers(
                QTableWidget.EditTrigger.NoEditTriggers if locked
                else QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.EditKeyPressed
            )

        # Offsets — disable WCS clear buttons (cell widgets need manual style refresh)
        for btn in self._t.ui.findChildren(QPushButton, "wcs_clear_btn"):
            btn.setEnabled(not locked)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        # Jog buttons
        for name in ("x_plus_jogbutton_3", "x_minus_jogbutton_3",
                     "y_plus_jogbutton_3", "y_minus_jogbutton_3",
                     "z_plus_jogbutton_3", "z_minus_jogbutton_3"):
            if b := self._t._w(QPushButton, name):
                b.setEnabled(not locked)

        # Jog increment + speed
        for name in ("btn_jog_cont", "btn_jog_1_0", "btn_jog_0_1", "btn_jog_0_01"):
            if b := self._t._w(QPushButton, name):
                b.setEnabled(not locked)
        from PySide6.QtWidgets import QSlider
        if s := self._t._w(QSlider, "jog_vel_slider"):
            s.setEnabled(not locked)

        # Manual spindle control
        for name in ("btn_spindle_fwd", "btn_spindle_rev", "btn_spindle_stop"):
            if b := self._t._w(QPushButton, name):
                b.setEnabled(not locked)

        # MDI view button
        if b := getattr(self._t, "_btn_show_mdi", None):
            b.setEnabled(not locked)

        # Load gcode button
        if b := getattr(self._t, "_btn_load", None):
            b.setEnabled(not locked)

        # Load Tool (M6) button
        if b := self._t._w(QPushButton, "btn_m6_change"):
            b.setEnabled(not locked)

        # DRO zero buttons (per-axis + zero-all)
        for btn in self._t.ui.findChildren(QPushButton, "dro_zero_btn"):
            btn.setEnabled(not locked)
        if b := self._t._w(QPushButton, "dro_zero_all_btn"):
            b.setEnabled(not locked)

        # Mode + Shorts flyout toggle buttons — disable and close if open
        for flyout_name in ("mode", "shorts"):
            if b := self._t._w(QPushButton, f"btn_flyout_toggle_{flyout_name}"):
                b.setEnabled(not locked)
            if locked and hasattr(self._t, "navigation"):
                nav = self._t.navigation
                if nav._current_flyout == flyout_name.upper():
                    nav._close_flyout(flyout_name.upper(), immediate=True)

        # Redirect to Main if on a fully-locked tab when running starts
        if running:
            if tab := self._t._w(QTabWidget, "tabWidget"):
                if tab.currentIndex() in (1, 4, 5):  # file, probing, surface_map
                    tab.setCurrentIndex(0)

    def _update_run_buttons(self):
        btn_run   = self._t._w(QPushButton, "btn_run")
        btn_pause = self._t._w(QPushButton, "btn_pause_mdi")
        btn_stop  = self._t._w(QPushButton, "stop_button")

        sv = self._t.simple_view_mod.simple_view
        s_run   = getattr(sv, "btn_start", None) if sv else None
        s_pause = getattr(sv, "btn_pause", None) if sv else None
        s_stop  = getattr(sv, "btn_stop",  None) if sv else None

        def set_status(w, status):
            if w and w.property("status") != status:
                w.setProperty("status", status)
                w.style().unpolish(w)
                w.style().polish(w)

        if not self._t._is_machine_on:
            for btn in (btn_run, btn_pause, btn_stop, s_run, s_pause, s_stop):
                set_status(btn, "disabled")
            return

        is_running = self._t._interp_state in (linuxcnc.INTERP_READING, linuxcnc.INTERP_WAITING)
        is_paused  = self._t._interp_state == linuxcnc.INTERP_PAUSED
        is_idle    = self._t._interp_state == linuxcnc.INTERP_IDLE

        if is_running:
            set_status(btn_run, "running"); set_status(s_run, "running")
        elif (is_idle or is_paused) and self._t._has_file:
            set_status(btn_run, "ready");   set_status(s_run, "ready")
        else:
            set_status(btn_run, "idle");    set_status(s_run, "idle")

        if is_paused:
            set_status(btn_pause, "paused");  set_status(s_pause, "paused")
        elif is_running:
            set_status(btn_pause, "running"); set_status(s_pause, "running")
        else:
            set_status(btn_pause, "idle");    set_status(s_pause, "idle")

        if is_running or is_paused:
            set_status(btn_stop, "active"); set_status(s_stop, "active")
        else:
            set_status(btn_stop, "idle");   set_status(s_stop, "idle")

        self._t.navigation.update_highlights()

    # ── Position / Program Line ───────────────────────────────────────────────

    @Slot(list)
    def _on_position(self, pos: list):
        significant = False
        if hasattr(self._t, "_last_gui_pos"):
            for i in range(min(3, len(pos))):
                if abs(pos[i] - self._t._last_gui_pos[i]) > 0.005:
                    significant = True
                    break

        if self._t.poller.stat.interp_state == linuxcnc.INTERP_IDLE:
            significant = True

        if not significant:
            return

        self._t._last_gui_pos = list(pos[:3])
        self._t._last_pos = pos
        self._t.dro.refresh()

    @Slot(int)
    def _on_program_line(self, line: int):
        self._t.gcode_view.set_current_line(line)
        self._t.simple_view_mod.set_gcode_line(line)

        if getattr(self._t, "is_single_block", False):
            if self._t._interp_state in (linuxcnc.INTERP_READING, linuxcnc.INTERP_WAITING):
                self._t.cmd.auto(linuxcnc.AUTO_PAUSE)

    # ── Machine Actions ───────────────────────────────────────────────────────

    def toggle_power(self):
        s = self._t.poller.stat
        if s.task_state == linuxcnc.STATE_ESTOP:
            self._t.cmd.state(linuxcnc.STATE_ESTOP_RESET)
        elif s.task_state == linuxcnc.STATE_ON:
            self._t.cmd.state(linuxcnc.STATE_OFF)
        else:
            self._t.cmd.state(linuxcnc.STATE_ON)

    def toggle_estop(self):
        s = self._t.poller.stat
        if s.task_state == linuxcnc.STATE_ESTOP:
            self._t.cmd.state(linuxcnc.STATE_ESTOP_RESET)
        else:
            self._t.cmd.state(linuxcnc.STATE_ESTOP)

    def run_program(self):
        s = self._t.poller.stat
        current_mode = s.task_mode
        interp_state = self._t._interp_state
        is_sb = getattr(self._t, "is_single_block", False)
        q_line = getattr(self._t, "_queued_start_line", None)

        if current_mode != linuxcnc.MODE_AUTO:
            self._t.cmd.mode(linuxcnc.MODE_AUTO)
            self._t.cmd.wait_complete()

        if interp_state == linuxcnc.INTERP_PAUSED:
            if is_sb:
                self._t.cmd.auto(linuxcnc.AUTO_STEP)
            else:
                self._t.cmd.auto(linuxcnc.AUTO_RESUME)
        else:
            if q_line:
                g5x_code = 54
                g43_active = False
                for g in s.gcodes:
                    if 540 <= g <= 590:
                        g5x_code = 54 + (g - 540) // 10
                    if g in (430, 431):
                        g43_active = True

                pre_cmd = f"G{g5x_code}"
                if g43_active:
                    pre_cmd += " G43"

                self._t.cmd.mode(linuxcnc.MODE_MDI)
                self._t.cmd.wait_complete()
                self._t.cmd.mdi(pre_cmd)
                self._t.cmd.wait_complete()

                self._t.cmd.mode(linuxcnc.MODE_AUTO)
                self._t.cmd.wait_complete()

                self._t.cmd.auto(linuxcnc.AUTO_RUN, q_line)

                self._t._queued_start_line = None
                if hasattr(self._t, "_btn_run_from_line"):
                    self._t._btn_run_from_line.setProperty("active", False)
                    self._t._btn_run_from_line.style().unpolish(self._t._btn_run_from_line)
                    self._t._btn_run_from_line.style().polish(self._t._btn_run_from_line)
                    self._t._btn_run_from_line.update()
            elif is_sb:
                self._t.cmd.auto(linuxcnc.AUTO_STEP)
            else:
                line = s.motion_line if (s.motion_line and s.motion_line > 0) else 0
                self._t.cmd.auto(linuxcnc.AUTO_RUN, line)

    def pause_program(self):
        self._t.cmd.auto(linuxcnc.AUTO_PAUSE)

    def stop_program(self):
        self._t.cmd.abort()
        self._t.cmd.wait_complete()
        self._t.cmd.mode(linuxcnc.MODE_MANUAL)
        self._t._status(_t("PROGRAMM ABGEBROCHEN"))
