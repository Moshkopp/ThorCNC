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
            # T (Werkzeug)
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
    """Schreibgeschützter G-Code Viewer mit Zeilennummern und Highlighting."""

    line_selected = Signal(int)   # Benutzer klickt auf eine Zeile

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        font = QFont("Monospace", 10)
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        self.setFont(font)

        self._highlighter = _GCodeHighlighter(self.document())
        self._current_line = -1          # hevorgehobene Zeile (0-basiert)

        self._line_area = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_number_width)
        self.updateRequest.connect(self._update_line_number_area)

        self._update_line_number_width(0)

        # Hintergrundfarben
        self._bg_current = QColor("#2c3e50")   # aktuelle Zeile
        self._fg_linenum  = QColor("#5d6d7e")
        self._fg_linenum_current = QColor("#aaaaaa")

    # ── Öffentliche API ──────────────────────────────────────────────────

    def load_file(self, path: str):
        try:
            with open(path, 'r', errors='replace') as fh:
                self.setPlainText(fh.read())
        except OSError:
            self.setPlainText(f"[Datei nicht lesbar: {path}]")
        self.set_current_line(-1)

    def set_current_line(self, line_num: int):
        """Hebt Zeile line_num hervor und scrollt sie sichtbar (1-basiert).
        -1 = keine Hervorhebung."""
        self._current_line = line_num - 1  # intern 0-basiert
        self.viewport().update()
        if line_num > 0:
            block = self.document().findBlockByLineNumber(line_num - 1)
            if block.isValid():
                cursor = QTextCursor(block)
                self.setTextCursor(cursor)
                self.centerCursor()

    # ── Zeilennummern ────────────────────────────────────────────────────

    def _line_number_width(self) -> int:
        digits = max(1, len(str(self.blockCount())))
        return 6 + self.fontMetrics().horizontalAdvance('9') * digits

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
        painter.fillRect(event.rect(), QColor("#1e1e1e"))

        block = self.firstVisibleBlock()
        block_num = block.blockNumber()
        top = round(self.blockBoundingGeometry(block)
                    .translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        fm = self.fontMetrics()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                is_current = (block_num == self._current_line)
                painter.setPen(self._fg_linenum_current if is_current
                               else self._fg_linenum)
                painter.drawText(
                    0, top,
                    self._line_area.width() - 3,
                    fm.height(),
                    Qt.AlignmentFlag.AlignRight,
                    str(block_num + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_num += 1

    # ── Aktuelle Zeile hervorheben ────────────────────────────────────────

    def paintEvent(self, event):
        if self._current_line >= 0:
            painter = QPainter(self.viewport())
            block = self.document().findBlockByLineNumber(self._current_line)
            if block.isValid():
                rect = self.blockBoundingGeometry(block) \
                           .translated(self.contentOffset())
                painter.fillRect(
                    QRect(0, int(rect.top()),
                          self.viewport().width(), int(rect.height())),
                    self._bg_current,
                )
            painter.end()
        super().paintEvent(event)
