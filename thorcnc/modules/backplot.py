"""Backplot/3D View Module.

Handles:
- Backplot widget initialization and configuration
- View perspective management (ISO, TOP, FRONT, SIDE)
- Toolpath loading and display
- View state save/restore
"""

from PySide6.QtWidgets import QPushButton
from PySide6.QtCore import Slot, Qt, QTimer

from thorcnc.widgets.backplot import BackplotWidget
from thorcnc.i18n import _t
from .base import ThorModule


class BackplotModule(ThorModule):
    """Manages 3D backplot view and visualization."""

    def __init__(self, app):
        """Initialize backplot module."""
        super().__init__(app)
        self.backplot = None
        self._view_restored = False

    def setup(self):
        """Initialize backplot widget and view buttons."""
        self._setup_backplot()

    def _setup_backplot(self):
        """Create and configure backplot widget."""
        # Get MSAA samples from settings
        _msaa = self._t.settings.get("msaa_samples", 4)
        self.backplot = BackplotWidget(msaa_samples=_msaa)
        self.backplot.setObjectName("vtk")

        # Create toolbar with view buttons
        tb_lay = self.backplot.toolbar_layout()
        for label, fn in (
            (_t("ISO"), self.backplot.set_view_iso),
            (_t("TOP"), self.backplot.set_view_z),
            (_t("FRONT"), self.backplot.set_view_y),
            (_t("SIDE"), self.backplot.set_view_x),
            (_t("CLR TRAIL"), self.backplot.clear_trail)
        ):
            btn = QPushButton(label)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.clicked.connect(fn)
            tb_lay.addWidget(btn)
        tb_lay.addStretch()  # Push buttons to the left

        # Restore saved view state from settings
        bpm = self._t.settings.get("backplot_view", None)
        if bpm:
            self.backplot.set_view_opts(bpm)
            self._view_restored = True

        # Apply saved backplot colors
        saved_colors = self._t.settings.get("backplot_colors", {})
        if saved_colors:
            self.backplot.set_colors(saved_colors)

        # Set machine envelope (from HAL/INI config)
        self._set_machine_envelope()

    def _set_machine_envelope(self):
        """Set machine working envelope from INI configuration."""
        if not self._t.ini:
            return

        def lim(axis, key, default):
            v = self._t.ini.find(f"AXIS_{axis}", key)
            return float(v) if v else default

        envelope = dict(
            x_min=lim("X", "MIN_LIMIT", 0),
            x_max=lim("X", "MAX_LIMIT", 600),
            y_min=lim("Y", "MIN_LIMIT", 0),
            y_max=lim("Y", "MAX_LIMIT", 500),
            z_min=lim("Z", "MIN_LIMIT", -200),
            z_max=lim("Z", "MAX_LIMIT", 0),
        )
        self.backplot.set_machine_envelope(**envelope)
        # Store for SimpleView overlay (created later)
        self._t._backplot_envelope = envelope

    def connect_signals(self):
        """Connect backplot signals from poller."""
        self._t.poller.program_line.connect(self._on_program_line)
        self._t.poller.homed_changed.connect(self._on_homed)

    @Slot(list)
    def _on_homed(self, homed: list):
        if all(i < len(homed) and homed[i] for i in range(3)):
            if self.backplot:
                self.backplot.hide_splash()

    @Slot(int)
    def _on_program_line(self, line: int):
        """Update backplot highlight when program line changes."""
        # Program line tracking is handled by backplot widget itself
        # This can be extended for additional tracking if needed
        pass

    def get_backplot_widget(self):
        """Return the backplot widget for insertion into UI."""
        return self.backplot

    def save_view_state(self):
        """Save current backplot view state to settings."""
        if self.backplot and hasattr(self.backplot, "get_view_opts"):
            view_opts = self.backplot.get_view_opts()
            self._t.settings.set("backplot_view", view_opts)

    def replace_vtk_placeholder(self):
        """Replace the vtk placeholder widget with the backplot widget."""
        from PySide6.QtWidgets import QSplitter, QWidget
        from PySide6.QtCore import QTimer
        old_vtk = self._t.ui.findChild(QWidget, "vtk")
        parent_vtk = old_vtk.parent() if old_vtk else None
        if parent_vtk:
            if isinstance(parent_vtk, QSplitter):
                idx = parent_vtk.indexOf(old_vtk)
                parent_vtk.replaceWidget(idx, self.backplot)
            elif parent_vtk.layout():
                lay = parent_vtk.layout()
                idx = lay.indexOf(old_vtk)
                lay.removeWidget(old_vtk)
                lay.insertWidget(idx, self.backplot)
            old_vtk.deleteLater()
        self._t.backplot = self.backplot
        if self._view_restored:
            QTimer.singleShot(1500, self.clear_view_restored_flag)
        QTimer.singleShot(800, lambda: self.backplot.start_splash("ThorCNC"))

    def clear_view_restored_flag(self):
        """Reset the view restored flag."""
        self._view_restored = False
