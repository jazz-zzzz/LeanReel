"""平铺表格适配器 — QTableView + FileTableModel + StrategyDelegate"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QTableView, QHeaderView

from leanreel.gui.adapters.file_table_model import FileTableModel
from leanreel.gui.adapters.strategy_delegate import StrategyDelegate


class FlatAdapter:
    """连接 FileTableStore → QTableView。

    零拷贝：Model 直接从 Store 读数据。QTableView 只渲染可见行。
    """

    _COMBO_BATCH = 64

    def __init__(self, store, view: QTableView, strategy_lookup=None, combo_factory=None):
        self._store = store
        self._view = view
        self._model = FileTableModel(store, view)
        self._combo_generation = 0
        self._combo_next_row = 0
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

    def enable_sorting(self):
        self._view.setSortingEnabled(True)

    def set_filter(self, filter_key: str):
        self._model.set_filter(filter_key)

    def create_combo_cells(self, combo_factory=None):
        """Compatibility entry point: ensure strategy editors are visible."""
        self._schedule_persistent_combos()

    def _close_persistent_combos(self):
        self._combo_generation += 1
        for row in range(self._model.rowCount()):
            self._view.closePersistentEditor(self._model.index(row, 5))

    def _schedule_persistent_combos(self):
        """Batch-open persistent QComboBox editors to avoid freezing large lists."""
        self._combo_generation += 1
        self._combo_next_row = 0
        self._open_combo_batch(self._combo_generation)

    def _open_combo_batch(self, generation):
        if generation != self._combo_generation:
            return
        scanned = 0
        row_count = self._model.rowCount()
        while self._combo_next_row < row_count and scanned < self._COMBO_BATCH:
            row = self._combo_next_row
            self._combo_next_row += 1
            scanned += 1
            store_idx = self._model._to_store_index(row)
            r = self._store.row_at(store_idx)
            if r and r.decision and r.decision.processable:
                self._view.openPersistentEditor(self._model.index(row, 5))
        if self._combo_next_row < row_count:
            QTimer.singleShot(1, lambda gen=generation: self._open_combo_batch(gen))
