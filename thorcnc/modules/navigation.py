"""Navigation module for ThorCNC — manages flyouts, sidebar, themes, and global navigation events."""

import os
import linuxcnc
from PySide6.QtCore import Qt, QPoint, QPropertyAnimation, QEvent, QEasingCurve
from PySide6.QtWidgets import QPushButton, QFrame, QVBoxLayout, QWidget, QLabel, QApplication

from .base import ThorModule
from ..i18n import _t

class NavigationModule(ThorModule):
    """Manages ThorCNC Flyout Navigation and Sidebar logic."""

    def __init__(self, thorc):
        """Initialize NavigationModule with reference to ThorCNC."""
        super().__init__(thorc)
        self._flyout_panels = {}
        self._flyout_item_buttons = {}
        self._current_flyout = None
        self._flyout_anim = None
        self._close_shorts_on_idle = False

    def setup(self):
        """Setup signal connections after ThorCNC is fully initialized."""
        if self._t.poller:
            self._t.poller.periodic.connect(self._periodic_nav_update)

    def connect_signals(self):
        """Wire nav tab buttons and tab-change sync."""
        from PySide6.QtWidgets import QTabWidget, QButtonGroup
        from PySide6.QtCore import QTimer
        ui = self._t.ui
        tab = ui.findChild(QTabWidget, "tabWidget")
        if not tab:
            return
        self._t.nav_group = QButtonGroup(self._t)
        self._t.nav_group.setExclusive(True)
        nav_names = ["nav_main", "nav_file", "nav_tool", "nav_offsets",
                     "nav_probing", "nav_surface_map", "nav_settings", "nav_status", "nav_quit"]
        for idx, name in enumerate(nav_names):
            b = ui.findChild(QPushButton, name)
            if not b:
                continue
            b.setMinimumHeight(38)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            if name == "nav_quit":
                b.setCheckable(False)
                b.clicked.connect(self._t.ui.close)
            else:
                b.setCheckable(True)
                self._t.nav_group.addButton(b, idx)
                b.clicked.connect(lambda _, i=idx, t=tab: t.setCurrentIndex(i))
        tab.currentChanged.connect(self._sync_nav_buttons)
        QTimer.singleShot(500, lambda: self._sync_nav_buttons(tab.currentIndex()))

    def setup_flyouts(self):
        """Create flyout button groups and overlay panels in the sidebar."""
        t = self._t
        ui = t.ui

        # Remove legacy widgets
        for name in ("combo_machine_mode", "btn_opt", "optExpandPanel"):
            if w := ui.findChild(QWidget, name):
                w.hide()
                if w.parent() and w.parent().layout():
                    w.parent().layout().removeWidget(w)

        t.cmd.set_block_delete(0)
        t.cmd.set_optional_stop(0)

        t.flyout_btn_group = QWidget()
        t.flyout_btn_group.setObjectName("flyout_btn_group")
        group_lay = QVBoxLayout(t.flyout_btn_group)
        group_lay.setContentsMargins(0, 50, 0, 0)
        group_lay.setSpacing(6)

        flyout_configs = [
            ("MODE",   ["MANUAL", "AUTO", "MDI"]),
            ("SHORTS", ["GO TO HOME", "GOTO ZERO XY"]),
            ("OPT",    ["COOLANT", "M1 STOP", "SINGLE BLOCK", "BLOCK DELETE"]),
        ]

        for name, items in flyout_configs:
            btn = QPushButton(name)
            btn.setObjectName(f"btn_flyout_toggle_{name.lower()}")
            btn.setProperty("is_flyout_toggle", True)
            btn.setMinimumHeight(60)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            group_lay.addWidget(btn)

            panel = QFrame(ui.centralwidget)
            panel.setWindowFlags(Qt.WindowType.FramelessWindowHint)
            panel.setObjectName(f"flyout_panel_{name.lower()}")
            panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            panel.stackUnder(ui.leftPanel)
            panel.hide()

            p_lay = QVBoxLayout(panel)
            p_lay.setContentsMargins(5, 5, 5, 5)
            p_lay.setSpacing(5)

            for item_text in items:
                i_btn = QPushButton(_t(item_text))
                i_btn.setObjectName("btn_flyout_item")
                i_btn.setMinimumHeight(60)
                i_btn.setMinimumWidth(180)
                i_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                p_lay.addWidget(i_btn)
                self._flyout_item_buttons[f"{name}_{item_text}"] = i_btn
                i_btn.clicked.connect(
                    lambda checked=False, tt=item_text, nn=name: self.handle_flyout_action(nn, tt))

            p_lay.addStretch()
            self._flyout_panels[name] = panel
            btn.clicked.connect(
                lambda checked=False, n=name, b=btn: self.toggle_flyout(n, b))

        sidebar_lay = ui.leftPanel.layout()
        if sidebar_lay:
            sidebar_lay.insertWidget(9, t.flyout_btn_group)

        t.btn_mode_toggle = ui.findChild(QPushButton, "btn_flyout_toggle_mode")
        t._queued_start_line = None

    def _sync_nav_buttons(self, index: int):
        """Sync nav button checked state and auto-switch LinuxCNC mode."""
        if hasattr(self._t, "nav_group"):
            if b := self._t.nav_group.button(index):
                b.blockSignals(True)
                b.setChecked(True)
                b.blockSignals(False)
        try:
            current_mode = self._t.poller.stat.task_mode
            target_mode = linuxcnc.MODE_AUTO if index in (0, 1) else linuxcnc.MODE_MANUAL
            if current_mode != target_mode and self._t._interp_state == linuxcnc.INTERP_IDLE:
                self._t.cmd.mode(target_mode)
                self._t.cmd.wait_complete()
        except Exception:
            pass

    def handle_event(self, event):
        """Processes events for light-dismiss and sidebar logic."""
        import shiboken6
        if not shiboken6.isValid(self._t) or not shiboken6.isValid(self._t.ui):
            return False

        if event.type() == QEvent.MouseButtonPress:
            if self._current_flyout:
                panel = self._flyout_panels.get(self._current_flyout)
                if panel and panel.isVisible():
                    if hasattr(event, "globalPosition"):
                        global_pt = event.globalPosition().toPoint()
                    else:
                        global_pt = event.globalPos()

                    child = QApplication.instance().widgetAt(global_pt)
                    if isinstance(child, QPushButton):
                        if child.property("is_flyout_toggle") or child.objectName().startswith("btn_flyout_toggle"):
                            return False

                    local_pt = panel.mapFromGlobal(global_pt)
                    if not panel.rect().contains(local_pt):
                        # OPT flyout only closes via its toggle button, not by clicking outside
                        if self._current_flyout == "OPT":
                            return False

                        if hasattr(self._t, "_line_queue_panel") and self._t._line_queue_panel.isVisible():
                            lq_local_pt = self._t._line_queue_panel.mapFromGlobal(global_pt)
                            if self._t._line_queue_panel.rect().contains(lq_local_pt):
                                return False

                        self._close_flyout(self._current_flyout)
        return False

    def toggle_flyout(self, name, button):
        panel = self._flyout_panels.get(name)
        if not panel:
            print(f"[ThorCNC] Navigation Error: Flyout panel '{name}' not found!")
            return

        if self._current_flyout and self._current_flyout != name:
            self._close_flyout(self._current_flyout, immediate=True)

        target_width = 250
        panel.setFixedWidth(target_width)

        sidebar_edge = self._t.ui.leftPanel.width()
        btn_local = self._t.ui.centralwidget.mapFromGlobal(button.mapToGlobal(QPoint(0, 0)))
        target_y = btn_local.y()

        is_opening = not panel.isVisible() or panel.x() < sidebar_edge

        if is_opening:
            self._update_flyout_highlights()

            num_items = panel.layout().count()
            panel_height = (num_items * 60) + ((num_items - 1) * 5) + 10
            panel.setFixedHeight(panel_height)

            panel.show()
            panel.raise_()
            self._t.ui.leftPanel.raise_()

            self._flyout_anim = QPropertyAnimation(panel, b"pos")
            self._flyout_anim.setDuration(350)
            self._flyout_anim.setEasingCurve(QEasingCurve.OutQuart)
            self._flyout_anim.setStartValue(QPoint(sidebar_edge - target_width, target_y))
            self._flyout_anim.setEndValue(QPoint(sidebar_edge + 7, target_y))
            self._flyout_anim.start()
            self._current_flyout = name
        else:
            self._close_flyout(name)

    def _close_flyout(self, name, immediate=False):
        panel = self._flyout_panels.get(name)
        if not panel: return

        sidebar_edge = self._t.ui.leftPanel.width()
        target_width = panel.width()

        if immediate:
            if self._flyout_anim: self._flyout_anim.stop()
            panel.move(sidebar_edge - target_width, panel.y())
            panel.hide()
            self._current_flyout = None
            return

        self._flyout_anim = QPropertyAnimation(panel, b"pos")
        self._flyout_anim.setDuration(250)
        self._flyout_anim.setEasingCurve(QEasingCurve.InQuart)
        self._flyout_anim.setStartValue(panel.pos())
        self._flyout_anim.setEndValue(QPoint(sidebar_edge - target_width, panel.y()))
        self._flyout_anim.finished.connect(lambda p=panel: p.hide())
        self._flyout_anim.start()
        self._current_flyout = None

    def _periodic_nav_update(self):
        """Periodic check for flyout highlights and auto-close logic."""
        if self._current_flyout:
            self._update_flyout_highlights()

            if self._current_flyout == "SHORTS" and self._close_shorts_on_idle:
                if self._t.poller.stat.interp_state == linuxcnc.INTERP_IDLE:
                    self._close_flyout("SHORTS")
                    self._close_shorts_on_idle = False

    def handle_flyout_action(self, flyout_name, action_text):
        """Routes actions from flyout buttons to machine commands."""
        if flyout_name == "MODE":
            mode_map = {"MANUAL": linuxcnc.MODE_MANUAL, "AUTO": linuxcnc.MODE_AUTO, "MDI": linuxcnc.MODE_MDI}
            if m := mode_map.get(action_text):
                self._t.cmd.mode(m)
                self._t.cmd.wait_complete()
                self._t._current_mode = m

        elif flyout_name == "SHORTS":
            if action_text == "GO TO HOME":
                # Go to machine zero (buttons are disabled if not all homed)
                self._t.mdi_mod._send_mdi("G53 G0 Z0")
                self._t.cmd.wait_complete()
                self._t.mdi_mod._send_mdi("G53 G0 X0 Y0")
                self._t._status(_t("Fahre zu Maschinen-Nullpunkt (G53 X0 Y0 Z0)"))

            elif action_text == "GOTO ZERO XY":
                # Go to WCS X0 Y0 via NGC subroutine
                self._t.mdi_mod._send_mdi("O<goto_zero_xy> call")
                self._t._status(_t("Fahre zu WCS X0 Y0 (via NGC)"))

        elif flyout_name == "OPT":
            if action_text == "COOLANT":
                self._t.spindle.toggle_coolant()
            elif action_text == "M1 STOP":
                curr = getattr(self._t.poller.stat, "optional_stop", False)
                self._t.cmd.set_optional_stop(not curr)
            elif action_text == "SINGLE BLOCK":
                if hasattr(self._t, "is_single_block"):
                    self._t.is_single_block = not self._t.is_single_block
            elif action_text == "BLOCK DELETE":
                curr = getattr(self._t.poller.stat, "block_delete", False)
                self._t.cmd.set_block_delete(not curr)

        if flyout_name == "MODE":
            self._close_flyout(flyout_name)
        elif flyout_name == "SHORTS":
            self._close_shorts_on_idle = True
        elif flyout_name == "OPT":
            pass

        self._update_flyout_highlights()

    def toggle_line_queue_flyout(self):
        """Toggles the mini-flyout for line selection."""
        if self._t._line_queue_panel.isVisible():
            self._t._line_queue_panel.hide()
            if self._t._queued_start_line is None:
                self._update_run_from_line_visual(False)
        else:
            if self._t.gcode_view:
                cursor = self._t.gcode_view.textCursor()
                self._t._line_input.setValue(cursor.blockNumber() + 1)

            pos = self._t._btn_run_from_line.mapToGlobal(QPoint(0, self._t._btn_run_from_line.height()))
            self._t._line_queue_panel.move(pos)
            self._t._line_queue_panel.show()
            self._t._line_queue_panel.raise_()

    def confirm_line_queue(self):
        """Confirmed the line from the mini-flyout."""
        line_num = self._t._line_input.value()
        self._t._queued_start_line = line_num
        self._t._line_queue_panel.hide()
        self._t._status(f"START AB ZEILE {line_num} VORGEMERKT. Drücke CYCLE START!")
        self._update_run_from_line_visual(True)

    def clear_line_queue(self):
        """Clears the queued line and resets the UI."""
        self._t._queued_start_line = None
        self._t._line_queue_panel.hide()
        self._t._status(_t("Start-Vormerkung aufgehoben"))
        self._update_run_from_line_visual(False)

    def _update_run_from_line_visual(self, active):
        if hasattr(self._t, "_btn_run_from_line") and self._t._btn_run_from_line:
            self._t._btn_run_from_line.setProperty("active", active)
            self._t._btn_run_from_line.style().unpolish(self._t._btn_run_from_line)
            self._t._btn_run_from_line.style().polish(self._t._btn_run_from_line)
            self._t._btn_run_from_line.update()

    def run_from_selected_line(self):
        self.toggle_line_queue_flyout()

    def _update_flyout_highlights(self):
        s = self._t.poller.stat
        is_idle = s.interp_state == linuxcnc.INTERP_IDLE
        is_on = not s.estop and s.enabled
        can_mdi = is_idle and is_on

        def set_btn_state(key, active=None, enabled=None):
            if b := self._flyout_item_buttons.get(key):
                updated = False
                if active is not None and b.property("active") != active:
                    b.setProperty("active", active)
                    updated = True
                if enabled is not None and b.isEnabled() != enabled:
                    b.setEnabled(enabled)
                    updated = True
                
                if updated:
                    b.style().unpolish(b); b.style().polish(b)
                    b.update()

        # Check if all axes are homed
        all_homed = all(s.homed[i] for i in range(s.joints))

        set_btn_state("OPT_COOLANT", active=(getattr(s, "flood", 0) > 0), enabled=is_on)
        set_btn_state("OPT_M1 STOP", active=getattr(s, "optional_stop", False), enabled=is_on)
        set_btn_state("OPT_BLOCK DELETE", active=getattr(s, "block_delete", False), enabled=is_on)
        set_btn_state("OPT_SINGLE BLOCK", active=getattr(self._t, "is_single_block", False), enabled=is_on)

        # Disable SHORTS buttons if not idle or not all homed
        set_btn_state("SHORTS_GO TO HOME", enabled=(can_mdi and all_homed))
        set_btn_state("SHORTS_GOTO ZERO XY", enabled=(can_mdi and all_homed))

        _MODES = {linuxcnc.MODE_MANUAL: "MANUAL", linuxcnc.MODE_AUTO: "AUTO", linuxcnc.MODE_MDI: "MDI"}
        current_txt = _MODES.get(self._t._current_mode, "")
        for m_txt in ("MANUAL", "AUTO", "MDI"):
            set_btn_state(f"MODE_{m_txt}", active=(m_txt == current_txt))

    def apply_theme(self, name: str):
        """Switches the UI theme and updates icons."""
        valid_themes = ["dark", "light"]
        if name not in valid_themes: return

        from PySide6.QtWidgets import QApplication
        from ..main import load_theme
        load_theme(QApplication.instance(), name)
        self._t.settings.set("theme", name)
        self._t.settings.save()
        self.update_nav_icons()

    def update_nav_icons(self):
        """Updates navigation icons for the sidebar based on theme."""
        theme = self._t.settings.get("theme", "dark")
        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "images", f"icons_{theme}")

        mapping = {
            "btn_nav_main": "home.svg",
            "btn_nav_file": "file.svg",
            "btn_nav_probing": "probe.svg",
            "btn_nav_tools": "tool.svg",
            "btn_nav_settings": "settings.svg"
        }

        from PySide6.QtGui import QIcon
        for btn_name, icon_file in mapping.items():
            if btn := self._t.ui.findChild(QPushButton, btn_name):
                full_path = os.path.join(icon_path, icon_file)
                if os.path.exists(full_path):
                    btn.setIcon(QIcon(full_path))
                

    def update_highlights(self):
        """Update flyout button highlights."""
        self._update_flyout_highlights()
