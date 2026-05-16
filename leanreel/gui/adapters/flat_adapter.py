"""平铺表格适配器 — QTableView + FileTableModel + StrategyDelegate"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableView, QHeaderView

from leanreel.gui.adapters.file_table_model import FileTableModel
from leanreel.gui.adapters.strategy_delegate import StrategyDelegate


class FlatAdapter:
    """连接 FileTableStore → QTableView。

    零拷贝：Model 直接从 Store 读数据。QTableView 只渲染可见行。
    """

    def __init__(self, store, view: QTableView, strategy_lookup=None, combo_factory=None):
        self._store = store
        self._view = view
        self._model = FileTableModel(store, view)
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
        if combo_factory and strategy_lookup:
            view.setItemDelegateForColumn(5, StrategyDelegate(strategy_lookup, combo_factory))

    def enable_sorting(self):
        self._view.setSortingEnabled(True)

    def set_filter(self, filter_key: str):
        self._model.set_filter(filter_key)
