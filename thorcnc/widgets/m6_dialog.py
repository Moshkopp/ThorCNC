from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFrame
from PySide6.QtCore import Qt, Property
from ..i18n import _t

class M6Dialog(QDialog):
    """
    A premium, industrial-style dialog for manual tool changes.
    """
    def __init__(self, tool_number: int, tool_data: dict = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_t("Manual Tool Change"))
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
        header_label = QLabel(_t("MANUAL TOOL CHANGE"))
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
        details_frame = QFrame()
        details_frame.setObjectName("m6DetailsFrame")
        details_layout = QVBoxLayout(details_frame)
        
        desc = self._tool_data.get('description', '---')
        dia = self._tool_data.get('diameter', '0.000')
        
        lbl_desc = QLabel(f"<b>{_t('Description')}:</b> {desc}")
        lbl_dia = QLabel(f"<b>{_t('Diameter (D)')}:</b> {dia} mm")
        
        details_layout.addWidget(lbl_desc)
        details_layout.addWidget(lbl_dia)
        content_layout.addWidget(details_frame)
        
        content_layout.addStretch()

        # Confirm Button
        self.btn_confirm = QPushButton(_t("LOADED & SECURED"))
        self.btn_confirm.setObjectName("m6ConfirmButton")
        self.btn_confirm.setFixedHeight(60)
        self.btn_confirm.clicked.connect(self.accept)
        content_layout.addWidget(self.btn_confirm)
