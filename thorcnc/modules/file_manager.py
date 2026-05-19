"""File Manager Module for ThorCNC.

Handles:
- File browser (QFileSystemModel + QTreeView)
- G-Code file preview (editable)
- File loading and saving
- Directory navigation with breadcrumbs
"""

import os
import linuxcnc
from PySide6.QtCore import Qt, QDir
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QTreeView, QWidget, QHBoxLayout, QLabel,
                               QPushButton, QFileDialog, QFileSystemModel,
                               QComboBox, QFrame)


from .base import ThorModule
from ._theme_utils import theme_color
from ..gcode_parser import parse_file
from ..widgets.gcode_view import GCodeView
from ..i18n import _t


class _GCodeFileSystemModel(QFileSystemModel):
    """QFileSystemModel that highlights .nc/.ngc files with a distinct color."""

    _GCODE_EXTS = {".nc", ".ngc"}

    def __init__(self, parent=None, thorc=None):
        super().__init__(parent)
        self._thorc = thorc
        self._color = QColor(theme_color(thorc, "marker.gcode")) if thorc else QColor("#4ec9b0")

    def refresh_color(self):
        if self._thorc is not None:
            self._color = QColor(theme_color(self._thorc, "marker.gcode"))

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 0:
            path = self.filePath(index)
            if os.path.splitext(path)[1].lower() in self._GCODE_EXTS:
                return self._color
        return super().data(index, role)


class FileManagerModule(ThorModule):
    """File management and G-Code file browser."""

    def setup(self):
        """Initialize file manager UI."""
        self._setup_file_manager()

    def refresh_theme(self):
        """Update G-Code marker color after a theme switch and repaint."""
        if hasattr(self, "_fs_model") and self._fs_model:
            self._fs_model.refresh_color()
            tree = self._t._w(QTreeView, "fileManagerView")
            if tree and tree.viewport():
                tree.viewport().update()

    def connect_signals(self):
        """Wire file manager signals."""
        tree = self._t._w(QTreeView, "fileManagerView")
        if tree:
            tree.selectionModel().selectionChanged.connect(self._on_file_selected)
            tree.doubleClicked.connect(self._on_file_double_clicked)

        if self._t._btn_nav_up:
            self._t._btn_nav_up.clicked.connect(self._nav_up)
        if self._t._btn_nav_home:
            self._t._btn_nav_home.clicked.connect(self._nav_home)
        if getattr(self._t, "_cmb_filter_gcode", None):
            self._t._cmb_filter_gcode.currentIndexChanged.connect(self._on_filter_changed)

        if self._t._btn_load:
            self._t._btn_load.clicked.connect(self._load_selected_file)

        if self._t._btn_save:
            self._t._btn_save.clicked.connect(self._save_file)
        if self._t._btn_save_as:
            self._t._btn_save_as.clicked.connect(self._save_as_file)
        if self._t._btn_cancel:
            self._t._btn_cancel.clicked.connect(self._cancel_edit)

        # File loaded signal
        if self._t.poller:
            self._t.poller.file_loaded.connect(self._on_file_loaded)

    def _setup_file_manager(self):
        """Build file manager UI."""
        tree = self._t._w(QTreeView, "fileManagerView")

        # Replace filePreviewArea placeholder with editable GCodeView
        old_preview = self._t.ui.findChild(QWidget, "filePreviewArea")
        if old_preview:
            parent = old_preview.parent()
            lay = parent.layout()
            idx = lay.indexOf(old_preview)
            lay.removeWidget(old_preview)
            old_preview.deleteLater()

            self._t._file_preview = GCodeView(editable=True)
            self._t._file_preview.setObjectName("filePreviewArea")
            e_size = self._t.settings.get("editor_gcode_font_size", 22)
            self._t._file_preview.set_font_size(e_size)
            self._t._file_preview.zoom_changed.connect(
                lambda s: (self._t.settings.set("editor_gcode_font_size", s), self._t.settings.save()))
            lay.insertWidget(idx, self._t._file_preview)
        else:
            self._t._file_preview = self._t._w(GCodeView, "filePreviewArea")

        # Get button refs
        self._t._btn_load = self._t._w(QPushButton, "load_gcode_button")
        self._t._btn_save = self._t._w(QPushButton, "btn_save_file")
        self._t._btn_save_as = self._t._w(QPushButton, "btn_save_as_file")
        self._t._btn_cancel = self._t._w(QPushButton, "btn_cancel_edit")

        self._t._btn_zoom_in = self._t._w(QPushButton, "btn_zoom_in")
        self._t._btn_zoom_out = self._t._w(QPushButton, "btn_zoom_out")
        if self._t._btn_zoom_in:
            self._t._btn_zoom_in.clicked.connect(lambda: self._t._file_preview.zoomIn(1))
        if self._t._btn_zoom_out:
            self._t._btn_zoom_out.clicked.connect(lambda: self._t._file_preview.zoomOut(1))

        self._t._btn_nav_up = self._t._w(QPushButton, "btn_nav_up")
        self._t._btn_nav_home = self._t._w(QPushButton, "btn_nav_home")

        # Nav button styling
        if self._t._btn_nav_up:
            self._t._btn_nav_up.setText("↑")
            self._t._btn_nav_up.setFixedWidth(60)
            self._t._btn_nav_up.setToolTip(_t("Parent Directory"))

        if self._t._btn_nav_home:
            self._t._btn_nav_home.setText("⌂")
            self._t._btn_nav_home.setFixedWidth(60)
            self._t._btn_nav_home.setToolTip(_t("Home Directory"))

        # G-Code filter combobox (below the tree, separated by a horizontal line)
        self._t._cmb_filter_gcode = QComboBox()
        self._t._cmb_filter_gcode.setObjectName("fileFilterCombo")
        self._t._cmb_filter_gcode.setFixedHeight(46)
        self._t._cmb_filter_gcode.setMinimumWidth(220)
        self._t._cmb_filter_gcode.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Items: (label, mode-id stored in settings)
        filter_items = [
            (_t("Show all"), "all"),
            (_t("Only .nc + .ngc"), "gcode"),
            (_t("Only .nc"), "nc"),
            (_t("Only .ngc"), "ngc"),
        ]
        for label, mode in filter_items:
            self._t._cmb_filter_gcode.addItem(label, mode)

        saved_mode = self._t.settings.get("file_filter_mode", "gcode")
        idx = self._t._cmb_filter_gcode.findData(saved_mode)
        self._t._cmb_filter_gcode.setCurrentIndex(idx if idx >= 0 else 1)

        self._t.navigation.update_nav_icons()

        # Breadcrumb setup
        self._t._breadcrumb_container = self._t._w(QWidget, "breadcrumb_container")
        self._t._breadcrumb_layout = None
        if self._t._breadcrumb_container:
            self._t._breadcrumb_layout = QHBoxLayout(self._t._breadcrumb_container)
            self._t._breadcrumb_layout.setContentsMargins(0, 0, 0, 0)
            self._t._breadcrumb_layout.setSpacing(2)

        if not tree or not self._t._file_preview or not self._t._btn_load:
            return

        # Determine start directory
        start_dir = os.path.expanduser("~/linuxcnc/nc_files")
        if self._t.ini and self._t.ini_path:
            cfg_dir = self._t.ini.find("DISPLAY", "PROGRAM_PREFIX")
            if cfg_dir:
                cfg_dir = os.path.expanduser(cfg_dir)
                if not os.path.isabs(cfg_dir):
                    ini_dir = os.path.dirname(self._t.ini_path)
                    cfg_dir = os.path.abspath(os.path.join(ini_dir, cfg_dir))
                start_dir = cfg_dir

        if not os.path.exists(start_dir):
            try:
                os.makedirs(start_dir, exist_ok=True)
            except Exception:
                start_dir = os.path.expanduser("~/linuxcnc/nc_files")

        self._file_home_dir = start_dir

        # File system model
        self._fs_model = _GCodeFileSystemModel(thorc=self._t)
        self._fs_model.setRootPath(start_dir)
        self._fs_model.setFilter(QDir.AllDirs | QDir.Files | QDir.NoDotAndDotDot)
        # Hide non-matching files (instead of just greying them out)
        self._fs_model.setNameFilterDisables(False)

        tree.setModel(self._fs_model)
        tree.setColumnWidth(0, 300)
        tree.hideColumn(1)  # size
        tree.hideColumn(2)  # type
        tree.hideColumn(3)  # date

        # Insert horizontal separator + filter combobox row below the tree
        parent_layout = tree.parent().layout() if tree.parent() else None
        if parent_layout is not None:
            tree_idx = parent_layout.indexOf(tree)
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setFrameShadow(QFrame.Sunken)
            sep.setObjectName("file_filter_separator")
            sep.setFixedHeight(2)
            parent_layout.insertWidget(tree_idx + 1, sep)

            filter_row = QHBoxLayout()
            filter_row.setContentsMargins(4, 6, 4, 4)
            filter_row.setSpacing(8)
            filter_label = QLabel(_t("Filter:"))
            filter_label.setObjectName("fileFilterLabel")
            filter_label.setMinimumHeight(44)
            filter_row.addWidget(filter_label)
            filter_row.addWidget(self._t._cmb_filter_gcode, 1)
            parent_layout.insertLayout(tree_idx + 2, filter_row)

        # Apply the initial filter now that the model is wired to the view
        self._apply_gcode_filter(self._current_filter_mode())

        # Initial state
        self._selected_filepath = None
        if self._t._btn_load:
            self._t._btn_load.setEnabled(False)
        if self._t._btn_save:
            self._t._btn_save.setEnabled(False)
        if self._t._btn_save_as:
            self._t._btn_save_as.setEnabled(False)
        if self._t._btn_cancel:
            self._t._btn_cancel.setEnabled(False)

        # Navigate to last directory or start
        last_dir = self._t.settings.get("last_file_dir")
        if last_dir and os.path.exists(last_dir):
            self._nav_set_dir(last_dir)
        else:
            self._nav_set_dir(start_dir)

    def _nav_set_dir(self, path: str):
        """Change file browser root to directory."""
        tree = self._t._w(QTreeView, "fileManagerView")
        if tree and os.path.isdir(path):
            tree.setRootIndex(self._fs_model.index(path))
            self._current_dir = path
            if hasattr(self._t, "_breadcrumb_container") and self._t._breadcrumb_container:
                self._update_breadcrumbs(path)

    def _update_breadcrumbs(self, path: str):
        """Update breadcrumb navigation buttons."""
        if not self._t._breadcrumb_layout:
            return

        while self._t._breadcrumb_layout.count():
            item = self._t._breadcrumb_layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        path = os.path.normpath(path)
        parts = [p for p in path.split(os.sep) if p]

        self._add_breadcrumb_button("/", os.sep)

        current_acc = os.sep
        for part in parts:
            sep = QLabel("›")
            sep.setObjectName("breadcrumb_sep")
            self._t._breadcrumb_layout.addWidget(sep)

            current_acc = os.path.join(current_acc, part)
            self._add_breadcrumb_button(part, current_acc)

        self._t._breadcrumb_layout.addStretch()

    def _add_breadcrumb_button(self, text: str, path: str):
        """Add single breadcrumb button."""
        btn = QPushButton(text)
        btn.setObjectName("breadcrumb_item")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda: self._nav_set_dir(path))
        self._t._breadcrumb_layout.addWidget(btn)

    _FILTER_PATTERNS = {
        "all": None,
        "gcode": ["*.nc", "*.ngc", "*.NC", "*.NGC"],
        "nc": ["*.nc", "*.NC"],
        "ngc": ["*.ngc", "*.NGC"],
    }

    def _current_filter_mode(self) -> str:
        cmb = getattr(self._t, "_cmb_filter_gcode", None)
        if cmb is None:
            return "gcode"
        mode = cmb.currentData()
        return mode if mode in self._FILTER_PATTERNS else "gcode"

    def _apply_gcode_filter(self, mode: str):
        """Apply name filter to the file system model based on selected mode."""
        if not getattr(self, "_fs_model", None):
            return
        patterns = self._FILTER_PATTERNS.get(mode)
        if patterns is None:
            self._fs_model.setNameFilters([])
            self._fs_model.setNameFilterDisables(True)
        else:
            self._fs_model.setNameFilters(patterns)
            self._fs_model.setNameFilterDisables(False)

        # Force the view to re-read the current directory
        tree = self._t._w(QTreeView, "fileManagerView")
        if tree is not None and hasattr(self, "_current_dir"):
            self._fs_model.setRootPath("")
            self._fs_model.setRootPath(self._current_dir)
            tree.setRootIndex(self._fs_model.index(self._current_dir))

    def _on_filter_changed(self, _idx: int):
        """Persist combobox selection and re-apply name filter."""
        mode = self._current_filter_mode()
        self._t.settings.set("file_filter_mode", mode)
        self._t.settings.save()
        self._apply_gcode_filter(mode)

    def _nav_up(self):
        """Navigate to parent directory."""
        if hasattr(self, "_current_dir"):
            parent_dir = os.path.dirname(self._current_dir)
            if parent_dir and parent_dir != self._current_dir:
                self._nav_set_dir(parent_dir)

    def _nav_home(self):
        """Navigate to configured home directory."""
        if hasattr(self, "_file_home_dir"):
            self._nav_set_dir(self._file_home_dir)

    def _on_file_double_clicked(self, idx):
        """Handle double-click: directory → navigate, file → load."""
        path = self._fs_model.filePath(idx)
        if os.path.isdir(path):
            self._nav_set_dir(path)
        else:
            self._selected_filepath = path
            self._load_selected_file()

    def _on_file_selected(self):
        """Handle file selection: show preview and enable buttons."""
        tree = self._t._w(QTreeView, "fileManagerView")
        idx = tree.currentIndex()
        if not idx.isValid():
            return

        path = self._fs_model.filePath(idx)
        if os.path.isdir(path):
            self._t.settings.set("last_file_dir", path)
            self._selected_filepath = None
            if self._t._btn_load:
                self._t._btn_load.setEnabled(False)
            self._t._file_preview.setPlainText(_t("[FOLDER SELECTED]"))
        else:
            self._t.settings.set("last_file_dir", os.path.dirname(path))
            self._selected_filepath = path
            if self._t._btn_load:
                self._t._btn_load.setEnabled(True)
            if self._t._btn_save:
                self._t._btn_save.setEnabled(True)
            if self._t._btn_save_as:
                self._t._btn_save_as.setEnabled(True)
            if self._t._btn_cancel:
                self._t._btn_cancel.setEnabled(True)

            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                self._t._file_preview.setPlainText(content)
            except Exception as e:
                self._t._file_preview.setPlainText(_t("Error loading:") + f"\n{e}")

    def _save_file(self):
        """Overwrite currently open file."""
        if not self._selected_filepath:
            return

        try:
            content = self._t._file_preview.toPlainText()
            with open(self._selected_filepath, "w", encoding="utf-8") as f:
                f.write(content)
            self._t._status(_t("File saved: {}").format(os.path.basename(self._selected_filepath)))
        except Exception as e:
            self._t._status(f"Error saving file: {e}", error=True)

    def _save_as_file(self):
        """Save file with new name."""
        start_dir = self._current_dir if hasattr(self, "_current_dir") else os.path.expanduser("~")
        path, _ = QFileDialog.getSaveFileName(self._t.ui, _t("SAVE AS"), start_dir,
                                              "G-Code (*.ngc *.tap *.txt);;All Files (*)")

        if path:
            try:
                content = self._t._file_preview.toPlainText()
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                self._selected_filepath = path
                self._t._status(_t("File saved as: {}").format(os.path.basename(path)))
            except Exception as e:
                self._t._status(f"Error saving file: {e}", error=True)

    def _cancel_edit(self):
        """Revert editor to last saved state."""
        if self._selected_filepath:
            self._on_file_selected()
        else:
            self._t._file_preview.clear()

    def _load_selected_file(self):
        """Load file into LinuxCNC."""
        if self._selected_filepath:
            self._t._user_program = self._selected_filepath
            if self._t.poller:
                self._t.poller.reset_file_state()
            self._t.cmd.mode(linuxcnc.MODE_AUTO)
            self._t.cmd.wait_complete()
            self._t.cmd.program_open(self._selected_filepath)

            from PySide6.QtWidgets import QTabWidget
            if tab := self._t._w(QTabWidget, "tabWidget"):
                tab.setCurrentIndex(0)

    def _on_file_loaded(self, path: str):
        """Handle file_loaded signal from poller."""
        if not path or not os.path.isfile(path):
            return
        if path != self._t._user_program:
            return

        self._t._has_file = True
        self._t.gcode_view.load_file(path)
        tp = parse_file(path)
        self._t._last_toolpath = tp
        self._t.backplot.load_toolpath(tp)

        sv = self._t.simple_view_mod.simple_view
        if sv and sv.backplot:
            sv.backplot.load_toolpath(tp)
            sv.load_gcode(path)

        self._t._update_run_buttons()

