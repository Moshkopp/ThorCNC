"""Offsets/WCS module for ThorCNC."""

import os
import linuxcnc
from PySide6.QtCore import Slot
from .base import ThorModule
from ..i18n import _t


class OffsetsModule(ThorModule):
    """Manages WCS (Work Coordinate System) offsets tab and display."""

    _WCS_LIST = [
        ("G54", 1, 5221), ("G55", 2, 5241), ("G56", 3, 5261),
        ("G57", 4, 5281), ("G58", 5, 5301), ("G59", 6, 5321),
        ("G59.1", 7, 5341), ("G59.2", 8, 5361), ("G59.3", 9, 5381),
    ]

    def setup(self):
        self._setup_offsets_tab()

    def connect_signals(self):
        if self._t.poller:
            self._t.poller.periodic.connect(self._refresh_offsets_table)
            self._t.poller.g5x_index_changed.connect(self._on_offset_wcs_changed)

    def _var_file_path(self) -> str | None:
        if not self._t.ini:
            return None
        name = self._t.ini.find("RS274NGC", "PARAMETER_FILE")
        if not name:
            return None
        p = os.path.join(os.path.dirname(self._t.ini_path), name)
        return p if os.path.exists(p) else None

    def _read_var_file(self) -> dict[int, float]:
        """Reads the LinuxCNC .var file and returns {param_nr: value}."""
        path = self._var_file_path()
        if not path:
            return {}
        params: dict[int, float] = {}
        try:
            with open(path, "r") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            params[int(parts[0])] = float(parts[1])
                        except ValueError:
                            pass
        except OSError:
            pass
        return params

    def _setup_offsets_tab(self):
        from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                                       QTableWidget, QTableWidgetItem,
                                       QPushButton, QHeaderView, QLabel,
                                       QAbstractItemView)
        from PySide6.QtCore import Qt as _Qt
        from PySide6.QtGui import QColor, QFont

        tab = self._t._w(QWidget, "tab_offsets")
        if not tab:
            return

        outer = QVBoxLayout(tab)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        title = QLabel(_t("Work Coordinate Offsets (G54 – G59.3)"))
        title.setObjectName("section_title")
        outer.addWidget(title)

        cols = ["WCS", "X", "Y", "Z", "R", ""]
        tbl = QTableWidget(len(self._WCS_LIST), len(cols))
        tbl.setObjectName("offsetTable")
        tbl.setHorizontalHeaderLabels(cols)
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tbl.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        tbl.setObjectName("offsetsTable")
        tbl.setFocusPolicy(_Qt.FocusPolicy.NoFocus)

        hdr = tbl.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        tbl.setColumnWidth(0, 100)
        tbl.setColumnWidth(5, 185)
        tbl.verticalHeader().setDefaultSectionSize(48)

        _bold = QFont()
        _bold.setBold(True)
        _bold.setPointSize(14)

        for row, (label, p_idx, base_param) in enumerate(self._WCS_LIST):
            name_item = QTableWidgetItem(label)
            name_item.setTextAlignment(_Qt.AlignmentFlag.AlignCenter)
            name_item.setFont(_bold)
            tbl.setItem(row, 0, name_item)
            for col in range(1, 5):
                it = QTableWidgetItem("–")
                it.setTextAlignment(_Qt.AlignmentFlag.AlignRight | _Qt.AlignmentFlag.AlignVCenter)
                tbl.setItem(row, col, it)
            cell = QWidget()
            cell_lay = QHBoxLayout(cell)
            cell_lay.setContentsMargins(4, 4, 4, 4)
            cell_lay.setSpacing(4)

            btn_clear = QPushButton(_t("CLEAR"))
            btn_clear.setObjectName("wcs_clear_btn")
            btn_clear.setFocusPolicy(_Qt.FocusPolicy.NoFocus)
            btn_clear.setFixedSize(80, 34)
            btn_clear.clicked.connect(lambda _=False, n=p_idx: self._clear_wcs(n))

            btn_clr_r = QPushButton(_t("CLR R"))
            btn_clr_r.setObjectName("wcs_clear_btn")
            btn_clr_r.setFocusPolicy(_Qt.FocusPolicy.NoFocus)
            btn_clr_r.setFixedSize(72, 34)
            btn_clr_r.clicked.connect(lambda _=False, n=p_idx: self._clear_wcs_r(n))

            cell_lay.addWidget(btn_clear)
            cell_lay.addWidget(btn_clr_r)
            tbl.setCellWidget(row, 5, cell)

        outer.addWidget(tbl)

        self._offset_table = tbl
        self._offset_active_row = 0
        self._offset_var_mtime = 0.0

        self._refresh_offsets_table()

    def _refresh_offsets_table(self):
        """Reads the .var file (only if mtime changed) and updates the table."""
        path = self._var_file_path()
        if not hasattr(self, "_offset_table"):
            return
        mtime = os.path.getmtime(path) if path else 0.0
        if mtime == self._offset_var_mtime:
            return
        self._offset_var_mtime = mtime

        from PySide6.QtGui import QColor
        params = self._read_var_file()
        tbl = self._offset_table

        for row, (_, _, base) in enumerate(self._WCS_LIST):
            for col, offset in enumerate((0, 1, 2, 9)):
                val = params.get(base + offset, 0.0)
                it = tbl.item(row, col + 1)
                if it:
                    it.setText(f"{val:+.4f}")
                    it.setForeground(QColor("#3db2ff" if val != 0.0 else "#999999"))

    @Slot(int)
    def _on_offset_wcs_changed(self, index: int):
        """Highlights the active WCS row."""
        if not hasattr(self, "_offset_table"):
            return
        from PySide6.QtGui import QColor
        tbl = self._offset_table
        for row, (_, p_idx, _) in enumerate(self._WCS_LIST):
            active = p_idx == index
            bg = QColor("#194a82") if active else QColor("#252525")
            for col in range(6):
                it = tbl.item(row, col)
                if it:
                    it.setBackground(bg)

    def _clear_wcs(self, p_idx: int):
        """Clears all offsets of the specified WCS to 0 via G10 L2."""
        try:
            self._t.cmd.mode(linuxcnc.MODE_MDI)
            self._t.cmd.wait_complete()
            self._t.cmd.mdi(f"G10 L2 P{p_idx} X0 Y0 Z0 R0")
            self._t.cmd.wait_complete()
            self._t.cmd.mode(linuxcnc.MODE_MANUAL)
            self._t._status(_t("WCS G{}{} → X0 Y0 Z0 R0").format(53 + p_idx if p_idx <= 6 else '59.', p_idx - 6 if p_idx > 6 else ""))
            self._offset_var_mtime = 0.0
        except Exception as e:
            self._t._status(_t("Error:") + f" {e}")

    def _clear_wcs_r(self, p_idx: int):
        """Clears only the rotation (R) offset of the specified WCS via G10 L2."""
        try:
            self._t.cmd.mode(linuxcnc.MODE_MDI)
            self._t.cmd.wait_complete()
            self._t.cmd.mdi(f"G10 L2 P{p_idx} R0")
            self._t.cmd.wait_complete()
            self._t.cmd.mode(linuxcnc.MODE_MANUAL)
            self._t._status(_t("WCS G{}{} → R0").format(53 + p_idx if p_idx <= 6 else '59.', p_idx - 6 if p_idx > 6 else ""))
            self._offset_var_mtime = 0.0
        except Exception as e:
            self._t._status(_t("Error:") + f" {e}")
