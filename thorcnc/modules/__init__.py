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

__all__ = [
    "ThorModule",
    "FileManagerModule",
    "ToolTableModule",
    "OffsetsModule",
    "MotionModule",
    "ProbingTabModule",
    "NavigationModule"
]
