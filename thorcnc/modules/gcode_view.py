"""GCode View Management Module.

Handles:
- GCode editing and saving
- M6 (tool change) navigation
- Active GCode/MCode display updates
"""

import os
import re
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (QLabel, QLineEdit, QPushButton, QWidget,
                                QVBoxLayout, QHBoxLayout, QFrame, QSpinBox,
                                QStackedWidget)

from .base import ThorModule
from ..widgets.gcode_view import GCodeView
from ..i18n import _t


class GCodeViewModule(ThorModule):
    """Manages G-Code viewer editing, M6 navigation, code display, and highlight settings."""

    def setup(self):
        self._setup_highlight_settings()

    def connect_signals(self):
        pass

    # ── Widget Setup (called from _replace_custom_widgets) ────────────────────

    def setup_widget(self):
        """Create GCode+MDI stacked widget and replace the UI placeholder."""
        t = self._t
        ui = t.ui

        old_gcode = ui.findChild(QWidget, "gcodeEditor")
        parent_gc = old_gcode.parent() if old_gcode else None

        for btn_name in ["btn_find_m6", "btn_main_zoom_in", "btn_main_zoom_out"]:
            if btn := ui.findChild(QPushButton, btn_name):
                if btn.parent() and btn.parent().layout():
                    btn.parent().layout().removeWidget(btn)
                btn.deleteLater()

        t._gcode_mdi_stack = QStackedWidget()
        t._gcode_mdi_stack.setObjectName("gcodeEditor")

        # Page 0: GCode editor
        gcode_container = QWidget()
        gcode_lay = QVBoxLayout(gcode_container)
        gcode_lay.setContentsMargins(0, 0, 0, 0)
        gcode_lay.setSpacing(0)

        t._gcode_header = QFrame()
        t._gcode_header.setObjectName("gcodeHeader")
        h_lay = QHBoxLayout(t._gcode_header)
        h_lay.setContentsMargins(4, 4, 4, 4)
        h_lay.setSpacing(6)

        t._btn_find_m6 = QPushButton(_t("FIND M6"))
        t._btn_find_m6.setObjectName("btn_find_m6")
        t._btn_find_m6.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        t._btn_find_m6.clicked.connect(self._find_next_m6)
        h_lay.addWidget(t._btn_find_m6)

        t._btn_run_from_line = QPushButton(_t("START AT LINE"))
        t._btn_run_from_line.setObjectName("btn_run_from_line")
        t._btn_run_from_line.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        t._btn_run_from_line.clicked.connect(t.navigation.toggle_line_queue_flyout)
        h_lay.addWidget(t._btn_run_from_line)

        # Line queue flyout panel
        t._line_queue_panel = QFrame(ui, Qt.WindowType.FramelessWindowHint | Qt.WindowType.ToolTip)
        t._line_queue_panel.setObjectName("line_queue_panel")
        t._line_queue_panel.setFixedWidth(220)
        t._line_queue_panel.setFixedHeight(170)
        t._line_queue_panel.hide()
        lq_lay = QVBoxLayout(t._line_queue_panel)
        lq_lay.setContentsMargins(10, 10, 10, 10)
        lq_lay.setSpacing(8)
        lq_title = QLabel(_t("STARTZEILE WÄHLEN:"))
        lq_title.setStyleSheet("font-weight: bold; color: #3a7abf;")
        lq_lay.addWidget(lq_title)
        t._line_input = QSpinBox()
        t._line_input.setRange(1, 999999)
        t._line_input.setFixedHeight(40)
        t._line_input.setStyleSheet("font-size: 14pt; font-weight: bold;")
        lq_lay.addWidget(t._line_input)
        lq_ok = QPushButton(_t("SET QUEUE"))
        lq_ok.setFixedHeight(40)
        lq_ok.setObjectName("btn_flyout_item")
        lq_ok.clicked.connect(t.navigation.confirm_line_queue)
        lq_lay.addWidget(lq_ok)
        lq_clr = QPushButton(_t("CLEAR QUEUE"))
        lq_clr.setFixedHeight(35)
        lq_clr.setObjectName("btn_flyout_item_clear")
        lq_clr.clicked.connect(t.navigation.clear_line_queue)
        lq_lay.addWidget(lq_clr)

        h_lay.addStretch()

        t._btn_edit_gcode = QPushButton(_t("EDIT"))
        t._btn_edit_gcode.setCheckable(True)
        t._btn_edit_gcode.setObjectName("btn_edit_gcode")
        t._btn_edit_gcode.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        t._btn_edit_gcode.clicked.connect(self._on_toggle_gcode_edit)
        h_lay.addWidget(t._btn_edit_gcode)

        t._btn_save_gcode = QPushButton(_t("SAVE"))
        t._btn_save_gcode.setObjectName("btn_save_gcode")
        t._btn_save_gcode.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        t._btn_save_gcode.clicked.connect(self._on_save_gcode)
        t._btn_save_gcode.setEnabled(False)
        h_lay.addWidget(t._btn_save_gcode)

        t._btn_main_zoom_out = QPushButton("-")
        t._btn_main_zoom_out.setObjectName("btn_main_zoom_out")
        t._btn_main_zoom_out.clicked.connect(lambda: t.gcode_view.zoomOut(1))
        h_lay.addWidget(t._btn_main_zoom_out)

        t._btn_main_zoom_in = QPushButton("+")
        t._btn_main_zoom_in.setObjectName("btn_main_zoom_in")
        t._btn_main_zoom_in.clicked.connect(lambda: t.gcode_view.zoomIn(1))
        h_lay.addWidget(t._btn_main_zoom_in)

        gcode_lay.addWidget(t._gcode_header)

        t.gcode_view = GCodeView()
        t.gcode_view.zoom_changed.connect(
            lambda s: (t.settings.set("viewer_gcode_font_size", s), t.settings.save()))
        t.gcode_view.set_font_size(t.settings.get("viewer_gcode_font_size", 30))
        t.gcode_view.document().modificationChanged.connect(self._on_gcode_modification_changed)
        gcode_lay.addWidget(t.gcode_view)
        t._gcode_mdi_stack.addWidget(gcode_container)

        # Page 1: MDI (built by MDIModule)
        t.mdi_mod.setup_widget(t._gcode_mdi_stack)

        # Sidebar GCode/MDI toggle buttons
        t._btn_show_gcode = ui.findChild(QPushButton, "btn_gcode_view")
        t._btn_show_mdi   = ui.findChild(QPushButton, "btn_mdi_view")
        if t._btn_show_gcode:
            t._btn_show_gcode.clicked.connect(lambda: t.mdi_mod._switch_gcode_panel(0))
        if t._btn_show_mdi:
            t._btn_show_mdi.clicked.connect(lambda: t.mdi_mod._switch_gcode_panel(1))

        self._setup_highlight_settings()

        # Replace placeholder
        if parent_gc and parent_gc.layout():
            lay = parent_gc.layout()
            idx = lay.indexOf(old_gcode)
            lay.removeWidget(old_gcode)
            old_gcode.deleteLater()
            lay.insertWidget(idx, t._gcode_mdi_stack)

        for entry in t.settings.get("mdi_history", []):
            t._mdi_history_widget.addItem(entry)

        t.mdi_mod._switch_gcode_panel(0)

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
            self._t._status(_t("G-CODE EDIT MODE ENABLED"))
            self._on_gcode_modification_changed(gcode_view.document().isModified())
        else:
            self._t._status(_t("G-CODE EDIT MODE DISABLED"))
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
            self._t._status(_t("SAVE FAILED: NO FILE LOADED"))
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
            self._t._status(_t("Kein M6 im Programm gefunden."))

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

    # ── Highlight Settings ────────────────────────────────────────────────────

    def _setup_highlight_settings(self):
        s = self._t.settings
        for prefix, le_name, btn_name in [
            ("hlight_gc_imp",  "le_gc_important",  "btn_gc_color_important"),
            ("hlight_gc_warn", "le_gc_warning",     "btn_gc_color_warning"),
            ("hlight_mc",      "le_mc_highlights",  "btn_mc_color"),
        ]:
            le  = self._t.ui.findChild(QLineEdit,  le_name)
            btn = self._t.ui.findChild(QPushButton, btn_name)

            if le:
                le.setText(s.get(f"{prefix}_list", ""))
                le.textChanged.connect(
                    lambda text, p=prefix: self._on_hlight_text_changed(p, text))

            if btn:
                color = s.get(f"{prefix}_color", "#ffffff")
                self._update_color_btn_style(btn, color)
                btn.clicked.connect(
                    lambda checked=False, p=prefix, b=btn: self._on_hlight_color_clicked(p, b))

    def _on_hlight_text_changed(self, prefix: str, text: str):
        self._t.settings.set(f"{prefix}_list", text)
        self._t.settings.save()
        self._update_active_codes_display()

    def _on_hlight_color_clicked(self, prefix: str, btn):
        from PySide6.QtWidgets import QColorDialog
        from PySide6.QtGui import QColor

        current = self._t.settings.get(f"{prefix}_color", "#ffffff")
        color = QColorDialog.getColor(QColor(current), self._t.ui, "Farbe wählen")

        if color.isValid():
            hex_color = color.name()
            self._t.settings.set(f"{prefix}_color", hex_color)
            self._t.settings.save()
            self._update_color_btn_style(btn, hex_color)
            self._update_active_codes_display()

    def _update_color_btn_style(self, btn, color: str):
        btn.setStyleSheet(
            f"background-color: {color}; "
            f"color: {'#000000' if self._is_light(color) else '#ffffff'}; "
            f"border: 1px solid #5d6d7e; font-weight: bold;")

    def _is_light(self, hex_color: str) -> bool:
        hex_color = hex_color.lstrip('#')
        if len(hex_color) != 6:
            return True
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        return (r * 0.299 + g * 0.587 + b * 0.114) > 128
