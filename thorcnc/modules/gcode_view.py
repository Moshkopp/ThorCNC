"""GCode View Management Module.

Handles:
- GCode editing and saving
- M6 (tool change) navigation
- Active GCode/MCode display updates
"""

import os
import re
from PySide6.QtCore import Slot
from PySide6.QtWidgets import QLabel

from .base import ThorModule


class GCodeViewModule(ThorModule):
    """Manages G-Code viewer editing, M6 navigation, and code display."""

    def setup(self):
        """Called after MainWindow initialization to set up references."""
        # These are set by MainWindow after UI is created
        pass

    def connect_signals(self):
        """Connect GCode-related signals from MainWindow."""
        # MainWindow will call these methods directly via self.gcode_view_mod.method_name()
        pass

    # ── GCode View / Edit ─────────────────────────────────────────────────────

    @Slot()
    def _on_toggle_gcode_edit(self):
        """Toggle G-Code edit mode."""
        gcode_view = self._t.gcode_view
        if not gcode_view:
            return

        is_edit = self._t._btn_edit_gcode.isChecked()
        gcode_view.setReadOnly(not is_edit)
        self._t._btn_save_gcode.setEnabled(is_edit)

        # Style update
        self._t._btn_edit_gcode.setProperty("active", is_edit)
        self._t._btn_edit_gcode.style().unpolish(self._t._btn_edit_gcode)
        self._t._btn_edit_gcode.style().polish(self._t._btn_edit_gcode)

        if is_edit:
            self._t._status(self._t._t("G-CODE EDIT MODE ENABLED"))
            self._on_gcode_modification_changed(gcode_view.document().isModified())
        else:
            self._t._status(self._t._t("G-CODE EDIT MODE DISABLED"))
            self._t._btn_save_gcode.setEnabled(False)

    @Slot(bool)
    def _on_gcode_modification_changed(self, modified: bool):
        """Update save button when GCode is modified."""
        gcode_view = self._t.gcode_view
        if not gcode_view:
            return

        is_edit = self._t._btn_edit_gcode.isChecked()
        self._t._btn_save_gcode.setEnabled(is_edit and modified)

        self._t._btn_save_gcode.setProperty("modified", modified)
        self._t._btn_save_gcode.style().unpolish(self._t._btn_save_gcode)
        self._t._btn_save_gcode.style().polish(self._t._btn_save_gcode)

    @Slot()
    def _on_save_gcode(self):
        """Save edited G-Code back to file."""
        gcode_view = self._t.gcode_view
        if not self._t._user_program or not os.path.exists(self._t._user_program):
            self._t._status(self._t._t("SAVE FAILED: NO FILE LOADED"))
            return

        try:
            content = gcode_view.toPlainText()
            with open(self._t._user_program, 'w') as f:
                f.write(content)

            gcode_view.document().setModified(False)
            self._t._status(f"G-CODE SAVED: {os.path.basename(self._t._user_program)}")

            # Re-parse for backplot
            from thorcnc.gcode_parser import parse_file
            tp = parse_file(self._t._user_program)
            self._t._last_toolpath = tp
            self._t.backplot.load_toolpath(tp)

        except Exception as e:
            self._t._status(f"SAVE ERROR: {str(e)}")

    @Slot()
    def _find_next_m6(self):
        """Find next M6 (tool change) in G-Code."""
        gcode_view = self._t.gcode_view
        if not gcode_view:
            return

        text = gcode_view.toPlainText()
        if not text:
            return

        lines = text.split('\n')
        total_lines = len(lines)

        cursor = gcode_view.textCursor()
        start_line = cursor.blockNumber()

        m6_ptrn = re.compile(r'(?<!\()(?:\bM6\b)', re.IGNORECASE)

        # Search from next line to end
        found_idx = -1
        for i in range(start_line + 1, total_lines):
            line_clean = re.sub(r'\(.*?\)|;.*', '', lines[i])
            if m6_ptrn.search(line_clean):
                found_idx = i
                break

        # Cyclic search from start to current line
        if found_idx == -1:
            for i in range(0, start_line + 1):
                line_clean = re.sub(r'\(.*?\)|;.*', '', lines[i])
                if m6_ptrn.search(line_clean):
                    found_idx = i
                    break

        if found_idx != -1:
            gcode_view.set_current_line(found_idx + 1, move_cursor=True)
            self._t._status(f"M6 gefunden in Zeile {found_idx + 1}")
        else:
            self._t._status(self._t._t("Kein M6 im Programm gefunden."))

    # ── GCode/MCode Display ───────────────────────────────────────────────────

    @Slot(tuple)
    def _on_gcodes(self, gcodes: tuple):
        """Handle G-Code active codes update."""
        self._t._current_gcodes = gcodes
        self._update_active_codes_display()
        self._t.dro._sync_wcs_from_gcodes(gcodes)

    @Slot(tuple)
    def _on_mcodes(self, mcodes: tuple):
        """Handle M-Code active codes update."""
        self._t._current_mcodes = mcodes
        self._update_active_codes_display()

    def _update_active_codes_display(self):
        """Update display of active G/M codes with highlighting and realtime coolant status."""
        lbl = self._t._w(QLabel, "active_gcodes_label")
        if not lbl:
            return

        s = self._t.settings
        imp_list = set(s.get("hlight_gc_imp_list", "").replace(",", " ").upper().split())
        warn_list = set(s.get("hlight_gc_warn_list", "").replace(",", " ").upper().split())
        m_list = set(s.get("hlight_mc_list", "").replace(",", " ").upper().split())

        col_imp = s.get("hlight_gc_imp_color", "#ffffff")
        col_warn = s.get("hlight_gc_warn_color", "#ffffff")
        col_m = s.get("hlight_mc_color", "#ffffff")
        col_def = "#cccccc"

        active_g = []
        for g in self._t._current_gcodes[1:]:
            if g == -1:
                continue
            val = g / 10.0
            g_str = f"G{val:g}".upper()

            color = col_def
            weight = "normal"

            if g_str in warn_list:
                color = col_warn
                weight = "bold"
            elif g_str in imp_list:
                color = col_imp
                weight = "bold"

            active_g.append(f'<span style="color: {color}; font-weight: {weight};">{g_str}</span>')

        active_m = []

        # Use real-time status for coolant codes (M7/M8/M9) to bypass interpreter caching
        flood_active = (self._t.poller.stat.flood > 0)
        mist_active = (self._t.poller.stat.mist > 0)

        for m in self._t._current_mcodes[1:]:
            if m == -1:
                continue

            # Skip interpreter's M7/M8/M9 - we insert our own based on real status
            if m in (7, 8, 9):
                continue

            m_str = f"M{m}".upper()
            color = col_def
            weight = "normal"
            if m_str in m_list:
                color = col_m
                weight = "bold"
            active_m.append(f'<span style="color: {color}; font-weight: {weight};">{m_str}</span>')

        # Insert real-time coolant codes
        if flood_active:
            active_m.append(f'<span style="color: {col_m if "M8" in m_list else col_def}; font-weight: bold;">M8</span>')
        else:
            active_m.append(f'<span style="color: {col_def};">M9</span>')

        if mist_active:
            active_m.append(f'<span style="color: {col_m if "M7" in m_list else col_def}; font-weight: bold;">M7</span>')

        all_codes = "<br>".join(active_g + active_m)
        lbl.setText(f'<html><body>{all_codes}</body></html>')
