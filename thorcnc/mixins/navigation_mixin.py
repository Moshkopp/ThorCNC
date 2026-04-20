import os
import linuxcnc
from PySide6.QtCore import Qt, QPoint, QPropertyAnimation, QEvent
from PySide6.QtWidgets import QPushButton, QFrame, QVBoxLayout, QWidget, QLabel, QApplication

from ..i18n import _t

class NavigationMixin:
    """Mixin for ThorCNC Flyout Navigation and Sidebar logic."""
    
    def _init_navigation(self):
        """Initializes navigation state variables."""
        self._flyout_panels = {}
        self._flyout_item_buttons = {}
        self._current_flyout = None
        self._flyout_anim = None

    def _handle_navigation_event(self, event):
        """Processes events for light-dismiss and sidebar logic."""
        import shiboken6
        if not shiboken6.isValid(self) or not shiboken6.isValid(self.ui):
            return False
            
        if event.type() == QEvent.MouseButtonPress:
            if self._current_flyout:
                panel = self._flyout_panels.get(self._current_flyout)
                if panel and panel.isVisible():
                    if hasattr(event, "globalPosition"):
                        global_pt = event.globalPosition().toPoint()
                    else:
                        global_pt = event.globalPos()

                    # 1. IMPORTANT: Check if we clicked ANY flyout toggle button.
                    # If so, let the button's clicked signal handle it to avoid race conditions.
                    child = QApplication.instance().widgetAt(global_pt)
                    if isinstance(child, QPushButton):
                        if child.property("is_flyout_toggle") or child.objectName().startswith("btn_flyout_toggle"):
                            # print(f"[ThorCNC] Click on toggle button {child.objectName()}, ignoring in filter")
                            return False

                    # 2. Check if click is inside the current panel
                    local_pt = panel.mapFromGlobal(global_pt)
                    if not panel.rect().contains(local_pt):
                        # Also check Start-At-Line mini flyout
                        if hasattr(self, "_line_queue_panel") and self._line_queue_panel.isVisible():
                            lq_local_pt = self._line_queue_panel.mapFromGlobal(global_pt)
                            if self._line_queue_panel.rect().contains(lq_local_pt):
                                return False

                        self._close_flyout(self._current_flyout)
        return False

    def _toggle_flyout(self, name, button):
        panel = self._flyout_panels.get(name)
        if not panel: 
            print(f"[ThorCNC] Navigation Error: Flyout panel '{name}' not found! (Keys: {list(self._flyout_panels.keys())})")
            return
        
        # 1. Close current if another one is open (IMMEDIATE)
        if self._current_flyout and self._current_flyout != name:
            print(f"[ThorCNC] Switching flyout: {self._current_flyout} -> {name}")
            self._close_flyout(self._current_flyout, immediate=True)
            
        is_opening = not panel.isVisible() or panel.width() == 0
        print(f"[ThorCNC] Toggle Flyout: {name} (Opening: {is_opening})")
        
        if is_opening:
            self._update_flyout_highlights()
            
            global_pos = button.mapToGlobal(QPoint(button.width(), 0))
            panel.move(global_pos.x(), global_pos.y())
            
            num_items = panel.layout().count()
            panel_height = (num_items * 60) + ((num_items - 1) * 5) + 10
            panel.setFixedHeight(panel_height)
            
            panel.show()
            panel.raise_()
            
            self._flyout_anim = QPropertyAnimation(panel, b"maximumWidth")
            self._flyout_anim.setDuration(300)
            self._flyout_anim.setStartValue(0)
            self._flyout_anim.setEndValue(250)
            self._flyout_anim.start()
            self._current_flyout = name
        else:
            self._close_flyout(name)

    def _close_flyout(self, name, immediate=False):
        panel = self._flyout_panels.get(name)
        if not panel: return
        
        if immediate:
            panel.setMaximumWidth(0)
            panel.hide()
            self._current_flyout = None
            return

        self._flyout_anim = QPropertyAnimation(panel, b"maximumWidth")
        self._flyout_anim.setDuration(250)
        self._flyout_anim.setStartValue(panel.width())
        self._flyout_anim.setEndValue(0)
        self._flyout_anim.finished.connect(lambda p=panel: p.hide())
        self._flyout_anim.start()
        self._current_flyout = None

    def _handle_flyout_action(self, flyout_name, action_text):
        """Routes actions from flyout buttons to machine commands."""
        print(f"[ThorCNC] Flyout Action: {flyout_name} -> {action_text}")
        
        if flyout_name == "MODE":
            mode_map = {"MANUAL": linuxcnc.MODE_MANUAL, "AUTO": linuxcnc.MODE_AUTO, "MDI": linuxcnc.MODE_MDI}
            if m := mode_map.get(action_text):
                self.cmd.mode(m)
                self.cmd.wait_complete()
                self._current_mode = m
                
        elif flyout_name == "SHORTS":
            if action_text == "GO TO HOME":
                # Check if all joints are homed
                s = self.poller.stat
                all_homed = all(s.homed[i] for i in range(s.joints))
                
                if all_homed:
                    # Already homed -> Go to machine zero (G53)
                    if hasattr(self, "_run_mdi_command"):
                        self._run_mdi_command("G53 G0 Z0") 
                        # Small wait to ensure the first command is processed
                        self.cmd.wait_complete()
                        self._run_mdi_command("G53 G0 X0 Y0")
                        self._status(_t("Fahre zu Maschinen-Nullpunkt (G53 X0 Y0 Z0)"))
                else:
                    # Not homed -> Start homing sequence
                    if hasattr(self, "_home_all"):
                        self._home_all()
                    else:
                        # Fallback to internal MDI homing if _home_all is missing
                        self.cmd.home(-1)
                
            elif action_text == "GOTO ZERO XY":
                if hasattr(self, "_run_mdi_command"):
                    self._run_mdi_command("O<goto_zero_xy> call")
                    self._status(_t("Fahre zu WCS X0 Y0 (via NGC)"))
                
        elif flyout_name == "OPT":
            if action_text == "COOLANT":
                if hasattr(self, "_toggle_coolant_internal"): self._toggle_coolant_internal()
            elif action_text == "M1 STOP":
                curr = getattr(self.poller.stat, "optional_stop", False)
                self.cmd.set_optional_stop(not curr)
            elif action_text == "SINGLE BLOCK":
                if hasattr(self, "is_single_block"):
                    self.is_single_block = not self.is_single_block
            elif action_text == "BLOCK DELETE":
                curr = getattr(self.poller.stat, "block_delete", False)
                self.cmd.set_block_delete(not curr)
        
        self._close_flyout(flyout_name)
        self._update_flyout_highlights()

    def _toggle_line_queue_flyout(self):
        """Toggles the mini-flyout for line selection."""
        if self._line_queue_panel.isVisible():
            self._line_queue_panel.hide()
            if self._queued_start_line is None:
                self._update_run_from_line_visual(False)
        else:
            if self.gcode_view:
                cursor = self.gcode_view.textCursor()
                self._line_input.setValue(cursor.blockNumber() + 1)
            
            pos = self._btn_run_from_line.mapToGlobal(QPoint(0, self._btn_run_from_line.height()))
            self._line_queue_panel.move(pos)
            self._line_queue_panel.show()
            self._line_queue_panel.raise_()

    def _confirm_line_queue(self):
        """Confirmed the line from the mini-flyout."""
        line_num = self._line_input.value()
        self._queued_start_line = line_num
        self._line_queue_panel.hide()
        self._status(f"START AB ZEILE {line_num} VORGEMERKT. Drücke CYCLE START!")
        self._update_run_from_line_visual(True)

    def _clear_line_queue(self):
        """Clears the queued line and resets the UI."""
        self._queued_start_line = None
        self._line_queue_panel.hide()
        self._status(_t("Start-Vormerkung aufgehoben"))
        self._update_run_from_line_visual(False)

    def _update_run_from_line_visual(self, active):
        if hasattr(self, "_btn_run_from_line") and self._btn_run_from_line:
            self._btn_run_from_line.setProperty("active", active)
            self._btn_run_from_line.style().unpolish(self._btn_run_from_line)
            self._btn_run_from_line.style().polish(self._btn_run_from_line)
            self._btn_run_from_line.update()

    def _run_from_selected_line(self):
        self._toggle_line_queue_flyout()

    def _update_flyout_highlights(self):
        if not hasattr(self, "_flyout_item_buttons"): return
        s = self.poller.stat
        
        # Helper to update button visual
        def set_btn_active(key, active):
            if b := self._flyout_item_buttons.get(key):
                if b.property("active") != active:
                    b.setProperty("active", active)
                    b.style().unpolish(b); b.style().polish(b)
                    b.update()

        set_btn_active("OPT_COOLANT", getattr(s, "flood", 0) > 0)
        set_btn_active("OPT_M1 STOP", getattr(s, "optional_stop", False))
        set_btn_active("OPT_BLOCK DELETE", getattr(s, "block_delete", False))
        set_btn_active("OPT_SINGLE BLOCK", getattr(self, "is_single_block", False))

        _MODES = {linuxcnc.MODE_MANUAL: "MANUAL", linuxcnc.MODE_AUTO: "AUTO", linuxcnc.MODE_MDI: "MDI"}
        current_txt = _MODES.get(self._current_mode, "")
        for m_txt in ("MANUAL", "AUTO", "MDI"):
            set_btn_active(f"MODE_{m_txt}", m_txt == current_txt)

    def _apply_theme(self, name: str):
        """Switches the UI theme and updates icons."""
        valid_themes = ["dark", "light"]
        if name not in valid_themes: return
        
        from PySide6.QtWidgets import QApplication
        from ..main import load_theme
        load_theme(QApplication.instance(), name)
        self.settings.set("theme", name)
        self.settings.save()
        self._update_nav_icons()

    def _update_nav_icons(self):
        """Updates navigation icons for the sidebar based on theme."""
        theme = self.settings.get("theme", "dark")
        icon_path = os.path.join(os.path.dirname(__file__), "..", "images", f"icons_{theme}")
        
        mapping = {
            "btn_nav_main": "home.svg",
            "btn_nav_file": "file.svg",
            "btn_nav_probing": "probe.svg",
            "btn_nav_tools": "tool.svg",
            "btn_nav_settings": "settings.svg",
            "btn_nav_html": "web.svg"
        }
        
        from PySide6.QtGui import QIcon
        for btn_name, icon_file in mapping.items():
            if btn := self.ui.findChild(QPushButton, btn_name):
                full_path = os.path.join(icon_path, icon_file)
                if os.path.exists(full_path):
                    btn.setIcon(QIcon(full_path))
