"""文件列表面板 — 文件表格 + 策略匹配结果"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QTableView,
    QHeaderView, QLabel, QHBoxLayout, QComboBox, QStackedWidget,
    QTreeWidget, QTreeWidgetItem, QPushButton, QProgressBar, QToolTip
)
from PySide6.QtCore import QEvent, Signal, Qt
from PySide6.QtGui import QColor

from leanreel.ui_text import UI_TEXT

_HEADERS = UI_TEXT.FILE_HEADERS
_TREE_HEADERS = UI_TEXT.FILE_TREE_HEADERS

from leanreel.gui.theme import (
    _COLOR_CODEC_OK,
    _COLOR_CODEC_MISSING,
    _COLOR_PROBE_FAILED,
    _COLOR_HDR_DV,
    _COLOR_HDR_HDR10,
    _COLOR_HDR_SDR,
)

from leanreel.domain.models import MatchResult, FileDecisionDisplay, FileRow


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


class _SortableTreeItem(QTreeWidgetItem):
    """QTreeWidgetItem that sorts by Qt.UserRole numeric value when present."""

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        col = self.treeWidget().sortColumn() if self.treeWidget() else 0
        left = self.data(col, Qt.UserRole)
        right = other.data(col, Qt.UserRole)
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return left < right
        return super().__lt__(other)


from leanreel.gui.utils import _format_bytes
from leanreel.domain.models import get_skip_reason


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
    strategy_override_changed = Signal(object, str)
    custom_strategy_requested = Signal(object)
    refresh_requested = Signal()
    tree_folder_refresh_requested = Signal(int)  # 树视图右键刷新文件夹，传 folder_id
    row_selected = Signal(object)  # 单行选中时发出 (library_folder_id, relative_path) 或 None

    def __init__(self):
        super().__init__()
        self._strategy_lookup: dict[str, Any] = {}
        self.current_view_mode = "flat"
        self._store = None
        self._flat_adapter = None
        self._tree_adapter = None
        self._last_check_anchor = None
        self._last_tree_check_anchor = None
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

    # ── Stack 视图切换（唯一入口，集中管理） ──

    def _show_table(self):
        self.stack.setCurrentWidget(self.table)

    def _show_tree(self):
        self.stack.setCurrentWidget(self.tree)

    def _show_current_view(self):
        """根据 current_view_mode 切换到正确视图（用于数据刷新后恢复视图状态）。"""
        if self.current_view_mode == "tree":
            self._show_tree()
            if self._tree_adapter:
                self._tree_adapter.ensure_current()
        else:
            self._show_table()

    def _show_empty(self, message=UI_TEXT.FILE_UNSCANNED):
        self.summary_label.setText(message)
        self.stack.setCurrentWidget(self.empty_label)

    def enable_sorting(self):
        """探测完成后启用表格排序（探测期间禁用避免 setItem 触发频繁重排）。"""
        self.table.setSortingEnabled(True)

    def set_progress_visible(self, visible: bool):
        """显示/隐藏进度条。"""
        self.progress_bar.setVisible(visible)

    def set_progress(self, done: int, total: int):
        """更新进度条（determinate 模式）。"""
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(done)

    def set_progress_indeterminate(self):
        """显示未知总量的忙碌进度，用于递归发现/缓存解析阶段。"""
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(0)
        self.progress_bar.setValue(0)

    def refresh_summary(self, snapshots: list):
        """Recompute the list summary from the current snapshot data."""
        total_size = sum(getattr(s, "size_bytes", 0) or 0 for s in snapshots)
        total_tb = total_size / (1024**4) if total_size else 0
        processable = sum(1 for s in snapshots if getattr(s, "video_codec", "") and not get_skip_reason(s))
        pending = sum(
            1 for s in snapshots
            if getattr(s, "probe_ok", None) is False
            and not getattr(s, "probe_error", "")
            and not getattr(s, "video_codec", "")
        )
        self.summary_label.setText(UI_TEXT.file_summary(len(snapshots), pending, processable, total_tb))

    def get_checked_file_keys(self) -> list[tuple[int, str]]:
        """返回所有勾中文件的 (library_folder_id, relative_path) key 列表（已排序）。"""
        if self._store:
            return self._store.checked_keys()
        return []

    def set_store(self, store):
        """注入 FileTableStore 并创建 Adapters（QTableView+Model/Delegate）。"""
        from leanreel.gui.adapters.flat_adapter import FlatAdapter
        from leanreel.gui.adapters.tree_adapter import TreeAdapter
        self._store = store
        self._flat_adapter = FlatAdapter(store, self.table,
            strategy_lookup=self._strategy_lookup,
            combo_factory=self._create_strategy_combo)
        self._tree_adapter = TreeAdapter(store, self.tree)
        # QTableView: model dataChanged → 复选框/策略变更
        self._model = self.table.model()
        self._model.dataChanged.connect(self._on_flat_data_changed)
        # QTableView: selectionModel → 行选中
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.tree.itemChanged.connect(self._on_tree_checkbox_changed)

    def _on_flat_data_changed(self, topLeft, bottomRight, roles):
        """Model 数据变更 — 处理复选框和策略下拉。"""
        if not roles:
            return
        # 复选框变更 → 同步到 Store
        if Qt.CheckStateRole in roles:
            for row in range(topLeft.row(), bottomRight.row() + 1):
                store_idx = self._model._to_store_index(row)
                row_obj = self._store.row_at(store_idx)
                if row_obj:
                    checked = self._model.data(self._model.index(row, 0), Qt.CheckStateRole) == Qt.Checked
                    self._store.set_checked(row_obj.key, checked)
            self._apply_filter()
        # 策略变更 → 通过 Store key 精确定位，避免同名文件冲突
        if Qt.EditRole in roles and topLeft.column() == 5:
            store_idx = self._model._to_store_index(topLeft.row())
            row_obj = self._store.row_at(store_idx) if store_idx >= 0 else None
            if row_obj:
                text = self._model.data(topLeft, Qt.DisplayRole) or ""
                self._on_strategy_combo_changed(row_obj.key, text)

    def _on_tree_checkbox_changed(self, item: QTreeWidgetItem, column: int):
        """树视图复选框变更 —— 委托给 Store（若已注入）。"""
        if column != 0:
            return
        key = self._coerce_key(item.data(0, Qt.UserRole))
        if self._store is not None and key is not None:
            self._store.set_checked(key, item.checkState(0) == Qt.Checked)
        self._apply_filter()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # 顶部信息栏
        info_layout = QHBoxLayout()
        self.summary_label = QLabel(UI_TEXT.FILE_UNSCANNED)
        self.refresh_btn = QPushButton(UI_TEXT.FILE_REBUILD_CACHE)
        self.refresh_btn.setToolTip(UI_TEXT.FILE_REBUILD_CACHE_TOOLTIP)
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat(UI_TEXT.FILE_PROGRESS_FORMAT)
        self.progress_bar.setFixedWidth(200)
        self.progress_bar.setMaximumHeight(22)
        self.progress_bar.hide()
        info_layout.addWidget(self.refresh_btn)
        info_layout.addWidget(self.progress_bar)
        self.view_combo = QComboBox()
        self.view_combo.addItem(UI_TEXT.FILE_VIEW_FLAT, "flat")
        self.view_combo.addItem(UI_TEXT.FILE_VIEW_TREE, "tree")
        self.view_combo.currentIndexChanged.connect(
            lambda _i: self.set_view_mode(self.view_combo.currentData())
        )
        self.filter_combo = QComboBox()
        self.filter_combo.addItem(UI_TEXT.FILE_FILTER_ALL, "all")
        self.filter_combo.addItem(UI_TEXT.FILE_FILTER_PROCESSABLE, "processable")
        self.filter_combo.addItem(UI_TEXT.FILE_FILTER_PROTECTED, "protected")
        self.filter_combo.addItem(UI_TEXT.FILE_FILTER_PROBE_FAILED, "probe_failed")
        self.filter_combo.addItem(UI_TEXT.FILE_FILTER_CHECKED, "checked")
        self.filter_combo.currentIndexChanged.connect(lambda _i: self._apply_filter())
        info_layout.addWidget(self.summary_label)
        info_layout.addStretch()
        info_layout.addWidget(self.view_combo)
        info_layout.addWidget(self.filter_combo)
        layout.addLayout(info_layout)

        # 文件表格 (QTableView + FileTableModel)
        self.table = QTableView()
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.ExtendedSelection)
        self.table.setEditTriggers(QTableView.NoEditTriggers)
        self.table.setSortingEnabled(False)
        self.table.setAutoScroll(False)
        self.table.viewport().installEventFilter(self)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(_TREE_HEADERS))
        self.tree.setHeaderLabels(_TREE_HEADERS)
        self.tree.setSortingEnabled(True)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        self.tree.viewport().installEventFilter(self)
        self.tree.hide()

        # 空状态提示
        self.empty_label = QLabel(UI_TEXT.FILE_EMPTY_HINT)
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
        self.select_all_btn = QPushButton(UI_TEXT.FILE_SELECT_ALL)
        self.select_all_btn.clicked.connect(self.select_all)
        self.deselect_all_btn = QPushButton(UI_TEXT.FILE_DESELECT_ALL)
        self.deselect_all_btn.clicked.connect(self.deselect_all)
        self.selection_label = QLabel(UI_TEXT.file_selection_count(0, 0))
        self.selection_label.setStyleSheet("color: #8a857c; font-size: 11px;")
        select_layout.addWidget(self.select_all_btn)
        select_layout.addWidget(self.deselect_all_btn)
        select_layout.addWidget(self.selection_label)
        select_layout.addStretch()
        layout.addLayout(select_layout)

        self.tree.itemChanged.connect(self._on_tree_item_changed)
        self.tree.itemSelectionChanged.connect(self._on_tree_selection_changed)

    def eventFilter(self, source, event):
        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            if source is self.table.viewport() and self._toggle_flat_check_at(pos):
                return True
            if source is self.table.viewport() and self._show_flat_disabled_check_reason_at(pos):
                return True
            if source is self.tree.viewport() and self._toggle_tree_check_at(pos):
                return True
            if source is self.tree.viewport() and self._show_tree_disabled_check_reason_at(pos):
                return True
        return super().eventFilter(source, event)

    def _toggle_flat_check_at(self, pos) -> bool:
        if self._store is None or self.table.model() is None:
            return False
        index = self.table.indexAt(pos)
        if not index.isValid() or index.column() != 0:
            return False
        flags = self.table.model().flags(index)
        if not (flags & Qt.ItemIsEnabled) or not (flags & Qt.ItemIsUserCheckable):
            return False

        modifiers = QApplication.keyboardModifiers()
        if modifiers & Qt.ShiftModifier and self._last_check_anchor is not None:
            anchor = self._last_check_anchor
            clicked = index.row()
            start, end = (anchor, clicked) if anchor < clicked else (clicked, anchor)
            anchor_state = self.table.model().data(self.table.model().index(anchor, 0), Qt.CheckStateRole)
            next_state = Qt.Unchecked if anchor_state == Qt.Checked else Qt.Checked
            for row in range(start, end + 1):
                ri = self.table.model().index(row, 0)
                rflags = self.table.model().flags(ri)
                if (rflags & Qt.ItemIsEnabled) and (rflags & Qt.ItemIsUserCheckable):
                    self.table.model().setData(ri, next_state, Qt.CheckStateRole)
        else:
            current = self.table.model().data(index, Qt.CheckStateRole)
            next_state = Qt.Unchecked if current == Qt.Checked else Qt.Checked
            self.table.model().setData(index, next_state, Qt.CheckStateRole)
            self._last_check_anchor = index.row()

        self._apply_filter()
        return True

    def _show_flat_disabled_check_reason_at(self, pos) -> bool:
        if self._store is None or self.table.model() is None:
            return False
        index = self.table.indexAt(pos)
        if not index.isValid() or index.column() != 0:
            return False
        flags = self.table.model().flags(index)
        if flags & Qt.ItemIsEnabled or not (flags & Qt.ItemIsUserCheckable):
            return False
        reason = self.table.model().data(index, Qt.ToolTipRole) or UI_TEXT.FILE_DISABLED_REASON
        QToolTip.showText(self.table.viewport().mapToGlobal(pos), reason, self.table)
        return True

    def _tree_leaf_items(self) -> list:
        """返回树中所有叶子节点（文件）的扁平列表。"""
        leaves = []
        for i in range(self.tree.topLevelItemCount()):
            folder = self.tree.topLevelItem(i)
            for j in range(folder.childCount()):
                child = folder.child(j)
                if child.childCount() == 0:
                    leaves.append(child)
        return leaves

    def _toggle_tree_check_at(self, pos) -> bool:
        if self._store is None:
            return False
        item = self.tree.itemAt(pos)
        if item is None or item.childCount() > 0:
            return False
        flags = item.flags()
        if not (flags & Qt.ItemIsEnabled) or not (flags & Qt.ItemIsUserCheckable):
            return False

        leaves = self._tree_leaf_items()
        modifiers = QApplication.keyboardModifiers()
        if modifiers & Qt.ShiftModifier and self._last_tree_check_anchor is not None:
            anchor = self._last_tree_check_anchor
            try:
                clicked_idx = leaves.index(item)
            except ValueError:
                clicked_idx = -1
            if clicked_idx >= 0 and anchor < len(leaves):
                start, end = (anchor, clicked_idx) if anchor < clicked_idx else (clicked_idx, anchor)
                anchor_item = leaves[anchor]
                next_checked = anchor_item.checkState(0) != Qt.Checked
                for idx in range(start, end + 1):
                    leaf = leaves[idx]
                    key = self._coerce_key(leaf.data(0, Qt.UserRole))
                    if key is not None:
                        self._store.set_checked(key, next_checked)
        else:
            key = self._coerce_key(item.data(0, Qt.UserRole))
            if key is None:
                return False
            self._store.set_checked(key, item.checkState(0) != Qt.Checked)
            try:
                self._last_tree_check_anchor = leaves.index(item)
            except ValueError:
                pass

        self._apply_filter()
        return True

    def _show_tree_disabled_check_reason_at(self, pos) -> bool:
        if self._store is None:
            return False
        item = self.tree.itemAt(pos)
        if item is None or item.childCount() > 0:
            return False
        flags = item.flags()
        if flags & Qt.ItemIsEnabled or not (flags & Qt.ItemIsUserCheckable):
            return False
        reason = item.toolTip(0) or UI_TEXT.FILE_DISABLED_REASON
        QToolTip.showText(self.tree.viewport().mapToGlobal(pos), reason, self.tree)
        return True

    def populate(self, snapshots: list, matched_strategies: dict[str, MatchResult | None], strategies: list | None = None, fast: bool = False):
        """填充文件表格行（委托给 Store + Adapter）。"""
        from leanreel.state.file_store import FileTableStore

        self.set_strategy_lookup(strategies)

        if not snapshots:
            self._show_empty()
            if self._store:
                self._store.rebuild([], strategies=strategies, keep_checked=False)
            self.summary_label.setText(UI_TEXT.FILE_UNSCANNED)
            self._update_selection_count()
            return

        # 确保 Store 和 Adapter 存在（测试兼容：测试可能直接调用 populate 而未 set_store）
        if self._store is None:
            self.set_store(FileTableStore())

        # 构建 FileRow 列表
        rows = []
        for s in snapshots:
            m = self._match_for_snap(s, matched_strategies)
            d = self._decision_display(s, m)
            rows.append(FileRow(snap=s, match=m, decision=d))
        self._store.rebuild(rows, strategies=strategies, keep_checked=not fast)

        # Store.rebuild 通过信号驱动 Model/Adapter 自动更新 UI
        self._show_current_view()

        self.refresh_summary(snapshots)
        self._update_selection_count()


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
                return UI_TEXT.FILE_PROBE_FAILED
            elif probe_ok is False and not probe_error:
                return UI_TEXT.FILE_PROBING
            return UI_TEXT.FILE_UNRECOGNIZED
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

    def set_strategy_lookup(self, strategies: list | None):
        self._strategy_lookup.clear()
        self._strategy_lookup.update(self._build_strategy_lookup(strategies))

    def _create_strategy_combo(self, relative_path: str, selected_name: str) -> QComboBox:
        combo = QComboBox()
        combo.wheelEvent = lambda event: event.ignore()  # 滚轮不改变策略，留给表格滚动
        combo.setMinimumWidth(140)
        combo.setMaximumHeight(28)
        combo.setStyleSheet("QComboBox { padding: 1px 4px; }")
        names = list(self._strategy_lookup)
        if selected_name and selected_name != UI_TEXT.FILE_UNMATCHED and selected_name not in names:
            names.insert(0, selected_name)
        if UI_TEXT.FILE_CUSTOM_STRATEGY not in names:
            names.append(UI_TEXT.FILE_CUSTOM_STRATEGY)
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
            self._show_tree()
            self.table.hide()
            self.tree.show()
            if self._tree_adapter:
                self._tree_adapter.ensure_current()
        else:
            self._show_table()
            self.tree.hide()
            self.table.show()

    def _on_strategy_combo_changed(self, relative_path: str, strategy_name: str):
        """策略下拉框变更 — 通过 Store 更新数据，Adapter 自动渲染 UI。"""
        if self._store is None:
            return
        # key 可能是 (folder_id, path) tuple 或纯 relative_path 字符串
        target_key = None
        target_row = None
        if isinstance(relative_path, tuple):
            target_key = relative_path
            target_row = self._store.row_by_key(relative_path)
        else:
            target_row = self._store.row_by_relative_path(relative_path)
            if target_row:
                target_key = target_row.key
        if target_key is None:
            return

        if strategy_name != UI_TEXT.FILE_CUSTOM_STRATEGY:
            lookup = self._strategy_lookup.get(strategy_name, strategy_name)
            match = MatchResult(strategy=lookup) if not isinstance(lookup, MatchResult) else lookup
            decision = self._decision_display(target_row.snap, match)
            self._store.update_row(target_key, target_row.snap, match, decision=decision)
        else:
            # "自定义"选项：不改变 store 中的 match，只发信号
            pass

        rel = target_row.snap.relative_path if target_row else (relative_path if isinstance(relative_path, str) else relative_path[1])
        signal_key = target_key if target_key is not None else rel
        self.strategy_override_changed.emit(signal_key, strategy_name)
        if strategy_name == UI_TEXT.FILE_CUSTOM_STRATEGY:
            self.custom_strategy_requested.emit(signal_key)
        self._apply_filter()

    def apply_strategy_to_row(self, path_or_key, strategy: Any):
        """Apply a strategy object to one row and refresh its savings estimate.（通过 Store）"""
        if self._store is None:
            return
        # 优先 key 查找（精确），回退 relative_path 查找（兼容旧调用）
        target_key = None
        if isinstance(path_or_key, tuple):
            target_key = path_or_key
        else:
            row = self._store.row_by_relative_path(path_or_key)
            if row:
                target_key = row.key
        if target_key is None:
            return
        row = self._store.row_by_key(target_key)
        if row:
            match = MatchResult(strategy=strategy) if not isinstance(strategy, MatchResult) else strategy
            decision = self._decision_display(row.snap, match)
            self._store.update_row(target_key, row.snap, match, decision=decision)
        self._apply_filter()

    def update_snapshot_row(self, snap: Any, match: Any = None):
        """后台探测完成后增量更新单行编码信息。

        新架构：Store.update_row + Adapter 信号自动更新 UI。此方法保留作为信号兼容层。
        """
        if self._store is None:
            return
        relative_path = str(getattr(snap, "relative_path", ""))
        if not relative_path:
            return
        key = (int(getattr(snap, "library_folder_id", 0) or 0), relative_path)
        decision = self._decision_display(snap, match)
        self._store.update_row(key, snap, match, decision=decision)

    def _find_row_by_relative_path(self, relative_path: str) -> int | None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)
            if item is not None:
                key = self._coerce_key(item.data(Qt.UserRole))
                if key is not None and key[1] == relative_path:
                    return row
        return None

    def get_checked_relative_paths(self) -> list[str]:
        """返回所有勾中文件的 relative_path 列表（基于 Store，与视图无关）。"""
        if self._store:
            return sorted({key[1] for key in self._store.checked_keys()})
        return []

    def _get_checked_tree_paths(self) -> list[str]:
        """兼容旧调用方：基于 Store 返回已勾选路径列表。"""
        return self.get_checked_relative_paths()

    def select_all(self):
        if self._store is None:
            return
        for i in range(self._store.count()):
            row = self._store.row_at(i)
            if row.decision and row.decision.processable:
                self._store.set_checked(row.key, True)
        # Adapter 的 checked_changed 信号会自动更新 UI 勾选状态
        self._update_selection_count()

    def deselect_all(self):
        if self._store is None:
            return
        for key in self._store.checked_keys():
            self._store.set_checked(key, False)
        # Adapter 的 checked_changed 信号会自动更新 UI 勾选状态
        self._update_selection_count()

    def _on_item_changed(self, item: QTableWidgetItem):
        """旧复选框回调 — 在 set_store 后会被 _on_flat_checkbox_changed 替换。

        保留作为 setup_ui 中的初始连接，避免启动时报错。
        """
        if item.column() == 0:
            key = self._coerce_key(item.data(Qt.UserRole))
            if key is not None and self._store is not None:
                self._store.set_checked(key, item.checkState() == Qt.Checked)
            self._apply_filter()

    def _on_selection_changed(self):
        rows = {idx.row() for idx in self.table.selectedIndexes()}
        if len(rows) == 1:
            row = next(iter(rows))
            m = self.table.model()
            key = m.data(m.index(row, 1), Qt.UserRole) if m else None
            if isinstance(key, tuple) and len(key) == 2:
                self.row_selected.emit(key)
            else:
                self.row_selected.emit(None)
        else:
            self.row_selected.emit(None)  # 多选或取消选中 -> 清空右面板绑定

    def _on_tree_item_changed(self, item: QTreeWidgetItem, column: int):
        """旧树复选框回调 — 在 set_store 后会被 _on_tree_checkbox_changed 替换。"""
        if column == 0:
            key = self._coerce_key(item.data(0, Qt.UserRole))
            if key is not None and self._store is not None:
                self._store.set_checked(key, item.checkState(0) == Qt.Checked)
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
        menu.addAction(UI_TEXT.FILE_REBUILD_FOLDER_CACHE, lambda: self.tree_folder_refresh_requested.emit(folder_id))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _on_tree_selection_changed(self):
        items = self.tree.selectedItems()
        if len(items) == 1 and items[0].childCount() == 0:
            data = items[0].data(0, Qt.UserRole)
            key = self._coerce_key(data) if data else None
            self.row_selected.emit(key)
        else:
            self.row_selected.emit(None)

    def _apply_filter(self):
        filter_key = self.filter_combo.currentData() if hasattr(self, "filter_combo") else "all"
        if self.current_view_mode == "tree":
            if self._tree_adapter:
                self._tree_adapter.apply_tree_filter(filter_key)
            else:
                self._apply_tree_filter_legacy(filter_key)
        else:
            if self._flat_adapter:
                self._flat_adapter.set_filter(filter_key)
        self._update_selection_count()

    def _apply_tree_filter_legacy(self, filter_key: str):
        """树视图过滤的回退实现（无 TreeAdapter 时使用）。"""
        for i in range(self.tree.topLevelItemCount()):
            folder_item = self.tree.topLevelItem(i)
            has_visible = False
            for j in range(folder_item.childCount()):
                child = folder_item.child(j)
                key = self._coerce_key(child.data(0, Qt.UserRole))
                row = self._store.row_by_key(key) if self._store and key else None
                d = row.decision if row else None
                checked = child.flags() & Qt.ItemIsEnabled and child.checkState(0) == Qt.Checked
                hide = False
                if d:
                    if filter_key == "processable":
                        hide = not d.processable
                    elif filter_key == "protected":
                        hide = d.status_key != "protected"
                    elif filter_key == "probe_failed":
                        hide = d.status_key != "probe_failed"
                    elif filter_key == "checked":
                        hide = not checked
                elif filter_key in ("processable", "protected", "probe_failed"):
                    hide = True
                child.setHidden(hide)
                if not hide:
                    has_visible = True
            folder_item.setHidden(not has_visible)

    def _update_selection_count(self):
        if self._store is None:
            self.selection_label.setText(UI_TEXT.file_selection_count(0, 0))
            return
        checked_count = 0
        processable_total = 0
        for row in self._store.rows():
            if row.decision and row.decision.processable:
                processable_total += 1
                if self._store.is_checked(row.key):
                    checked_count += 1
        self.selection_label.setText(UI_TEXT.file_selection_count(checked_count, processable_total))

    def _decision_display(
        self,
        snap: Any,
        match: MatchResult | None,
        compressed_record: dict | None = None,
    ) -> FileDecisionDisplay:
        # ── 已压缩检测（最早） ──
        if compressed_record:
            encoder_label_map = {
                "libx265": "HEVC", "hevc_nvenc": "HEVC",
                "av1_nvenc": "AV1", "copy": "流复制",
            }
            encoder = compressed_record.get("encoder", "")
            label = encoder_label_map.get(encoder, encoder)
            strategy_name = compressed_record.get("strategy_name", "")
            savings = compressed_record.get("savings_pct", 0)
            return FileDecisionDisplay(
                status_key="compressed",
                strategy_text=f"已被压缩为 {label} 片源",
                result_text=f"节省 {savings:.0f}%" if savings else "已完成",
                result_sort=-5,
                processable=False,
                tooltip=f"策略: {strategy_name}",
            )

        # ── 等待探测 ──
        if (
            getattr(snap, "probe_ok", None) is False
            and not getattr(snap, "video_codec", "")
            and not getattr(snap, "probe_error", "")
        ):
            return FileDecisionDisplay(
                status_key="pending",
                strategy_text=UI_TEXT.FILE_PROBING,
                result_text="...",
                result_sort=-4,
                processable=False,
                tooltip=UI_TEXT.FILE_PROBING_TOOLTIP,
            )

        skip_reason = get_skip_reason(snap)
        if skip_reason:
            return FileDecisionDisplay(
                status_key="protected",
                strategy_text=skip_reason,
                result_text=UI_TEXT.FILE_NOT_PROCESS,
                result_sort=-2,
                processable=False,
                tooltip=skip_reason,
            )

        if (
            getattr(snap, "probe_ok", None) is False
            and not getattr(snap, "video_codec", "")
            and getattr(snap, "probe_error", "")
        ):
            probe_error = getattr(snap, "probe_error", "") or UI_TEXT.FILE_PROBE_FAILED
            return FileDecisionDisplay(
                status_key="probe_failed",
                strategy_text=UI_TEXT.FILE_PROBE_FAILED,
                result_text=UI_TEXT.FILE_CANNOT_ESTIMATE,
                result_sort=-3,
                processable=False,
                tooltip=probe_error,
            )

        strategy_name, savings_text, savings_sort = self._resolve_match_display(snap, match)
        return FileDecisionDisplay(
            status_key="processable" if strategy_name != UI_TEXT.FILE_UNMATCHED else "unmatched",
            strategy_text=strategy_name,
            result_text=savings_text,
            result_sort=savings_sort,
            processable=strategy_name != UI_TEXT.FILE_UNMATCHED,
            tooltip=strategy_name,
        )

    def _resolve_match_display(self, snap: Any, match: MatchResult | None) -> tuple[str, str, int | float]:
        """将 MatchResult 解析为（策略名, 节省文本, 排序列数值）三元组。"""
        if match is None:
            return UI_TEXT.FILE_UNMATCHED, "—", -1

        strategy = match.strategy
        estimate = match.estimate or {}

        # ── 提取策略名称 ──
        strategy_name: str = UI_TEXT.FILE_UNMATCHED
        if hasattr(strategy, "name"):
            strategy_name = strategy.name or UI_TEXT.FILE_UNMATCHED
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
