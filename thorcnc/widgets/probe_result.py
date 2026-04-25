"""Probe Result Panel and History Dialog for ThorCNC.

Reads the GUI Communication Block (#1000-#1099) populated by probing G-code
subroutines and presents the latest result + a history dialog.
"""
from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QFrame,
)


# Type codes - keep in sync with probe_run.ngc header table
PROBE_TYPES = {
    1:  ("outside_edge_left",   "edge_x"),
    2:  ("outside_edge_right",  "edge_x"),
    3:  ("outside_edge_top",    "edge_y"),
    4:  ("outside_edge_bottom", "edge_y"),
    10: ("outside_corner_bl",   "corner"),
    11: ("outside_corner_br",   "corner"),
    12: ("outside_corner_tl",   "corner"),
    13: ("outside_corner_tr",   "corner"),
    20: ("inside_edge_left",    "edge_x"),
    21: ("inside_edge_right",   "edge_x"),
    22: ("inside_edge_top",     "edge_y"),
    23: ("inside_edge_bottom",  "edge_y"),
    30: ("inside_corner_bl",    "corner"),
    31: ("inside_corner_br",    "corner"),
    32: ("inside_corner_tl",    "corner"),
    33: ("inside_corner_tr",    "corner"),
    40: ("outside_center",      "z_only"),
    41: ("inside_center",       "z_only"),
    50: ("center_round",        "round"),
    51: ("center_rect_x",       "rect_x"),
    52: ("center_rect_y",       "rect_y"),
    60: ("inside_round",        "round"),
    61: ("inside_rect_x",       "rect_x"),
    62: ("inside_rect_y",       "rect_y"),
    70: ("angle_edge_bottom",   "angle"),
    71: ("angle_edge_top",      "angle"),
    72: ("angle_edge_left",     "angle"),
    73: ("angle_edge_right",    "angle"),
}

WCS_NAMES = ["G54", "G55", "G56", "G57", "G58", "G59", "G59.1", "G59.2", "G59.3"]
DELTA_TOLERANCE = 0.05  # mm


@dataclass
class ProbeResult:
    timestamp: float
    type_code: int
    type_name: str
    kind: str
    wcs: str
    auto_zero: bool
    x_hit: float = 0.0
    y_hit: float = 0.0
    z_surface: float = 0.0
    p2_x: float = 0.0
    p2_y: float = 0.0
    x_result: float = 0.0
    y_result: float = 0.0
    measured_x: float = 0.0
    measured_y: float = 0.0
    angle: float = 0.0
    expected: Optional[float] = None


def format_result_summary(r: ProbeResult) -> str:
    if r.kind == "edge_x":
        return f"X {r.x_result:+.3f}"
    if r.kind == "edge_y":
        return f"Y {r.y_result:+.3f}"
    if r.kind == "corner":
        return f"({r.x_result:+.3f}, {r.y_result:+.3f})"
    if r.kind == "z_only":
        return f"Z {r.z_surface:+.3f}"
    if r.kind == "round":
        s = f"ø{r.measured_x:.3f}"
        if r.expected and r.expected > 0:
            s += f"  Δ{r.measured_x - r.expected:+.3f}"
        return s
    if r.kind == "rect_x":
        s = f"X w{r.measured_x:.3f}"
        if r.expected and r.expected > 0:
            s += f"  Δ{r.measured_x - r.expected:+.3f}"
        return s
    if r.kind == "rect_y":
        s = f"Y w{r.measured_y:.3f}"
        if r.expected and r.expected > 0:
            s += f"  Δ{r.measured_y - r.expected:+.3f}"
        return s
    if r.kind == "angle":
        return f"∠ {r.angle:+.3f}°"
    return ""


class ProbeResultPanel(QGroupBox):
    """Displays the latest probe measurement."""

    history_clicked = Signal()
    clear_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__("PROBE RESULT", parent)
        self.setObjectName("probe_result_panel")
        self._result: Optional[ProbeResult] = None
        self._build_ui()
        self.set_empty()

    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(12)

        # Row 1: Info (WCS, Type, Time)
        row1 = QHBoxLayout()
        row1.setSpacing(10)

        self._lbl_wcs = QLabel("---")
        self._lbl_wcs.setObjectName("probe_wcs_pill")
        self._lbl_wcs.setStyleSheet(
            "QLabel#probe_wcs_pill { background:#3776ab; color:white; "
            "padding:4px 12px; border-radius:10px; font-weight:bold; }"
        )
        row1.addWidget(self._lbl_wcs)

        self._lbl_type = QLabel("(no result yet)")
        self._lbl_type.setStyleSheet("font-weight: bold; font-size: 11pt;")
        row1.addWidget(self._lbl_type)

        row1.addStretch()

        self._lbl_time = QLabel("")
        self._lbl_time.setStyleSheet("color: #ccc; font-size: 10pt;")
        row1.addWidget(self._lbl_time)
        
        v.addLayout(row1)

        # Row 2: Actions (History, Clear)
        row2 = QHBoxLayout()
        row2.setSpacing(10)
        
        self._btn_history = QPushButton("History")
        self._btn_history.clicked.connect(self.history_clicked)
        row2.addWidget(self._btn_history)

        self._btn_clear = QPushButton("Clear")
        self._btn_clear.clicked.connect(self._on_clear)
        row2.addWidget(self._btn_clear)
        
        v.addLayout(row2)

        # Add a subtle separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        sep.setStyleSheet("color: #333;")
        v.addWidget(sep)

        self._body = QGridLayout()
        self._body.setHorizontalSpacing(20)
        self._body.setVerticalSpacing(8)
        v.addLayout(self._body)

        self._lbl_az = QLabel("")
        self._lbl_az.setStyleSheet("color: #d97706; font-style: italic;")
        v.addWidget(self._lbl_az)

        v.addStretch()

    def _clear_body(self):
        while self._body.count():
            it = self._body.takeAt(0)
            if w := it.widget():
                w.setParent(None)

    def _add_row(self, row: int, label: str, value: str, color: str = ""):
        l = QLabel(label)
        l.setStyleSheet("color: #fff; font-size: 13pt; font-weight: bold;")
        v = QLabel(value)
        if color:
            v.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 13pt;")
        else:
            v.setStyleSheet("color: #fff; font-weight: bold; font-size: 13pt;")
        self._body.addWidget(l, row, 0)
        self._body.addWidget(v, row, 1)

    def _add_dim_row(self, row: int, label: str, measured: float, expected: Optional[float]):
        if expected is None or expected <= 0:
            self._add_row(row, label, f"{measured:.3f}")
            return
        delta = measured - expected
        color = "#16a34a" if abs(delta) <= DELTA_TOLERANCE else "#dc2626"
        text = f"{measured:.3f}    Δ{delta:+.3f}    (Expected {expected:.3f})"
        self._add_row(row, label, text, color)

    def set_empty(self):
        self._result = None
        self._lbl_wcs.setText("---")
        self._lbl_type.setText("(no result yet)")
        self._lbl_time.setText("")
        self._lbl_az.setText("")
        self._clear_body()

    def set_result(self, r: ProbeResult):
        self._result = r
        self._lbl_wcs.setText(r.wcs)
        self._lbl_type.setText(r.type_name)
        self._lbl_time.setText(time.strftime("%H:%M:%S", time.localtime(r.timestamp)))

        if r.kind == "angle":
            self._lbl_az.setText("")
        elif not r.auto_zero:
            self._lbl_az.setText("Auto-Zero: OFF (measure only)")
        else:
            self._lbl_az.setText("")

        self._clear_body()

        if r.kind == "edge_x":
            self._add_row(0, "X Wall:",    f"{r.x_result:+.3f}")
            self._add_row(1, "Z Surface:", f"{r.z_surface:+.3f}")
        elif r.kind == "edge_y":
            self._add_row(0, "Y Wall:",    f"{r.y_result:+.3f}")
            self._add_row(1, "Z Surface:", f"{r.z_surface:+.3f}")
        elif r.kind == "corner":
            self._add_row(0, "X Corner:",  f"{r.x_result:+.3f}")
            self._add_row(1, "Y Corner:",  f"{r.y_result:+.3f}")
            self._add_row(2, "Z Surface:", f"{r.z_surface:+.3f}")
        elif r.kind == "z_only":
            self._add_row(0, "Z Surface:", f"{r.z_surface:+.3f}")
        elif r.kind == "round":
            self._add_row(0, "X Center:",  f"{r.x_result:+.3f}")
            self._add_row(1, "Y Center:",  f"{r.y_result:+.3f}")
            self._add_row(2, "Z Surface:", f"{r.z_surface:+.3f}")
            self._add_dim_row(3, "Diameter:", r.measured_x, r.expected)
            if abs(r.measured_x - r.measured_y) > 0.01:
                self._add_dim_row(4, "Diameter Y:", r.measured_y, r.expected)
        elif r.kind == "rect_x":
            self._add_row(0, "X Center:",  f"{r.x_result:+.3f}")
            self._add_row(1, "Z Surface:", f"{r.z_surface:+.3f}")
            self._add_dim_row(2, "X Width:", r.measured_x, r.expected)
        elif r.kind == "rect_y":
            self._add_row(0, "Y Center:",  f"{r.y_result:+.3f}")
            self._add_row(1, "Z Surface:", f"{r.z_surface:+.3f}")
            self._add_dim_row(2, "Y Width:", r.measured_y, r.expected)
        elif r.kind == "angle":
            self._add_row(0, "Angle:",     f"{r.angle:+.3f}°")
            self._add_row(1, "Z Surface:", f"{r.z_surface:+.3f}")

    def _on_clear(self):
        self.set_empty()
        self.clear_clicked.emit()


class ProbeHistoryDialog(QDialog):
    """Modeless dialog showing probe history."""

    cleared = Signal()

    def __init__(self, history, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Probe History")
        self.resize(720, 400)
        self._build_ui()
        self.set_history(history)

    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)

        self._table = QTableWidget(0, 5, self)
        self._table.setHorizontalHeaderLabels(["Time", "Type", "Result", "WCS", "AZ"])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        v.addWidget(self._table)

        bottom = QHBoxLayout()
        self._btn_clear = QPushButton("Clear All")
        self._btn_clear.clicked.connect(self._on_clear)
        bottom.addWidget(self._btn_clear)
        bottom.addStretch()
        self._btn_close = QPushButton("Close")
        self._btn_close.clicked.connect(self.close)
        bottom.addWidget(self._btn_close)
        v.addLayout(bottom)

    def set_history(self, history):
        self._table.setRowCount(len(history))
        for i, r in enumerate(reversed(history)):
            ts = time.strftime("%H:%M:%S", time.localtime(r.timestamp))
            az = "-" if r.kind == "angle" else ("ON" if r.auto_zero else "OFF")
            row = [ts, r.type_name, format_result_summary(r), r.wcs, az]
            for col, val in enumerate(row):
                item = QTableWidgetItem(val)
                item.setToolTip(self._tooltip(r))
                self._table.setItem(i, col, item)

    def _tooltip(self, r: ProbeResult) -> str:
        L = [f"{r.type_name}  ({time.strftime('%H:%M:%S', time.localtime(r.timestamp))})",
             f"WCS: {r.wcs}"]
        if r.kind in ("edge_x", "corner", "round", "rect_x"):
            L.append(f"X Hit: {r.x_hit:+.4f}")
        if r.kind in ("edge_y", "corner", "round", "rect_y"):
            L.append(f"Y Hit: {r.y_hit:+.4f}")
        L.append(f"Z Surface: {r.z_surface:+.4f}")
        if r.kind == "angle":
            L.append(f"P1: ({r.x_hit:+.4f}, {r.y_hit:+.4f})")
            L.append(f"P2: ({r.p2_x:+.4f}, {r.p2_y:+.4f})")
            L.append(f"Angle: {r.angle:+.4f}°")
        if r.measured_x:
            L.append(f"Measured X: {r.measured_x:.4f}")
        if r.measured_y:
            L.append(f"Measured Y: {r.measured_y:.4f}")
        if r.expected:
            L.append(f"Expected: {r.expected:.4f}")
        return "\n".join(L)

    def _on_clear(self):
        self._table.setRowCount(0)
        self.cleared.emit()
