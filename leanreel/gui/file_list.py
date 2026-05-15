"""文件列表面板 — 文件表格 + 策略匹配结果"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel, QHBoxLayout, QComboBox, QStackedWidget,
    QTreeWidget, QTreeWidgetItem, QPushButton
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor

_HEADERS = ["", "文件名", "体积", "编码信息", "HDR", "匹配策略", "预计节省"]

# ── 列配色 ──
_COLOR_CODEC_OK = QColor("#8db87c")
_COLOR_CODEC_MISSING = QColor("#6b6560")
_COLOR_PROBE_FAILED = QColor("#c8675e")
_COLOR_HDR_DV = QColor("#6ba8d6")
_COLOR_HDR_HDR10 = QColor("#d4a853")
_COLOR_HDR_SDR = QColor("#6b6560")


@dataclass
class MatchResult:
    """匹配结果 — 包含策略及其估算节省空间

    ``strategy`` 可以是 Strategy 对象、策略名称字符串，或 None。
    ``estimate`` 是 ``estimate_savings()`` 返回的字典，
    包含 ``percentage``、``estimated_min_bytes``、``estimated_max_bytes`` 等键。
    """
    strategy: "Strategy | str | None" = None
    estimate: dict | None = None


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


from leanreel.gui.utils import _format_bytes


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
    file_selection_changed = Signal(list)  # 预留：选中文件变化时通知外部（当前无人连接）
    strategy_override_changed = Signal(str, str)
    custom_strategy_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self._snapshots_by_path: dict[str, Any] = {}
        self._strategy_lookup: dict[str, Any] = {}
        self._last_snapshots: list[Any] = []
        self._last_matches: dict[str, Any] = {}
        self._last_strategies: list[Any] | None = None
        self.current_view_mode = "flat"
        self._row_index: dict[str, int] = {}
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # 顶部信息栏
        info_layout = QHBoxLayout()
        self.summary_label = QLabel("未扫描")
        self.view_combo = QComboBox()
        self.view_combo.addItem("平铺", "flat")
        self.view_combo.addItem("目录树", "tree")
        self.view_combo.currentIndexChanged.connect(
            lambda _i: self.set_view_mode(self.view_combo.currentData())
        )
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["全部", "待处理", "已跳过", "已完成"])
        info_layout.addWidget(self.summary_label)
        info_layout.addStretch()
        info_layout.addWidget(self.view_combo)
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
        header.setSectionsMovable(False)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        for i in range(2, len(_HEADERS)):
            header.setSectionResizeMode(i, QHeaderView.Interactive)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(0, 30)
        self.table.setColumnWidth(1, 260)
        self.table.setColumnWidth(2, 70)
        self.table.setColumnWidth(3, 175)
        self.table.setColumnWidth(4, 60)
        self.table.setColumnWidth(5, 160)
        self.table.setColumnWidth(6, 190)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(_HEADERS))
        self.tree.setHeaderLabels(_HEADERS)
        self.tree.setSortingEnabled(True)
        self.tree.hide()

        # 空状态提示
        self.empty_label = QLabel("请先在左侧添加库和文件夹以扫描视频文件")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet("color: #6b6560; font-size: 14px; padding: 40px;")

        self.stack = QStackedWidget()
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.tree)
        self.stack.addWidget(self.empty_label)
        self.stack.setCurrentWidget(self.empty_label)
        layout.addWidget(self.stack)

        # 底部勾选控制栏
        select_layout = QHBoxLayout()
        select_layout.setContentsMargins(0, 0, 0, 0)
        select_layout.setSpacing(6)
        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.clicked.connect(self.select_all)
        self.deselect_all_btn = QPushButton("取消全选")
        self.deselect_all_btn.clicked.connect(self.deselect_all)
        self.selection_label = QLabel("已选中 0/0 个文件")
        self.selection_label.setStyleSheet("color: #8a857c; font-size: 11px;")
        select_layout.addWidget(self.select_all_btn)
        select_layout.addWidget(self.deselect_all_btn)
        select_layout.addWidget(self.selection_label)
        select_layout.addStretch()
        layout.addLayout(select_layout)

        self.table.itemChanged.connect(self._on_item_changed)

    def populate(self, snapshots: list, matched_strategies: dict[str, MatchResult | None], strategies: list | None = None):
        """填充文件表格行。

        ``matched_strategies`` 将 ``relative_path`` 映射到 ``MatchResult``，
        或 ``None``（表示未匹配）。
        """
        self._last_snapshots = list(snapshots)
        self._last_matches = dict(matched_strategies)
        self._last_strategies = strategies
        self._snapshots_by_path = {snap.relative_path: snap for snap in snapshots}
        self._strategy_lookup = self._build_strategy_lookup(strategies)

        if not snapshots:
            self.stack.setCurrentWidget(self.empty_label)
            return

        self.stack.setCurrentWidget(self.table)
        self.table.setSortingEnabled(False)
        self.table.blockSignals(True)
        self.table.clearContents()
        self.table.setRowCount(len(snapshots))
        self._row_index.clear()
        total_size = 0
        for row, snap in enumerate(snapshots):
            self._row_index[snap.relative_path] = row
            # 列0：勾选框
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check_item.setCheckState(Qt.Checked)
            self.table.setItem(row, 0, check_item)
            # 列1：文件名
            file_item = QTableWidgetItem(snap.file_name)
            file_item.setData(Qt.UserRole, snap.relative_path)
            self.table.setItem(row, 1, file_item)
            # 列2：体积
            self.table.setItem(
                row, 2,
                SortableTableWidgetItem(_format_bytes(snap.size_bytes), snap.size_bytes),
            )
            # 列3：编码信息
            codec_item = QTableWidgetItem(self._format_codec(snap))
            if getattr(snap, "video_codec", ""):
                codec_item.setForeground(_COLOR_CODEC_OK)
            elif getattr(snap, "probe_ok", None) is False:
                codec_item.setForeground(_COLOR_PROBE_FAILED)
            else:
                codec_item.setForeground(_COLOR_CODEC_MISSING)
            self.table.setItem(row, 3, codec_item)
            # 列4：HDR
            hdr_item = QTableWidgetItem(self._format_hdr(snap.hdr_type))
            hdr_item.setForeground(self._hdr_color(getattr(snap, "hdr_type", None)))
            self.table.setItem(row, 4, hdr_item)
            strategy_name, savings_text, savings_sort = self._resolve_match_display(
                snap, matched_strategies.get(snap.relative_path)
            )
            # 列6：预计节省
            self.table.setItem(row, 6, SortableTableWidgetItem(savings_text, savings_sort))
            if strategies:
                self.table.setCellWidget(
                    row, 5,
                    self._create_strategy_combo(snap.relative_path, strategy_name),
                )
            else:
                self.table.setItem(row, 5, QTableWidgetItem(strategy_name))
            total_size += snap.size_bytes

        self.table.blockSignals(False)
        total_tb = total_size / (1024**4)
        self.summary_label.setText(
            f"已扫描 {len(snapshots)} 个文件 · 总计 {total_tb:.2f} TB"
        )
        self._update_selection_count()
        self.table.setSortingEnabled(True)
        self._populate_tree(snapshots, matched_strategies)

    def _format_hdr(self, hdr_type: Any) -> str:
        return getattr(hdr_type, "value", str(hdr_type))

    @staticmethod
    def _hdr_color(hdr_type) -> QColor:
        val = getattr(hdr_type, "value", str(hdr_type))
        if "DV" in val or "Dolby" in val:
            return _COLOR_HDR_DV
        if "HDR" in val:
            return _COLOR_HDR_HDR10
        return _COLOR_HDR_SDR

    @staticmethod
    def _format_codec(snap: Any) -> str:
        codec = getattr(snap, "video_codec", "") or ""
        if not codec:
            if getattr(snap, "probe_ok", None) is False:
                return "探测失败"
            return "未识别"
        parts = [codec]
        w = getattr(snap, "video_width", 0) or 0
        h = getattr(snap, "video_height", 0) or 0
        if h >= 4320:
            parts.append("8K")
        elif h >= 2160:
            parts.append("4K")
        elif h >= 1440:
            if w >= 2560:
                parts.append("2K")
            else:
                parts.append(f"{h}p")
        elif h >= 1080:
            parts.append("1080p")
        elif h >= 720:
            parts.append("720p")
        elif h > 0:
            parts.append(f"{h}p")
        br = getattr(snap, "bitrate_bps", 0) or 0
        if br > 0:
            parts.append(f"{br / 1e6:.1f} Mbps")
        return " ".join(parts)

    def _build_strategy_lookup(self, strategies: list | None) -> dict[str, Any]:
        lookup: dict[str, Any] = {}
        for strategy in strategies or []:
            name = getattr(strategy, "name", str(strategy))
            if name:
                lookup[name] = strategy
        return lookup

    def _create_strategy_combo(self, relative_path: str, selected_name: str) -> QComboBox:
        combo = QComboBox()
        combo.setMinimumWidth(140)
        combo.setMaximumHeight(28)
        combo.setStyleSheet("QComboBox { padding: 1px 4px; }")
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

    def set_view_mode(self, mode: str):
        if mode not in {"flat", "tree"}:
            return
        self.current_view_mode = mode
        if mode == "tree":
            self.stack.setCurrentWidget(self.tree)
            self.table.hide()
            self.tree.show()
        else:
            self.stack.setCurrentWidget(self.table)
            self.tree.hide()
            self.table.show()

    def _populate_tree(self, snapshots: list, matched_strategies: dict):
        self.tree.clear()
        folders: dict[str, QTreeWidgetItem] = {}
        for snap in snapshots:
            folder_name = str(snap.relative_path).replace("\\", "/").rsplit("/", 1)[0]
            folder_name = folder_name or "."
            folder_item = folders.get(folder_name)
            if folder_item is None:
                folder_item = QTreeWidgetItem([folder_name])
                folder_item.setFirstColumnSpanned(True)
                folders[folder_name] = folder_item
                self.tree.addTopLevelItem(folder_item)
            strategy_name, savings_text, _savings_sort = self._resolve_match_display(
                snap, matched_strategies.get(snap.relative_path)
            )
            child = QTreeWidgetItem([
                snap.file_name,
                _format_bytes(snap.size_bytes),
                self._format_codec(snap),
                self._format_hdr(snap.hdr_type),
                strategy_name,
                savings_text,
            ])
            child.setData(0, Qt.UserRole, snap.relative_path)
            folder_item.addChild(child)
        # 默认折叠，用户按需展开目录

    def _on_strategy_combo_changed(self, relative_path: str, strategy_name: str):
        row = self._find_row_by_relative_path(relative_path)
        if row is None:
            return

        snap = self._snapshots_by_path.get(relative_path)
        if snap is not None and strategy_name != "自定义":
            lookup = self._strategy_lookup.get(strategy_name, strategy_name)
            match = MatchResult(strategy=lookup) if not isinstance(lookup, MatchResult) else lookup
            _, savings_text, savings_sort = self._resolve_match_display(snap, match)
            self.table.setItem(row, 6, SortableTableWidgetItem(savings_text, savings_sort))
        elif snap is not None:
            self.table.setItem(row, 6, SortableTableWidgetItem("—", -1))

        self.strategy_override_changed.emit(relative_path, strategy_name)
        if strategy_name == "自定义":
            self.custom_strategy_requested.emit(relative_path)

    def apply_strategy_to_row(self, relative_path: str, strategy: Any):
        """Apply a strategy object to one row and refresh its savings estimate."""
        row = self._find_row_by_relative_path(relative_path)
        snap = self._snapshots_by_path.get(relative_path)
        if row is None or snap is None:
            return

        match = MatchResult(strategy=strategy) if not isinstance(strategy, MatchResult) else strategy
        strategy_name, savings_text, savings_sort = self._resolve_match_display(snap, match)
        self.table.setItem(row, 6, SortableTableWidgetItem(savings_text, savings_sort))
        combo = self.table.cellWidget(row, 5)
        if isinstance(combo, QComboBox):
            if combo.findText(strategy_name) < 0:
                combo.addItem(strategy_name)
            if combo.currentText() != strategy_name:
                combo.blockSignals(True)
                combo.setCurrentText(strategy_name)
                combo.blockSignals(False)
        else:
            item = self.table.item(row, 5)
            if item:
                item.setText(strategy_name)

    def update_snapshot_row(self, snap: Any):
        """后台探测完成后增量更新单行编码信息。"""
        relative_path = str(getattr(snap, "relative_path", ""))
        if not relative_path:
            return

        self._snapshots_by_path[relative_path] = snap
        row = self._find_row_by_relative_path(relative_path)
        if row is not None:
            probe_failed = getattr(snap, "probe_ok", None) is False and not getattr(
                snap, "video_codec", ""
            )
            if probe_failed:
                codec_item = QTableWidgetItem("探测失败")
                codec_item.setForeground(_COLOR_PROBE_FAILED)
            else:
                codec_item = QTableWidgetItem(self._format_codec(snap))
                codec_item.setForeground(
                    _COLOR_CODEC_OK if getattr(snap, "video_codec", "") else _COLOR_CODEC_MISSING
                )
            self.table.setItem(row, 3, codec_item)
            hdr_item = QTableWidgetItem(self._format_hdr(snap.hdr_type))
            hdr_item.setForeground(self._hdr_color(getattr(snap, "hdr_type", None)))
            self.table.setItem(row, 4, hdr_item)

    def _find_row_by_relative_path(self, relative_path: str) -> int | None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)
            if item is not None and item.data(Qt.UserRole) == relative_path:
                return row
        return None

    def get_checked_relative_paths(self) -> list[str]:
        """返回所有勾中文件的 relative_path 列表。"""
        checked: list[str] = []
        for row in range(self.table.rowCount()):
            check_item = self.table.item(row, 0)
            if check_item and check_item.checkState() == Qt.Checked:
                name_item = self.table.item(row, 1)
                if name_item:
                    path = name_item.data(Qt.UserRole)
                    if path:
                        checked.append(path)
        return checked

    def select_all(self):
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                item.setCheckState(Qt.Checked)
        self.table.blockSignals(False)
        self._update_selection_count()

    def deselect_all(self):
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                item.setCheckState(Qt.Unchecked)
        self.table.blockSignals(False)
        self._update_selection_count()

    def _on_item_changed(self, item: QTableWidgetItem):
        if item.column() == 0:
            self._update_selection_count()

    def _update_selection_count(self):
        checked = 0
        total = self.table.rowCount()
        for row in range(total):
            item = self.table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                checked += 1
        self.selection_label.setText(f"已选中 {checked}/{total} 个文件")

    def _resolve_match_display(self, snap: Any, match: MatchResult | None) -> tuple[str, str, int | float]:
        """将 MatchResult 解析为（策略名, 节省文本, 排序列数值）三元组。"""
        if match is None:
            return "未匹配", "—", -1

        strategy = match.strategy
        estimate = match.estimate or {}

        # ── 提取策略名称 ──
        strategy_name: str = "未匹配"
        if hasattr(strategy, "name"):
            strategy_name = strategy.name or "未匹配"
        elif isinstance(strategy, str):
            strategy_name = strategy
        elif estimate.get("strategy_name"):
            strategy_name = str(estimate["strategy_name"])

        # ── 提取节省百分比文本 ──
        percent_text = ""
        if estimate.get("percentage"):
            percent_text = str(estimate["percentage"])
        elif hasattr(strategy, "estimated_savings") and strategy.estimated_savings:
            percent_text = str(strategy.estimated_savings)

        # ── 提取字节估算 ──
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
