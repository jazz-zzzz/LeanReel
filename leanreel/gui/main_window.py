"""LeanReel 主窗口"""
from PySide6.QtWidgets import (
    QMainWindow, QMenuBar, QStatusBar, QHBoxLayout, QWidget,
    QSplitter, QDockWidget
)
from PySide6.QtCore import Qt


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LeanReel")
        self.resize(1280, 800)
        self._setup_central()
        self._setup_menu()
        self._setup_status()
        self._setup_queue()

    def _setup_central(self):
        """中心区域：水平分割器 放置 库面板 | 文件列表 | 策略面板"""
        self.central = QWidget()
        self.setCentralWidget(self.central)
        self.layout = QHBoxLayout(self.central)
        self.layout.setContentsMargins(0, 0, 0, 0)

        self.splitter = QSplitter(Qt.Horizontal)
        # 占位 — 子面板将在后续任务中填入
        self.library_panel = QWidget()
        self.file_list_panel = QWidget()
        self.strategy_panel = QWidget()

        self.splitter.addWidget(self.library_panel)
        self.splitter.addWidget(self.file_list_panel)
        self.splitter.addWidget(self.strategy_panel)
        self.splitter.setSizes([180, 700, 220])

        self.layout.addWidget(self.splitter)

    def _setup_menu(self):
        menu = self.menuBar()

        file_menu = menu.addMenu("文件(&F)")
        file_menu.addAction("新建库...")
        file_menu.addAction("打开库目录...")
        file_menu.addSeparator()
        file_menu.addAction("退出(&X)", self.close)

        tools_menu = menu.addMenu("工具(&T)")
        tools_menu.addAction("扫描所有库")
        tools_menu.addAction("队列面板")

        help_menu = menu.addMenu("帮助(&H)")
        help_menu.addAction("关于 LeanReel")

    def _setup_status(self):
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("就绪")

    def set_library_panel(self, widget: QWidget):
        self.splitter.replaceWidget(0, widget)

    def set_file_list_panel(self, widget: QWidget):
        self.splitter.replaceWidget(1, widget)

    def set_strategy_panel(self, widget: QWidget):
        self.splitter.replaceWidget(2, widget)

    def _setup_queue(self):
        """底部可折叠队列面板"""
        self.queue_dock = QDockWidget("任务队列", self)
        self.queue_dock.setAllowedAreas(Qt.BottomDockWidgetArea)
        self.queue_panel = QWidget()
        self.queue_dock.setWidget(self.queue_panel)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.queue_dock)
        self.queue_dock.hide()

    def set_queue_panel(self, widget: QWidget):
        self.queue_dock.setWidget(widget)
