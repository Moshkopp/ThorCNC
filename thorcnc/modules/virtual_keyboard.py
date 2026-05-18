"""Touch-friendly virtual keyboard for text and numeric input widgets."""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QAbstractSpinBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
import shiboken6

from .base import ThorModule
from ..i18n import _t


class VirtualKeyboardDialog(QDialog):
    """Compact centered keyboard dialog that sends key events to a target."""

    _LETTERS = (
        "qwertzuiop",
        "asdfghjkl",
        "yxcvbnm",
    )
    _SYMBOLS = (
        "!\"'§$%&/()=",
        "+-*_:;@#<>",
        "[]{}\\|?^~",
    )
    _NUMBERS = (
        ("7", "8", "9"),
        ("4", "5", "6"),
        ("1", "2", "3"),
        (",", "0", "."),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("virtualKeyboardDialog")
        self.setWindowTitle(_t("Virtual Keyboard"))
        self.setModal(False)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._target = None
        self._shift = False
        self._symbols = False
        self._letter_buttons = []
        self._shift_btn = None
        self._sym_btn = None
        self._buffer = QLineEdit()
        self._buffer.setObjectName("virtualKeyboardBuffer")
        self._buffer.setMinimumHeight(42)
        self._buffer.installEventFilter(self)
        self._text_buffer = QTextEdit()
        self._text_buffer.setObjectName("virtualKeyboardTextBuffer")
        self._text_buffer.setMinimumHeight(110)
        self._text_buffer.installEventFilter(self)
        self._buffer_stack = QStackedWidget()
        self._buffer_stack.addWidget(self._buffer)
        self._buffer_stack.addWidget(self._text_buffer)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        edit_row = QHBoxLayout()
        edit_row.setSpacing(6)
        edit_row.addWidget(self._buffer_stack, 1)
        edit_row.addWidget(self._make_button("<", lambda _checked=False: self._move_cursor(-1)))
        edit_row.addWidget(self._make_button(">", lambda _checked=False: self._move_cursor(1)))
        edit_row.addWidget(self._make_button("CLR", lambda _checked=False: self._active_buffer().clear(), wide=True))
        edit_row.addWidget(self._make_button("BACK", self._backspace, wide=True))
        root.addLayout(edit_row)

        body = QHBoxLayout()
        body.setSpacing(10)
        self._letter_grid = QGridLayout()
        self._letter_grid.setSpacing(6)
        self._number_grid = QGridLayout()
        self._number_grid.setSpacing(6)

        body.addLayout(self._letter_grid, 4)
        body.addLayout(self._number_grid, 1)
        enter_btn = self._make_button("ENTER", self._enter, wide=True)
        enter_btn.setObjectName("virtualKeyboardEnterKey")
        enter_btn.setMinimumSize(86, 194)
        enter_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        body.addWidget(enter_btn)
        root.addLayout(body)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self._shift_btn = self._make_button("SHIFT", self._toggle_shift, wide=True)
        self._sym_btn = self._make_button("SYM", self._toggle_symbols, wide=True)
        self._shift_btn.setCheckable(True)
        self._sym_btn.setCheckable(True)
        actions.addWidget(self._shift_btn)
        actions.addWidget(self._sym_btn)
        actions.addWidget(self._make_button("NL", lambda _checked=False: self._send_text("\n"), wide=True))
        space_btn = self._make_button("SPACE", lambda _checked=False: self._send_text(" "), wide=True)
        space_btn.setMinimumWidth(220)
        actions.addWidget(space_btn, 1)
        actions.addWidget(self._make_button("ESC", self._cancel, wide=True))
        root.addLayout(actions)

        self._build_letters()
        self._build_numbers()
        self._refresh_mode_buttons()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._enter()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event):
        if watched in (self._buffer, self._text_buffer) and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self._cancel()
                return True
            if watched is self._buffer and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._enter()
                return True
        return super().eventFilter(watched, event)

    def _set_multiline_mode(self, enabled):
        self._buffer_stack.setCurrentWidget(self._text_buffer if enabled else self._buffer)

    def _is_multiline_mode(self):
        return self._buffer_stack.currentWidget() is self._text_buffer

    def _active_buffer(self):
        return self._text_buffer if self._is_multiline_mode() else self._buffer

    def _buffer_text(self):
        return self._text_buffer.toPlainText() if self._is_multiline_mode() else self._buffer.text()

    def _set_buffer_text(self, text, multiline=False):
        self._set_multiline_mode(multiline)
        if multiline:
            self._text_buffer.setPlainText(text)
            cursor = self._text_buffer.textCursor()
            cursor.select(QTextCursor.SelectionType.Document)
            self._text_buffer.setTextCursor(cursor)
        else:
            self._buffer.setText(text)
            self._buffer.setCursorPosition(len(text))
            self._buffer.selectAll()

    def _buffer_cursor_position(self):
        if self._is_multiline_mode():
            return self._text_buffer.textCursor().position()
        return self._buffer.cursorPosition()

    def set_target(self, widget):
        self._target = widget
        self._load_target_text(widget)

    def set_text_line_target(self, widget):
        cursor = widget.textCursor()
        start_block = cursor.block()
        end_block = start_block
        for _ in range(5):
            nxt = end_block.next()
            if not nxt.isValid():
                break
            end_block = nxt
        start = start_block.position()
        end = end_block.position() + max(0, end_block.length() - 1)
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self._target = ("text_block", widget, start, end, start_block.blockNumber())
        text = cursor.selectedText().replace("\u2029", "\n")
        self._set_buffer_text(text, multiline=True)

    def set_table_target(self, table, row, column):
        self._target = ("table", table, row, column)
        item = table.item(row, column) if shiboken6.isValid(table) else None
        self._set_buffer_text(item.text() if item else "", multiline=False)

    def show_for(self, widget):
        self.set_target(widget)
        if not self.isVisible():
            self.adjustSize()
            self.show()
        self.raise_()
        self._center_on_parent()

    def show_for_text_line(self, widget):
        self.set_text_line_target(widget)
        if not self.isVisible():
            self.adjustSize()
            self.show()
        self.raise_()
        self._center_on_parent()

    def show_for_table_cell(self, table, row, column):
        self.set_table_target(table, row, column)
        if not self.isVisible():
            self.adjustSize()
            self.show()
        self.raise_()
        self._center_on_parent()

    def _center_on_parent(self):
        parent = self.parentWidget()
        if not parent:
            return
        parent_rect = parent.frameGeometry()
        geom = self.frameGeometry()
        geom.moveCenter(parent_rect.center())
        self.move(geom.topLeft())

    def _build_letters(self):
        while self._letter_grid.count():
            item = self._letter_grid.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        self._letter_buttons.clear()
        rows = self._SYMBOLS if self._symbols else self._LETTERS
        for row, chars in enumerate(rows):
            offset = row if not self._symbols else 0
            for col, char in enumerate(chars):
                btn = self._make_button(char, lambda _checked=False, c=char: self._send_text(c))
                self._letter_grid.addWidget(btn, row, col + offset)
                self._letter_buttons.append(btn)
        self._refresh_letters()

    def _build_numbers(self):
        for row, values in enumerate(self._NUMBERS):
            for col, value in enumerate(values):
                btn = self._make_button(value, lambda _checked=False, c=value: self._send_text(c))
                btn.setObjectName("virtualKeyboardNumberKey")
                self._number_grid.addWidget(btn, row, col)

    def _make_button(self, text, callback, wide=False):
        btn = QPushButton(text)
        btn.setObjectName("virtualKeyboardKey")
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setMinimumSize(54 if not wide else 74, 44)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.clicked.connect(callback)
        return btn

    def _toggle_shift(self, _checked=False):
        self._shift = not self._shift
        self._refresh_letters()
        self._refresh_mode_buttons()

    def _toggle_symbols(self, _checked=False):
        self._symbols = not self._symbols
        self._shift = False
        self._build_letters()
        self._refresh_mode_buttons()

    def _refresh_letters(self):
        if self._symbols:
            return
        for btn in self._letter_buttons:
            label = btn.text()
            btn.setText(label.upper() if self._shift else label.lower())

    def _refresh_mode_buttons(self):
        if self._shift_btn:
            self._shift_btn.setChecked(self._shift)
            self._shift_btn.setProperty("active", self._shift)
            self._repolish(self._shift_btn)
        if self._sym_btn:
            self._sym_btn.setChecked(self._symbols)
            self._sym_btn.setProperty("active", self._symbols)
            self._repolish(self._sym_btn)

    def _send_text(self, text):
        text = str(text)
        if text == "\n" and not self._is_multiline_mode():
            return
        if not self._symbols and len(text) == 1 and text.isalpha() and self._shift:
            text = text.upper()
            self._shift = False
            self._refresh_letters()
            self._refresh_mode_buttons()
        if self._is_multiline_mode():
            self._text_buffer.textCursor().insertText(text)
        else:
            self._buffer.insert(text)

    def _backspace(self, _checked=False):
        if self._is_multiline_mode():
            cursor = self._text_buffer.textCursor()
            if cursor.hasSelection():
                cursor.removeSelectedText()
            else:
                cursor.deletePreviousChar()
            self._text_buffer.setTextCursor(cursor)
        else:
            self._buffer.backspace()

    def _enter(self, _checked=False):
        target = self._target_widget()
        if target is not None:
            self._write_buffer_to_target(target)
            self._commit_target(target)
            if not self._is_table_target(target) and not self._is_text_block_target(target) and shiboken6.isValid(target):
                target.clearFocus()
        self.close()

    def _cancel(self, _checked=False):
        self.close()

    def _move_cursor(self, delta):
        if self._is_multiline_mode():
            cursor = self._text_buffer.textCursor()
            op = QTextCursor.MoveOperation.Right if delta > 0 else QTextCursor.MoveOperation.Left
            for _ in range(abs(delta)):
                cursor.movePosition(op)
            self._text_buffer.setTextCursor(cursor)
            return
        pos = self._buffer.cursorPosition() + delta
        self._buffer.setCursorPosition(max(0, min(len(self._buffer.text()), pos)))

    def _target_widget(self):
        target = self._target
        if self._is_table_target(target):
            table = target[1]
            if table is None or not shiboken6.isValid(table):
                self._target = None
                return None
            return target
        if self._is_text_block_target(target):
            widget = target[1]
            if widget is None or not shiboken6.isValid(widget):
                self._target = None
                return None
            return target
        if target is None or not shiboken6.isValid(target):
            self._target = None
            return None
        return target

    def _is_table_target(self, target):
        return isinstance(target, tuple) and len(target) == 4 and target[0] == "table"

    def _is_text_block_target(self, target):
        return isinstance(target, tuple) and len(target) == 5 and target[0] == "text_block"

    def _line_edit_for(self, widget):
        if isinstance(widget, QLineEdit):
            return widget
        if isinstance(widget, QAbstractSpinBox):
            try:
                line_edit = widget.lineEdit()
                return line_edit if shiboken6.isValid(line_edit) else None
            except Exception:
                return None
        return None

    def _load_target_text(self, widget):
        if self._is_table_target(widget):
            _kind, table, row, column = widget
            item = table.item(row, column) if shiboken6.isValid(table) else None
            self._set_buffer_text(item.text() if item else "", multiline=False)
            return
        if self._is_text_block_target(widget):
            _kind, text_widget, start, end, _line = widget
            cursor = text_widget.textCursor()
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            self._set_buffer_text(cursor.selectedText().replace("\u2029", "\n"), multiline=True)
            return
        if widget is None or not shiboken6.isValid(widget):
            self._set_buffer_text("", multiline=False)
            return
        line_edit = self._line_edit_for(widget)
        if line_edit is not None:
            text = line_edit.text()
            self._set_buffer_text(text, multiline=False)
            return
        if isinstance(widget, QTextEdit):
            self._set_buffer_text(widget.toPlainText(), multiline=True)
            return
        if isinstance(widget, QPlainTextEdit):
            self._set_buffer_text(widget.toPlainText(), multiline=True)
            return
        self._set_buffer_text("", multiline=False)

    def _write_buffer_to_target(self, widget):
        text = self._buffer_text()
        if self._is_table_target(widget):
            _kind, table, row, column = widget
            if not shiboken6.isValid(table):
                return
            item = table.item(row, column)
            if item is None:
                item = QTableWidgetItem("")
                table.setItem(row, column, item)
            item.setText(text)
            table.setCurrentCell(row, column)
            return
        if self._is_text_block_target(widget):
            _kind, text_widget, start, end, start_line = widget
            if not shiboken6.isValid(text_widget):
                return
            text = self._renumber_gcode_text(text_widget, text, start_line)
            cursor = text_widget.textCursor()
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            cursor.insertText(text)
            text_widget.setTextCursor(cursor)
            new_pos = start + min(len(text), self._buffer_cursor_position())
            cursor.setPosition(new_pos)
            text_widget.setTextCursor(cursor)
            return
        if shiboken6.isValid(widget):
            widget.setFocus(Qt.FocusReason.OtherFocusReason)
        if isinstance(widget, QAbstractSpinBox):
            line_edit = self._line_edit_for(widget)
            if line_edit is not None:
                line_edit.setText(text)
                line_edit.setCursorPosition(min(len(text), self._buffer_cursor_position()))
            try:
                widget.interpretText()
            except Exception:
                pass
            return
        line_edit = self._line_edit_for(widget)
        if line_edit is not None:
            line_edit.setText(text)
            line_edit.setCursorPosition(self._buffer_cursor_position())
            return
        if isinstance(widget, (QTextEdit, QPlainTextEdit)):
            widget.setPlainText(text)
            cursor = widget.textCursor()
            cursor.setPosition(min(len(text), self._buffer_cursor_position()))
            widget.setTextCursor(cursor)

    def _delete_previous(self, widget):
        line_edit = self._line_edit_for(widget)
        if line_edit is not None:
            line_edit.backspace()
            return
        if isinstance(widget, (QTextEdit, QPlainTextEdit)):
            cursor = widget.textCursor()
            if not cursor.hasSelection():
                cursor.deletePreviousChar()
            else:
                cursor.removeSelectedText()
            widget.setTextCursor(cursor)

    def _commit_target(self, widget):
        if self._is_table_target(widget):
            _kind, table, _row, _column = widget
            if shiboken6.isValid(table):
                table.clearFocus()
            return
        if self._is_text_block_target(widget):
            _kind, text_widget, _start, _end, _line = widget
            if shiboken6.isValid(text_widget):
                text_widget.clearFocus()
            return
        if isinstance(widget, QAbstractSpinBox):
            try:
                widget.editingFinished.emit()
            except Exception:
                pass
            return
        line_edit = self._line_edit_for(widget)
        if line_edit is not None:
            try:
                line_edit.returnPressed.emit()
            except Exception:
                self._send_key(line_edit, Qt.Key.Key_Return, "\r")
            return
        if isinstance(widget, (QTextEdit, QPlainTextEdit)):
            cursor = widget.textCursor()
            cursor.clearSelection()
            widget.setTextCursor(cursor)

    def _renumber_gcode_text(self, text_widget, text, start_line):
        if not self._is_gcode_widget(text_widget):
            return text
        start_n, step = self._detect_gcode_n_sequence(text_widget, start_line)
        if start_n is None:
            return text

        import re
        number = start_n
        out = []
        for line in text.splitlines():
            if re.match(r"^\s*N\d+\b", line, re.IGNORECASE):
                line = re.sub(r"^(\s*)N\d+\b", rf"\1N{number}", line, count=1, flags=re.IGNORECASE)
                number += step
            out.append(line)
        return "\n".join(out)

    def _detect_gcode_n_sequence(self, text_widget, start_line):
        import re

        lines = text_widget.toPlainText().splitlines()

        def n_at(idx):
            if 0 <= idx < len(lines):
                m = re.match(r"\s*N(\d+)\b", lines[idx], re.IGNORECASE)
                if m:
                    return int(m.group(1))
            return None

        current = n_at(start_line)
        prev_idx = next((i for i in range(start_line - 1, -1, -1) if n_at(i) is not None), None)
        next_idx = next((i for i in range(start_line + 1, len(lines)) if n_at(i) is not None), None)
        prev_n = n_at(prev_idx) if prev_idx is not None else None
        next_n = n_at(next_idx) if next_idx is not None else None

        step = 1
        if current is not None and next_n is not None and next_n > current:
            step = max(1, (next_n - current) // max(1, next_idx - start_line))
        elif current is not None and prev_n is not None and current > prev_n:
            step = max(1, (current - prev_n) // max(1, start_line - prev_idx))
        elif prev_n is not None and next_n is not None and next_n > prev_n:
            step = max(1, (next_n - prev_n) // max(1, next_idx - prev_idx))

        if current is not None:
            return current, step
        if prev_n is not None:
            return prev_n + step * max(1, start_line - prev_idx), step
        return None, step

    def _is_gcode_widget(self, widget):
        names = {"gcodeViewer", "filePreviewArea"}
        candidate = widget
        while candidate is not None:
            if candidate.objectName() in names:
                return True
            candidate = candidate.parent()
        return False

    def _send_key(self, target, key, text):
        if target is None or not shiboken6.isValid(target):
            return
        press = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, text)
        release = QKeyEvent(QEvent.Type.KeyRelease, key, Qt.KeyboardModifier.NoModifier, text)
        try:
            QApplication.sendEvent(target, press)
            if shiboken6.isValid(target):
                QApplication.sendEvent(target, release)
        except RuntimeError:
            self._target = None

    def _repolish(self, widget):
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()


class VirtualKeyboardModule(ThorModule):
    """Integrates the virtual keyboard with ThorCNC's global event filter."""

    _INPUT_TYPES = (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QTableWidget)

    def setup(self):
        self._enabled = bool(self._t.settings.get("virtual_keyboard_enabled", False))
        self._dialog = VirtualKeyboardDialog(self._t.ui)
        self._toggle_btn = self._ensure_toggle_button()
        self._sync_toggle_button()

    def connect_signals(self):
        if self._toggle_btn:
            self._toggle_btn.toggled.connect(self._set_enabled)

    def handle_event(self, watched, event):
        if not self._enabled:
            return False
        if event.type() != QEvent.Type.MouseButtonPress:
            return False
        widget = self._input_widget(watched, event)
        if widget is None:
            return False
        if isinstance(widget, tuple) and widget[0] == "table":
            _kind, table, row, column = widget
            self._dialog.show_for_table_cell(table, row, column)
            return False
        if isinstance(widget, tuple) and widget[0] == "text_block":
            _kind, text_widget = widget
            self._dialog.show_for_text_line(text_widget)
            return False
        self._dialog.show_for(widget)
        return False

    def refresh_theme(self):
        if getattr(self, "_dialog", None):
            self._dialog.style().unpolish(self._dialog)
            self._dialog.style().polish(self._dialog)
            self._dialog.update()
        self._sync_toggle_button()

    def _ensure_toggle_button(self):
        existing = self._t.ui.findChild(QPushButton, "btn_virtual_keyboard")
        if existing:
            return existing

        jog = self._t.ui.findChild(QWidget, "jog_xyz")
        if not jog or not jog.layout():
            return None

        btn = QPushButton("KBD")
        btn.setObjectName("btn_virtual_keyboard")
        btn.setToolTip(_t("Virtual keyboard"))
        btn.setCheckable(True)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setMinimumSize(54, 40)
        btn.setMaximumHeight(44)

        layout = jog.layout()
        try:
            layout.addWidget(btn, 0, 2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        except TypeError:
            layout.addWidget(btn)
        return btn

    def _set_enabled(self, enabled):
        self._enabled = bool(enabled)
        self._t.settings.set("virtual_keyboard_enabled", self._enabled)
        self._t.settings.save()
        if not self._enabled and self._dialog.isVisible():
            self._dialog.close()
        self._sync_toggle_button()

    def _sync_toggle_button(self):
        if not self._toggle_btn:
            return
        self._toggle_btn.blockSignals(True)
        self._toggle_btn.setChecked(self._enabled)
        self._toggle_btn.setProperty("active", self._enabled)
        self._toggle_btn.style().unpolish(self._toggle_btn)
        self._toggle_btn.style().polish(self._toggle_btn)
        self._toggle_btn.blockSignals(False)

    def _input_widget(self, widget, event):
        if self._is_keyboard_widget(widget):
            return None

        candidate = widget
        while candidate is not None:
            if isinstance(candidate, QTableWidget):
                return self._table_target(candidate, widget, event)
            if isinstance(candidate, QPlainTextEdit) and self._is_gcode_editor(candidate):
                return self._text_line_target(candidate, widget, event)
            if isinstance(candidate, self._INPUT_TYPES):
                if self._is_editable(candidate):
                    return candidate
                return None
            candidate = candidate.parent()
        return None

    def _table_target(self, table, watched, event):
        viewport = table.viewport()
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        if watched is not viewport and isinstance(watched, QWidget):
            pos = viewport.mapFrom(watched, pos)
        item = table.itemAt(pos)
        if item is None:
            return None
        if not item.flags() & Qt.ItemFlag.ItemIsEditable:
            return None
        table.setCurrentItem(item)
        return ("table", table, item.row(), item.column())

    def _text_line_target(self, text_widget, watched, event):
        if text_widget.isReadOnly():
            return None
        viewport = text_widget.viewport()
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        if watched is not viewport and isinstance(watched, QWidget):
            pos = viewport.mapFrom(watched, pos)
        cursor = text_widget.cursorForPosition(pos)
        text_widget.setTextCursor(cursor)
        return ("text_block", text_widget)

    def _is_keyboard_widget(self, widget):
        dialog = getattr(self, "_dialog", None)
        while widget is not None:
            if widget is dialog:
                return True
            widget = widget.parent()
        return False

    def _is_editable(self, widget):
        if not widget.isEnabled():
            return False
        if isinstance(widget, QLineEdit):
            return not widget.isReadOnly()
        if isinstance(widget, (QTextEdit, QPlainTextEdit)):
            return not widget.isReadOnly()
        if isinstance(widget, QAbstractSpinBox):
            return not widget.isReadOnly()
        return True

    def _is_gcode_editor(self, widget):
        names = {"gcodeViewer", "filePreviewArea"}
        candidate = widget
        while candidate is not None:
            if candidate.objectName() in names:
                return True
            candidate = candidate.parent()
        return False
