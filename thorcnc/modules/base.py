"""Base class for all ThorCNC functional modules."""


class ThorModule:
    """Base class for ThorCNC modules.

    Each module encapsulates a functional area (FileManager, Probing, Motion, etc.).
    Modules don't inherit from QObject—they're orchestrated by the main ThorCNC window.
    """

    def __init__(self, thorc):
        """Initialize module with reference to ThorCNC.

        Args:
            thorc: ThorCNC main window instance. Access via self._t.
                Provides: cmd, poller, settings, ini, ui, etc.
        """
        self._t = thorc

    def setup(self):
        """Build UI components and initialize state.

        Called after MainWindow._load_ui(), before any signals are wired.
        Override to create UI widgets and establish initial state.
        """
        pass

    def connect_signals(self):
        """Wire Qt signals between UI and logic.

        Called after all modules' setup() methods have completed.
        Override to connect clicked, changed, and poller signals.
        """
        pass

    def teardown(self):
        """Clean up before shutdown.

        Called when the application is closing.
        Override to release resources, save state, disconnect signals.
        """
        pass
