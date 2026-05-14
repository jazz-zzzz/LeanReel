"""主窗口测试"""
import pytest
from PySide6.QtWidgets import QApplication

_app = None

def get_app():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app

def test_main_window_creates():
    from leanreel.gui.main_window import MainWindow
    app = get_app()
    win = MainWindow()
    assert win.windowTitle() == "LeanReel"
    win.close()

def test_main_window_has_menu_bar():
    from leanreel.gui.main_window import MainWindow
    app = get_app()
    win = MainWindow()
    menu = win.menuBar()
    assert menu is not None
    win.close()

def test_main_window_has_status_bar():
    from leanreel.gui.main_window import MainWindow
    app = get_app()
    win = MainWindow()
    status = win.statusBar()
    assert status is not None
    win.close()
