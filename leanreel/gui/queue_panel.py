"""队列面板 — 任务队列 + 进度，TMM 风格"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QProgressBar, QLabel,
    QHBoxLayout, QPushButton, QScrollArea
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor

from leanreel.domain.models import TaskStatus

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

_TERMINAL_STATUSES = {
    TaskStatus.COMPLETED.value,
    TaskStatus.FAILED.value,
    TaskStatus.SKIPPED.value,
    TaskStatus.CANCELLED.value,
}


from leanreel.gui.utils import _format_bytes


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
        self.cancel_btn = QPushButton("取消全部")
        self.cancel_btn.clicked.connect(lambda: self.cancel_requested.emit(-1))
        self.clear_btn = QPushButton("清空已完成")
        self.clear_btn.clicked.connect(self.clear_finished)
        btn_layout.addWidget(self.pause_btn)
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.clear_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def update_progress(self, progress: dict):
        self.total_progress.setValue(int(progress["percentage"]))
        self.total_label.setText(
            f"完成 {progress['completed']}/{progress['total']}  "
            f"跳过 {progress['skipped']}  "
            f"失败 {progress['failed']}  "
            f"取消 {progress.get('cancelled', 0)}"
        )

    def add_task_row(self, task):
        row = QWidget()
        row.setProperty("task_status", task.status.value)
        row.setProperty("task_key", task.input_path)  # 唯一标识：全路径
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(4, 2, 4, 2)
        row_layout.setSpacing(8)

        icon_label = QLabel(_STATUS_ICONS.get(task.status, "?"))
        icon_label.setObjectName("queue_icon")
        icon_color = _STATUS_COLORS.get(task.status, QColor("#5c5851"))
        icon_label.setStyleSheet(f"color: {icon_color.name()}; font-weight: bold; font-size: 14px;")
        icon_label.setFixedWidth(20)
        row_layout.addWidget(icon_label)

        name_label = QLabel(task.file_name)
        name_label.setObjectName("queue_name")
        name_label.setToolTip(task.input_path)  # 悬停显示完整路径
        name_label.setStyleSheet("color: #e8e3db;")
        row_layout.addWidget(name_label, 1)

        info = self._task_info_text(task)
        info_label = QLabel(info)
        info_label.setObjectName("queue_info")
        info_label.setStyleSheet("color: #8a857c; font-size: 11px;")
        if task.status == TaskStatus.FAILED:
            info_label.setToolTip(getattr(task, "error_message", "") or "未知错误")
        row_layout.addWidget(info_label)

        self.task_layout.insertWidget(self.task_layout.count() - 1, row)

    @staticmethod
    def _task_info_text(task) -> str:
        if task.status == TaskStatus.FAILED:
            error_message = getattr(task, "error_message", "") or "未知错误"
            return f"失败：{error_message}"
        if task.status == TaskStatus.COMPLETED:
            orig = _format_bytes(task.original_size)
            comp = _format_bytes(task.compressed_size) if task.compressed_size else "—"
            ratio = ""
            if task.compressed_size and task.original_size:
                pct = (1 - task.compressed_size / task.original_size) * 100
                ratio = f" ({pct:.0f}%)"
            return f"{orig} → {comp}{ratio}"
        if task.status == TaskStatus.SKIPPED:
            return getattr(task, "error_message", "") or "已跳过"
        if task.status == TaskStatus.RUNNING:
            stage = getattr(task, "current_stage", None)
            if stage:
                stage_name = stage.slot.display_name
                if stage.progress_type.value == "indeterminate":
                    return f"{stage_name}..."
                pct = stage.internal_progress * 100
                return f"{stage_name}: {pct:.0f}%"
            return f"压缩中... {task.progress:.0f}%"
        return _format_bytes(task.original_size)

    def clear_all(self):
        """清空所有任务行（包括 RUNNING、PENDING 等）。"""
        for i in reversed(range(self.task_layout.count() - 1)):
            item = self.task_layout.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()

    def clear_finished(self):
        """清空已完成、失败、跳过和已取消任务，保留运行中和等待中任务。"""
        for i in reversed(range(self.task_layout.count() - 1)):
            item = self.task_layout.itemAt(i)
            widget = item.widget() if item else None
            if widget and widget.property("task_status") in _TERMINAL_STATUSES:
                widget.deleteLater()

    def clear_tasks(self):
        self.clear_all()
        self.total_progress.setValue(0)
        self.total_label.setText("就绪")

    def update_task_row(self, task):
        """增量更新已存在的任务行（根据 input_path 全路径匹配）"""
        for i in range(self.task_layout.count()):
            item = self.task_layout.itemAt(i)
            if item and item.widget():
                row = item.widget()
                if row.property("task_key") != task.input_path:
                    continue
                row.setProperty("task_status", task.status.value)

                icon_label = row.findChild(QLabel, "queue_icon")
                if icon_label is not None:
                    icon_color = _STATUS_COLORS.get(task.status, QColor("#5c5851"))
                    icon_label.setText(_STATUS_ICONS.get(task.status, "?"))
                    icon_label.setStyleSheet(f"color: {icon_color.name()}; font-weight: bold; font-size: 14px;")

                info_label = row.findChild(QLabel, "queue_info")
                if info_label is not None:
                    info_label.setText(self._task_info_text(task))
                    if task.status == TaskStatus.FAILED:
                        info_label.setToolTip(getattr(task, "error_message", "") or "未知错误")
                    else:
                        info_label.setToolTip("")
                return
