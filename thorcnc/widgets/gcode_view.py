"""
G-Code Viewer mit Syntax-Highlighting und aktueller Zeilen-Hervorhebung.
"""
import re
from PySide6.QtWidgets import QPlainTextEdit, QWidget, QHBoxLayout
from PySide6.QtGui import (
    QSyntaxHighlighter, QTextCharFormat, QColor, QFont,
    QTextCursor, QPainter, QPalette,
)
from PySide6.QtCore import Qt, QRect, QSize, Signal


# ──────────────────────────────────────────────────────────── Highlighter ──

class _GCodeHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)

        def fmt(color, bold=False):
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if bold:
                f.setFontWeight(QFont.Weight.Bold)
            return f

        self._rules = [
            # Wichtige G-Codes (G54-G59, G43, G49, G20, G21, G90, G91)
            (re.compile(r'\bG(?:5[4-9](?:\.\d)?|43|49|2[01]|9[01])\b', re.IGNORECASE), fmt("#e74c3c", bold=True)),
            # Normale G-Codes
            (re.compile(r'\bG\d+(?:\.\d+)?', re.IGNORECASE), fmt("#5dade2", bold=True)),
            # M-Codes
            (re.compile(r'\bM\d+', re.IGNORECASE),            fmt("#e67e22")),
            # Koordinaten X Y Z A B C
            (re.compile(r'\b[XYZABC][-+]?[\d.]+', re.IGNORECASE), fmt("#2ecc71")),
            # F, S
            (re.compile(r'\b[FS][\d.]+', re.IGNORECASE),      fmt("#f1c40f")),
            # T (Tool)
            (re.compile(r'\bT\d+', re.IGNORECASE),            fmt("#bb8fce")),
            # I J K R (Bogen-Parameter)
            (re.compile(r'\b[IJKR][-+]?[\d.]+', re.IGNORECASE), fmt("#85c1e9")),
            # Kommentare ( ... ) und ; ...
            (re.compile(r'\(.*?\)|;.*'),                       fmt("#7f8c8d")),
            # Zeilennummer N
            (re.compile(r'\bN\d+', re.IGNORECASE),            fmt("#5d6d7e")),
        ]

    def highlightBlock(self, text: str):
        for pattern, fmt in self._rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


# ──────────────────────────────────────────────────────────── Line Numbers ──

class _LineNumberArea(QWidget):
    def __init__(self, editor: "GCodeView"):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor._line_number_width(), 0)

    def paintEvent(self, event):
        self._editor._paint_line_numbers(event)


# ──────────────────────────────────────────────────────────── GCodeView ────

class GCodeView(QPlainTextEdit):
    """G-Code Viewer with syntax highlighting and current line highlighting."""

    line_selected = Signal(int)   # User clicks on a line
    zoom_changed = Signal(int)    # Font size changed

    def __init__(self, parent=None, editable=False):
        super().__init__(parent)
        self.setReadOnly(not editable)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self._font_size = 22 if editable else 30
        
        # Highlighter
        self._highlighter = _GCodeHighlighter(self.document())
        self._current_line = -1          # highlighted line (0-indexed)

        self._line_area = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_number_width)
        self.updateRequest.connect(self._update_line_number_area)

        self._update_line_number_width(0)
        
        # Apply initial font
        self._update_font()

    # ── Public API ──────────────────────────────────────────────────

    def load_file(self, path: str):
        try:
            with open(path, 'r', errors='replace') as fh:
                self.setPlainText(fh.read())
            self.document().setModified(False)
        except OSError:
            self.setPlainText(f"[File not readable: {path}]")
        self.set_current_line(-1)

    def set_current_line(self, line_num: int, move_cursor: bool = False):
        """Highlights line line_num and scrolls it into view (1-indexed).
        -1 = no highlight."""
        self._current_line = line_num - 1  # internal 0-indexed
        self.viewport().update()
        if line_num > 0:
            block = self.document().findBlockByLineNumber(line_num - 1)
            if block.isValid():
                cursor = QTextCursor(block)
                # Move cursor if explicitly requested or if we are in read-only mode (navigation)
                if move_cursor or self.isReadOnly():
                    self.setTextCursor(cursor)
                    self.centerCursor()
                else:
                    # Just scroll to it if it's the current executing line but don't steal cursor
                    self.ensureCursorVisible()

    # ── Line Numbers ────────────────────────────────────────────────────

    def _line_number_width(self) -> int:
        digits = max(1, len(str(self.blockCount())))
        return 10 + self.fontMetrics().horizontalAdvance('9') * digits

    def _update_line_number_width(self, _=0):
        self.setViewportMargins(self._line_number_width(), 0, 0, 0)

    def _update_line_number_area(self, rect: QRect, dy: int):
        if dy:
            self._line_area.scroll(0, dy)
        else:
            self._line_area.update(0, rect.y(),
                                   self._line_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_number_width()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_area.setGeometry(
            QRect(cr.left(), cr.top(), self._line_number_width(), cr.height()))

    def _paint_line_numbers(self, event):
        painter = QPainter(self._line_area)
        
        # Background for line numbers area (use theme colors if possible)
        bg_color = self.palette().color(QPalette.ColorRole.Window).darker(110)
        painter.fillRect(event.rect(), bg_color)

        block = self.firstVisibleBlock()
        block_num = block.blockNumber()
        top = round(self.blockBoundingGeometry(block)
                    .translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        fm = self.fontMetrics()

        pen_normal = self.palette().color(QPalette.ColorRole.Text)
        pen_normal.setAlpha(120)
        pen_current = self.palette().color(QPalette.ColorRole.Highlight)

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                is_current = (block_num == self._current_line)
                painter.setPen(pen_current if is_current else pen_normal)
                painter.drawText(
                    0, top,
                    self._line_area.width() - 5,
                    fm.height(),
                    Qt.AlignmentFlag.AlignRight,
                    str(block_num + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_num += 1

    # ── Current Line Highlight ────────────────────────────────────────

    def paintEvent(self, event):
        if self._current_line >= 0:
            painter = QPainter(self.viewport())
            block = self.document().findBlockByLineNumber(self._current_line)
            if block.isValid():
                rect = self.blockBoundingGeometry(block) \
                           .translated(self.contentOffset())
                # Use highlight color with transparency
                highlight_color = self.palette().color(QPalette.ColorRole.Highlight)
                highlight_color.setAlpha(40)
                painter.fillRect(
                    QRect(0, int(rect.top()),
                          self.viewport().width(), int(rect.height())),
                    highlight_color,
                )
            painter.end()
        super().paintEvent(event)

    def zoomIn(self, range: int = 1):
        self._font_size += range * 2
        self._update_font()

    def zoomOut(self, range: int = 1):
        self._font_size = max(6, self._font_size - range * 2)
        self._update_font()

    def set_font_size(self, size: int):
        self._font_size = size
        self._update_font()

    def _update_font(self):
        self.setStyleSheet(
            f"font-size: {self._font_size}pt; font-family: 'Monospace';"
        )
        self.zoom_changed.emit(self._font_size)

    def wheelEvent(self, event):
        """Handle zooming with Ctrl + Mouse Wheel."""
        if event.modifiers() & Qt.ControlModifier:
            if event.angleDelta().y() > 0:
                self.zoomIn(1)
            else:
                self.zoomOut(1)
            event.accept()
        else:
            super().wheelEvent(event)
