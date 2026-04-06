import sys

print("--- Debugging Backplot OpenGL ---")
print(f"Python Version: {sys.version}")
print(f"Path: {sys.path}")

try:
    import PySide6
    print(f"PySide6 version: {PySide6.__version__}")
except ImportError as e:
    print(f"PySide6 Error: {e}")

try:
    import pyqtgraph as pg
    print(f"pyqtgraph version: {pg.__version__}")
    
    # Try the shim patch manually
    if not hasattr(pg.Qt.QtWidgets, "QOpenGLWidget"):
        print("Patching QOpenGLWidget...")
        try:
            from PySide6.QtOpenGLWidgets import QOpenGLWidget
            pg.Qt.QtWidgets.QOpenGLWidget = QOpenGLWidget
            print("QOpenGLWidget patched!")
        except ImportError as e:
            print(f"Could not import QOpenGLWidget: {e}")
    else:
        print("QOpenGLWidget already present.")

    import pyqtgraph.opengl as gl
    print("pyqtgraph.opengl import: SUCCESS")
    
    # Test creating a widget
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    w = gl.GLViewWidget()
    print("GLViewWidget creation: SUCCESS")

except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

print("--- End Debug ---")
