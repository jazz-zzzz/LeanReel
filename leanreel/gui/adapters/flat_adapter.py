"""平铺表格适配器 — QTableView + FileTableModel + StrategyDelegate"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QTableView, QHeaderView

from leanreel.gui.adapters.file_table_model import FileTableModel
from leanreel.gui.adapters.strategy_delegate import StrategyDelegate


class FlatAdapter:
    """连接 FileTableStore → QTableView。

    零拷贝：Model 直接从 Store 读数据。QTableView 只渲染可见行。
    QComboBox 视口内懒创建：只为可见区域的行创建策略下拉，滚动时动态维护。
    """

    _COMBO_BATCH = 32

    def __init__(self, store, view: QTableView, strategy_lookup=None, combo_factory=None):
        self._store = store
        self._view = view
        self._model = FileTableModel(store, view)
        self._combo_generation = 0
        self._combo_next_row = 0
        self._combo_rows: set[int] = set()  # 当前持有 QComboBox 的行号
        self._strategy_lookup = strategy_lookup if strategy_lookup is not None else {}
        view.setModel(self._model)
        view.verticalHeader().setDefaultSectionSize(32)
        view.verticalHeader().setMinimumSectionSize(32)
        view.verticalHeader().setMaximumSectionSize(32)
        view.verticalHeader().setVisible(False)
        h = view.horizontalHeader()
        h.setSortIndicatorShown(True)
        h.setSectionsMovable(False)
        h.setSectionResizeMode(0, QHeaderView.Fixed)
        for i in range(1, 7):
            h.setSectionResizeMode(i, QHeaderView.Interactive)
        view.setColumnWidth(0, 30)
        view.setColumnWidth(1, 260)
        view.setColumnWidth(2, 70)
        view.setColumnWidth(3, 175)
        view.setColumnWidth(4, 60)
        view.setColumnWidth(5, 260)
        view.setColumnWidth(6, 190)
        view.setItemDelegateForColumn(5, StrategyDelegate(self._strategy_lookup, combo_factory, view))
        self._model.layoutAboutToBeChanged.connect(self._close_persistent_combos)
        self._model.layoutChanged.connect(self._schedule_persistent_combos)
        # E.1 滚动时维护视口内可见行的 QComboBox
        view.verticalScrollBar().valueChanged.connect(self._on_scroll)
        # D 手动表头排序（探测期间 setSortingEnabled(False)，但仍可点击表头排序）
        h.sectionClicked.connect(self._on_header_clicked)

    def enable_sorting(self):
        self._view.setSortingEnabled(True)

    def _on_header_clicked(self, section: int):
        """表头点击触发一次性排序，不会因数据更新自动重排。"""
        if not self._view.isSortingEnabled():
            order = Qt.AscendingOrder
            if self._model._sort_col == section:
                order = Qt.DescendingOrder if self._model._sort_order == Qt.AscendingOrder else Qt.AscendingOrder
            self._model.sort(section, order)

    def set_filter(self, filter_key: str):
        self._model.set_filter(filter_key)

    def create_combo_cells(self, combo_factory=None):
        """确保可见行的策略编辑器已创建。"""
        self._schedule_persistent_combos()

    def _close_persistent_combos(self):
        self._combo_generation += 1
        # 只关闭已有 combo 的行，不遍历全表
        for row in list(self._combo_rows):
            self._view.closePersistentEditor(self._model.index(row, 5))
        self._combo_rows.clear()

    def _schedule_persistent_combos(self):
        """为视口内可见行批量创建 QComboBox。"""
        self._combo_generation += 1
        self._combo_next_row = 0
        self._combo_rows.clear()
        self._open_combo_batch(self._combo_generation)

    def _on_scroll(self, _value):
        """滚动时刷新视口内 QComboBox — 关闭离开视口的，创建进入视口的。"""
        self._update_viewport_combos()

    def _update_viewport_combos(self):
        """只为视口内行创建 QComboBox，关闭不在视口内的。"""
        row_count = self._model.rowCount()
        if row_count == 0:
            return
        top_row = self._view.rowAt(0)
        bottom_row = self._view.rowAt(self._view.viewport().height() - 4)
        if top_row < 0:
            top_row = 0
        if bottom_row < 0:
            bottom_row = row_count - 1
        # 扩展一行缓冲，减少滚动边缘的创建/销毁抖动
        top_row = max(0, top_row - 1)
        bottom_row = min(row_count - 1, bottom_row + 1)
        visible = set(range(top_row, bottom_row + 1))

        # 关闭离开视口的行
        gone = self._combo_rows - visible
        for row in gone:
            if row < row_count:
                self._view.closePersistentEditor(self._model.index(row, 5))

        # 打开新进入视口的行（仅 processable 的行）
        new_rows = visible - self._combo_rows
        for row in sorted(new_rows):
            if row < row_count:
                store_idx = self._model._to_store_index(row)
                r = self._store.row_at(store_idx)
                if r and r.decision and r.decision.processable:
                    self._view.openPersistentEditor(self._model.index(row, 5))

        self._combo_rows = visible

    def _open_combo_batch(self, generation):
        """批量打开 QComboBox：优先覆盖视口内可见行，viewport 未布局时回退到固定批大小。"""
        if generation != self._combo_generation:
            return
        row_count = self._model.rowCount()
        if row_count == 0:
            return

        vp_height = self._view.viewport().height()
        if vp_height > 0:
            visible_bottom = self._view.rowAt(vp_height - 1)
        else:
            visible_bottom = -1
        if visible_bottom < 0:
            visible_bottom = min(row_count - 1, self._COMBO_BATCH - 1)

        scanned = 0
        while self._combo_next_row <= visible_bottom and scanned < self._COMBO_BATCH:
            row = self._combo_next_row
            self._combo_next_row += 1
            scanned += 1
            store_idx = self._model._to_store_index(row)
            r = self._store.row_at(store_idx)
            if r and r.decision and r.decision.processable:
                self._view.openPersistentEditor(self._model.index(row, 5))
                self._combo_rows.add(row)

        if self._combo_next_row <= visible_bottom:
            QTimer.singleShot(1, lambda gen=generation: self._open_combo_batch(gen))
