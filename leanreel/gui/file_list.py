"""文件列表面板 — 文件表格 + 策略匹配结果"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel, QHBoxLayout, QComboBox
)
from PySide6.QtCore import Signal, Qt

_HEADERS = ["文件名", "体积", "视频编码", "HDR", "匹配策略", "预计节省"]


class FileListPanel(QWidget):
    file_selection_changed = Signal(list)

    def __init__(self):
        super().__init__()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # 顶部信息栏
        info_layout = QHBoxLayout()
        self.summary_label = QLabel("未扫描")
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["全部", "待处理", "已跳过", "已完成"])
        info_layout.addWidget(self.summary_label)
        info_layout.addStretch()
        info_layout.addWidget(self.filter_combo)
        layout.addLayout(info_layout)

        # 文件表格
        self.table = QTableWidget()
        self.table.setColumnCount(len(_HEADERS))
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, len(_HEADERS)):
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        layout.addWidget(self.table)

    def populate(self, snapshots: list, matched_strategies: dict):
        """snapshots: list[FileSnapshot], matched_strategies: {rel_path: strategy_name}"""
        self.table.setRowCount(len(snapshots))
        total_size = 0
        for row, snap in enumerate(snapshots):
            self.table.setItem(row, 0, QTableWidgetItem(snap.file_name))
            size_gb = snap.size_bytes / (1024**3)
            self.table.setItem(row, 1, QTableWidgetItem(f"{size_gb:.1f} GB"))
            self.table.setItem(row, 2, QTableWidgetItem(snap.video_codec))
            self.table.setItem(row, 3, QTableWidgetItem(str(snap.hdr_type)))
            strategy = matched_strategies.get(snap.relative_path, "未匹配")
            self.table.setItem(row, 4, QTableWidgetItem(strategy))
            self.table.setItem(row, 5, QTableWidgetItem("—"))
            total_size += snap.size_bytes

        total_tb = total_size / (1024**4)
        self.summary_label.setText(
            f"已扫描 {len(snapshots)} 个文件 · 总计 {total_tb:.2f} TB"
        )
