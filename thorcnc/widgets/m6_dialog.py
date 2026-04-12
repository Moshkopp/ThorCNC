from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFrame
from PySide6.QtCore import Qt, Property

class M6Dialog(QDialog):
    """
    A premium, industrial-style dialog for manual tool changes.
    """
    def __init__(self, tool_number: int, tool_name: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manual Tool Change")
        self.setMinimumSize(450, 350)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._tool_number = tool_number
        self._tool_name = tool_name

        self._setup_ui()
        self._apply_styling()

    def _setup_ui(self):
        # Main Container (for the border and background)
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

        # Tool indicator frame
        self.tool_frame = QFrame()
        self.tool_frame.setObjectName("toolFrame")
        tool_layout = QVBoxLayout(self.tool_frame)
        
        self.lbl_tool_num = QLabel(f"T{self._tool_number}")
        self.lbl_tool_num.setObjectName("toolNumLarge")
        self.lbl_tool_num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tool_layout.addWidget(self.lbl_tool_num)
        
        if self._tool_name:
            self.lbl_tool_name = QLabel(self._tool_name)
            self.lbl_tool_name.setObjectName("toolName")
            self.lbl_tool_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.lbl_tool_name.setWordWrap(True)
            tool_layout.addWidget(self.lbl_tool_name)
        
        content_layout.addWidget(self.tool_frame)
        
        # Instruction
        instruction = QLabel("Insert tool and secure the spindle.")
        instruction.setObjectName("m6Instruction")
        instruction.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(instruction)

        content_layout.addStretch()

        # Confirm Button
        self.btn_confirm = QPushButton("CONFIRM CHANGE")
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
                color: white;
                font-size: 64pt;
                font-weight: 900;
                font-family: 'Bebas Kai', 'DejaVu Sans', sans-serif;
            }
            QLabel#toolName {
                color: #aaaaaa;
                font-size: 12pt;
                font-style: italic;
            }
            QLabel#m6Instruction {
                color: #eeeeee;
                font-size: 11pt;
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
