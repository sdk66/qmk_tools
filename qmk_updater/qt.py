"""Qt 5 for Windows 7, Qt 6 for modern macOS/Linux."""
try:
    from PySide2.QtCore import *
    from PySide2.QtGui import *
    from PySide2.QtWidgets import *
    BINDING = "PySide2"
except ImportError:
    from PySide6.QtCore import *
    from PySide6.QtGui import *
    from PySide6.QtWidgets import *
    BINDING = "PySide6"
