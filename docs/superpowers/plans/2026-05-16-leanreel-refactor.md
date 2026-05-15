# LeanReel 架构重构计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除并发 Bug、统一错误处理、解耦核心模块，确保 295 个现有测试持续通过，不破坏任何功能。

**Architecture:** 5 层渐进重构：数据层隔离 → 扫描器拆分 → 控制器瘦身 → 执行器加固 → 信号契约化。每层独立可交付，不依赖后续层。

**Tech Stack:** Python 3.12, PySide6, SQLite (WAL), subprocess (ffprobe/ffmpeg/dovi_tool), pytest + pytest-qt

---

## 审查发现的 Bug 清单（本次需修复）

| # | 严重度 | 文件 | 行号 | 问题 |
|---|--------|------|------|------|
| B1 | 🔴严重 | `executor/ffmpeg.py` | 42,83-84 | `_active_cancel_event` 多 worker 竞态——取消只杀最新编码 |
| B2 | 🔴严重 | `executor/ffmpeg.py` | 282-284 | 临时目录泄漏——`rmdir()` 非空目录静默失败 |
| B3 | 🔴严重 | `executor/dovi.py` | 49,55 | `TimeoutExpired` 未捕获，stderr 丢弃 |
| B4 | 🟡中等 | `executor/ffmpeg.py` | 275 | `rpu_file.unlink()` 无异常保护 |
| B5 | 🟡中等 | `executor/ffmpeg.py` | 238-240 | `sync_output=False` 时输出丢失 |
| B6 | 🟡中等 | `executor/worker.py` | 93-95 | `future.result()` 异常静默吞没 |
| B7 | 🟡中等 | `executor/worker.py` | 124 | `_cancelled` 标志在锁外设置 |
| B8 | 🟡中等 | `core/pipeline.py` | 128 | `needs_io` 死代码 |
| B9 | 🟢低 | `core/pipeline.py` | 81,90 | `__import__("time")` 重复内联 |
| B10 | 🟢低 | `executor/ffmpeg.py` | 155,165 | `import copy/re` 在循环内 |

## 架构问题清单（本次重构）

| # | 严重度 | 模块 | 问题 |
|---|--------|------|------|
| A1 | 🔴严重 | `data/database.py` | 多线程共享单一 SQLite 连接 (`check_same_thread=False`)，即使加锁仍脆弱 |
| A2 | 🔴严重 | `core/scanner.py` | 上帝类：文件发现 + 探测 + 持久化 + 并行编排全在一个类 |
| A3 | 🔴严重 | `main.py` | Application 类 ~610 行，承担 controller + service locator + state owner + signal hub |
| A4 | 🟡中等 | `gui/file_list.py` | 状态分散在 `_snapshots_by_path`, `_row_by_path`, `_last_matches`, `_row_status_keys`, `_row_processable`, `_path_gen`, `_populate_gen` — 无单一真相来源 |
| A5 | 🟡中等 | `executor/*.py` | 全局路径变量 (`_FFPROBE_PATH`, `_FFMPEG_PATH`, `_DOVI_TOOL_PATH`) 无锁保护 |
| A6 | 🟡中等 | 全局 | 信号连接分散在 `_wire_signals()`，难以追踪数据流 |
| A7 | 🟢低 | `gui/strategy_panel.py` | `PresetCardPanel` 和 `CollapsibleGroup` 耦合在 state reset 上 |

---

## 重构原则

1. **每一层独立可交付** — 重构完一层即可停止，不影响后续
2. **不破坏任何测试** — 295 个测试必须全程通过
3. **接口兼容** — 公共方法签名不变，内部实现可更换
4. **不引入新功能** — 只重构，不加 feature
5. **高频提交** — 每完成一个 Step 就 commit

---

## Phase 1: 数据层隔离（SQLite 连接池）

**目标:** 每个线程使用独立 SQLite 连接，从根本上消除 FOREIGN KEY / cannot commit 错误。

**Files:**
- Modify: `leanreel/data/database.py`

### Task 1.1: 改为连接池模式

- [ ] **Step 1: 实现 ThreadLocal 连接池**

```python
# leanreel/data/database.py 新增
import threading

class ConnectionPool:
    """为每个线程提供独立 SQLite 连接，消除并发写入冲突。"""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._local = threading.local()

    def get(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    def close_all(self):
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None
```

- [ ] **Step 2: 修改 Database 类使用连接池**

```python
class Database:
    def __init__(self, db_path: str = ":memory:"):
        self._pool = ConnectionPool(db_path)
        conn = self._pool.get()
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables(conn)

    def _create_tables(self, conn):
        conn.executescript("""...""")  # 同原代码，去掉 self.conn 改为参数
        self._migrate(conn)

    def execute(self, sql: str, params=None):
        conn = self._pool.get()
        try:
            cur = conn.execute(sql, params or [])
            rows = [dict(row) for row in cur.fetchall()] if cur.description else []
            if conn.in_transaction:
                conn.commit()
            return rows
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise

    def close(self):
        self._pool.close_all()
```

- [ ] **Step 3: 删除 `check_same_thread=False` 和 `_save_lock`**

在 `database.py` 中移除 `check_same_thread=False`（不再需要）。
在 `scanner.py` 中移除 `self._save_lock = threading.Lock()` 和所有 `with self._save_lock:` 包装。

- [ ] **Step 4: 运行全量测试**

```bash
"C:\Users\groun\AppData\Local\Programs\Python\Python312\python.exe" -m pytest tests/ -q --tb=short
```

Expected: 295 passed

- [ ] **Step 5: Commit**

```bash
git add leanreel/data/database.py leanreel/core/scanner.py
git commit -m "refactor: replace shared SQLite connection with thread-local pool"
```

---

## Phase 2: 扫描器拆分

**目标:** 将 Scanner 上帝类拆分为三个独立模块：文件发现、探测编排、持久化。

**Files:**
- Create: `leanreel/core/file_discovery.py`
- Modify: `leanreel/core/scanner.py`（简化为编排层）
- 不动: `leanreel/core/__init__.py`

### Task 2.1: 提取文件发现模块

- [ ] **Step 1: 创建 `leanreel/core/file_discovery.py`**

```python
"""文件发现 — 递归扫描视频文件，便携式 I/O 操作"""
import os

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".ts", ".mov", ".wmv", ".m2ts", ".mts"}


def find_video_files(folder_path: str) -> list[tuple[str, str]]:
    """递归查找所有视频文件，使用 scandir 加速。

    返回 [(relative_path, absolute_path), ...]
    """
    results: list[tuple[str, str]] = []
    folder_path = os.path.normpath(folder_path)

    def _walk(current: str):
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        _walk(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        ext = os.path.splitext(entry.name)[1].lower()
                        if ext in VIDEO_EXTENSIONS:
                            rel_path = os.path.relpath(entry.path, folder_path)
                            results.append((rel_path, entry.path))
        except OSError:
            pass

    _walk(folder_path)
    return results
```

- [ ] **Step 2: 更新 scanner.py 引用新模块**

```python
# scanner.py 顶部
from leanreel.core.file_discovery import find_video_files
```

Remove the `find_video_files` function and `VIDEO_EXTENSIONS` from scanner.py.

- [ ] **Step 3: 运行测试**

Expected: 295 passed

- [ ] **Step 4: Commit**

```bash
git add leanreel/core/file_discovery.py leanreel/core/scanner.py
git commit -m "refactor: extract file discovery to separate module"
```

### Task 2.2: 提取 SnapshotRepository 为独立持久化模块

- [ ] **Step 1: 创建 `leanreel/core/repository.py`**

将 `SnapshotRepository` 类从 `scanner.py` 移到新文件。接口不变。

- [ ] **Step 2: 更新引用**

```python
# scanner.py
from leanreel.core.repository import SnapshotRepository
```

- [ ] **Step 3: 运行测试**

Expected: 295 passed

- [ ] **Step 4: Commit**

```bash
git add leanreel/core/repository.py leanreel/core/scanner.py
git commit -m "refactor: extract SnapshotRepository to separate module"
```

### Task 2.3: 简化 Scanner 为纯编排层

- [ ] **Step 1: 移除 Scanner 中的持久化方法**

Scanner 不再直接处理数据库。保留：
- `scan_folder()` / `scan_folder_fast_batch()` / `scan_folder_fast()` — 编排
- `start_background_probe_jobs()` / `probe_next()` — 并行调度
- `_get_probe()` — 懒加载 probe runner

去掉 `load_cached()`（移到 repository 调用方）。

- [ ] **Step 2: 运行测试**

Expected: 295 passed

- [ ] **Step 3: Commit**

```bash
git add leanreel/core/scanner.py
git commit -m "refactor: simplify Scanner to pure orchestration layer"
```

---

## Phase 3: 执行器加固

**目标:** 修复审查发现的所有执行器 Bug（B1-B6），统一错误处理模式。

**Files:**
- Modify: `leanreel/executor/ffmpeg.py`
- Modify: `leanreel/executor/dovi.py`
- Modify: `leanreel/executor/worker.py`
- Modify: `leanreel/core/pipeline.py`

### Task 3.1: 修复 _active_cancel_event 竞态 (B1)

- [ ] **Step 1: 改用 task-keyed cancel events**

```python
# ffmpeg.py FFmpegExecutor class
def __init__(self, ...):
    ...
    self._cancel_events: dict[str, threading.Event] = {}
    self._cancel_lock = threading.Lock()

def encode(self, task: EncodeTask) -> None:
    cancel_event = threading.Event()
    with self._cancel_lock:
        self._cancel_events[task.input_path] = cancel_event
    try:
        ...
    finally:
        with self._cancel_lock:
            self._cancel_events.pop(task.input_path, None)

def cancel(self):
    with self._cancel_lock:
        for event in list(self._cancel_events.values()):
            event.set()
```

- [ ] **Step 2: 更新 `_active_cancel_event` 引用**

在 `encode()` 中，将 `self._active_cancel_event` 替换为 `cancel_event`。

- [ ] **Step 3: 运行相关测试**

```bash
"C:\Users\groun\AppData\Local\Programs\Python\Python312\python.exe" -m pytest tests/test_encoding_controller.py -q --tb=short
```

### Task 3.2: 修复临时目录泄漏 (B2)

- [ ] **Step 1: 用 `shutil.rmtree` 替换 `rmdir()`**

```python
# ffmpeg.py 第 282-284 行
import shutil
shutil.rmtree(str(task_temp_dir), ignore_errors=True)
```

- [ ] **Step 2: 在 finally 块中清理**

确保临时目录清理在 `finally` 块中执行，不受异常路径影响。

### Task 3.3: 修复 dovi.py 错误诊断丢失 (B3)

- [ ] **Step 1: 修改返回值包含 stderr**

```python
# dovi.py
@staticmethod
def extract_rpu(input_file: str, rpu_output: str) -> tuple[bool, str]:
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120
    )
    return result.returncode == 0, result.stderr.strip()

@staticmethod
def inject_rpu(encoded_hevc: str, rpu_file: str, output: str) -> tuple[bool, str]:
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120
    )
    return result.returncode == 0, result.stderr.strip()
```

- [ ] **Step 2: 更新 ffmpeg.py 调用处**

```python
ok, stderr = DoviTool.extract_rpu(str(local_input), str(rpu_file))
if not ok:
    raise RuntimeError(
        f"Dolby Vision RPU extraction failed: {task.file_name}\n{stderr[:500]}"
    )
```

### Task 3.4: 修复 rpu_file.unlink() 无保护 (B4)

- [ ] **Step 1: 加异常捕获**

```python
try:
    rpu_file.unlink()
except OSError:
    pass
```

### Task 3.5: 修复 sync_output=False 输出丢失 (B5)

- [ ] **Step 1: 当 sync_output=False 时仍复制到 final_output**

```python
if self.sync_output:
    # copy to final output
    shutil.copy2(str(temp_output), str(final_output))
else:
    # 至少移动到 final_output，否则输出丢失
    shutil.move(str(temp_output), str(final_output))
```

### Task 3.6: 修复 worker.py 异常吞没 (B6)

- [ ] **Step 1: 记录异常而非吞没**

```python
for f in concurrent.futures.as_completed(futures):
    try:
        f.result()
    except Exception as e:
        task = futures[f]
        if task.error_message:
            import sys
            print(f"[LeanReel] 编码失败: {task.file_name}\n  {task.error_message}",
                  file=sys.stderr, flush=True)
```

### Task 3.7: 修复 pipeline.py 死代码 (B8, B9)

- [ ] **Step 1: 删除 `needs_io` 死代码（第 128 行）**
- [ ] **Step 2: 将 `__import__("time")` 替换为顶部 `import time`**

### Task 3.8: 全量测试

```bash
"C:\Users\groun\AppData\Local\Programs\Python\Python312\python.exe" -m pytest tests/ -q --tb=short
```

Expected: 295 passed

### Task 3.9: Commit

```bash
git add leanreel/executor/ffmpeg.py leanreel/executor/dovi.py leanreel/executor/worker.py leanreel/core/pipeline.py
git commit -m "fix: executor hardening - cancel race, tempdir leak, dovi diagnostics, dead code"
```

---

## Phase 4: 控制器瘦身

**目标:** 将 Application 类 (~610行) 拆分为信号接线和业务逻辑两层。

**Files:**
- Create: `leanreel/controllers/scan_controller.py`
- Create: `leanreel/controllers/strategy_controller.py`
- Modify: `leanreel/main.py`

### Task 4.1: 提取扫描控制器

- [ ] **Step 1: 创建 `leanreel/controllers/__init__.py`**
- [ ] **Step 2: 创建 `leanreel/controllers/scan_controller.py`**

将以下方法从 Application 移到 `ScanController`：
- `_on_folder_added`
- `_on_scan_finished`
- `_on_refresh_requested`
- `_populate_file_list`
- `_on_library_selected`
- `_on_library_deleted`
- `_on_folder_removed`
- 关联的状态：`current_snapshots`, `current_folder_paths`, `strategy_overrides`

`ScanController` 接收 `Services`, `ProbeNotifier`, `FileListPanel`, `StrategyPanel`, `MainWindow` 作为构造参数。

- [ ] **Step 3: Application 委托给 ScanController**

```python
class Application:
    def __init__(self):
        ...
        self.scan_ctrl = ScanController(
            services=self.services,
            notifier=self.notifier,
            file_panel=self.file_panel,
            strategy_panel=self.strategy_panel,
            win=self.win,
        )
```

- [ ] **Step 4: 运行测试**

Expected: 295 passed

### Task 4.2: 提取策略控制器

- [ ] **Step 1: 创建 `leanreel/controllers/strategy_controller.py`**

将以下方法从 Application 移到 `StrategyController`：
- `_on_strategy_override_changed`
- `_on_custom_strategy_requested`
- `_on_custom_strategy_changed`
- `_on_file_row_selected`
- `_on_preset_strategy_changed`
- `_on_start_requested`
- 关联的状态：`strategy_overrides`, `active_custom_path`

### Task 4.3: 清理 Application

Application 只保留：
- 初始化（`_init_*`）
- `_wire_signals()` — 连接各控制器到信号
- `_refresh_libraries()`
- `run()`

### Task 4.4: Commit

```bash
git add leanreel/controllers/ leanreel/main.py
git commit -m "refactor: extract scan and strategy controllers from Application god class"
```

---

## Phase 5: 信号契约化

**目标:** 将 `ProbeNotifier` 的信号定义集中管理，确保类型安全。

**Files:**
- Create: `leanreel/controllers/signals.py`
- Modify: `leanreel/main.py`

### Task 5.1: 提取信号定义

- [ ] **Step 1: 创建 `leanreel/controllers/signals.py`**

```python
from PySide6.QtCore import QObject, Signal

class AppSignals(QObject):
    # 扫描信号
    probed = Signal(object, object)        # (FileSnapshot, MatchResult|None)
    scan_finished = Signal(object, object, object, object)  # (snapshots, folder_id|None, path|None, pending_jobs)
    all_done = Signal()
    progress = Signal(int, int)            # (done, total)

    # 编码信号
    task_updated = Signal(object)          # EncodeTask
    encoding_done = Signal()
```

- [ ] **Step 2: Application 使用 AppSignals**

替换 `ProbeNotifier` 为 `AppSignals`。

- [ ] **Step 3: 运行测试**

Expected: 295 passed

---

## Phase 6: 树/表格视图统一

**目标:** 目录树和平铺表格共享同一数据源，所有操作（勾选、过滤、策略覆盖、批量）在两种视图下行为一致。

**Files:**
- Modify: `leanreel/gui/file_list.py`
- Modify: `leanreel/main.py`

### 当前问题

树视图 (`_populate_tree`) 是完全独立的副本——建完就不再更新。所有关键操作只操作表格：

| 操作 | 表格 | 树 |
|------|------|-----|
| `get_checked_relative_paths()` | ✅ | ✗ |
| `select_all()` / `deselect_all()` | ✅ | ✗ |
| `apply_strategy_to_row()` | ✅ | ✗ |
| `_apply_filter()` | ✅ | ✗ |
| `update_snapshot_row()` | ✅ | ✗ |

根因：两者没有共享数据模型，树是 `QTreeWidget` 用字符串填充的。

### Task 6.1: 让 get_checked_relative_paths 支持两种视图

- [ ] **Step 1: 修改 `get_checked_relative_paths`**

```python
def get_checked_relative_paths(self) -> list[str]:
    if self.current_view_mode == "tree":
        return self._get_checked_tree_paths()
    checked: list[str] = []
    for row in range(self.table.rowCount()):
        item = self.table.item(row, 0)
        if item and item.checkState() == Qt.Checked and item.flags() & Qt.ItemIsEnabled:
            rel_item = self.table.item(row, 1)
            if rel_item:
                checked.append(rel_item.data(Qt.UserRole))
    return checked

def _get_checked_tree_paths(self) -> list[str]:
    checked: list[str] = []
    def _walk(item):
        if item.childCount() == 0:
            return
        for i in range(item.childCount()):
            child = item.child(i)
            if child.childCount() > 0:
                _walk(child)
            else:
                data = child.data(0, Qt.UserRole)
                if data and child.checkState(0) == Qt.Checked:
                    checked.append(data)
    for i in range(self.tree.topLevelItemCount()):
        _walk(self.tree.topLevelItem(i))
    return checked
```

### Task 6.2: 让 select_all/deselect_all 支持树视图

- [ ] **Step 1: 修改 `select_all` 和 `deselect_all`**

```python
def select_all(self):
    if self.current_view_mode == "tree":
        self._set_tree_checked(True)
    else:
        for row in range(self.table.rowCount()):
            if self._row_processable.get(row, False):
                item = self.table.item(row, 0)
                if item and item.flags() & Qt.ItemIsEnabled:
                    item.setCheckState(Qt.Checked)
    self._update_selection_count()

def deselect_all(self):
    if self.current_view_mode == "tree":
        self._set_tree_checked(False)
    else:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                item.setCheckState(Qt.Unchecked)
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
```

### Task 6.3: 让 apply_strategy_to_row 更新树视图

- [ ] **Step 1: 添加 `_update_tree_item` 方法**

```python
def _update_tree_item(self, relative_path: str, decision: FileDecisionDisplay):
    """更新树视图中对应文件行的策略和结果列。"""
    def _walk(item):
        for i in range(item.childCount()):
            child = item.child(i)
            if child.childCount() > 0:
                _walk(child)
            elif child.data(0, Qt.UserRole) == relative_path:
                child.setText(4, decision.strategy_text)
                child.setText(5, decision.result_text)
                child.setToolTip(4, decision.tooltip)
                return
    for i in range(self.tree.topLevelItemCount()):
        _walk(self.tree.topLevelItem(i))
```

- [ ] **Step 2: 在 `apply_strategy_to_row` 末尾调用**

```python
# 在 apply_strategy_to_row 末尾
if self.current_view_mode == "tree":
    self._update_tree_item(relative_path, decision)
```

### Task 6.4: 让 update_snapshot_row 更新树视图

- [ ] **Step 1: 在 `update_snapshot_row` 末尾更新树**

```python
# 在 update_snapshot_row 末尾（决策计算后）
if self.current_view_mode == "tree":
    match = self._last_matches.get(relative_path)
    decision = self._decision_display(snap, match)
    self._update_tree_item(relative_path, decision)
```

### Task 6.5: 树视图添加复选框列

- [ ] **Step 1: 树列数从 6 改为 7，加复选框列**

当前树：`["文件名", "体积", "编码信息", "HDR", "处理策略", "预计结果"]` 共 6 列。
改为与表格对齐：树使用 `QTreeWidgetItem` 的 `setCheckState(0, ...)` 在第 0 列显示勾选框。

修改 `_populate_tree`：每行 child 设置 `child.setFlags(child.flags() | Qt.ItemIsUserCheckable)` 和 `child.setCheckState(0, Qt.Unchecked)`。

- [ ] **Step 2: 连接树的 itemChanged 信号**

```python
self.tree.itemChanged.connect(self._on_tree_item_changed)
```

### Task 6.6: 运行测试和提交

```bash
"C:\Users\groun\AppData\Local\Programs\Python\Python312\python.exe" -m pytest tests/ -q --tb=short
```

Expected: 295 passed

```bash
git add leanreel/gui/file_list.py
git commit -m "fix: unify tree and table views - checkbox, batch, filter work in both modes"
```

---

## 验证清单

重构完成后逐项确认：

- [ ] `pytest tests/ -q` → 295 passed
- [ ] 新建库 + 添加 TV 文件夹 → 1345 文件全部显示编码信息
- [ ] 新建库 + 添加 Anime 文件夹 → 无 FOREIGN KEY 错误
- [ ] 刷新按钮 → 列表不重复，编码信息正确
- [ ] 树视图 → 切过去显示最新数据
- [ ] 右键面板策略 → 选行同步
- [ ] 批量策略覆盖 → 多选后策略面板变更应用到全部
- [ ] 编码功能 → 启动/暂停/取消正常
- [ ] 探测失败文件 → 显示"探测失败"且有重试

---

## 不在此次重构范围内

- ❌ 不引入 ORM（保持原生 SQL）
- ❌ 不改 ffprobe 探测参数（probesize/analyzeduration 已优化）
- ❌ 不改 UI 布局/样式
- ❌ 不改编码策略逻辑（CQ 计算、匹配规则）
- ❌ 不添加新功能
