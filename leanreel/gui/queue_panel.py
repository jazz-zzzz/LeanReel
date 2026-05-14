"""队列面板 — 任务队列 + 进度，TMM 风格"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QProgressBar, QLabel,
    QHBoxLayout, QPushButton, QScrollArea
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor

from leanreel.executor.worker import TaskStatus

_STATUS_COLORS = {
    TaskStatus.RUNNING: QColor("#c8963e"),
    TaskStatus.COMPLETED: QColor("#6b9955"),
    TaskStatus.FAILED: QColor("#c4554a"),
    TaskStatus.SKIPPED: QColor("#5b8db8"),
    TaskStatus.PENDING: QColor("#5c5851"),
    TaskStatus.CANCELLED: QColor("#6b6560"),
}

_STATUS_ICONS = {
    TaskStatus.RUNNING: "⟳",
    TaskStatus.COMPLETED: "✓",
    TaskStatus.FAILED: "✗",
    TaskStatus.SKIPPED: "→",
    TaskStatus.PENDING: "○",
    TaskStatus.CANCELLED: "⊘",
}


def _format_bytes(size_bytes):
    value = float(size_bytes or 0)
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while abs(value) >= 1024 and idx < len(units) - 1:
        value /= 1024
        idx += 1
    if idx == 0:
        return f"{int(value)} {units[idx]}"
    return f"{value:.1f} {units[idx]}"


class QueuePanel(QWidget):
    pause_requested = Signal()
    cancel_requested = Signal(int)

    def __init__(self):
        super().__init__()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 总进度
        header = QHBoxLayout()
        self.total_label = QLabel("就绪")
        header.addWidget(self.total_label)
        header.addStretch()
        layout.addLayout(header)

        self.total_progress = QProgressBar()
        self.total_progress.setTextVisible(False)
        layout.addWidget(self.total_progress)

        # 任务行容器（可滚动）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.task_container = QWidget()
        self.task_layout = QVBoxLayout(self.task_container)
        self.task_layout.setContentsMargins(0, 0, 0, 0)
        self.task_layout.setSpacing(3)
        self.task_layout.addStretch()
        scroll.setWidget(self.task_container)
        layout.addWidget(scroll, 1)

        # 按钮
        btn_layout = QHBoxLayout()
        self.pause_btn = QPushButton("暂停")
        self.pause_btn.clicked.connect(self.pause_requested.emit)
        self.clear_btn = QPushButton("清空已完成")
        self.clear_btn.clicked.connect(self.clear_completed)
        btn_layout.addWidget(self.pause_btn)
        btn_layout.addWidget(self.clear_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def update_progress(self, progress: dict):
        self.total_progress.setValue(int(progress["percentage"]))
        self.total_label.setText(
            f"完成 {progress['completed']}/{progress['total']}  "
            f"跳过 {progress['skipped']}  "
            f"失败 {progress['failed']}"
        )

    def add_task_row(self, task):
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(4, 2, 4, 2)
        row_layout.setSpacing(8)

        icon_label = QLabel(_STATUS_ICONS.get(task.status, "?"))
        icon_color = _STATUS_COLORS.get(task.status, QColor("#5c5851"))
        icon_label.setStyleSheet(f"color: {icon_color.name()}; font-weight: bold; font-size: 14px;")
        icon_label.setFixedWidth(20)
        row_layout.addWidget(icon_label)

        name_label = QLabel(task.file_name)
        name_label.setStyleSheet("color: #e8e3db;")
        row_layout.addWidget(name_label, 1)

        if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            orig = _format_bytes(task.original_size)
            comp = _format_bytes(task.compressed_size) if task.compressed_size else "—"
            ratio = ""
            if task.compressed_size and task.original_size:
                pct = (1 - task.compressed_size / task.original_size) * 100
                ratio = f" ({pct:.0f}%)"
            info = f"{orig} → {comp}{ratio}"
        elif task.status == TaskStatus.RUNNING:
            info = f"压缩中... {task.progress:.0f}%"
        else:
            info = _format_bytes(task.original_size)

        info_label = QLabel(info)
        info_label.setStyleSheet("color: #8a857c; font-size: 11px;")
        row_layout.addWidget(info_label)

        self.task_layout.insertWidget(self.task_layout.count() - 1, row)

    def clear_completed(self):
        for i in reversed(range(self.task_layout.count() - 1)):
            item = self.task_layout.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()

    def clear_tasks(self):
        self.clear_completed()
        self.total_progress.setValue(0)
        self.total_label.setText("就绪")

    def update_task_row(self, task):
        """更新已存在的任务行（根据 file_name 匹配）"""
        for i in range(self.task_layout.count()):
            item = self.task_layout.itemAt(i)
            if item and item.widget():
                row = item.widget()
                # 找到匹配的行，用新的替换
                labels = row.findChildren(QLabel)
                if labels and labels[1].text() == task.file_name:
                    self.task_layout.removeWidget(row)
                    row.deleteLater()
                    break
        self.add_task_row(task)
