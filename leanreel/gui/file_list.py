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

_HEADERS = ["", "文件名", "体积", "编码信息", "HDR", "处理策略", "预计结果"]
_TREE_HEADERS = ["文件名", "体积", "编码信息", "HDR", "处理策略", "预计结果"]

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


@dataclass(frozen=True)
class FileDecisionDisplay:
    status_key: str
    strategy_text: str
    result_text: str
    result_sort: int | float
    processable: bool
    tooltip: str


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
from leanreel.core.matcher import get_skip_reason


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
    refresh_requested = Signal()
    tree_folder_refresh_requested = Signal(int)  # 树视图右键刷新文件夹，传 folder_id
    row_selected = Signal(str)  # 某行被选中时发出 relative_path 或空串

    def __init__(self):
        super().__init__()
        self._snapshots_by_path: dict[str, Any] = {}
        self._snapshots_by_key: dict[tuple[int, str], Any] = {}
        self._strategy_lookup: dict[str, Any] = {}
        self._last_snapshots: list[Any] = []
        self._last_matches: dict[str, Any] = {}
        self._last_strategies: list[Any] | None = None
        self._row_by_path: dict[str, int] = {}
        self._row_by_key: dict[tuple[int, str], int] = {}
        self._row_status_keys: dict[int, str] = {}
        self._row_processable: dict[int, bool] = {}
        self._status_by_key: dict[tuple[int, str], str] = {}
        self._processable_by_key: dict[tuple[int, str], bool] = {}
        self._checked_keys: set[tuple[int, str]] = set()
        self._tree_item_by_key: dict[tuple[int, str], QTreeWidgetItem] = {}
        self._populate_gen = 0
        self._path_gen: dict[str, int] = {}
        self.current_view_mode = "flat"
        self.setup_ui()

    @staticmethod
    def _file_key(snap: Any) -> tuple[int, str]:
        return (int(getattr(snap, "library_folder_id", 0) or 0), str(getattr(snap, "relative_path", "")))

    @staticmethod
    def _coerce_key(value: Any) -> tuple[int, str] | None:
        if isinstance(value, tuple) and len(value) == 2:
            return (int(value[0] or 0), str(value[1]))
        if isinstance(value, str) and value:
            return (0, value)
        return None

    def _match_for_snap(self, snap: Any, matches: dict):
        key = self._file_key(snap)
        return matches.get(key, matches.get(snap.relative_path))

    def get_checked_file_keys(self) -> list[tuple[int, str]]:
        """返回所有勾中文件的 (library_folder_id, relative_path) key 列表（已排序）。"""
        return sorted(self._checked_keys)

    def _sync_checked_from_view(self):
        """将当前视图的勾选状态同步回 _checked_keys。"""
        if self.current_view_mode == "tree":
            for key, item in list(self._tree_item_by_key.items()):
                if item.flags() & Qt.ItemIsEnabled and item.checkState(0) == Qt.Checked:
                    self._checked_keys.add(key)
                else:
                    self._checked_keys.discard(key)
        else:
            for row in range(self.table.rowCount()):
                check_item = self.table.item(row, 0)
                if check_item is not None:
                    key = self._coerce_key(check_item.data(Qt.UserRole))
                    if key is not None:
                        if check_item.checkState() == Qt.Checked and check_item.flags() & Qt.ItemIsEnabled:
                            self._checked_keys.add(key)
                        else:
                            self._checked_keys.discard(key)

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # 顶部信息栏
        info_layout = QHBoxLayout()
        self.summary_label = QLabel("未扫描")
        self.refresh_btn = QPushButton("重建缓存")
        self.refresh_btn.setToolTip("重新扫描所有文件夹并重建编码信息缓存")
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        info_layout.addWidget(self.refresh_btn)
        self.view_combo = QComboBox()
        self.view_combo.addItem("平铺", "flat")
        self.view_combo.addItem("目录树", "tree")
        self.view_combo.currentIndexChanged.connect(
            lambda _i: self.set_view_mode(self.view_combo.currentData())
        )
        self.filter_combo = QComboBox()
        self.filter_combo.addItem("全部", "all")
        self.filter_combo.addItem("可处理", "processable")
        self.filter_combo.addItem("已保护跳过", "protected")
        self.filter_combo.addItem("探测失败", "probe_failed")
        self.filter_combo.addItem("已选择", "checked")
        self.filter_combo.currentIndexChanged.connect(lambda _i: self._apply_filter())
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
        self.table.setAutoScroll(False)
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
        self.table.setColumnWidth(5, 260)
        self.table.setColumnWidth(6, 190)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(_TREE_HEADERS))
        self.tree.setHeaderLabels(_TREE_HEADERS)
        self.tree.setSortingEnabled(True)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_tree_context_menu)
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
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.itemChanged.connect(self._on_tree_item_changed)
        self.tree.itemSelectionChanged.connect(self._on_tree_selection_changed)

    def populate(self, snapshots: list, matched_strategies: dict[str, MatchResult | None], strategies: list | None = None):
        """分批填充文件表格行，避免一次性创建大量控件导致主线程冻结。"""
        self._populate_gen += 1
        self._last_snapshots = list(snapshots)
        self._last_matches = dict(matched_strategies)
        self._last_strategies = strategies
        self._snapshots_by_path = {snap.relative_path: snap for snap in snapshots}
        self._snapshots_by_key = {self._file_key(snap): snap for snap in snapshots}
        self._row_by_path = {}
        self._row_by_key = {}
        self._row_status_keys = {}
        self._row_processable = {}
        self._status_by_key = {}
        self._processable_by_key = {}
        self._tree_item_by_key = {}
        valid_keys = set(self._snapshots_by_key)
        self._checked_keys = {key for key in self._checked_keys if key in valid_keys}
        self._path_gen = {snap.relative_path: self._populate_gen for snap in snapshots}
        self._strategy_lookup = self._build_strategy_lookup(strategies)

        if not snapshots:
            self.stack.setCurrentWidget(self.empty_label)
            self.summary_label.setText("未扫描")
            self._update_selection_count()
            return

        self.stack.setCurrentWidget(self.table)
        self.table.setSortingEnabled(False)
        self.table.blockSignals(True)
        self.table.clearContents()
        self.table.setRowCount(len(snapshots))

        # 存储分批渲染状态，首屏同步渲染让测试通过，后续分批
        self._batch_snapshots = list(snapshots)
        self._batch_matches = dict(matched_strategies)
        self._batch_strategies = strategies
        self._batch_total_size = 0
        self._batch_row_index = 0
        self._render_row_batch()  # 首屏立即渲染

    def _render_row_batch(self):
        """每批渲染最多 100 行，剩余用 QTimer 调度以保持 UI 响应。"""
        batch_size = 100
        snapshots = self._batch_snapshots
        matched_strategies = self._batch_matches
        strategies = self._batch_strategies
        for _ in range(batch_size):
            row = self._batch_row_index
            if row >= len(snapshots):
                # 全部分批完成
                self._finish_populate()
                return
            snap = snapshots[row]
            file_key = self._file_key(snap)
            self._row_by_path[snap.relative_path] = row
            self._row_by_key[file_key] = row
            check_item = QTableWidgetItem()
            skip_reason = get_skip_reason(snap)
            if skip_reason:
                check_item.setFlags(Qt.ItemIsUserCheckable)
                check_item.setToolTip(skip_reason)
            else:
                check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check_item.setData(Qt.UserRole, file_key)
            check_item.setCheckState(Qt.Checked if file_key in self._checked_keys else Qt.Unchecked)
            self.table.setItem(row, 0, check_item)
            file_item = QTableWidgetItem(snap.file_name)
            file_item.setData(Qt.UserRole, file_key)
            self.table.setItem(row, 1, file_item)
            self.table.setItem(
                row, 2,
                SortableTableWidgetItem(_format_bytes(snap.size_bytes), snap.size_bytes),
            )
            codec_item = QTableWidgetItem(self._format_codec(snap))
            if getattr(snap, "video_codec", ""):
                codec_item.setForeground(_COLOR_CODEC_OK)
            elif getattr(snap, "probe_ok", None) is False and getattr(snap, "probe_error", ""):
                codec_item.setForeground(_COLOR_PROBE_FAILED)
                codec_item.setToolTip(getattr(snap, "probe_error", ""))
            elif getattr(snap, "probe_ok", None) is False:
                codec_item.setForeground(_COLOR_CODEC_MISSING)
            else:
                codec_item.setForeground(_COLOR_CODEC_MISSING)
            self.table.setItem(row, 3, codec_item)
            hdr_item = QTableWidgetItem(self._format_hdr(snap.hdr_type))
            hdr_item.setForeground(self._hdr_color(getattr(snap, "hdr_type", None)))
            self.table.setItem(row, 4, hdr_item)
            decision = self._decision_display(
                snap, self._match_for_snap(snap, matched_strategies)
            )
            self._row_status_keys[row] = decision.status_key
            self._row_processable[row] = decision.processable
            self._status_by_key[file_key] = decision.status_key
            self._processable_by_key[file_key] = decision.processable
            self.table.setItem(
                row, 6,
                SortableTableWidgetItem(decision.result_text, decision.result_sort),
            )
            if strategies and decision.processable:
                self.table.setCellWidget(
                    row, 5,
                    self._create_strategy_combo(snap.relative_path, decision.strategy_text),
                )
            else:
                strategy_item = QTableWidgetItem(decision.strategy_text)
                strategy_item.setToolTip(decision.tooltip)
                if decision.status_key == "protected":
                    strategy_item.setForeground(_COLOR_HDR_DV)
                elif decision.status_key == "probe_failed":
                    strategy_item.setForeground(_COLOR_PROBE_FAILED)
                self.table.setItem(row, 5, strategy_item)
            self._batch_total_size += snap.size_bytes
            self._batch_row_index += 1

        # 还有剩余行，调度下一批
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._render_row_batch)

    def _finish_populate(self):
        """分批渲染完成后的收尾工作。"""
        snapshots = self._batch_snapshots
        self.table.blockSignals(False)
        total_tb = self._batch_total_size / (1024**4)
        processable_count = sum(1 for value in self._row_processable.values() if value)
        protected_count = sum(1 for value in self._row_status_keys.values() if value == "protected")
        self.summary_label.setText(
            f"已扫描 {len(snapshots)} 个文件 · 可处理 {processable_count} · "
            f"已保护跳过 {protected_count} · 总计 {total_tb:.2f} TB"
        )
        self._update_selection_count()
        self.table.setSortingEnabled(True)
        self._populate_tree(snapshots, self._batch_matches)
        self._apply_filter()

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
            probe_ok = getattr(snap, "probe_ok", None)
            probe_error = getattr(snap, "probe_error", "") or ""
            if probe_ok is False and probe_error:
                return "探测失败"
            elif probe_ok is False and not probe_error:
                return "探测中..."
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
        # 切换前将当前视图勾选状态同步到 _checked_keys
        self._sync_checked_from_view()
        self.current_view_mode = mode
        if mode == "tree":
            self._populate_tree(list(self._snapshots_by_path.values()), self._last_matches)
            self.stack.setCurrentWidget(self.tree)
            self.table.hide()
            self.tree.show()
        else:
            # 切回平铺时从 _checked_keys 同步表格勾选状态
            self.table.blockSignals(True)
            for row in range(self.table.rowCount()):
                check_item = self.table.item(row, 0)
                if check_item is not None:
                    key = self._coerce_key(check_item.data(Qt.UserRole))
                    if key is not None:
                        if key in self._checked_keys and check_item.flags() & Qt.ItemIsEnabled:
                            check_item.setCheckState(Qt.Checked)
                        else:
                            check_item.setCheckState(Qt.Unchecked)
            self.table.blockSignals(False)
            self.stack.setCurrentWidget(self.table)
            self.tree.hide()
            self.table.show()

    def _populate_tree(self, snapshots: list, matched_strategies: dict):
        self.tree.clear()
        self.tree.blockSignals(True)
        self._tree_item_by_key.clear()
        # 预计算每个文件夹的总大小
        folder_sizes: dict[str, int] = {}
        for snap in snapshots:
            folder_name = str(snap.relative_path).replace("\\", "/").rsplit("/", 1)[0]
            folder_sizes[folder_name] = folder_sizes.get(folder_name, 0) + snap.size_bytes
        folders: dict[str, QTreeWidgetItem] = {}
        for snap in snapshots:
            folder_name = str(snap.relative_path).replace("\\", "/").rsplit("/", 1)[0]
            folder_name = folder_name or "."
            folder_item = folders.get(folder_name)
            if folder_item is None:
                total = _format_bytes(folder_sizes.get(folder_name, 0))
                folder_item = QTreeWidgetItem([f"{folder_name}  [{total}]"])
                folder_item.setFirstColumnSpanned(True)
                folder_item.setData(0, Qt.UserRole, snap.library_folder_id)
                folders[folder_name] = folder_item
                self.tree.addTopLevelItem(folder_item)
            decision = self._decision_display(
                snap, matched_strategies.get(snap.relative_path)
            )
            file_key = self._file_key(snap)
            child = QTreeWidgetItem([
                snap.file_name,
                _format_bytes(snap.size_bytes),
                self._format_codec(snap),
                self._format_hdr(snap.hdr_type),
                decision.strategy_text,
                decision.result_text,
            ])
            child.setData(0, Qt.UserRole, file_key)
            child.setToolTip(0, decision.tooltip or snap.file_name)
            child.setToolTip(4, decision.tooltip)
            # 颜色标记 — 与平铺表格一致
            if getattr(snap, "video_codec", ""):
                child.setForeground(2, _COLOR_CODEC_OK)
            elif getattr(snap, "probe_ok", None) is False and getattr(snap, "probe_error", ""):
                child.setForeground(2, _COLOR_PROBE_FAILED)
            else:
                child.setForeground(2, _COLOR_CODEC_MISSING)
            child.setForeground(3, self._hdr_color(getattr(snap, "hdr_type", None)))
            if decision.status_key == "protected":
                child.setForeground(4, _COLOR_HDR_DV)
            elif decision.status_key == "probe_failed":
                child.setForeground(4, _COLOR_PROBE_FAILED)
            if decision.processable:
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                child.setCheckState(0, Qt.Checked if file_key in self._checked_keys else Qt.Unchecked)
            else:
                child.setFlags((child.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEnabled)
                child.setToolTip(0, decision.tooltip)
            self._tree_item_by_key[file_key] = child
            folder_item.addChild(child)
        self.tree.blockSignals(False)
        # 默认折叠，用户按需展开目录

    def _find_tree_child(self, relative_path: str) -> QTreeWidgetItem | None:
        """在树视图中按 relative_path 查找叶子节点（通过 _tree_item_by_key 定位）。"""
        for (folder_id, path), item in self._tree_item_by_key.items():
            if path == relative_path:
                return item
        return None

    def _update_tree_child(self, relative_path: str, snap: Any, decision: FileDecisionDisplay):
        """更新树视图中单个文件行的编码、策略、结果列及颜色。"""
        child = self._find_tree_child(relative_path)
        if child is None:
            return
        # 同步数据追踪字典
        key = self._file_key(snap)
        if key:
            self._status_by_key[key] = decision.status_key
            self._processable_by_key[key] = decision.processable
        child.setText(1, _format_bytes(snap.size_bytes))
        child.setText(2, self._format_codec(snap))
        child.setText(3, self._format_hdr(snap.hdr_type))
        child.setText(4, decision.strategy_text)
        child.setText(5, decision.result_text)
        child.setToolTip(4, decision.tooltip)
        # 颜色
        if getattr(snap, "video_codec", ""):
            child.setForeground(2, _COLOR_CODEC_OK)
        elif getattr(snap, "probe_ok", None) is False and getattr(snap, "probe_error", ""):
            child.setForeground(2, _COLOR_PROBE_FAILED)
        else:
            child.setForeground(2, _COLOR_CODEC_MISSING)
        child.setForeground(3, self._hdr_color(getattr(snap, "hdr_type", None)))
        if decision.status_key == "protected":
            child.setForeground(4, _COLOR_HDR_DV)
        elif decision.status_key == "probe_failed":
            child.setForeground(4, _COLOR_PROBE_FAILED)
        else:
            child.setForeground(4, QColor())  # 恢复默认
        # 可处理性
        if decision.processable:
            child.setFlags(child.flags() | Qt.ItemIsEnabled)
        else:
            child.setFlags((child.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEnabled)
            child.setToolTip(0, decision.tooltip)

    def _on_strategy_combo_changed(self, relative_path: str, strategy_name: str):
        row = self._row_by_path.get(relative_path)
        if row is None:
            return

        snap = self._snapshots_by_path.get(relative_path)
        if snap is not None and strategy_name != "自定义":
            lookup = self._strategy_lookup.get(strategy_name, strategy_name)
            match = MatchResult(strategy=lookup) if not isinstance(lookup, MatchResult) else lookup
            decision = self._decision_display(snap, match)
            self._row_status_keys[row] = decision.status_key
            self._row_processable[row] = decision.processable
            self.table.setItem(row, 6, SortableTableWidgetItem(decision.result_text, decision.result_sort))
        elif snap is not None:
            self.table.setItem(row, 6, SortableTableWidgetItem("—", -1))

        self.strategy_override_changed.emit(relative_path, strategy_name)
        if strategy_name == "自定义":
            self.custom_strategy_requested.emit(relative_path)
        self._apply_filter()

    def apply_strategy_to_row(self, relative_path: str, strategy: Any):
        """Apply a strategy object to one row and refresh its savings estimate."""
        row = self._row_by_path.get(relative_path)
        snap = self._snapshots_by_path.get(relative_path)
        if row is None or snap is None:
            return

        match = MatchResult(strategy=strategy) if not isinstance(strategy, MatchResult) else strategy
        decision = self._decision_display(snap, match)
        self._row_status_keys[row] = decision.status_key
        self._row_processable[row] = decision.processable
        self.table.setItem(row, 6, SortableTableWidgetItem(decision.result_text, decision.result_sort))
        combo = self.table.cellWidget(row, 5)
        if isinstance(combo, QComboBox):
            if combo.findText(decision.strategy_text) < 0:
                combo.addItem(decision.strategy_text)
            if combo.currentText() != decision.strategy_text:
                combo.blockSignals(True)
                combo.setCurrentText(decision.strategy_text)
                combo.blockSignals(False)
        else:
            item = self.table.item(row, 5)
            if item:
                item.setText(decision.strategy_text)
                item.setToolTip(decision.tooltip)
        if self.current_view_mode == "tree":
            self._update_tree_child(relative_path, snap, decision)
        self._apply_filter()

    def update_snapshot_row(self, snap: Any, match: Any = None):
        """后台探测完成后增量更新单行编码信息。"""
        relative_path = str(getattr(snap, "relative_path", ""))
        if not relative_path:
            return

        self._snapshots_by_path[relative_path] = snap
        if match is not None:
            self._last_matches[relative_path] = match
        row = self._row_by_path.get(relative_path)
        if row is not None:
            # 验证缓存行号未因排序而失效
            item = self.table.item(row, 1)
            if item is None:
                row = None
            else:
                key = self._coerce_key(item.data(Qt.UserRole))
                if key is None or key[1] != relative_path:
                    row = None
        if row is None:
            # 缓存失效（例如排序后），回退到线性扫描并重建缓存
            row = self._find_row_by_relative_path(relative_path)
            if row is not None:
                self._row_by_path[relative_path] = row
        if row is not None:
            probe_failed = getattr(snap, "probe_ok", None) is False and not getattr(
                snap, "video_codec", ""
            )
            probe_error = getattr(snap, "probe_error", "") or ""
            if probe_failed and probe_error:
                codec_item = QTableWidgetItem("探测失败")
                codec_item.setToolTip(probe_error)
                codec_item.setForeground(_COLOR_PROBE_FAILED)
            elif probe_failed:
                codec_item = QTableWidgetItem("探测中...")
                codec_item.setForeground(_COLOR_CODEC_MISSING)
            else:
                codec_item = QTableWidgetItem(self._format_codec(snap))
                codec_item.setForeground(
                    _COLOR_CODEC_OK if getattr(snap, "video_codec", "") else _COLOR_CODEC_MISSING
                )
            self.table.setItem(row, 3, codec_item)
            hdr_item = QTableWidgetItem(self._format_hdr(snap.hdr_type))
            hdr_item.setForeground(self._hdr_color(getattr(snap, "hdr_type", None)))
            self.table.setItem(row, 4, hdr_item)
            # 更新列 2（体积）— 优先用探测结果，仅当占位值为0时刷新
            old_size_item = self.table.item(row, 2)
            old_sort = old_size_item.data(Qt.UserRole) if old_size_item else 0
            if (isinstance(old_sort, (int, float)) and old_sort <= 0) or (snap.size_bytes and snap.size_bytes > 0):
                self.table.setItem(row, 2, SortableTableWidgetItem(_format_bytes(snap.size_bytes), snap.size_bytes))
            # 更新列 5（处理状态）和列 6（预计结果）
            match = self._last_matches.get(relative_path)
            decision = self._decision_display(snap, match)
            self._row_status_keys[row] = decision.status_key
            self._row_processable[row] = decision.processable
            self.table.setItem(
                row, 6,
                SortableTableWidgetItem(decision.result_text, decision.result_sort),
            )
            combo = self.table.cellWidget(row, 5)
            if isinstance(combo, QComboBox):
                if decision.processable and self._last_strategies:
                    if combo.findText(decision.strategy_text) < 0:
                        combo.addItem(decision.strategy_text)
                    combo.blockSignals(True)
                    combo.setCurrentText(decision.strategy_text)
                    combo.blockSignals(False)
                else:
                    combo.setEnabled(False)
            else:
                strategy_item = QTableWidgetItem(decision.strategy_text)
                strategy_item.setToolTip(decision.tooltip)
                if decision.status_key == "protected":
                    strategy_item.setForeground(_COLOR_HDR_DV)
                elif decision.status_key == "probe_failed":
                    strategy_item.setForeground(_COLOR_PROBE_FAILED)
                self.table.setItem(row, 5, strategy_item)
            # 同步更新树视图
            if self.current_view_mode == "tree":
                self._update_tree_child(relative_path, snap, decision)

    def _find_row_by_relative_path(self, relative_path: str) -> int | None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)
            if item is not None:
                key = self._coerce_key(item.data(Qt.UserRole))
                if key is not None and key[1] == relative_path:
                    return row
        return None

    def get_checked_relative_paths(self) -> list[str]:
        """返回所有勾中文件的 relative_path 列表（基于 _checked_keys，与视图无关）。"""
        return sorted({key[1] for key in self._checked_keys})

    def _get_checked_tree_paths(self) -> list[str]:
        """兼容旧调用方：基于 _checked_keys 返回已勾选路径列表。"""
        return self.get_checked_relative_paths()

    def select_all(self):
        # 更新共享状态
        for key in self._snapshots_by_key:
            if self._processable_by_key.get(key, False):
                self._checked_keys.add(key)
        # 更新 UI
        if self.current_view_mode == "tree":
            self._set_tree_checked(True)
        else:
            self.table.blockSignals(True)
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item and item.flags() & Qt.ItemIsEnabled:
                    item.setCheckState(Qt.Checked)
            self.table.blockSignals(False)
        self._update_selection_count()

    def deselect_all(self):
        self._checked_keys.clear()
        if self.current_view_mode == "tree":
            self._set_tree_checked(False)
        else:
            self.table.blockSignals(True)
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item:
                    item.setCheckState(Qt.Unchecked)
            self.table.blockSignals(False)
        self._update_selection_count()

    def _set_tree_checked(self, checked: bool):
        state = Qt.Checked if checked else Qt.Unchecked
        def _walk(item):
            for i in range(item.childCount()):
                child = item.child(i)
                if child.childCount() > 0:
                    _walk(child)
                else:
                    if child.flags() & Qt.ItemIsEnabled:
                        child.setCheckState(0, state)
        for i in range(self.tree.topLevelItemCount()):
            _walk(self.tree.topLevelItem(i))

    def _on_item_changed(self, item: QTableWidgetItem):
        if item.column() == 0:
            key = self._coerce_key(item.data(Qt.UserRole))
            if key is not None:
                if item.checkState() == Qt.Checked and item.flags() & Qt.ItemIsEnabled:
                    self._checked_keys.add(key)
                else:
                    self._checked_keys.discard(key)
            self._apply_filter()

    def _on_selection_changed(self):
        rows = {idx.row() for idx in self.table.selectedIndexes()}
        if len(rows) == 1:
            row = next(iter(rows))
            item = self.table.item(row, 1)
            data = item.data(Qt.UserRole) if item else None
            key = self._coerce_key(data) if data else None
            rel = key[1] if key else ""
            self.row_selected.emit(rel or "")
        else:
            self.row_selected.emit("")  # 多选或取消选中 → 清空右面板绑定

    def _on_tree_item_changed(self, item: QTreeWidgetItem, column: int):
        if column == 0:
            key = self._coerce_key(item.data(0, Qt.UserRole))
            if key is not None:
                if item.checkState(0) == Qt.Checked and item.flags() & Qt.ItemIsEnabled:
                    self._checked_keys.add(key)
                else:
                    self._checked_keys.discard(key)
            self._apply_filter()

    def _on_tree_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None or item.childCount() == 0:
            return
        folder_id = item.data(0, Qt.UserRole)
        if folder_id is None:
            return
        from PySide6.QtWidgets import QMenu
        menu = QMenu()
        menu.addAction("重建此文件夹缓存", lambda: self.tree_folder_refresh_requested.emit(folder_id))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _on_tree_selection_changed(self):
        items = self.tree.selectedItems()
        if len(items) == 1 and items[0].childCount() == 0:
            data = items[0].data(0, Qt.UserRole)
            key = self._coerce_key(data) if data else None
            rel = key[1] if key else ""
            self.row_selected.emit(rel)
        else:
            self.row_selected.emit("")

    def _apply_filter(self):
        filter_key = self.filter_combo.currentData() if hasattr(self, "filter_combo") else "all"
        if self.current_view_mode == "tree":
            self._apply_tree_filter(filter_key)
        else:
            for row in range(self.table.rowCount()):
                status_key = self._row_status_keys.get(row, "unmatched")
                check_item = self.table.item(row, 0)
                checked = check_item is not None and check_item.checkState() == Qt.Checked
                hide = False
                if filter_key == "processable":
                    hide = not self._row_processable.get(row, False)
                elif filter_key == "protected":
                    hide = status_key != "protected"
                elif filter_key == "probe_failed":
                    hide = status_key != "probe_failed"
                elif filter_key == "checked":
                    hide = not checked
                self.table.setRowHidden(row, hide)
        self._update_selection_count()

    def _apply_tree_filter(self, filter_key: str):
        """树视图过滤：隐藏不匹配的叶子节点，并隐藏空文件夹。"""
        # 先对每个叶子项决定可见性
        for key, child in self._tree_item_by_key.items():
            status_key = self._status_by_key.get(key, "unmatched")
            checked = (
                child.flags() & Qt.ItemIsEnabled
                and child.checkState(0) == Qt.Checked
            )
            hide = False
            if filter_key == "processable":
                hide = not self._processable_by_key.get(key, False)
            elif filter_key == "protected":
                hide = status_key != "protected"
            elif filter_key == "probe_failed":
                hide = status_key != "probe_failed"
            elif filter_key == "checked":
                hide = not checked
            child.setHidden(hide)
        # 遍历顶层文件夹：有可见子项的保持可见，否则隐藏
        for i in range(self.tree.topLevelItemCount()):
            folder_item = self.tree.topLevelItem(i)
            has_visible = False
            for j in range(folder_item.childCount()):
                if not folder_item.child(j).isHidden():
                    has_visible = True
                    break
            folder_item.setHidden(not has_visible)

    def _update_selection_count(self):
        checked = len([k for k in self._checked_keys if self._processable_by_key.get(k, False)])
        processable_total = sum(1 for v in self._processable_by_key.values() if v)
        self.selection_label.setText(f"已选中 {checked}/{processable_total} 个可处理文件")

    def _decision_display(self, snap: Any, match: MatchResult | None) -> FileDecisionDisplay:
        skip_reason = get_skip_reason(snap)
        if skip_reason:
            return FileDecisionDisplay(
                status_key="protected",
                strategy_text=skip_reason,
                result_text="不处理",
                result_sort=-2,
                processable=False,
                tooltip=skip_reason,
            )

        if (
            getattr(snap, "probe_ok", None) is False
            and not getattr(snap, "video_codec", "")
            and getattr(snap, "probe_error", "")
        ):
            probe_error = getattr(snap, "probe_error", "") or "探测失败"
            return FileDecisionDisplay(
                status_key="probe_failed",
                strategy_text="探测失败",
                result_text="无法估算",
                result_sort=-3,
                processable=False,
                tooltip=probe_error,
            )

        strategy_name, savings_text, savings_sort = self._resolve_match_display(snap, match)
        return FileDecisionDisplay(
            status_key="processable" if strategy_name != "未匹配" else "unmatched",
            strategy_text=strategy_name,
            result_text=savings_text,
            result_sort=savings_sort,
            processable=strategy_name != "未匹配",
            tooltip=strategy_name,
        )

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
