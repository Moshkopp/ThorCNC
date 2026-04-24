"""ThorCNC Module System

Modular architecture for organizing ThorCNC functionality.
Each module handles a specific domain (FileManager, Probing, Motion, etc.).
"""

from .base import ThorModule
from .file_manager import FileManagerModule
from .tool_table import ToolTableModule
from .offsets import OffsetsModule
from .motion import MotionModule
from .probing_tab import ProbingTabModule
from .navigation import NavigationModule
from .settings_tab import SettingsTabModule
from .dro import DROModule
from .spindle import SpindleModule
from .simple_view import SimpleViewModule
from .gcode_view import GCodeViewModule
from .mdi import MDIModule

__all__ = [
    "ThorModule",
    "FileManagerModule",
    "ToolTableModule",
    "OffsetsModule",
    "MotionModule",
    "ProbingTabModule",
    "NavigationModule",
    "SettingsTabModule",
    "DROModule",
    "SpindleModule",
    "SimpleViewModule",
    "GCodeViewModule",
    "MDIModule"
]
