"""Save & Load dialogs for WCS offset snapshots."""

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QAbstractItemView)

from ..i18n import _t


_AXES = ("x", "y", "z", "r")


def _fmt(v) -> str:
    try:
        return f"{float(v):+.4f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_date(snap: dict) -> str:
    raw = snap.get("created") or snap.get("id") or ""
    return raw.replace("T", " ")


class OffsetsSnapshotSaveDialog(QDialog):
    """Modal dialog to enter a comment for a new snapshot."""

    def __init__(self, wcs_preview: dict, wcs_list: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_t("Save WCS Snapshot"))
        self.setMinimumSize(520, 540)
        self.setModal(True)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._setup_ui(wcs_preview, wcs_list)
        self.comment_input.setFocus()

    def _setup_ui(self, wcs_preview: dict, wcs_list: list):
        self.container = QFrame(self)
        self.container.setObjectName("toolDialogContainer")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.container)

        layout = QVBoxLayout(self.container)
        layout.setSpacing(15)
        layout.setContentsMargins(25, 25, 25, 25)

        header = QLabel(_t("SAVE WCS SNAPSHOT"))
        header.setObjectName("toolDialogHeader")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        layout.addWidget(QLabel(_t("Values to be saved:")))

        tbl = QTableWidget(len(wcs_list), 5)
        tbl.setObjectName("snapshotPreviewTable")
        tbl.setHorizontalHeaderLabels(["WCS", "X", "Y", "Z", "R"])
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tbl.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        tbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        hdr = tbl.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        for c in range(1, 5):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)
        tbl.setColumnWidth(0, 80)
        _fill_preview_table(tbl, wcs_preview, wcs_list)
        layout.addWidget(tbl)

        layout.addWidget(QLabel(_t("Comment:")))
        self.comment_input = QLineEdit()
        self.comment_input.setObjectName("toolSearchInput")
        self.comment_input.setPlaceholderText(_t("Description…"))
        self.comment_input.returnPressed.connect(self.accept)
        layout.addWidget(self.comment_input)

        btn_layout = QHBoxLayout()
        self.btn_cancel = QPushButton(_t("CANCEL"))
        self.btn_cancel.setObjectName("btnToolCancel")
        self.btn_cancel.setFixedHeight(50)
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_save = QPushButton(_t("SAVE"))
        self.btn_save.setObjectName("btnToolConfirm")
        self.btn_save.setFixedHeight(50)
        self.btn_save.clicked.connect(self.accept)

        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_save)
        layout.addLayout(btn_layout)

    def get_comment(self) -> str:
        return self.comment_input.text().strip()


class OffsetsSnapshotLoadDialog(QDialog):
    """Modal dialog to pick (and optionally delete) a saved snapshot."""

    def __init__(self, snapshots: list, wcs_list: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_t("Load WCS Snapshot"))
        self.setMinimumSize(900, 560)
        self.setModal(True)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._snapshots = list(snapshots)
        self._wcs_list = wcs_list
        self._setup_ui()
        self._populate_table()

    def _setup_ui(self):
        self.container = QFrame(self)
        self.container.setObjectName("toolDialogContainer")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.container)

        layout = QVBoxLayout(self.container)
        layout.setSpacing(15)
        layout.setContentsMargins(25, 25, 25, 25)

        header = QLabel(_t("LOAD WCS SNAPSHOT"))
        header.setObjectName("toolDialogHeader")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        body = QHBoxLayout()
        body.setSpacing(15)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels([_t("Date"), _t("Comment")])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setObjectName("toolSelectionTable")
        self.table.verticalHeader().setVisible(False)
        self.table.itemDoubleClicked.connect(self.accept)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        body.addWidget(self.table, 3)

        self.preview = QFrame()
        self.preview.setObjectName("snapshotPreviewFrame")
        preview_layout = QVBoxLayout(self.preview)
        preview_layout.setContentsMargins(8, 8, 8, 8)
        preview_layout.addWidget(QLabel(_t("Preview")))

        self.preview_table = QTableWidget(len(self._wcs_list), 5)
        self.preview_table.setObjectName("snapshotPreviewTable")
        self.preview_table.setHorizontalHeaderLabels(["WCS", "X", "Y", "Z", "R"])
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.preview_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        hdr = self.preview_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        for c in range(1, 5):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)
        self.preview_table.setColumnWidth(0, 80)
        _fill_preview_table(self.preview_table, {}, self._wcs_list)
        preview_layout.addWidget(self.preview_table)

        body.addWidget(self.preview, 4)
        layout.addLayout(body)

        btn_layout = QHBoxLayout()
        self.btn_delete = QPushButton(_t("DELETE"))
        self.btn_delete.setObjectName("btnToolUnload")
        self.btn_delete.setFixedHeight(50)
        self.btn_delete.clicked.connect(self._on_delete_clicked)

        self.btn_cancel = QPushButton(_t("CANCEL"))
        self.btn_cancel.setObjectName("btnToolCancel")
        self.btn_cancel.setFixedHeight(50)
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_load = QPushButton(_t("LOAD"))
        self.btn_load.setObjectName("btnToolConfirm")
        self.btn_load.setFixedHeight(50)
        self.btn_load.clicked.connect(self.accept)

        btn_layout.addWidget(self.btn_delete)
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_load)
        layout.addLayout(btn_layout)

    def _populate_table(self):
        self.table.setRowCount(0)
        for snap in self._snapshots:
            row = self.table.rowCount()
            self.table.insertRow(row)

            date_item = QTableWidgetItem(_fmt_date(snap))
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 0, date_item)
            self.table.setItem(row, 1, QTableWidgetItem(snap.get("comment", "")))

        self._update_preview(None)
        if self._snapshots:
            self.table.selectRow(0)

    @Slot()
    def _on_selection_changed(self):
        row = self.table.currentRow()
        snap = self._snapshots[row] if 0 <= row < len(self._snapshots) else None
        self._update_preview(snap)

    def _update_preview(self, snap):
        wcs_values = (snap.get("wcs") or {}) if snap else {}
        _fill_preview_table(self.preview_table, wcs_values, self._wcs_list)

    def _on_delete_clicked(self):
        row = self.table.currentRow()
        if not (0 <= row < len(self._snapshots)):
            return
        del self._snapshots[row]
        self._populate_table()

    def get_selected_snapshot(self):
        row = self.table.currentRow()
        if 0 <= row < len(self._snapshots):
            return self._snapshots[row]
        return None

    def get_remaining_snapshots(self) -> list:
        return list(self._snapshots)


def _fill_preview_table(tbl: QTableWidget, wcs_values: dict, wcs_list: list):
    """Render a WCS×axes table; empty cells when wcs_values lacks data."""
    for row, entry in enumerate(wcs_list):
        label, p_idx = entry[0], entry[1]
        name_item = QTableWidgetItem(label)
        name_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        tbl.setItem(row, 0, name_item)
        values = wcs_values.get(str(p_idx), {}) if wcs_values else {}
        for col, axis in enumerate(_AXES, start=1):
            it = QTableWidgetItem(_fmt(values.get(axis)) if values else "—")
            it.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            tbl.setItem(row, col, it)
