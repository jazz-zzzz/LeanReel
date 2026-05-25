"""历史转换面板 — 全屏 DB 驱动历史记录"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableView, QHeaderView, QComboBox, QLabel, QMessageBox,
)
from PySide6.QtCore import (
    Qt, Signal, QAbstractTableModel, QModelIndex,
    QSortFilterProxyModel,
)
from PySide6.QtGui import QColor

from leanreel.gui.utils import _format_bytes

_HEADERS = [
    "源文件名", "库", "文件夹", "源体积", "输出体积",
    "节省量", "节省率", "策略", "编码器", "CQ/CRF",
    "耗时", "完成时间", "状态", "源已删",
]

_ENCODER_STATUS = {
    "libx265": "HEVC",
    "hevc_nvenc": "HEVC",
    "av1_nvenc": "AV1",
    "copy": "流复制",
}


def _format_duration(seconds):
    seconds = int(seconds or 0)
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"


def _encode_label(encoder: str) -> str:
    return _ENCODER_STATUS.get(encoder, encoder)


class HistoryTableModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self._rows: list[dict] = []

    def set_rows(self, rows: list[dict]):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(_HEADERS)

    def headerData(self, section, orientation, role):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return _HEADERS[section]
        return None

    def data(self, index, role):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            return self._display_text(row, col)
        if role == Qt.UserRole:
            return row.get("output_path", "")
        if role == Qt.ForegroundRole:
            status = row.get("status", "")
            if status == "failed":
                return QColor("#c4554a")
            if status == "cancelled":
                return QColor("#6b6560")
        if role == Qt.ToolTipRole:
            return row.get("error_message", "") or row.get("output_path", "")
        return None

    def _display_text(self, row: dict, col: int) -> str:
        field_map = {
            0: lambda r: r.get("file_name", ""),
            1: lambda r: r.get("library_name", ""),
            2: lambda r: r.get("folder_path", ""),
            3: lambda r: _format_bytes(r.get("original_size", 0)),
            4: lambda r: _format_bytes(r.get("output_size_bytes", 0) or r.get("compressed_size", 0)),
            5: lambda r: _format_bytes(
                (r.get("original_size", 0) or 0) - (r.get("output_size_bytes", 0) or r.get("compressed_size", 0) or 0)
            ),
            6: lambda r: f"{r.get('savings_pct', 0):.1f}%" if r.get("savings_pct") else "—",
            7: lambda r: r.get("strategy_name", ""),
            8: lambda r: _encode_label(r.get("encoder", "")),
            9: lambda r: str(r.get("cq_value", "")) if r.get("cq_value") else "—",
            10: lambda r: _format_duration(r.get("duration_seconds", 0)),
            11: lambda r: r.get("created_at", ""),
            12: lambda r: r.get("status", ""),
            13: lambda r: "是" if r.get("source_deleted") else "否",
        }
        fn = field_map.get(col)
        return fn(row) if fn else ""


class StatusProxyModel(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self._status_filter = ""

    def set_status_filter(self, status: str):
        self._status_filter = status
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        if not self._status_filter or self._status_filter == "全部":
            return True
        model = self.sourceModel()
        idx = model.index(source_row, 12)
        return model.data(idx, Qt.DisplayRole) == self._status_filter


class HistoryPanel(QWidget):
    back_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # ── 顶部：返回按钮 + 筛选 ──
        top = QHBoxLayout()

        self.back_btn = QPushButton("← 返回文件列表")
        self.back_btn.setFixedWidth(140)
        self.back_btn.clicked.connect(self.back_requested.emit)
        top.addWidget(self.back_btn)

        top.addSpacing(16)

        top.addWidget(QLabel("库:"))
        self.library_filter = QComboBox()
        self.library_filter.addItem("全部")
        self.library_filter.setMinimumWidth(120)
        top.addWidget(self.library_filter)

        top.addWidget(QLabel("策略:"))
        self.strategy_filter = QComboBox()
        self.strategy_filter.addItem("全部")
        self.strategy_filter.setMinimumWidth(160)
        top.addWidget(self.strategy_filter)

        top.addWidget(QLabel("状态:"))
        self.status_filter = QComboBox()
        self.status_filter.addItems(["全部", "成功", "失败", "已取消"])
        self.status_filter.setMinimumWidth(100)
        self.status_filter.currentTextChanged.connect(self._on_status_changed)
        top.addWidget(self.status_filter)

        self.summary_label = QLabel()
        top.addWidget(self.summary_label)

        top.addStretch()
        layout.addLayout(top)

        # ── 表格 ──
        self.table = QTableView()
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setEditTriggers(QTableView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(self._on_double_click)

        self._source_model = HistoryTableModel()
        self._proxy = StatusProxyModel()
        self._proxy.setSourceModel(self._source_model)
        self.table.setModel(self._proxy)

        layout.addWidget(self.table)

    def populate(self, rows: list[dict]):
        self._source_model.set_rows(rows)
        self._update_filters(rows)
        self._update_summary(rows)

    def _update_filters(self, rows: list[dict]):
        libs = sorted({r.get("library_name", "") for r in rows if r.get("library_name")})
        strategies = sorted({r.get("strategy_name", "") for r in rows if r.get("strategy_name")})

        current_lib = self.library_filter.currentText()
        current_strat = self.strategy_filter.currentText()

        self.library_filter.clear()
        self.library_filter.addItem("全部")
        self.library_filter.addItems(libs)
        if current_lib in libs:
            self.library_filter.setCurrentText(current_lib)

        self.strategy_filter.clear()
        self.strategy_filter.addItem("全部")
        self.strategy_filter.addItems(strategies)
        if current_strat in strategies:
            self.strategy_filter.setCurrentText(current_strat)

    def _update_summary(self, rows: list[dict]):
        total = len(rows)
        completed = sum(1 for r in rows if r.get("status") == "completed")
        failed = sum(1 for r in rows if r.get("status") == "failed")
        total_savings = sum(
            (r.get("original_size", 0) or 0) - (r.get("output_size_bytes", 0) or r.get("compressed_size", 0) or 0)
            for r in rows if r.get("status") == "completed"
        )
        self.summary_label.setText(
            f"共 {total} 条 · 成功 {completed} · 失败 {failed} · 累计节省 {_format_bytes(total_savings)}"
        )

    def _on_status_changed(self, text: str):
        status_map = {"成功": "completed", "失败": "failed", "已取消": "cancelled"}
        self._proxy.set_status_filter(status_map.get(text, ""))

    def _on_double_click(self, index: QModelIndex):
        source_idx = self._proxy.mapToSource(index)
        row = self._source_model._rows[source_idx.row()]
        output_path = row.get("output_path", "")
        if output_path and Path(output_path).exists():
            os.startfile(str(Path(output_path).parent))
        else:
            QMessageBox.information(
                self, "文件不存在",
                f"输出文件已不存在：\n{output_path}\n\n"
                "可能原因：体积反超被丢弃 / 文件被手动删除"
            )
