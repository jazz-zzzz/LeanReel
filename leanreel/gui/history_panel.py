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
from leanreel.ui_text import UI_TEXT

STATUS_ROLE = Qt.UserRole + 1
SORT_ROLE = Qt.UserRole + 2
LIBRARY_ROLE = Qt.UserRole + 3
STRATEGY_ROLE = Qt.UserRole + 4

_HEADERS = [
    "源文件名", "进度", "库", "文件夹", "源体积", "输出体积",
    "节省量", "节省率", "策略", "编码器", "CQ/CRF",
    "耗时", "开始时间", "完成时间", "源已删", "备注",
]

_ENCODER_STATUS = {
    "libx265": "HEVC",
    "hevc_nvenc": "HEVC",
    "h264_nvenc": "H.264",
    "av1_nvenc": "AV1",
    "copy": "流复制",
}

_STATUS_LABELS = {
    "pending": "等待中",
    "running": "转码中",
    "completed": "成功",
    "failed": "失败",
    "cancelled": "已取消",
    "discarded": "已丢弃",
    "skipped": "已跳过",
}

_STATUS_COLORS = {
    "pending": QColor("#5c5851"),
    "running": QColor("#c8963e"),
    "completed": QColor("#6b9955"),
    "failed": QColor("#c4554a"),
    "cancelled": QColor("#6b6560"),
    "discarded": QColor("#5b8db8"),
    "skipped": QColor("#5b8db8"),
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


def _normalize_time(t: str) -> str:
    if not t:
        return ""
    return t.replace("T", " ")[:19]


def _encode_label(encoder: str) -> str:
    return _ENCODER_STATUS.get(encoder, encoder)


def _output_size(row: dict) -> int:
    return int(row.get("output_size_bytes", 0) or row.get("compressed_size", 0) or 0)


def _has_completed_output(row: dict) -> bool:
    return row.get("status") == "completed" and _output_size(row) > 0


def _savings_bytes(row: dict) -> int:
    return max(0, int(row.get("original_size", 0) or 0) - _output_size(row))


def _format_savings(row: dict) -> str:
    savings = _savings_bytes(row)
    return "0 B" if savings == 0 else _format_bytes(savings)


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
        if role == STATUS_ROLE:
            return row.get("status", "")
        if role == LIBRARY_ROLE:
            return row.get("library_name", "")
        if role == STRATEGY_ROLE:
            return row.get("strategy_name", "")
        if role == SORT_ROLE:
            return self._sort_value(row, col)
        if role == Qt.ForegroundRole:
            if col == 1:
                return _STATUS_COLORS.get(row.get("status", ""))
        if role == Qt.ToolTipRole:
            return row.get("error_message", "") or row.get("output_path", "")
        return None

    def _progress_text(self, row: dict) -> str:
        status = row.get("status", "")
        label = _STATUS_LABELS.get(status, status)
        progress = float(row.get("progress") or 0)
        if status in ("completed", "discarded", "skipped"):
            progress = 100.0
        return f"{progress:.0f}%  {label}"

    def _display_text(self, row: dict, col: int) -> str:
        field_map = {
            0: lambda r: r.get("file_name", ""),
            1: self._progress_text,
            2: lambda r: r.get("library_name", ""),
            3: lambda r: r.get("folder_path", ""),
            4: lambda r: _format_bytes(r.get("original_size", 0)),
            5: lambda r: _format_bytes(_output_size(r)) if _output_size(r) else "—",
            6: lambda r: _format_savings(r) if _has_completed_output(r) else "—",
            7: lambda r: f"{float(r.get('savings_pct', 0) or 0):.1f}%" if _has_completed_output(r) else "—",
            8: lambda r: r.get("strategy_name", ""),
            9: lambda r: _encode_label(r.get("encoder", "")),
            10: lambda r: str(r.get("cq_value", "")) if r.get("cq_value") else "—",
            11: lambda r: _format_duration(r.get("duration_seconds", 0)),
            12: lambda r: _normalize_time(r.get("started_at", "") or r.get("created_at", "")),
            13: lambda r: _normalize_time(r.get("completed_at", "") or r.get("created_at", "")),
            14: lambda r: "是" if r.get("source_deleted") else "否",
            15: lambda r: r.get("error_message", "") or r.get("stage", "") or r.get("output_path", ""),
        }
        fn = field_map.get(col)
        return fn(row) if fn else ""

    def _sort_value(self, row: dict, col: int):
        if col == 1:
            return float(row.get("progress") or 0)
        if col == 4:
            return int(row.get("original_size", 0) or 0)
        if col == 5:
            return _output_size(row)
        if col == 6:
            return _savings_bytes(row) if _has_completed_output(row) else -1
        if col == 7:
            return float(row.get("savings_pct", 0) or 0) if _has_completed_output(row) else -1.0
        if col == 10:
            return int(row.get("cq_value", 0) or 0)
        if col == 11:
            return int(row.get("duration_seconds", 0) or 0)
        if col == 12:
            return _normalize_time(row.get("started_at", "") or row.get("created_at", ""))
        if col == 13:
            return _normalize_time(row.get("completed_at", "") or row.get("created_at", ""))
        if col == 14:
            return int(bool(row.get("source_deleted")))
        return self._display_text(row, col).casefold()


class HistoryFilterProxyModel(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self._status_filter = ""
        self._library_filter = ""
        self._strategy_filter = ""

    def set_status_filter(self, status: str):
        self._status_filter = status
        self._invalidate()

    def set_library_filter(self, library: str):
        self._library_filter = library
        self._invalidate()

    def set_strategy_filter(self, strategy: str):
        self._strategy_filter = strategy
        self._invalidate()

    def _invalidate(self):
        if hasattr(self, "beginFilterChange") and hasattr(self, "endFilterChange"):
            self.beginFilterChange()
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        elif hasattr(self, "invalidateRowsFilter"):
            self.invalidateRowsFilter()
        else:
            self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        model = self.sourceModel()
        status_idx = model.index(source_row, 1)
        if self._status_filter and model.data(status_idx, STATUS_ROLE) != self._status_filter:
            return False
        library_idx = model.index(source_row, 2)
        if self._library_filter and model.data(library_idx, LIBRARY_ROLE) != self._library_filter:
            return False
        strategy_idx = model.index(source_row, 8)
        if self._strategy_filter and model.data(strategy_idx, STRATEGY_ROLE) != self._strategy_filter:
            return False
        return True


class HistoryPanel(QWidget):
    back_requested = Signal()
    refresh_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        top = QHBoxLayout()

        self.back_btn = QPushButton(UI_TEXT.HISTORY_BACK)
        self.back_btn.setMinimumWidth(140)
        self.back_btn.clicked.connect(self.back_requested.emit)
        top.addWidget(self.back_btn)

        self.refresh_btn = QPushButton(UI_TEXT.HISTORY_REFRESH)
        self.refresh_btn.setMinimumWidth(60)
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        top.addWidget(self.refresh_btn)

        top.addSpacing(16)

        top.addWidget(QLabel(UI_TEXT.HISTORY_FILTER_LIBRARY))
        self.library_filter = QComboBox()
        self.library_filter.addItem(UI_TEXT.HISTORY_FILTER_ALL)
        self.library_filter.setMinimumWidth(120)
        top.addWidget(self.library_filter)

        top.addWidget(QLabel(UI_TEXT.HISTORY_FILTER_STRATEGY))
        self.strategy_filter = QComboBox()
        self.strategy_filter.addItem(UI_TEXT.HISTORY_FILTER_ALL)
        self.strategy_filter.setMinimumWidth(160)
        top.addWidget(self.strategy_filter)

        top.addWidget(QLabel(UI_TEXT.HISTORY_FILTER_STATUS))
        self.status_filter = QComboBox()
        self.status_filter.addItems([
            UI_TEXT.HISTORY_FILTER_ALL,
            UI_TEXT.HISTORY_STATUS_RUNNING,
            UI_TEXT.HISTORY_STATUS_COMPLETED,
            UI_TEXT.HISTORY_STATUS_FAILED,
            UI_TEXT.HISTORY_STATUS_CANCELLED,
            UI_TEXT.HISTORY_STATUS_DISCARDED,
            UI_TEXT.HISTORY_STATUS_SKIPPED,
        ])
        self.status_filter.setMinimumWidth(100)
        self.status_filter.currentTextChanged.connect(self._on_status_changed)
        top.addWidget(self.status_filter)

        self.summary_label = QLabel()
        top.addWidget(self.summary_label)

        top.addStretch()
        layout.addLayout(top)

        self.table = QTableView()
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setEditTriggers(QTableView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(self._on_double_click)

        self._source_model = HistoryTableModel()
        self._proxy = HistoryFilterProxyModel()
        self._proxy.setSourceModel(self._source_model)
        self._proxy.setSortRole(SORT_ROLE)
        self.table.setModel(self._proxy)
        self.library_filter.currentTextChanged.connect(self._on_library_changed)
        self.strategy_filter.currentTextChanged.connect(self._on_strategy_changed)

        layout.addWidget(self.table)

    def populate(self, rows: list[dict]):
        self._source_model.set_rows(rows)
        self._update_filters(rows)
        self._update_summary_from_proxy()

    def _update_filters(self, rows: list[dict]):
        libs = sorted({r.get("library_name", "") for r in rows if r.get("library_name")})
        strategies = sorted({r.get("strategy_name", "") for r in rows if r.get("strategy_name")})

        current_lib = self.library_filter.currentText()
        current_strat = self.strategy_filter.currentText()

        self.library_filter.blockSignals(True)
        self.library_filter.clear()
        self.library_filter.addItem(UI_TEXT.HISTORY_FILTER_ALL)
        self.library_filter.addItems(libs)
        self.library_filter.setCurrentText(current_lib if current_lib in libs else UI_TEXT.HISTORY_FILTER_ALL)
        self.library_filter.blockSignals(False)
        self._on_library_changed(self.library_filter.currentText())

        self.strategy_filter.blockSignals(True)
        self.strategy_filter.clear()
        self.strategy_filter.addItem(UI_TEXT.HISTORY_FILTER_ALL)
        self.strategy_filter.addItems(strategies)
        self.strategy_filter.setCurrentText(current_strat if current_strat in strategies else UI_TEXT.HISTORY_FILTER_ALL)
        self.strategy_filter.blockSignals(False)
        self._on_strategy_changed(self.strategy_filter.currentText())

    def _update_summary(self, rows: list[dict]):
        total = len(rows)
        completed = sum(1 for r in rows if r.get("status") == "completed")
        failed = sum(1 for r in rows if r.get("status") == "failed")
        running = sum(1 for r in rows if r.get("status") in ("pending", "running"))
        total_savings = sum(
            _savings_bytes(r)
            for r in rows if _has_completed_output(r)
        )
        parts = [
            UI_TEXT.HISTORY_SUMMARY_TEMPLATE.format(total=total),
            UI_TEXT.HISTORY_SUMMARY_COMPLETED.format(completed=completed),
            UI_TEXT.HISTORY_SUMMARY_FAILED.format(failed=failed),
        ]
        if running:
            parts.append(UI_TEXT.HISTORY_SUMMARY_RUNNING.format(running=running))
        parts.append(UI_TEXT.HISTORY_SUMMARY_SAVINGS.format(savings=_format_bytes(total_savings)))
        self.summary_label.setText(" · ".join(parts))

    def _update_summary_from_proxy(self):
        rows = []
        for proxy_row in range(self._proxy.rowCount()):
            source_idx = self._proxy.mapToSource(self._proxy.index(proxy_row, 0))
            if source_idx.isValid():
                rows.append(self._source_model._rows[source_idx.row()])
        self._update_summary(rows)

    def _on_status_changed(self, text: str):
        status_map = {
            UI_TEXT.HISTORY_STATUS_RUNNING: "running",
            UI_TEXT.HISTORY_STATUS_COMPLETED: "completed",
            UI_TEXT.HISTORY_STATUS_FAILED: "failed",
            UI_TEXT.HISTORY_STATUS_CANCELLED: "cancelled",
            UI_TEXT.HISTORY_STATUS_DISCARDED: "discarded",
            UI_TEXT.HISTORY_STATUS_SKIPPED: "skipped",
        }
        self._proxy.set_status_filter(status_map.get(text, ""))
        self._update_summary_from_proxy()

    def _on_library_changed(self, text: str):
        self._proxy.set_library_filter("" if text == UI_TEXT.HISTORY_FILTER_ALL else text)
        self._update_summary_from_proxy()

    def _on_strategy_changed(self, text: str):
        self._proxy.set_strategy_filter("" if text == UI_TEXT.HISTORY_FILTER_ALL else text)
        self._update_summary_from_proxy()

    def show_error(self, message: str):
        self.summary_label.setText(f"历史加载失败：{message}")  # 错误消息动态组合，保持原样

    def _on_double_click(self, index: QModelIndex):
        source_idx = self._proxy.mapToSource(index)
        row = self._source_model._rows[source_idx.row()]
        output_path = row.get("output_path", "")
        status = row.get("status", "")

        if status in ("running", "pending"):
            stage = row.get("stage", "") or _STATUS_LABELS.get(status, "")
            QMessageBox.information(self, UI_TEXT.HISTORY_TASK_RUNNING_TITLE,
                                    UI_TEXT.HISTORY_TASK_RUNNING_MSG.format(stage=stage))
            return

        if status == "failed":
            error = row.get("error_message", UI_TEXT.UNKNOWN_ERROR)
            QMessageBox.critical(self, UI_TEXT.HISTORY_ENCODE_FAILED_TITLE,
                                 f"错误信息：\n{error[:500] if error else UI_TEXT.UNKNOWN_ERROR}")
            return

        if status == "discarded":
            reason = row.get("error_message", "输出体积不小于源文件")
            QMessageBox.information(self, UI_TEXT.HISTORY_DISCARDED_TITLE, reason)
            return

        if output_path and Path(output_path).exists():
            os.startfile(str(Path(output_path).parent))
        else:
            QMessageBox.information(
                self, UI_TEXT.HISTORY_FILE_NOT_FOUND_TITLE,
                f"{UI_TEXT.HISTORY_FILE_NOT_FOUND_MSG}\n{output_path}\n\n"
                f"{UI_TEXT.HISTORY_FILE_NOT_FOUND_HINT}"
            )
