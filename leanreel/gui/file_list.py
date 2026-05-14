"""文件列表面板 — 文件表格 + 策略匹配结果"""
from __future__ import annotations

import re
from typing import Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel, QHBoxLayout, QComboBox
)
from PySide6.QtCore import Signal, Qt

_HEADERS = ["文件名", "体积", "视频编码", "HDR", "匹配策略", "预计节省"]


class SortableTableWidgetItem(QTableWidgetItem):
    """QTableWidgetItem that sorts by a hidden numeric value when present."""

    def __init__(self, text: str, sort_value: int | float | None = None):
        super().__init__(text)
        if sort_value is not None:
            self.setData(Qt.UserRole, sort_value)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        left = self.data(Qt.UserRole)
        right = other.data(Qt.UserRole)
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return left < right
        return super().__lt__(other)


def _format_bytes(size_bytes: int | float | None) -> str:
    if size_bytes is None:
        return "—"
    value = float(size_bytes)
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    while abs(value) >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{int(value)} {units[unit_index]}"
    return f"{value:.1f} {units[unit_index]}"


def _scale_bytes(size_bytes: int | float) -> tuple[float, str, int]:
    value = float(size_bytes)
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    while abs(value) >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1
    return value, units[unit_index], unit_index


def _format_byte_range(min_bytes: int | float, max_bytes: int | float) -> str:
    min_value, min_unit, min_index = _scale_bytes(min_bytes)
    max_value, max_unit, max_index = _scale_bytes(max_bytes)
    if min_index == max_index:
        if min_index == 0:
            return f"{int(min_value)}-{int(max_value)} {min_unit}"
        return f"{min_value:.1f}-{max_value:.1f} {min_unit}"
    return f"{_format_bytes(min_bytes)}-{_format_bytes(max_bytes)}"


def _parse_savings_range(percent_text: str) -> tuple[float, float] | None:
    numbers = re.findall(r"\d+(?:\.\d+)?", percent_text or "")
    if not numbers:
        return None
    lo = float(numbers[0]) / 100
    hi = float(numbers[1]) / 100 if len(numbers) > 1 else lo
    return lo, hi


class FileListPanel(QWidget):
    file_selection_changed = Signal(list)
    strategy_override_changed = Signal(str, str)
    custom_strategy_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self._snapshots_by_path: dict[str, Any] = {}
        self._strategy_lookup: dict[str, Any] = {}
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
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        header = self.table.horizontalHeader()
        header.setSortIndicatorShown(True)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, len(_HEADERS)):
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        layout.addWidget(self.table)

    def populate(self, snapshots: list, matched_strategies: dict, strategies: list | None = None):
        """Populate rows from snapshots and compatible strategy/estimate mappings.

        ``matched_strategies`` supports the legacy ``{rel_path: strategy_name}``
        shape as well as Strategy objects or dictionaries containing strategy
        and estimate fields.
        """
        self._snapshots_by_path = {snap.relative_path: snap for snap in snapshots}
        self._strategy_lookup = self._build_strategy_lookup(strategies)
        self.table.setSortingEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(len(snapshots))
        total_size = 0
        for row, snap in enumerate(snapshots):
            file_item = QTableWidgetItem(snap.file_name)
            file_item.setData(Qt.UserRole, snap.relative_path)
            self.table.setItem(row, 0, file_item)
            self.table.setItem(
                row, 1,
                SortableTableWidgetItem(_format_bytes(snap.size_bytes), snap.size_bytes),
            )
            self.table.setItem(row, 2, QTableWidgetItem(snap.video_codec))
            self.table.setItem(row, 3, QTableWidgetItem(self._format_hdr(snap.hdr_type)))
            strategy_name, savings_text, savings_sort = self._resolve_match_display(
                snap, matched_strategies.get(snap.relative_path)
            )
            self.table.setItem(row, 4, QTableWidgetItem(strategy_name))
            self.table.setItem(row, 5, SortableTableWidgetItem(savings_text, savings_sort))
            if strategies:
                self.table.setCellWidget(
                    row, 4,
                    self._create_strategy_combo(snap.relative_path, strategy_name),
                )
            total_size += snap.size_bytes

        total_tb = total_size / (1024**4)
        self.summary_label.setText(
            f"已扫描 {len(snapshots)} 个文件 · 总计 {total_tb:.2f} TB"
        )
        self.table.setSortingEnabled(True)

    def _format_hdr(self, hdr_type: Any) -> str:
        return getattr(hdr_type, "value", str(hdr_type))

    def _build_strategy_lookup(self, strategies: list | None) -> dict[str, Any]:
        lookup: dict[str, Any] = {}
        for strategy in strategies or []:
            name = getattr(strategy, "name", str(strategy))
            if name:
                lookup[name] = strategy
        return lookup

    def _create_strategy_combo(self, relative_path: str, selected_name: str) -> QComboBox:
        combo = QComboBox()
        names = list(self._strategy_lookup)
        if selected_name and selected_name != "未匹配" and selected_name not in names:
            names.insert(0, selected_name)
        if "自定义" not in names:
            names.append("自定义")
        combo.addItems(names)
        if selected_name in names:
            combo.setCurrentText(selected_name)
        combo.currentTextChanged.connect(
            lambda strategy_name, path=relative_path: self._on_strategy_combo_changed(path, strategy_name)
        )
        return combo

    def _on_strategy_combo_changed(self, relative_path: str, strategy_name: str):
        row = self._find_row_by_relative_path(relative_path)
        if row is None:
            return

        self.table.item(row, 4).setText(strategy_name)
        snap = self._snapshots_by_path.get(relative_path)
        if snap is not None and strategy_name != "自定义":
            _, savings_text, savings_sort = self._resolve_match_display(
                snap, self._strategy_lookup.get(strategy_name, strategy_name)
            )
            self.table.setItem(row, 5, SortableTableWidgetItem(savings_text, savings_sort))
        elif snap is not None:
            self.table.setItem(row, 5, SortableTableWidgetItem("—", -1))

        self.strategy_override_changed.emit(relative_path, strategy_name)
        if strategy_name == "自定义":
            self.custom_strategy_requested.emit(relative_path)

    def apply_strategy_to_row(self, relative_path: str, strategy: Any):
        """Apply a strategy object to one row and refresh its savings estimate."""
        row = self._find_row_by_relative_path(relative_path)
        snap = self._snapshots_by_path.get(relative_path)
        if row is None or snap is None:
            return

        strategy_name, savings_text, savings_sort = self._resolve_match_display(snap, strategy)
        self.table.item(row, 4).setText(strategy_name)
        self.table.setItem(row, 5, SortableTableWidgetItem(savings_text, savings_sort))
        combo = self.table.cellWidget(row, 4)
        if isinstance(combo, QComboBox):
            if combo.findText(strategy_name) < 0:
                combo.addItem(strategy_name)
            if combo.currentText() != strategy_name:
                combo.blockSignals(True)
                combo.setCurrentText(strategy_name)
                combo.blockSignals(False)

    def _find_row_by_relative_path(self, relative_path: str) -> int | None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == relative_path:
                return row
        return None

    def _resolve_match_display(self, snap: Any, match: Any) -> tuple[str, str, int | float]:
        if match is None:
            return "未匹配", "—", -1

        strategy = None
        estimate: dict[str, Any] = {}
        strategy_name: str | None = None
        percent_text = ""

        if isinstance(match, dict):
            strategy = match.get("strategy") or match.get("matched_strategy")
            nested_estimate = match.get("estimate") or match.get("savings")
            if isinstance(nested_estimate, dict):
                estimate.update(nested_estimate)
            estimate.update(match)
            strategy_name = (
                match.get("strategy_name")
                or match.get("strategy")
                or match.get("name")
            )
        elif hasattr(match, "name") or hasattr(match, "estimated_savings"):
            strategy = match
        else:
            return str(match), "—", -1

        if hasattr(strategy, "name"):
            strategy_name = getattr(strategy, "name") or strategy_name
        if not strategy_name:
            strategy_name = "未匹配"
        elif not isinstance(strategy_name, str):
            strategy_name = getattr(strategy_name, "name", str(strategy_name))

        percent_text = (
            str(estimate.get("percentage") or estimate.get("estimated_savings") or "")
            or str(getattr(strategy, "estimated_savings", "") or "")
        )
        min_bytes = estimate.get("estimated_min_bytes")
        max_bytes = estimate.get("estimated_max_bytes")

        if min_bytes is None or max_bytes is None:
            parsed = _parse_savings_range(percent_text)
            if parsed:
                lo, hi = parsed
                min_bytes = int(snap.size_bytes * lo)
                max_bytes = int(snap.size_bytes * hi)

        if min_bytes is None or max_bytes is None:
            return strategy_name, "—", -1

        savings_text = _format_byte_range(min_bytes, max_bytes)
        if percent_text:
            savings_text = f"{savings_text} ({percent_text})"
        return strategy_name, savings_text, max_bytes
