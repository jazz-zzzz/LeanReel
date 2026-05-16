# LeanReel 文件列表重构计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构文件列表页的数据架构——用单一数据源 + 适配器模式替代当前 23 个分散的 dict/set/list，保持功能和外观不变。

**Architecture:** 借鉴 Qt Model/View + Flux 单向数据流。`FileTableStore` 是唯一数据源（QObject + Signal），Flat 和 Tree 两个适配器只读 Store 并同步 UI，不持有业务状态。控制器只操作 Store，不直接操作视图。

**Tech Stack:** Python 3.12, PySide6, pytest + pytest-qt, 现有 LeanReel dataclass 模型。

**参考项目:** qBittorrent (torrent list model), KDE Dolphin (dual flat/tree), Redux (single source of truth).

---

## 当前问题量化

| 指标 | 当前值 | 目标值 |
|------|--------|--------|
| FileListPanel 状态变量 | 17 个 dict/set/list | 0（全部移到 Store）|
| main.py 控制器状态变量 | 6 个 | 2 个 |
| 同份数据存储份数 | 3-4 份（by_path × by_key × by_row × snap） | 1 份 |
| 视图切换数据同步 | 7 个方法手动同步 | 自动（信号驱动） |
| 探测定时更新代码路径 | 3 条（flat/ tree/ both） | 1 条（Store 信号分发） |

---

## 核心设计：FileTableStore

```python
class FileTableStore(QObject):
    """文件列表唯一数据源 — 所有视图和控制器只读写这一个对象。"""

    # ── 信号 ──
    rows_rebuilt = Signal()                        # 全部行被替换（populate）
    row_updated = Signal(int, object, object)       # 单行更新（index, FileRow, old_snap）
    checked_changed = Signal()                      # 勾选状态变更
    filter_changed = Signal(str)                    # 过滤条件变更

    # ── 内部数据（唯一副本） ──
    _rows: list[FileRow]                           # 有序全量行
    _by_key: dict[tuple[int, str], int]            # (folder_id, path) → index
    _checked: set[tuple[int, str]]                 # 勾选 key 集合
    _filter_key: str = "all"                       # 当前过滤
    _strategies: list | None = None                # 策略列表

    # ── 查询 ──
    def count(self) -> int: ...
    def row_at(self, index: int) -> FileRow: ...
    def row_by_key(self, key) -> FileRow | None: ...
    def is_checked(self, key) -> bool: ...
    def checked_keys(self) -> list[tuple[int, str]]: ...
    def visible_rows(self) -> list[tuple[int, FileRow]]: ...  # 过滤后
    def folder_stats(self) -> dict[str, int]: ...             # 文件夹→总大小
```

### FileRow 数据结构

```python
@dataclass
class FileRow:
    key: tuple[int, str]           # (library_folder_id, relative_path)
    snap: FileSnapshot              # 最新快照
    match: MatchResult | None       # 策略匹配结果
    decision: FileDecisionDisplay   # 预计算的显示状态
    folder_name: str                # 目录名（树视图用）
```

所有 17 个 dict 的功能统一收敛到 `_rows` + `_by_key` + `_checked` 三个结构中。

---

## 架构对比

```
【当前】
main.py                 file_list.py
current_snapshots ───→ _snapshots_by_path
strategy_overrides ──→ _snapshots_by_key
                      _last_matches
                      _row_by_path
probed signal ───────→ _row_by_key ──→ table.setItem()
                      _row_status_keys
                      _row_processable ──→ 17个dict互相同步
                      _status_by_key
                      _processable_by_key
                      _checked_keys ──→ _sync_checked_from_view()
                      _tree_item_by_key ──→ _populate_tree()
                      _path_gen
                      _populate_gen
                      _render_gen
                      _batch_* (×5)

【重构后】
main.py                file_list.py (FlatAdapter)      file_list.py (TreeAdapter)
        ↘           ↙                ↘              ↙
              FileTableStore               FileTableStore
              (唯一数据源)                 (同一实例)
              _rows: list[FileRow]         ← 读
              _by_key: dict               ← 读
              _checked: set               ← 读/写
              signals ────────────────────→ 适配器自动更新 UI
```

**关键变化：**
- 控制器不再"持有"快照列表——只调用 `store.rebuild(rows)` 或 `store.update_row(key, snap, match)`
- 视图不再"持有"任何业务状态——每个 `row_updated` 信号直接对应一次 `setItem`
- 勾选状态只在 Store 里存一份——两个视图读同一份
- `_populate_tree` 不再需要独立维护——从 Store 读取 `folder_stats()` 和 `visible_rows()`

---

## 文件结构

**新建:**
- `leanreel/data/file_store.py` — `FileRow`, `FileTableStore`
- `leanreel/gui/adapters/__init__.py`
- `leanreel/gui/adapters/flat_adapter.py` — 平铺表格适配器
- `leanreel/gui/adapters/tree_adapter.py` — 树视图适配器

**修改:**
- `leanreel/gui/file_list.py` — 删除 17 个 dict，委托给 Store + Adapter
- `leanreel/main.py` — 控制器只操作 Store，删除 `current_snapshots` 等 6 个变量

**不动:**
- `leanreel/core/scanner.py` — `probe_stream` 对外接口不变
- `leanreel/executor/*` — 执行器不变
- `leanreel/gui/strategy_panel.py` — 策略面板不变

---

## 分阶段执行

### Phase 1: FileTableStore（数据层，4 个 Task）

纯数据层，无 GUI 依赖，可独立测试。

#### Task 1.1: FileRow 和 FileTableStore 基础结构

**Files:** Create `leanreel/data/file_store.py`

- [ ] **Step 1: 写 FileRow dataclass 测试**

```python
# tests/test_file_store.py
def test_file_row_from_snapshot():
    from leanreel.data.file_store import FileRow
    from leanreel.data.models import FileSnapshot, HDRType

    snap = FileSnapshot(
        library_folder_id=7, relative_path="a.mkv",
        file_name="a.mkv", size_bytes=1024,
        video_codec="h264", hdr_type=HDRType.SDR,
    )
    row = FileRow(snap=snap)
    assert row.key == (7, "a.mkv")
    assert row.folder_name == "."
    assert row.snap == snap
```

```python
def test_file_row_folder_name():
    from leanreel.data.file_store import FileRow
    snap = FileSnapshot(library_folder_id=1, relative_path="Season 1/E01.mkv", ...)
    row = FileRow(snap=snap)
    assert row.folder_name == "Season 1"
```

- [ ] **Step 2: 实现 FileRow**

```python
@dataclass
class FileRow:
    snap: FileSnapshot
    match: MatchResult | None = None
    decision: FileDecisionDisplay | None = None

    @property
    def key(self) -> tuple[int, str]:
        return (self.snap.library_folder_id, self.snap.relative_path)

    @property
    def folder_name(self) -> str:
        name = str(self.snap.relative_path).replace("\\", "/").rsplit("/", 1)[0]
        return name or "."
```

- [ ] **Step 3: 写 FileTableStore 基础测试**

```python
def test_store_rebuild():
    store = FileTableStore()
    snap = FileSnapshot(library_folder_id=7, relative_path="a.mkv",
                        file_name="a.mkv", size_bytes=1024, video_codec="h264")
    rows = [FileRow(snap=snap)]
    store.rebuild(rows)
    assert store.count() == 1
    assert store.row_at(0).key == (7, "a.mkv")

def test_store_rebuild_clears_old():
    store = FileTableStore()
    store.rebuild([FileRow(snap=...)])
    store.rebuild([])
    assert store.count() == 0
```

- [ ] **Step 4: 实现 FileTableStore 核心方法**

```python
class FileTableStore(QObject):
    rows_rebuilt = Signal()
    row_updated = Signal(int, object)       # index, FileRow
    checked_changed = Signal()

    def __init__(self):
        super().__init__()
        self._rows: list[FileRow] = []
        self._by_key: dict[tuple[int, str], int] = {}
        self._checked: set[tuple[int, str]] = set()
        self._strategies: list | None = None

    def rebuild(self, rows: list[FileRow], strategies=None, keep_checked=True):
        if not keep_checked:
            self._checked.clear()
        else:
            valid = {r.key for r in rows}
            self._checked = {k for k in self._checked if k in valid}
        self._rows = list(rows)
        self._by_key = {r.key: i for i, r in enumerate(self._rows)}
        self._strategies = strategies
        self.rows_rebuilt.emit()

    def update_row(self, key: tuple[int, str], snap: FileSnapshot, match=None):
        idx = self._by_key.get(key)
        if idx is None:
            return
        row = self._rows[idx]
        row.snap = snap
        if match is not None:
            row.match = match
        # 重新计算 decision（需要策略上下文，由调用方传入或 Store 内部计算）
        self.row_updated.emit(idx, row)

    def count(self) -> int:
        return len(self._rows)

    def row_at(self, index: int) -> FileRow:
        return self._rows[index]

    def row_by_key(self, key) -> FileRow | None:
        idx = self._by_key.get(key)
        return self._rows[idx] if idx is not None else None

    def is_checked(self, key) -> bool:
        return key in self._checked

    def toggle_checked(self, key):
        if key in self._checked:
            self._checked.discard(key)
        else:
            self._checked.add(key)
        self.checked_changed.emit()

    def set_checked(self, key, state: bool):
        if state:
            self._checked.add(key)
        else:
            self._checked.discard(key)
        self.checked_changed.emit()

    def checked_keys(self) -> list[tuple[int, str]]:
        return sorted(self._checked)

    def folder_stats(self) -> dict[str, int]:
        stats: dict[str, int] = {}
        for row in self._rows:
            stats[row.folder_name] = stats.get(row.folder_name, 0) + row.snap.size_bytes
        return stats
```

- [ ] **Step 5: Commit**

```bash
git add leanreel/data/file_store.py tests/test_file_store.py
git commit -m "feat: add FileTableStore — single source of truth for file list data"
```

#### Task 1.2: FileTableStore 过滤和排序

- [ ] **Step 1: 写过滤测试**

```python
def test_store_filter_processable():
    store = FileTableStore()
    from leanreel.gui.file_list import FileDecisionDisplay
    r1 = FileRow(snap=make_snap("a.mkv", codec="h264"))
    r1.decision = FileDecisionDisplay(status_key="processable", strategy_text="均衡", result_text="50%", result_sort=50, processable=True, tooltip="")
    r2 = FileRow(snap=make_snap("b.mkv", codec="hevc"))
    r2.decision = FileDecisionDisplay(status_key="protected", strategy_text="跳过", result_text="不处理", result_sort=-2, processable=False, tooltip="")
    store.rebuild([r1, r2])
    store.set_filter("processable")
    visible = store.visible_rows()
    assert len(visible) == 1
    assert visible[0][1].snap.file_name == "a.mkv"
```

- [ ] **Step 2: 实现过滤**

```python
def set_filter(self, filter_key: str):
    self._filter_key = filter_key

def visible_rows(self) -> list[tuple[int, FileRow]]:
    result = []
    for i, row in enumerate(self._rows):
        if self._is_visible(row):
            result.append((i, row))
    return result

def _is_visible(self, row: FileRow) -> bool:
    if self._filter_key == "all":
        return True
    d = row.decision
    if d is None:
        return self._filter_key != "checked"
    if self._filter_key == "processable":
        return d.processable
    if self._filter_key == "protected":
        return d.status_key == "protected"
    if self._filter_key == "probe_failed":
        return d.status_key == "probe_failed"
    if self._filter_key == "checked":
        return row.key in self._checked
    return True
```

- [ ] **Step 3: Commit**

```bash
git add leanreel/data/file_store.py tests/test_file_store.py
git commit -m "feat: add filter and visible_rows to FileTableStore"
```

#### Task 1.3: FileTableStore 决策计算

将 `_decision_display` 逻辑移到 Store 内部，确保每次 `rebuild` 和 `update_row` 后 decision 自动更新。

- [ ] **Step 1: 实现 `_compute_decision`**

```python
def _compute_decision(self, row: FileRow):
    snap = row.snap
    skip_reason = get_skip_reason(snap)
    if skip_reason:
        row.decision = FileDecisionDisplay(
            status_key="protected", strategy_text=skip_reason,
            result_text="不处理", result_sort=-2, processable=False, tooltip=skip_reason,
        )
        return
    probe_failed = not snap.probe_ok and not snap.video_codec and snap.probe_error
    if probe_failed:
        row.decision = FileDecisionDisplay(
            status_key="probe_failed", strategy_text="探测失败",
            result_text="无法估算", result_sort=-3, processable=False,
            tooltip=snap.probe_error or "探测失败",
        )
        return
    strategy_name, savings_text, savings_sort = _resolve_match_display(snap, row.match)
    row.decision = FileDecisionDisplay(
        status_key="processable" if strategy_name != "未匹配" else "unmatched",
        strategy_text=strategy_name, result_text=savings_text,
        result_sort=savings_sort, processable=strategy_name != "未匹配",
        tooltip=strategy_name,
    )
```

- [ ] **Step 2: 在 `rebuild` 和 `update_row` 中调用**

```python
def rebuild(self, rows, strategies=None, keep_checked=True):
    ...
    for row in self._rows:
        self._compute_decision(row)
    self.rows_rebuilt.emit()

def update_row(self, key, snap, match=None):
    ...
    row.snap = snap
    if match is not None:
        row.match = match
    self._compute_decision(row)
    self.row_updated.emit(idx, row)
```

- [ ] **Step 3: Commit**

```bash
git add leanreel/data/file_store.py
git commit -m "feat: compute FileDecisionDisplay inside FileTableStore"
```

---

### Phase 2: Flat 适配器（视图层，3 个 Task）

#### Task 2.1: 创建 FlatAdapter

**Files:** Create `leanreel/gui/adapters/flat_adapter.py`

FlatAdapter 连接 `FileTableStore` 和 `QTableWidget`。监听 Store 信号，自动更新表格。

- [ ] **Step 1: 写测试**

```python
def test_flat_adapter_rebuild_populates_table():
    store = FileTableStore()
    table = QTableWidget()
    adapter = FlatAdapter(store, table)

    snap = make_snap("a.mkv", codec="h264", size=1024)
    row = FileRow(snap=snap)
    store.rebuild([row])

    assert table.rowCount() == 1
    assert table.item(0, 1).text() == "a.mkv"
    assert table.item(0, 3).text() == "h264"

def test_flat_adapter_row_update():
    store = FileTableStore()
    table = QTableWidget()
    adapter = FlatAdapter(store, table)

    snap = make_snap("a.mkv", codec="", size=0)
    store.rebuild([FileRow(snap=snap)])
    assert table.item(0, 3).text() == "未识别"

    new_snap = make_snap("a.mkv", codec="h264", size=1024, probe_ok=True)
    store.update_row((0, "a.mkv"), new_snap)
    assert table.item(0, 3).text() == "h264"
```

- [ ] **Step 2: 实现 FlatAdapter**

```python
class FlatAdapter(QObject):
    def __init__(self, store: FileTableStore, table: QTableWidget, strategies=None):
        super().__init__()
        self._store = store
        self._table = table
        self._strategies = strategies
        self._row_key: list[tuple] = []  # 当前表格中每行的 key
        store.rows_rebuilt.connect(self._on_rebuild)
        store.row_updated.connect(self._on_row_updated)

    def _on_rebuild(self):
        store = self._store
        self._table.setSortingEnabled(False)
        self._table.blockSignals(True)
        self._table.clearContents()
        self._table.setRowCount(store.count())
        self._row_key = []
        for i in range(store.count()):
            row = store.row_at(i)
            self._row_key.append(row.key)
            self._render_row(i, row)
        self._table.blockSignals(False)
        self._after_rebuild()

    def _render_row(self, table_row: int, row: FileRow):
        """渲染单行——从 Store 读取所有数据，不自行缓存"""
        # 列0: 勾选框
        check = QTableWidgetItem()
        key = row.key
        check.setData(Qt.UserRole, key)
        if row.decision and row.decision.processable:
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        else:
            check.setFlags(Qt.ItemIsUserCheckable)
            check.setToolTip(row.decision.tooltip if row.decision else "")
        check.setCheckState(Qt.Checked if self._store.is_checked(key) else Qt.Unchecked)
        self._table.setItem(table_row, 0, check)
        # 列1: 文件名
        name = QTableWidgetItem(row.snap.file_name)
        name.setData(Qt.UserRole, key)
        self._table.setItem(table_row, 1, name)
        # 列2: 体积
        self._table.setItem(table_row, 2,
            SortableTableWidgetItem(_format_bytes(row.snap.size_bytes), row.snap.size_bytes))
        # 列3: 编码
        codec = QTableWidgetItem(_format_codec(row.snap))
        codec.setForeground(...)  # 颜色逻辑
        self._table.setItem(table_row, 3, codec)
        # 列4: HDR
        hdr = QTableWidgetItem(_format_hdr(row.snap.hdr_type))
        hdr.setForeground(...)
        self._table.setItem(table_row, 4, hdr)
        # 列5: 策略
        self._render_strategy_cell(table_row, row)
        # 列6: 结果
        d = row.decision
        self._table.setItem(table_row, 6,
            SortableTableWidgetItem(d.result_text if d else "—", d.result_sort if d else -1))

    def _on_row_updated(self, idx: int, row: FileRow):
        table_row = self._find_table_row(row.key)
        if table_row is None:
            return
        self._render_row(table_row, row)

    def _find_table_row(self, key) -> int | None:
        for i, k in enumerate(self._row_key):
            if k == key:
                return i
        return None
```

- [ ] **Step 3: Commit**

#### Task 2.2: 集成策略下拉框（延后创建）

保持当前的 `_create_combo_cells` 模式——文本先渲染，QComboBox 延后异步创建。

#### Task 2.3: 勾选操作委托给 Store

FlatAdapter 的 `_on_item_changed` 改为调用 `store.toggle_checked(key)` 和 `store.set_checked(key, state)`。

---

### Phase 3: Tree 适配器（视图层，4 个 Task）

TreeAdapter 连接同一个 `FileTableStore` 实例到 `QTreeWidget`。关键差异于 FlatAdapter：
- 顶层节点是**文件夹**（非叶子），子节点是**文件**（叶子）
- 文件夹行显示累计大小（从 `store.folder_stats()` 读取）
- 叶子行渲染与表格行一致
- 勾选操作只作用于叶子节点
- 过滤需同时隐藏叶子 + 清空文件夹

#### Task 3.1: TreeAdapter 基础结构

**Files:** Create `leanreel/gui/adapters/tree_adapter.py`

- [ ] **Step 1: 写测试**

```python
# tests/test_tree_adapter.py
def test_tree_adapter_rebuild_creates_folders_and_children():
    store = FileTableStore()
    tree = QTreeWidget()
    tree.setColumnCount(6)
    adapter = TreeAdapter(store, tree)

    s1 = make_snap("Season 1/E01.mkv", library_folder_id=7, size=1024, codec="h264")
    s2 = make_snap("Season 1/E02.mkv", library_folder_id=7, size=2048, codec="h264")
    s3 = make_snap("Season 2/E01.mkv", library_folder_id=7, size=512, codec="hevc")
    store.rebuild([FileRow(snap=s) for s in [s1, s2, s3]])

    assert tree.topLevelItemCount() == 2  # Season 1, Season 2
    folder1 = tree.topLevelItem(0)
    assert "Season 1" in folder1.text(0)
    assert folder1.childCount() == 2
    assert folder1.child(0).text(0) == "E01.mkv"

def test_tree_adapter_folder_total_size():
    store = FileTableStore()
    tree = QTreeWidget()
    tree.setColumnCount(6)
    adapter = TreeAdapter(store, tree)

    s1 = make_snap("S1/a.mkv", library_folder_id=7, size=1000)
    s2 = make_snap("S1/b.mkv", library_folder_id=7, size=2000)
    store.rebuild([FileRow(snap=s) for s in [s1, s2]])

    folder = tree.topLevelItem(0)
    assert "3.0 KB" in folder.text(1)  # 体积列显示 1000+2000=3000

def test_tree_adapter_row_update():
    store = FileTableStore()
    tree = QTreeWidget()
    tree.setColumnCount(6)
    adapter = TreeAdapter(store, tree)

    snap = make_snap("S1/a.mkv", codec="", size=0, probe_ok=False)
    store.rebuild([FileRow(snap=snap)])
    child = tree.topLevelItem(0).child(0)
    assert "未识别" in child.text(2)

    new_snap = make_snap("S1/a.mkv", codec="h264", size=1024, probe_ok=True)
    store.update_row((7, "S1/a.mkv"), new_snap)
    assert "h264" in child.text(2)
    assert "1.0 KB" in child.text(1)
```

- [ ] **Step 2: 实现 TreeAdapter 核心方法**

```python
class TreeAdapter(QObject):
    def __init__(self, store: FileTableStore, tree: QTreeWidget):
        super().__init__()
        self._store = store
        self._tree = tree
        self._folder_items: dict[str, QTreeWidgetItem] = {}
        self._child_by_key: dict[tuple[int, str], QTreeWidgetItem] = {}
        store.rows_rebuilt.connect(self._on_rebuild)
        store.row_updated.connect(self._on_row_updated)
        store.checked_changed.connect(self._on_checked_changed)

    def _on_rebuild(self):
        self._tree.blockSignals(True)
        self._tree.clear()
        self._folder_items.clear()
        self._child_by_key.clear()
        store = self._store
        stats = store.folder_stats()
        for i in range(store.count()):
            row = store.row_at(i)
            fname = row.folder_name
            folder = self._folder_items.get(fname)
            if folder is None:
                total = _format_bytes(stats.get(fname, 0))
                folder = _SortableTreeItem([fname, total, "", "", "", ""])
                folder.setData(1, Qt.UserRole, stats.get(fname, 0))
                folder.setData(0, Qt.UserRole, row.key[0])  # folder_id
                font = folder.font(0)
                font.setBold(True)
                folder.setFont(0, font)
                self._folder_items[fname] = folder
                self._tree.addTopLevelItem(folder)
            child = self._render_tree_child(row)
            self._child_by_key[row.key] = child
            folder.addChild(child)
        self._tree.blockSignals(False)

    def _render_tree_child(self, row: FileRow) -> QTreeWidgetItem:
        d = row.decision
        child = QTreeWidgetItem([
            row.snap.file_name,
            _format_bytes(row.snap.size_bytes),
            self._format_codec(row.snap),
            self._format_hdr(row.snap.hdr_type),
            d.strategy_text if d else "—",
            d.result_text if d else "—",
        ])
        child.setData(0, Qt.UserRole, row.key)
        child.setToolTip(0, d.tooltip if d else row.snap.file_name)
        if d and d.processable:
            child.setFlags(child.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            child.setCheckState(0, Qt.Checked if self._store.is_checked(row.key) else Qt.Unchecked)
        else:
            child.setFlags((child.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEnabled)
            child.setToolTip(0, d.tooltip if d else "")
        # 颜色
        if row.snap.video_codec:
            child.setForeground(2, _COLOR_CODEC_OK)
        elif d and d.status_key == "probe_failed":
            child.setForeground(2, _COLOR_PROBE_FAILED)
        else:
            child.setForeground(2, _COLOR_CODEC_MISSING)
        child.setForeground(3, self._hdr_color(row.snap.hdr_type))
        if d and d.status_key == "protected":
            child.setForeground(4, _COLOR_HDR_DV)
        elif d and d.status_key == "probe_failed":
            child.setForeground(4, _COLOR_PROBE_FAILED)
        return child

    def _on_row_updated(self, idx: int, row: FileRow):
        child = self._child_by_key.get(row.key)
        if child is None:
            return
        self._update_child_content(child, row)
        # 更新文件夹总计
        fname = row.folder_name
        folder = self._folder_items.get(fname)
        if folder:
            stats = self._store.folder_stats()
            total = stats.get(fname, 0)
            folder.setText(1, _format_bytes(total))
            folder.setData(1, Qt.UserRole, total)

    def _update_child_content(self, child, row):
        d = row.decision
        child.setText(1, _format_bytes(row.snap.size_bytes))
        child.setText(2, self._format_codec(row.snap))
        child.setText(3, self._format_hdr(row.snap.hdr_type))
        child.setText(4, d.strategy_text if d else "—")
        child.setText(5, d.result_text if d else "—")
        ...  # 颜色更新同 _render_tree_child

    def _on_checked_changed(self):
        for key, child in self._child_by_key.items():
            if child.flags() & Qt.ItemIsEnabled:
                child.setCheckState(0, Qt.Checked if self._store.is_checked(key) else Qt.Unchecked)
```

- [ ] **Step 3: 实现树视图过滤**

```python
def apply_tree_filter(self, filter_key: str):
    for fname, folder in self._folder_items.items():
        visible_children = 0
        for i in range(folder.childCount()):
            child = folder.child(i)
            key = child.data(0, Qt.UserRole)
            row = self._store.row_by_key(key)
            hide = not self._child_visible(row, filter_key, key)
            child.setHidden(hide)
            if not hide:
                visible_children += 1
        folder.setHidden(visible_children == 0)

def _child_visible(self, row, filter_key, key) -> bool:
    if filter_key == "all":
        return True
    d = row.decision
    if d is None:
        return filter_key != "checked"
    if filter_key == "processable":
        return d.processable
    if filter_key == "protected":
        return d.status_key == "protected"
    if filter_key == "probe_failed":
        return d.status_key == "probe_failed"
    if filter_key == "checked":
        return self._store.is_checked(key)
    return True
```

- [ ] **Step 4: 提交**

```bash
git add leanreel/gui/adapters/tree_adapter.py tests/test_tree_adapter.py
git commit -m "feat: add TreeAdapter — Store-driven tree view with folder totals and filter"
```

---

### Phase 4: 控制器精简（3 个 Task）

**关键架构决策（B 方案）：** `strategy_overrides` 留在控制器。Store 只持有原始 `match`（由 matcher 计算），覆盖策略由控制器在 `probed` 回调中计算好 `match`，再传给 `store.update_row()`。

#### Task 4.1: 删除 current_snapshots

用 `store.rebuild()` 替代所有 `current_snapshots` 的直接操作。

逐一替换：
- `_on_library_selected`：`self.current_snapshots = snapshots` → `self.store.rebuild(rows, strategies=..., keep_checked=False)`
- `_probe_folder_streaming`：`self.current_snapshots = placeholders` → `self.store.rebuild(rows, keep_checked=True)`
- `_on_refresh_requested`：同上
- `_on_single_folder_refresh`：先过滤 `current_snapshots`（Store 不支持部分替换），改为 `store.rebuild(合并后 rows)`
- `_on_folder_removed`：同上
- `_on_library_deleted`：`self.store.rebuild([])`
- `_on_start_requested`（编码启动）：用 `store.checked_keys()` 获取勾选 key，从 store 查 snap

删除 `self.current_snapshots`、`self.current_folder_paths` 中不需要的部分（folder_paths 仍需保留，用于扫描和编码时重建路径）。

#### Task 4.2: 统一探测更新路径

`probed` 信号处理从：
```python
def on_probed(snap):
    match = self.services.matcher.match(snap) if snap.probe_ok else None
    self.notifier.probed.emit(snap, match)
```
变为：
```python
def on_probed(snap):
    if snap.probe_ok:
        strategy = self.services.matcher.match(snap)
        match = MatchResult(strategy=strategy, estimate=estimate_savings(snap, strategy))
    else:
        match = None
    key = (snap.library_folder_id, snap.relative_path)
    self.store.update_row(key, snap, match)
```

`probed` 信号不再需要传到 FileListPanel——Store 的 `row_updated` 信号会自动驱动两个 Adapter 更新 UI。

删除 `file_panel.update_snapshot_row()` 方法及相关的 `_update_tree_child()`、`_find_tree_child()`。

#### Task 4.3: 策略覆盖保持 B 方案

`strategy_overrides` 留在控制器，不做任何迁移。在需要匹配结果的地方（`_on_preset_strategy_changed`、`_on_strategy_override_changed`、编码启动），控制器从 `strategy_overrides` 读取覆盖策略，构造正确的 `match`，然后调用 `store.update_row(key, snap, match)`。

```python
# _on_preset_strategy_changed 中
for rel in targets:
    snap = store.row_by_key((folder_id, rel)).snap  # 从 Store 读
    store.update_row(key, snap, MatchResult(strategy=strategy, estimate=...))
```

---

### Phase 5: FileListPanel 瘦身（3 个 Task）

#### Task 5.1: 逐项删除 12 个 dict

以下是 `FileListPanel` 当前持有的 12 个 dict，以及重构后的替代方案：

| # | 当前 dict | 删除后由谁承担 |
|---|-----------|---------------|
| 1 | `_snapshots_by_path` | `store.row_by_key()` |
| 2 | `_snapshots_by_key` | `store._by_key` |
| 3 | `_strategy_lookup` | 移到 `_build_strategy_lookup` 局部变量 |
| 4 | `_last_matches` | `row.match` in Store |
| 5 | `_row_by_path` | `flat_adapter._row_key` (private) |
| 6 | `_row_by_key` | `flat_adapter._row_key` (private) |
| 7 | `_row_status_keys` | `row.decision.status_key` in Store |
| 8 | `_row_processable` | `row.decision.processable` in Store |
| 9 | `_status_by_key` | `row.decision.status_key` in Store |
| 10 | `_processable_by_key` | `row.decision.processable` in Store |
| 11 | `_tree_item_by_key` | `tree_adapter._child_by_key` (private) |
| 12 | `_path_gen` | 不再需要（`_render_gen` 已处理竞态） |

另外删除不再需要的方法（约 15 个）：
- `_render_row_batch`、`_finish_populate`、`_render_all_rows` — 移到 FlatAdapter
- `update_snapshot_row` — 移到 Store.update_row + Adapter 信号
- `_update_tree_child`、`_find_tree_child` — 移到 TreeAdapter
- `_populate_tree` — 移到 TreeAdapter._on_rebuild
- `_decision_display` — 移到 Store._compute_decision
- `apply_strategy_to_row` — 简化为 `store.update_row(key, snap, match)`
- `_on_strategy_combo_changed` — 保留（它是 UI 交互，但改为调用 `store.update_row`）
- `_sync_checked_from_view` — 删除（Store._checked 是唯一源）
- `_apply_filter` — 简化为委托给 Adapter
- `_apply_tree_filter` — 移到 TreeAdapter
- `get_checked_relative_paths` — 委托给 `store.checked_keys()`
- `select_all` / `deselect_all` — 改为迭代 `store.visible_rows()` 然后 `store.set_checked()`
- `_update_selection_count` — 改为从 `store` 统计

#### Task 5.2: 保留的 FileListPanel 内容

瘦身后 `FileListPanel` 只保留：
- UI 布局（`setup_ui`）— 表头、按钮、combo、stack
- 对外信号 — `strategy_override_changed`、`refresh_requested`、`row_selected` 等
- `store` 引用 + `flat_adapter` + `tree_adapter`
- `set_view_mode` — 切换到树时调用 `tree_adapter._on_rebuild()`
- `_create_strategy_combo` — UI 组件工厂
- 组合框相关 handler — `_on_strategy_combo_changed`
- `_format_codec`、`_format_hdr`、`_hdr_color` — 纯函数，可保留或提取

目标：FileListPanel 从当前 ~900 行缩减到 ~300 行。

#### Task 5.3: 过渡兼容

重构期间新旧代码共存：
1. Phase 1-3 完成后，Store + 两个 Adapter 已就绪，但 FileListPanel 仍用自己的 dict
2. Phase 4 完成后，控制器改用 Store，但 FileListPanel 的 `populate()` 仍可接受外部调用
3. Phase 5 完成后，FileListPanel 的 dict 全部删除，完全委托给 Store+Adapter

每个 Phase 结束时跑全量测试确认 304+ passed。

---

## 验证清单

- [ ] `pytest tests/ -q` → 304+ passed
- [ ] 新建库 + 添加 TV 文件夹 → 1345 文件全部显示编码信息
- [ ] 平铺 ↔ 树视图切换 → 勾选保持、数据一致
- [ ] 策略批量覆盖 → 选中文件全部应用
- [ ] 探测完成 → 列表即时更新、不卡
- [ ] 切库 → 缓存秒加载
- [ ] 刷新/重建缓存 → 流程正确
- [ ] 过滤 → 两种视图下都正确
- [ ] 队列 → 编码功能正常

---

## 不在此次重构范围内

- ❌ 不换 QTableWidget→QTableView（风险太大，下次迭代）
- ❌ 不改 UI 外观
- ❌ 不改编码/策略逻辑
- ❌ 不改数据库
