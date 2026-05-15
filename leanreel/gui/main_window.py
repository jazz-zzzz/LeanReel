"""LeanReel 主窗口 — TMM 风格布局"""
from PySide6.QtWidgets import (
    QMainWindow, QMenuBar, QStatusBar, QHBoxLayout, QWidget,
    QSplitter, QDockWidget, QLabel
)
from PySide6.QtCore import Qt


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LeanReel")
        self.resize(1400, 900)
        self.setMinimumSize(900, 600)
        self._setup_central()
        self._setup_menu()
        self._setup_status()
        self._setup_docks()

    def _setup_central(self):
        self.central = QWidget()
        self.setCentralWidget(self.central)
        self.layout = QHBoxLayout(self.central)
        self.layout.setContentsMargins(4, 4, 4, 4)
        self.layout.setSpacing(0)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(3)

        self.library_panel = QWidget()
        self.file_list_panel = QWidget()
        self.strategy_placeholder = QWidget()
        self.library_panel.setMinimumWidth(220)
        self.strategy_placeholder.setMinimumWidth(320)

        self.splitter.addWidget(self.library_panel)
        self.splitter.addWidget(self.file_list_panel)
        self.splitter.addWidget(self.strategy_placeholder)
        self.splitter.setSizes([240, 820, 340])

        self.layout.addWidget(self.splitter)

    def _setup_menu(self):
        menu = self.menuBar()
        file_menu = menu.addMenu("文件(&F)")
        file_menu.addAction("退出(&X)", self.close)

        view_menu = menu.addMenu("视图(&V)")
        self._toggle_queue_action = view_menu.addAction("显示/隐藏队列")

        help_menu = menu.addMenu("帮助(&H)")
        help_menu.addAction("关于 LeanReel", self._show_about)

    def _show_about(self):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.about(self, "关于 LeanReel",
            "LeanReel — 视频压缩管理工具\n\n"
            "GPU 加速 HEVC 编码，完整无损流保留。\n"
            "I/O 分离加速，支持 SMB/NAS 片库。"
        )

    def set_toggle_queue_action(self, callback):
        self._toggle_queue_action.triggered.connect(callback)

    def _setup_status(self):
        self.status = QStatusBar()
        self.status.setFixedHeight(28)
        self.setStatusBar(self.status)
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color: #e8e3db; font-size: 12px; padding: 2px 16px;")
        self.status.addWidget(self.status_label, 1)

    def set_status(self, text: str):
        self.status_label.setText(text)

    def set_library_panel(self, widget: QWidget):
        self.splitter.replaceWidget(0, widget)
        widget.setVisible(True)

    def set_file_list_panel(self, widget: QWidget):
        self.splitter.replaceWidget(1, widget)
        widget.setVisible(True)

    def set_strategy_widget(self, widget: QWidget):
        widget.setMinimumWidth(320)
        self.splitter.replaceWidget(2, widget)
        widget.setVisible(True)

    def _setup_docks(self):
        self.queue_dock = QDockWidget("任务队列", self)
        self.queue_dock.setAllowedAreas(Qt.BottomDockWidgetArea)
        self.queue_panel = QWidget()
        self.queue_dock.setWidget(self.queue_panel)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.queue_dock)
        self.queue_dock.hide()

    def set_queue_panel(self, widget: QWidget):
        self.queue_dock.setWidget(widget)

    def show_queue(self):
        self.queue_dock.show()
        self.queue_dock.raise_()

    def hide_queue(self):
        self.queue_dock.hide()
