from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, 
                             QTableWidget, QTableWidgetItem, QPushButton, 
                             QLabel, QHeaderView, QAbstractItemView, QFrame)
from PySide6.QtCore import Qt, Slot

class ToolSelectionDialog(QDialog):
    """
    An interactive tool selection dialog with live filtering and tool table display.
    """
    def __init__(self, tool_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Tool for M6")
        self.setMinimumSize(600, 800)
        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self._selected_tool = None
        self._data = tool_data  # List of dicts or tuples
        
        self._setup_ui()
        self.search_input.setFocus()

    def _setup_ui(self):
        # Main Container (Frameless support)
        self.container = QFrame(self)
        self.container.setObjectName("toolDialogContainer")
        
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(self.container)

        layout = QVBoxLayout(self.container)
        layout.setSpacing(15)
        layout.setContentsMargins(25, 25, 25, 25)

        # Header
        header_label = QLabel("MANUAL TOOL SELECTION")
        header_label.setObjectName("toolDialogHeader")
        header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header_label)

        # Search field
        layout.addWidget(QLabel("FILTER TOOLS:"))
        self.search_input = QLineEdit()
        self.search_input.setObjectName("toolSearchInput")
        self.search_input.setPlaceholderText("Type tool number or name...")
        self.search_input.textChanged.connect(self._on_search_changed)
        self.search_input.returnPressed.connect(self._accept_from_search)
        layout.addWidget(self.search_input)

        # Table
        self.table = QTableWidget(0, 3)
        self.table.setObjectName("toolSelectionTable")
        self.table.setAlternatingRowColors(True)
        self.table.setHorizontalHeaderLabels(["T#", "DIAMETER", "COMMENT"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemDoubleClicked.connect(self.accept)
        
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 60)
        self.table.setColumnWidth(1, 110)
        
        layout.addWidget(self.table)
        self._populate_table()

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()
        
        self.btn_cancel = QPushButton("CANCEL")
        self.btn_cancel.setObjectName("btnToolCancel")
        self.btn_cancel.setMinimumWidth(120)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)
        
        self.btn_confirm = QPushButton("SELECT TOOL")
        self.btn_confirm.setObjectName("btnToolConfirm")
        self.btn_confirm.setMinimumWidth(150)
        self.btn_confirm.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_confirm)

        layout.addLayout(btn_layout)
        
        self.search_input.setFocus()

    def _populate_table(self):
        self.table.setRowCount(0)
        for tool in self._data:
            row = self.table.rowCount()
            self.table.insertRow(row)
            
            t_item = QTableWidgetItem(str(tool.get('nr', '')))
            t_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            
            d_item = QTableWidgetItem(f"{tool.get('dia', 0.0):.3f}")
            d_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            
            c_item = QTableWidgetItem(tool.get('comment', ''))
            
            self.table.setItem(row, 0, t_item)
            self.table.setItem(row, 1, d_item)
            self.table.setItem(row, 2, c_item)

    @Slot(str)
    def _on_search_changed(self, text):
        text = text.lower()
        for i in range(self.table.rowCount()):
            match = False
            for j in range(3):
                item = self.table.item(i, j)
                if item and text in item.text().lower():
                    match = True
                    break
            self.table.setRowHidden(i, not match)
            
        # Optional: auto-select the first visible row if it's a numeric match
        if text.isdigit():
             for i in range(self.table.rowCount()):
                 if not self.table.isRowHidden(i) and self.table.item(i, 0).text() == text:
                     self.table.selectRow(i)
                     break

    def _accept_from_search(self):
        # If the text is a direct number and nothing is selected, use that
        text = self.search_input.text().strip()
        if text.isdigit():
            self._selected_tool = int(text)
            self.accept()
        else:
            # Otherwise use current table selection
            self.accept()

    def get_selected_tool(self):
        # If we have an explicit override from search
        if self._selected_tool is not None:
            return self._selected_tool
            
        # Otherwise read from table
        row = self.table.currentRow()
        if row >= 0:
            try:
                return int(self.table.item(row, 0).text())
            except (ValueError, AttributeError):
                return None
        return None
