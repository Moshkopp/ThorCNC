from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFrame
from PySide6.QtCore import Qt, Property

class M6Dialog(QDialog):
    """
    A premium, industrial-style dialog for manual tool changes.
    """
    def __init__(self, tool_number: int, tool_data: dict = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manual Tool Change")
        self.setMinimumSize(500, 450)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._tool_number = tool_number
        self._tool_data = tool_data or {}

        self._setup_ui()

    def _setup_ui(self):
        # Main Container
        self.container = QFrame(self)
        self.container.setObjectName("m6Container")
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.container)

        content_layout = QVBoxLayout(self.container)
        content_layout.setContentsMargins(30, 30, 30, 30)
        content_layout.setSpacing(15)

        # Header
        header_label = QLabel("MANUAL TOOL CHANGE")
        header_label.setObjectName("m6Header")
        header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(header_label)

        # Tool indicator frame (The "Big Number")
        self.tool_frame = QFrame()
        self.tool_frame.setObjectName("m6ToolFrame")
        tool_layout = QVBoxLayout(self.tool_frame)
        
        self.lbl_tool_num = QLabel(f"T{self._tool_number}")
        self.lbl_tool_num.setObjectName("m6ToolNumLarge")
        self.lbl_tool_num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tool_layout.addWidget(self.lbl_tool_num)
        content_layout.addWidget(self.tool_frame)
        
        # Details section
        details_layout = QVBoxLayout()
        details_layout.setSpacing(10)
        
        # Description (Comment)
        comment = self._tool_data.get('comment', '--- No Description ---')
        self.lbl_desc = QLabel(comment)
        self.lbl_desc.setObjectName("m6ToolDescription")
        self.lbl_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_desc.setWordWrap(True)
        details_layout.addWidget(self.lbl_desc)
        
        # Diameter Badge (Centered)
        dia = self._tool_data.get('diameter', 0.0)
        self.lbl_dia = QLabel(f"DIAMETER: {dia:.2f} mm")
        self.lbl_dia.setObjectName("m6ToolSpec")
        self.lbl_dia.setAlignment(Qt.AlignmentFlag.AlignCenter)
        details_layout.addWidget(self.lbl_dia, 0, Qt.AlignmentFlag.AlignCenter)
        
        content_layout.addLayout(details_layout)
        
        content_layout.addStretch()

        # Confirm Button
        self.btn_confirm = QPushButton("LOADED & SECURED")
        self.btn_confirm.setObjectName("m6ConfirmBtn")
        self.btn_confirm.setMinimumHeight(60)
        self.btn_confirm.clicked.connect(self.accept)
        content_layout.addWidget(self.btn_confirm)
