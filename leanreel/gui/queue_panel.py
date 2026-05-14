"""队列面板 — 任务队列 + 进度 + 历史"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QListWidgetItem,
    QProgressBar, QLabel, QHBoxLayout, QPushButton
)
from PySide6.QtCore import Signal, Qt

from leanreel.executor.worker import TaskStatus


class QueuePanel(QWidget):
    pause_requested = Signal()
    cancel_requested = Signal(int)  # task_index

    def __init__(self):
        super().__init__()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # 总进度
        self.total_progress = QProgressBar()
        self.total_label = QLabel("就绪")
        layout.addWidget(self.total_label)
        layout.addWidget(self.total_progress)

        # 任务列表
        self.task_list = QListWidget()
        layout.addWidget(self.task_list)

        # 按钮
        btn_layout = QHBoxLayout()
        self.pause_btn = QPushButton("暂停")
        self.pause_btn.clicked.connect(self.pause_requested.emit)
        btn_layout.addWidget(self.pause_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def update_progress(self, progress: dict):
        self.total_progress.setValue(int(progress["percentage"]))
        self.total_label.setText(
            f"完成 {progress['completed']}/{progress['total']} · "
            f"跳过 {progress['skipped']} · 失败 {progress['failed']}"
        )

    def add_task_row(self, task):
        item = QListWidgetItem()
        status_icon = {"completed": "✓", "failed": "✗", "running": "...",
                       "skipped": "→", "pending": "○"}.get(task.status.value, "?")
        item.setText(f"{status_icon} {task.file_name} — {task.status.value}")
        if task.status == TaskStatus.RUNNING:
            item.setForeground(Qt.blue)
        elif task.status == TaskStatus.COMPLETED:
            item.setForeground(Qt.darkGreen)
        elif task.status == TaskStatus.FAILED:
            item.setForeground(Qt.red)
        self.task_list.addItem(item)

    def clear_tasks(self):
        self.task_list.clear()
