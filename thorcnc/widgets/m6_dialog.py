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
        self._apply_styling()

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
        self.tool_frame.setObjectName("toolFrame")
        tool_layout = QVBoxLayout(self.tool_frame)
        
        self.lbl_tool_num = QLabel(f"T{self._tool_number}")
        self.lbl_tool_num.setObjectName("toolNumLarge")
        self.lbl_tool_num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tool_layout.addWidget(self.lbl_tool_num)
        content_layout.addWidget(self.tool_frame)
        
        # Details section
        details_layout = QVBoxLayout()
        details_layout.setSpacing(10)
        
        # Description (Comment)
        comment = self._tool_data.get('comment', '--- No Description ---')
        self.lbl_desc = QLabel(comment)
        self.lbl_desc.setObjectName("toolDescription")
        self.lbl_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_desc.setWordWrap(True)
        details_layout.addWidget(self.lbl_desc)
        
        # Diameter Badge (Centered)
        dia = self._tool_data.get('diameter', 0.0)
        self.lbl_dia = QLabel(f"DIAMETER: {dia:.2f} mm")
        self.lbl_dia.setObjectName("toolSpec")
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

    def _apply_styling(self):
        self.setStyleSheet("""
            QFrame#m6Container {
                background-color: #1a1b1e;
                border: 2px solid #f0883e;
                border-radius: 12px;
            }
            QLabel#m6Header {
                color: #f0883e;
                font-size: 14pt;
                font-weight: bold;
                letter-spacing: 2px;
            }
            QFrame#toolFrame {
                background-color: #25262b;
                border-radius: 8px;
                margin: 10px 0;
            }
            QLabel#toolNumLarge {
                color: #f0883e;
                font-size: 72pt;
                font-weight: 900;
                font-family: 'Bebas Kai', 'DejaVu Sans', sans-serif;
                margin-bottom: -10px;
            }
            QLabel#toolDescription {
                color: #f0883e;
                font-size: 24pt;
                font-weight: 900;
                font-style: italic;
                padding: 10px;
                background-color: #25262b;
                border: 1px solid #333333;
                border-radius: 6px;
            }
            QLabel#toolSpec {
                color: #aaaaaa;
                font-size: 12pt;
                background-color: #25262b;
                padding: 4px 12px;
                border-radius: 4px;
            }
            QPushButton#m6ConfirmBtn {
                background-color: #2ea043;
                color: white;
                font-size: 14pt;
                font-weight: bold;
                border: none;
                border-radius: 6px;
                padding: 10px;
            }
            QPushButton#m6ConfirmBtn:hover {
                background-color: #3fb950;
            }
            QPushButton#m6ConfirmBtn:pressed {
                background-color: #238636;
                padding-top: 12px;
            }
        """)
