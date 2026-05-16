# LeanReel QTableView 最终迁移 + 遗留清理

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 彻底完成 QTableView+Model 迁移，删除所有 QTableWidget hack，清掉 `_on_rebuild`/`create_combo_cells` 等旧 FlatAdapter 残留方法，统一到信号驱动。

**Architecture:** QTableView + FileTableModel(QAbstractTableModel) + StrategyDelegate。FileListPanel 只当布局容器，FlatAdapter 薄层连 Store→View。

**Tech Stack:** Python 3.12, PySide6, 现有 FileTableStore

---

## 当前问题（git stash pop 后恢复的状态）

1. `flat_adapter.py` — 引用 QTableWidget/QTableWidgetItem，有 `_render_row`/`_on_rebuild`/`_render_batch`/`create_combo_cells` — 全是旧 API
2. `file_list.py:214` — `self.table = QTableWidget()` — 功能退化回原始
3. `file_list.py:306-307` — 调用已删除的 `_flat_adapter._on_rebuild()`
4. `file_list.py:322` — 调用已删除的 `create_combo_cells()`
5. `set_view_mode` — 调用已删除的 `_on_rebuild()`
6. 测试用旧 QTableWidget API + helper 函数（`_text`/`_check` 等）
7. `file_table_model.py` 已创建但未被 FlatAdapter 使用

---

## 修复方案

### Task 1: 恢复 QTableView 基础设施

**Files:** Modify `leanreel/gui/file_list.py`

- [ ] **Step 1: setup_ui 改回 QTableView**

```python
# 第214行，替换为:
self.table = QTableView()
self.table.setSelectionBehavior(QTableView.SelectRows)
self.table.setEditTriggers(QTableView.NoEditTriggers)
self.table.setSortingEnabled(False)
self.table.setAutoScroll(False)
```

删除第215-236行的旧 QTableWidget 配置代码。

- [ ] **Step 2: set_store 改为创建 Model+Delegate 版 FlatAdapter**

```python
def set_store(self, store):
    from leanreel.gui.adapters.flat_adapter import FlatAdapter
    from leanreel.gui.adapters.tree_adapter import TreeAdapter
    self._store = store
    self._flat_adapter = FlatAdapter(store, self.table,
        strategy_lookup=self._strategy_lookup,
        combo_factory=self._create_strategy_combo)
    self._tree_adapter = TreeAdapter(store, self.tree)
    # QTableView 信号
    self._model = self.table.model()
    self._model.dataChanged.connect(self._on_flat_data_changed)
    self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)
    self.tree.itemChanged.connect(self._on_tree_checkbox_changed)
```

注意：删除 `self.table.itemChanged` 相关代码。

- [ ] **Step 3: 删除 populate() 中的旧 FlatAdapter 调用**

删除第306-323行：
```python
# 删除这两段
if self._flat_adapter:
    self._flat_adapter._on_rebuild()
if self._tree_adapter:
    self._tree_adapter._on_rebuild()
...
if self._flat_adapter:
    self._flat_adapter.create_combo_cells(...)
```

`store.rebuild()` 已经通过 `rows_rebuilt` signal 触发 Model 更新，不需要手动调用。

- [ ] **Step 4: 删除 set_view_mode 中的旧调用**

删除 `self._flat_adapter._on_rebuild()` 和 `self._tree_adapter._on_rebuild()` 调用。Model 信号驱动无需手动刷新。

- [ ] **Step 5: 删除 enable_sorting 旧实现**

改为 `self.table.setSortingEnabled(True)` — QTableView 原生支持。

### Task 2: 重写 FlatAdapter 为纯委托

**Files:** Modify `leanreel/gui/adapters/flat_adapter.py`

- [ ] **Step 1: 替换为最小实现**

```python
"""平铺表格适配器 — QTableView + FileTableModel + StrategyDelegate"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableView, QHeaderView, QAbstractItemView

from leanreel.gui.adapters.file_table_model import FileTableModel
from leanreel.gui.adapters.strategy_delegate import StrategyDelegate


class FlatAdapter:
    def __init__(self, store, view: QTableView, strategy_lookup=None, combo_factory=None):
        self._store = store
        self._view = view
        self._model = FileTableModel(store, view)
        view.setModel(self._model)
        view.verticalHeader().setDefaultSectionSize(32)
        view.verticalHeader().setVisible(False)
        h = view.horizontalHeader()
        h.setSortIndicatorShown(True)
        h.setSectionsMovable(False)
        h.setSectionResizeMode(0, QHeaderView.Fixed)
        h.setSectionResizeMode(1, QHeaderView.Interactive)
        for i in range(2, 7):
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
```

删除所有旧方法：`_on_rebuild`、`_render_batch`、`_render_row`、`_on_row_updated`、`_find_table_row`、`_on_checked_changed`、`create_combo_cells`、`_render_combo_batch`、`_format_codec`。

### Task 3: 删除 file_list.py 中的 QTableWidget API 引用

- [ ] **Step 1: 删除 `ensure_combos_created` 方法**

QComboBox 由 delegate 按需创建，不需要预创建。

- [ ] **Step 2: 删除 `_on_flat_checkbox_changed` 方法**

改为 `_on_flat_data_changed`（已在 set_store 中连接）。

- [ ] **Step 3: 简化 `_apply_filter`**

直接委托给 FlatAdapter.set_filter：

```python
def _apply_filter(self):
    filter_key = self.filter_combo.currentData() or "all"
    if self.current_view_mode == "tree":
        if self._tree_adapter:
            self._tree_adapter.apply_tree_filter(filter_key)
    else:
        if self._flat_adapter:
            self._flat_adapter.set_filter(filter_key)
    self._update_selection_count()
```

删除旧的 `setRowHidden` 循环。

### Task 4: 更新测试

- [ ] **Step 1: 删除 test_main_window.py 中的 helper 函数**

删除 `_text`/`_check`/`_set_check`/`_flags`/`_userdata`/`_combo`。改为原生 model API。

- [ ] **Step 2: 更新 test_flat_adapter.py**

所有测试用 QTableView + Model API：

```python
def test_model_rebuild(qtbot):
    from leanreel.gui.adapters.file_table_model import FileTableModel
    from PySide6.QtWidgets import QTableView
    store = FileTableStore()
    view = QTableView()
    model = FileTableModel(store, view)
    view.setModel(model)
    ...
```

- [ ] **Step 3: 更新 test_controller_integration.py**

同上述模式，删除 helper 函数。

### Task 5: 全量验证

```bash
pytest tests/ -q --tb=short
```

期望：333+ passed

### Task 6: 提交

```bash
git add leanreel/gui/file_list.py leanreel/gui/adapters/flat_adapter.py tests/
git commit -m "refactor: complete QTableView migration, remove all QTableWidget hacks"
```

---

## 功能检查清单

- [ ] 平铺表格显示 7 列完整数据
- [ ] 勾选框正常（Checked→Unchecked→Checked）
- [ ] 策略列点击弹出 QComboBox（delegate）
- [ ] 过滤切换（全部/可处理/已保护/探测失败/已选择）
- [ ] 排序点击表头
- [ ] 探测完成后 `enable_sorting` 调用
- [ ] `all_done` 时 QComboBox delegate 正常工作
- [ ] 重建缓存不丢旧数据
- [ ] 树视图独立工作
- [ ] 平铺↔树切换勾选保持
