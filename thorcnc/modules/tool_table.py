"""Tool Table Module for ThorCNC.

Handles:
- Tool table UI (QTableWidget)
- Tool table file I/O (.tbl parsing)
- Tool change requests (HAL + MDI)
- Tool geometry synchronization (backplot)
"""

import os
import re
import linuxcnc
from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (QTableWidget, QTableWidgetItem, QPushButton, QMenu, QColorDialog)
from PySide6.QtGui import QColor

from .base import ThorModule
from ..i18n import _t
from ..widgets.m6_dialog import M6Dialog
from ..widgets.tool_dialog import ToolSelectionDialog


class NumericTableWidgetItem(QTableWidgetItem):
    """Table item that sorts numerically instead of lexicographically."""
    def __lt__(self, other):
        try:
            a = float(self.text()) if self.text().strip() else 0.0
            b = float(other.text()) if other.text().strip() else 0.0
            return a < b
        except (ValueError, TypeError):
            return self.text() < other.text()


class ToolTableModule(ThorModule):
    """Tool table management and tool change handling."""

    def setup(self):
        """Initialize tool table UI."""
        self._setup_tool_table()

    def connect_signals(self):
        """Wire tool table signals."""
        # Table item changes (for auto-description from diameter)
        if self._widget:
            self._widget.itemChanged.connect(self._on_tool_item_changed)

        # Poller signals: tool change
        if self._t.poller:
            self._t.poller.tool_in_spindle.connect(self._on_tool)
            self._t.poller.tool_offset_changed.connect(self._on_tool_offset_changed)
            self._t.poller.tool_change_request.connect(self._on_tool_change_request)

        # MDI M6 button
        if b := self._t._w(QPushButton, "btn_m6_change"):
            b.clicked.connect(self._send_m6)

    def _setup_tool_table(self):
        """Build tool table UI and initialize from .tbl file."""
        self._widget = self._t._w(QTableWidget, "toolTable")
        self._btn_add = self._t._w(QPushButton, "btn_add_tool")
        self._btn_delete = self._t._w(QPushButton, "btn_delete_tool")
        self._btn_reload = self._t._w(QPushButton, "btn_reload_tools")
        self._btn_save = self._t._w(QPushButton, "btn_save_tools")

        if not self._widget:
            return

        self._widget.verticalHeader().setVisible(False)
        self._widget.setSortingEnabled(True)

        # Determine tool table path from INI
        self._tbl_path = None
        if self._t.ini and self._t.ini_path:
            tbl_name = self._t.ini.find("EMCIO", "TOOL_TABLE")
            if tbl_name:
                if not os.path.isabs(tbl_name):
                    self._tbl_path = os.path.abspath(
                        os.path.join(os.path.dirname(self._t.ini_path), tbl_name))
                else:
                    self._tbl_path = tbl_name


        # Button connections (within setup, not in connect_signals)
        if self._btn_add:
            self._btn_add.clicked.connect(self._add_tool)
        if self._btn_delete:
            self._btn_delete.clicked.connect(self._delete_tool)
        if self._btn_reload:
            self._btn_reload.clicked.connect(self._load_tool_table)
        if self._btn_save:
            self._btn_save.clicked.connect(self._save_tool_table)

        self._widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self._widget.customContextMenuRequested.connect(self._show_tool_table_context_menu)

        # Initial load
        self._load_tool_table()

        # Restore column widths from settings
        tt_state = self._t.settings.get("tool_table_state")
        if tt_state:
            from PySide6.QtCore import QByteArray
            self._widget.horizontalHeader().restoreState(
                QByteArray.fromHex(tt_state.encode()))

    def _load_tool_table(self):
        """Load tool table from .tbl file."""
        if not self._tbl_path or not os.path.exists(self._tbl_path):
            return

        self._widget.setSortingEnabled(False)
        self._widget.setRowCount(0)

        # Set column headers
        self._widget.setColumnCount(5)
        self._widget.setHorizontalHeaderLabels([
            _t("Tool #"),
            _t("Pocket"),
            _t("Diameter"),
            _t("Length"),
            _t("Comment")
        ])
        try:
            with open(self._tbl_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith(";"):
                        continue

                    parts = line.split(";", 1)
                    data = parts[0].strip()
                    comment = parts[1].strip() if len(parts) > 1 else ""

                    t = re.search(r'T(\d+)', data)
                    p = re.search(r'P(\d+)', data)
                    d = re.search(r'D([+-]?\d*\.\d+|\d+)', data)
                    z = re.search(r'Z([+-]?\d*\.\d+|\d+)', data)

                    dia_str = d.group(1) if d else ""
                    if dia_str.startswith("+"):
                        dia_str = dia_str[1:]

                    row = self._widget.rowCount()
                    self._widget.insertRow(row)

                    self._widget.setItem(row, 0, NumericTableWidgetItem(t.group(1) if t else ""))
                    self._widget.setItem(row, 1, NumericTableWidgetItem(p.group(1) if p else ""))
                    self._widget.setItem(row, 2, NumericTableWidgetItem(dia_str))
                    self._widget.setItem(row, 3, NumericTableWidgetItem(z.group(1) if z else ""))
                    self._widget.setItem(row, 4, QTableWidgetItem(comment))

            self._widget.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        except Exception as e:
            self._t._status(_t("Error loading tool table: ") + str(e), error=True)
        finally:
            self._widget.setSortingEnabled(True)

    def _delete_tool(self):
        """Delete selected tool rows."""
        if not self._widget:
            return
        rows = set()
        for item in self._widget.selectedItems():
            rows.add(item.row())

        if not rows and self._widget.currentRow() >= 0:
            rows.add(self._widget.currentRow())

        if not rows:
            return

        self._widget.setSortingEnabled(False)
        for row in sorted(list(rows), reverse=True):
            self._widget.removeRow(row)
        self._widget.setSortingEnabled(True)

    def _show_tool_table_context_menu(self, pos):
        """Show context menu for tool table."""
        menu = QMenu(self._widget)
        delete_action = menu.addAction(_t("- Delete Selected"))
        delete_action.triggered.connect(self._delete_tool)
        menu.exec(self._widget.mapToGlobal(pos))

    def _add_tool(self):
        """Add blank tool row with next available tool number."""
        if not self._widget:
            return

        # Find next available tool number
        used_numbers = set()
        for r in range(self._widget.rowCount()):
            t_item = self._widget.item(r, 0)
            if t_item and t_item.text().strip():
                try:
                    used_numbers.add(int(t_item.text().strip()))
                except ValueError:
                    pass

        next_tool = 1
        while next_tool in used_numbers:
            next_tool += 1

        self._widget.setSortingEnabled(False)
        row = self._widget.rowCount()
        self._widget.insertRow(row)
        self._widget.setItem(row, 0, NumericTableWidgetItem(str(next_tool)))
        self._widget.setItem(row, 1, NumericTableWidgetItem(str(next_tool)))  # Pocket = Tool-Nr
        dia_item = QTableWidgetItem("")
        self._widget.setItem(row, 2, dia_item)
        for c in [3, 4]:
            self._widget.setItem(row, c, QTableWidgetItem(""))

        # Focus on diameter field (keep sorting off to prevent data loss)
        self._widget.setCurrentItem(dia_item)
        QTimer.singleShot(10, lambda: self._widget.editItem(dia_item))

    def _save_tool_table(self):
        """Save tool table to .tbl file and reload in LinuxCNC."""
        if not self._tbl_path or not self._widget:
            return

        # Re-enable sorting before save (was disabled during add_tool)
        if not self._widget.isSortingEnabled():
            self._widget.setSortingEnabled(True)

        lines = []
        for row in range(self._widget.rowCount()):
            t = self._widget.item(row, 0)
            p = self._widget.item(row, 1)
            d = self._widget.item(row, 2)
            z = self._widget.item(row, 3)
            c = self._widget.item(row, 4)

            ts = t.text().strip() if t and t.text().strip() else ""
            ps = p.text().strip() if p and p.text().strip() else ""
            ds = d.text().strip().replace(",", ".") if d and d.text().strip() else ""
            zs = z.text().strip().replace(",", ".") if z and z.text().strip() else ""
            cs = c.text().strip() if c and c.text().strip() else ""

            if not ts:
                continue  # T is required

            parts = [f"T{ts}"]
            # Pocket (P) is optional - use tool number as default if empty (non-ATC systems)
            pocket = ps if ps else ts
            parts.append(f"P{pocket}")
            if ds:
                parts.append(f"D{ds}")
            if zs:
                parts.append(f"Z{zs}")

            line = " ".join(parts)
            if cs:
                line += f" ;{cs}"
            lines.append(line)

        try:
            with open(self._tbl_path, "w", encoding="utf-8", errors="ignore") as f:
                f.write("\n".join(lines) + "\n")
            self._t.cmd.load_tool_table()
            self._t._status(_t("Tool table saved and reloaded!"))
        except Exception as e:
            self._t._status(_t("Error saving tool table: ") + str(e), error=True)

    def _on_tool(self, tool: int):
        """Update tool display and geometry when tool changes."""
        if tool == 0:
            return  # Tool 0 = unknown

        # Update status bar label
        from PySide6.QtWidgets import QLabel
        if lbl := self._t.status_bar.findChild(QLabel, "label_tool_nr"):
            lbl.setText(f"T{tool}")

        # Update MDI M6 entry
        if entry := self._t._w(QLabel, "mdi_m6_entry"):
            if not entry.hasFocus():
                entry.setText(str(tool))

        # Reload tool table (in case tool.tbl changed)
        self._load_tool_table()

        # Read tool geometry from reloaded widget
        dia, length, comment = "0.000", "0.000", "-"
        if self._widget:
            for r in range(self._widget.rowCount()):
                t_item = self._widget.item(r, 0)
                if t_item and t_item.text().strip() == str(tool):
                    d_item = self._widget.item(r, 2)
                    len_item = self._widget.item(r, 3)
                    c_item = self._widget.item(r, 4)
                    if d_item:
                        dia = d_item.text()
                    if len_item:
                        length = len_item.text()
                    if c_item:
                        comment = c_item.text()
                    break

        def _fmt3(val: str) -> str:
            try:
                return f"{float(val):.3f}"
            except ValueError:
                return val

        # Update main status bar labels
        from PySide6.QtWidgets import QLabel
        if dia_lbl := self._t._w(QLabel, "tool_dia_label"):
            dia_lbl.setText(_fmt3(dia))
        if len_lbl := self._t._w(QLabel, "tool_len_label"):
            len_lbl.setText(_fmt3(length))
        if c_lbl := self._t._w(QLabel, "tool_comment_label"):
            c_lbl.setText(comment)

        # Update probe tab labels
        if nr_lbl := self._t._w(QLabel, "probe_tool_nr_label"):
            nr_lbl.setText(f"T{tool}")
        if dia_lbl := self._t._w(QLabel, "probe_tool_dia_label"):
            dia_lbl.setText(_fmt3(dia))
        if len_lbl := self._t._w(QLabel, "probe_tool_len_label"):
            len_lbl.setText(_fmt3(length))
        if c_lbl := self._t._w(QLabel, "probe_tool_comment_label"):
            c_lbl.setText(comment)

        # Update backplot geometry
        try:
            fdia = float(dia) if dia.strip() else 0.0
        except ValueError:
            fdia = 0.0
        try:
            flen = float(length) if length.strip() else 0.0
        except ValueError:
            flen = 0.0

        self._t.backplot.set_tool_geometry(fdia, flen)

        # Sync to simple view if present
        if self._t.simple_view_mod and self._t.simple_view_mod.simple_view:
            sv = self._t.simple_view_mod.simple_view
            if hasattr(sv, "backplot") and sv.backplot:
                sv.backplot.set_tool_geometry(fdia, flen)

    @Slot(list)
    def _on_tool_offset_changed(self, _):
        """Tool offset changed (e.g. after measurement) → update display."""
        tool = self._t.poller.stat.tool_in_spindle
        if tool > 0:
            self._on_tool(tool)

    def _on_tool_change_request(self, tool_nr: int):
        """Handle HAL tool-change-request pin."""
        tool_data = {'id': tool_nr, 'comment': '', 'diameter': 0.0, 'zoffset': 0.0}
        try:
            for t in self._t.poller.stat.tool_table:
                if t.id == tool_nr:
                    tool_data['comment'] = getattr(t, 'comment', "").strip()
                    tool_data['diameter'] = getattr(t, 'diameter', 0.0)
                    tool_data['zoffset'] = getattr(t, 'zoffset', 0.0)
                    break

            # Fallback: read comment from file if LinuxCNC gave nothing
            if not tool_data['comment'] and self._t.ini:
                tbl_path = self._t.ini.find("EMCIO", "TOOL_TABLE")
                if tbl_path:
                    if not os.path.isabs(tbl_path):
                        tbl_path = os.path.join(os.path.dirname(self._t.ini_path), tbl_path)

                    if os.path.exists(tbl_path):
                        with open(tbl_path, 'r') as f:
                            for line in f:
                                if line.strip().startswith(f"T{tool_nr} "):
                                    if ";" in line:
                                        tool_data['comment'] = line.split(";", 1)[1].strip()
                                        break
        except Exception as e:
            print(f"[M6] Error loading tool details: {e}")

        dlg = M6Dialog(tool_nr, tool_data, self._t.ui)

        if dlg.exec():
            if self._t._hal_comp:
                self._t._hal_comp["tool-changed-confirm"] = True
                QTimer.singleShot(1000, lambda: self._t._set_hal_pin("tool-changed-confirm", False))

    def _on_tool_item_changed(self, item: QTableWidgetItem):
        """Auto-fill pocket from tool number; auto-populate comment from diameter."""
        row = item.row()
        self._widget.blockSignals(True)
        try:
            if item.column() == 0:  # Tool-Nr geändert → Pocket mitziehen wenn leer
                tool_nr = item.text().strip()
                pocket_item = self._widget.item(row, 1)
                if tool_nr and (pocket_item is None or not pocket_item.text().strip()):
                    if pocket_item is None:
                        self._widget.setItem(row, 1, NumericTableWidgetItem(tool_nr))
                    else:
                        pocket_item.setText(tool_nr)

            if item.column() == 2:  # Durchmesser → Kommentar vorbelegen wenn leer
                dia_text = item.text().strip()
                comment_item = self._widget.item(row, 4)
                if dia_text and comment_item is not None and not comment_item.text().strip():
                    comment_item.setText(f"Ø{dia_text}mm")
        finally:
            self._widget.blockSignals(False)

    def _send_m6(self):
        """Send M6 tool change via MDI."""
        tool_data = []
        if self._widget:
            for row in range(self._widget.rowCount()):
                try:
                    nr_item = self._widget.item(row, 0)
                    dia_item = self._widget.item(row, 2)
                    comment_item = self._widget.item(row, 4)

                    if nr_item:
                        nr_str = nr_item.text().strip()
                        if nr_str:
                            tool_data.append({
                                'nr': int(nr_str),
                                'dia': float(dia_item.text()) if dia_item and dia_item.text().strip() else 0.0,
                                'comment': comment_item.text() if comment_item else ""
                            })
                except Exception:
                    continue

        dialog = ToolSelectionDialog(tool_data, self._t.ui)
        if dialog.exec():
            val = dialog.get_selected_tool()
            if val is not None:
                self._t.mdi_mod._send_mdi(f"T{val} M6 G43")
