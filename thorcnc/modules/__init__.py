"""ThorCNC Module System

Modular architecture for organizing ThorCNC functionality.
Each module handles a specific domain (FileManager, Probing, Motion, etc.).
"""

from .base import ThorModule

__all__ = ["ThorModule"]
