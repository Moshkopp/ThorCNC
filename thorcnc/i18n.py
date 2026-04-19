import os
import json
from PySide6.QtWidgets import QWidget, QLabel, QPushButton, QCheckBox, QGroupBox, QRadioButton, QTabWidget, QComboBox, QMainWindow
from PySide6.QtCore import Qt

class TranslationManager:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(TranslationManager, cls).__new__(cls)
        return cls._instance

    def __init__(self, lang="English"):
        if hasattr(self, "_initialized") and self._initialized:
            return
        self.lang = lang
        self.translations = {}
        self._load_translations()
        self._initialized = True

    def _load_translations(self):
        base_dir = os.path.dirname(__file__)
        # Accept both "Deutsch" and "German"
        lang_code = "de" if self.lang in ["Deutsch", "German"] else "en"
        file_path = os.path.join(base_dir, "i18n", f"{lang_code}.json")
        
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    self.translations = json.load(f)
            except Exception as e:
                print(f"[i18n] Error loading translations: {e}")
        else:
            print(f"[i18n] Translation file not found: {file_path}")

    def translate(self, text: str) -> str:
        if not text:
            return ""
        lookup = text.strip()
        return self.translations.get(lookup, text)

    def _translate_single_widget(self, widget: QWidget):
        """Helper to translate a single widget's properties."""
        if isinstance(widget, (QLabel, QPushButton, QCheckBox, QRadioButton, QGroupBox)):
            if hasattr(widget, "text") and widget.text():
                widget.setText(self.translate(widget.text()))
            if hasattr(widget, "toolTip") and widget.toolTip():
                widget.setToolTip(self.translate(widget.toolTip()))
        
        elif isinstance(widget, QMainWindow):
            if widget.windowTitle():
                widget.setWindowTitle(self.translate(widget.windowTitle()))
        
        elif isinstance(widget, QTabWidget):
            for i in range(widget.count()):
                widget.setTabText(i, self.translate(widget.tabText(i)))
                widget.setTabToolTip(i, self.translate(widget.tabToolTip(i)))

    def apply_to_widget(self, widget: QWidget):
        """Translates a widget and all its children in one pass."""
        if not widget:
            return
        # Translate the root widget
        self._translate_single_widget(widget)
        # findChildren(QWidget) is recursive by default in Qt
        for child in widget.findChildren(QWidget):
            self._translate_single_widget(child)

def _t(text: str) -> str:
    """Global helper for translations."""
    if TranslationManager._instance:
        return TranslationManager._instance.translate(text)
    return text
