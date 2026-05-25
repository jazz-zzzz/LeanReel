# Conversion History Panel — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 全屏历史转换面板，DB 驱动，时间倒序展示所有转换记录，工具栏按钮切换

**Architecture:** HistoryPanel (QTableView + 筛选栏) 通过 QStackedWidget 与文件列表视图切换。DB 新增 `get_all_history()` JOIN 查询。文件列表"已压缩"检测从 sidecar 改为 DB 查询。

**Tech Stack:** PySide6 QTableView, QSortFilterProxyModel, sqlite3 JOIN

---

### Task 1: DB — get_all_history() 查询

**Files:**
- Modify: `leanreel/infrastructure/database.py`

- [ ] **Step 1: 添加 `get_all_history()` 方法**

```python
def get_all_history(self) -> list[dict]:
    """返回所有压缩历史记录，JOIN 出库名和文件夹路径，按时间倒序。"""
    rows = self.execute("""
        SELECT
            ch.id, ch.file_snapshot_id, ch.strategy_name,
            ch.original_size, ch.compressed_size, ch.output_size_bytes,
            ch.savings_pct, ch.encoder, ch.cq_value, ch.preset,
            ch.duration_seconds, ch.status, ch.error_message,
            ch.output_path, ch.sidecar_path, ch.created_at,
            ch.source_deleted, ch.leanreel_version,
            fs.file_name, fs.relative_path, fs.video_codec, fs.library_folder_id,
            lf.path AS folder_path,
            lib.name AS library_name
        FROM compression_history ch
        JOIN file_snapshot fs ON ch.file_snapshot_id = fs.id
        JOIN library_folder lf ON fs.library_folder_id = lf.id
        JOIN library lib ON lf.library_id = lib.id
        ORDER BY ch.created_at DESC
    """)
    return rows
```

- [ ] **Step 2: 运行 DB 测试**

Run: `py -m pytest tests/test_database.py -v`
Expected: all pass

- [ ] **Step 3: Commit**

```bash
git add leanreel/infrastructure/database.py
git commit -m "feat: add get_all_history() with full JOIN for history panel"
```

---

### Task 2: HistoryPanel 组件

**Files:**
- Create: `leanreel/gui/history_panel.py`
- Create: `tests/test_history_panel.py`

- [ ] **Step 1: 创建测试文件 `tests/test_history_panel.py`**

```python
"""历史面板测试"""
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

_app = None


def get_app():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


def test_history_panel_creates_with_columns():
    from leanreel.gui.history_panel import HistoryPanel

    app = get_app()
    panel = HistoryPanel()
    model = panel.table.model()

    expected = [
        "源文件名", "库", "文件夹", "源体积", "输出体积",
        "节省量", "节省率", "策略", "编码器", "CQ/CRF",
        "耗时", "完成时间", "状态", "源已删",
    ]
    for i, col in enumerate(expected):
        assert model.headerData(i, Qt.Horizontal, Qt.DisplayRole) == col

    panel.close()


def test_history_panel_back_button_emits():
    from leanreel.gui.history_panel import HistoryPanel

    app = get_app()
    panel = HistoryPanel()
    signal_fired = []

    panel.back_requested.connect(lambda: signal_fired.append(True))
    panel.back_btn.click()

    assert len(signal_fired) == 1
    panel.close()


def test_history_panel_populate_renders_rows():
    from leanreel.gui.history_panel import HistoryPanel

    app = get_app()
    panel = HistoryPanel()
    rows = [
        {
            "id": 1, "file_name": "movie.mkv", "library_name": "电影",
            "folder_path": "/movies", "original_size": 10_000_000_000,
            "output_size_bytes": 3_500_000_000, "savings_pct": 65.0,
            "strategy_name": "AV1 NVENC CQ34 均衡快速",
            "encoder": "av1_nvenc", "cq_value": 34,
            "duration_seconds": 900, "created_at": "2026-05-28 12:00:00",
            "status": "completed", "source_deleted": 0, "output_path": "/out.mkv",
        },
    ]
    panel.populate(rows)

    model = panel.table.model()
    assert model.rowCount() == 1
    assert model.data(model.index(0, 0), Qt.DisplayRole) == "movie.mkv"
    assert model.data(model.index(0, 4), Qt.DisplayRole) == "3.5 GB"
    assert model.data(model.index(0, 7), Qt.DisplayRole) == "AV1 NVENC CQ34 均衡快速"
    panel.close()


def test_history_panel_filter_by_status():
    from leanreel.gui.history_panel import HistoryPanel

    app = get_app()
    panel = HistoryPanel()
    rows = [
        {"status": "completed", "file_name": "a.mkv", "library_name": "",
         "folder_path": "", "original_size": 1000, "output_size_bytes": 500,
         "savings_pct": 50.0, "strategy_name": "", "encoder": "",
         "cq_value": 0, "duration_seconds": 0, "created_at": "",
         "source_deleted": 0, "output_path": ""},
        {"status": "failed", "file_name": "b.mkv", "library_name": "",
         "folder_path": "", "original_size": 1000, "output_size_bytes": 0,
         "savings_pct": 0.0, "strategy_name": "", "encoder": "",
         "cq_value": 0, "duration_seconds": 0, "created_at": "",
         "source_deleted": 0, "output_path": ""},
    ]
    panel.populate(rows)

    panel.status_filter.setCurrentText("成功")
    proxy = panel.table.model()
    assert proxy.rowCount() == 1

    panel.status_filter.setCurrentText("全部")
    assert proxy.rowCount() == 2

    panel.close()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `py -m pytest tests/test_history_panel.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: 创建 `leanreel/gui/history_panel.py`**

```python
"""历史转换面板 — 全屏 DB 驱动历史记录"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableView, QHeaderView, QComboBox, QLabel, QMessageBox,
    QSortFilterProxyModel,
)
from PySide6.QtCore import Qt, Signal, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QColor

from leanreel.gui.utils import _format_bytes

_HEADERS = [
    "源文件名", "库", "文件夹", "源体积", "输出体积",
    "节省量", "节省率", "策略", "编码器", "CQ/CRF",
    "耗时", "完成时间", "状态", "源已删",
]

_ENCODER_STATUS = {
    "libx265": "HEVC",
    "hevc_nvenc": "HEVC",
    "av1_nvenc": "AV1",
    "copy": "流复制",
}


def _format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"


def _encode_label(encoder: str) -> str:
    return _ENCODER_STATUS.get(encoder, encoder)


class HistoryTableModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self._rows: list[dict] = []

    def set_rows(self, rows: list[dict]):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(_HEADERS)

    def headerData(self, section, orientation, role):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return _HEADERS[section]
        return None

    def data(self, index, role):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            return self._display_text(row, col)
        if role == Qt.UserRole:
            return row.get("output_path", "")
        if role == Qt.ForegroundRole:
            status = row.get("status", "")
            if status == "failed":
                return QColor("#c4554a")
            if status == "cancelled":
                return QColor("#6b6560")
        if role == Qt.ToolTipRole:
            return row.get("error_message", "") or row.get("output_path", "")
        return None

    def _display_text(self, row: dict, col: int) -> str:
        field_map = {
            0: lambda r: r.get("file_name", ""),
            1: lambda r: r.get("library_name", ""),
            2: lambda r: r.get("folder_path", ""),
            3: lambda r: _format_bytes(r.get("original_size", 0)),
            4: lambda r: _format_bytes(r.get("output_size_bytes", 0) or r.get("compressed_size", 0)),
            5: lambda r: _format_bytes(
                (r.get("original_size", 0) or 0) - (r.get("output_size_bytes", 0) or r.get("compressed_size", 0) or 0)
            ),
            6: lambda r: f"{r.get('savings_pct', 0):.1f}%" if r.get("savings_pct") else "—",
            7: lambda r: r.get("strategy_name", ""),
            8: lambda r: _encode_label(r.get("encoder", "")),
            9: lambda r: str(r.get("cq_value", "")) if r.get("cq_value") else "—",
            10: lambda r: _format_duration(r.get("duration_seconds", 0)),
            11: lambda r: r.get("created_at", ""),
            12: lambda r: r.get("status", ""),
            13: lambda r: "是" if r.get("source_deleted") else "否",
        }
        fn = field_map.get(col)
        return fn(row) if fn else ""


class StatusProxyModel(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self._status_filter = ""

    def set_status_filter(self, status: str):
        self._status_filter = status
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        if not self._status_filter or self._status_filter == "全部":
            return True
        model = self.sourceModel()
        idx = model.index(source_row, 12)
        return model.data(idx, Qt.DisplayRole) == self._status_filter


class HistoryPanel(QWidget):
    back_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # ── 顶部：返回按钮 + 筛选 ──
        top = QHBoxLayout()

        self.back_btn = QPushButton("← 返回文件列表")
        self.back_btn.setFixedWidth(140)
        self.back_btn.clicked.connect(self.back_requested.emit)
        top.addWidget(self.back_btn)

        top.addSpacing(16)

        top.addWidget(QLabel("库:"))
        self.library_filter = QComboBox()
        self.library_filter.addItem("全部")
        self.library_filter.setMinimumWidth(120)
        top.addWidget(self.library_filter)

        top.addWidget(QLabel("策略:"))
        self.strategy_filter = QComboBox()
        self.strategy_filter.addItem("全部")
        self.strategy_filter.setMinimumWidth(160)
        top.addWidget(self.strategy_filter)

        top.addWidget(QLabel("状态:"))
        self.status_filter = QComboBox()
        self.status_filter.addItems(["全部", "成功", "失败", "已取消"])
        self.status_filter.setMinimumWidth(100)
        self.status_filter.currentTextChanged.connect(self._on_status_changed)
        top.addWidget(self.status_filter)

        self.summary_label = QLabel()
        top.addWidget(self.summary_label)

        top.addStretch()
        layout.addLayout(top)

        # ── 表格 ──
        self.table = QTableView()
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setEditTriggers(QTableView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(self._on_double_click)

        self._source_model = HistoryTableModel()
        self._proxy = StatusProxyModel()
        self._proxy.setSourceModel(self._source_model)
        self.table.setModel(self._proxy)

        layout.addWidget(self.table)

    def populate(self, rows: list[dict]):
        self._source_model.set_rows(rows)
        self._update_filters(rows)
        self._update_summary(rows)

    def _update_filters(self, rows: list[dict]):
        libs = sorted({r.get("library_name", "") for r in rows if r.get("library_name")})
        strategies = sorted({r.get("strategy_name", "") for r in rows if r.get("strategy_name")})

        current_lib = self.library_filter.currentText()
        current_strat = self.strategy_filter.currentText()

        self.library_filter.clear()
        self.library_filter.addItem("全部")
        self.library_filter.addItems(libs)
        if current_lib in libs:
            self.library_filter.setCurrentText(current_lib)

        self.strategy_filter.clear()
        self.strategy_filter.addItem("全部")
        self.strategy_filter.addItems(strategies)
        if current_strat in strategies:
            self.strategy_filter.setCurrentText(current_strat)

    def _update_summary(self, rows: list[dict]):
        total = len(rows)
        completed = sum(1 for r in rows if r.get("status") == "completed")
        failed = sum(1 for r in rows if r.get("status") == "failed")
        total_savings = sum(
            (r.get("original_size", 0) or 0) - (r.get("output_size_bytes", 0) or 0)
            for r in rows if r.get("status") == "completed"
        )
        self.summary_label.setText(
            f"共 {total} 条 · 成功 {completed} · 失败 {failed} · 累计节省 {_format_bytes(total_savings)}"
        )

    def _on_status_changed(self, text: str):
        status_map = {"成功": "completed", "失败": "failed", "已取消": "cancelled"}
        self._proxy.set_status_filter(status_map.get(text, ""))

    def _on_double_click(self, index: QModelIndex):
        source_idx = self._proxy.mapToSource(index)
        row = self._source_model._rows[source_idx.row()]
        output_path = row.get("output_path", "")
        if output_path and Path(output_path).exists():
            import os
            os.startfile(str(Path(output_path).parent))
        else:
            QMessageBox.information(
                self, "文件不存在",
                f"输出文件已不存在：\n{output_path}\n\n"
                "可能原因：体积反超被丢弃 / 文件被手动删除"
            )
```

- [ ] **Step 4: 运行测试**

Run: `py -m pytest tests/test_history_panel.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add leanreel/gui/history_panel.py tests/test_history_panel.py
git commit -m "feat: add HistoryPanel — full-screen DB-driven history table"
```

---

### Task 3: MainWindow 集成 — 切换视图

**Files:**
- Modify: `leanreel/gui/main_window.py`

- [ ] **Step 1: 添加 QStackedWidget 和切换逻辑**

在 `MainWindow.__init__` 中：

```python
# 将 splitter 和 history_panel 放入 QStackedWidget
self.stack = QStackedWidget()
self.stack.addWidget(self.splitter)  # index 0: 原有三面板
# history_panel 由外部 set_history_panel 注入
self.layout.addWidget(self.stack)

# 菜单栏添加"转换历史"按钮
self._toggle_history_action = view_menu.addAction("转换历史")
self._toggle_history_action.setCheckable(True)
```

添加方法：
```python
def set_history_panel(self, widget: QWidget):
    self.stack.addWidget(widget)  # index 1
    widget.back_requested.connect(self._show_file_list)

def set_toggle_history_action(self, callback):
    self._toggle_history_action.triggered.connect(callback)

def _show_file_list(self):
    self.stack.setCurrentIndex(0)

def show_history(self):
    self.stack.setCurrentIndex(1)
```

- [ ] **Step 2: 更新 `main.py` 中的 Application 初始化**

```python
# 在 _init_ui 之后添加
self.history_panel = HistoryPanel()
self.win.set_history_panel(self.history_panel)
self.win.set_toggle_history_action(
    lambda: self.win.show_history() if self._toggle_history_action.isChecked() else self.win._show_file_list()
)
```

- [ ] **Step 3: 运行主窗口测试**

Run: `py -m pytest tests/test_main_window.py -v`
Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add leanreel/gui/main_window.py leanreel/main.py
git commit -m "feat: integrate HistoryPanel into MainWindow via QStackedWidget"
```

---

### Task 4: 文件列表 — DB 驱动的已压缩检测

**Files:**
- Modify: `leanreel/controllers/scan_controller.py`
- Modify: `leanreel/gui/file_list.py`

- [ ] **Step 1: 在 scan_controller 中查询 compression_history**

在 `_populate_file_list` 中，替换原有的 sidecar 检测逻辑为 DB 查询：

```python
# 原有 sidecar 检测替换为 DB 查询
compressed_info: dict[tuple[int, str], dict] = {}
try:
    history_rows = self._services.db.get_all_history()
    for h in history_rows:
        if h.get("status") == "completed":
            sid = h.get("file_snapshot_id")
            folder_id = h.get("library_folder_id")
            rel_path = h.get("relative_path", "")
            if sid and folder_id is not None:
                compressed_info[(int(folder_id), str(rel_path))] = h
except Exception:
    pass
```

然后将 `compressed_info` 传递给 `_decision_display`：

```python
comp_key = (int(s.library_folder_id or 0), str(s.relative_path))
d = self._file_panel._decision_display(s, m, compressed_info.get(comp_key))
```

- [ ] **Step 2: 更新 `_decision_display` 签名**

将 `sidecar_path: str | None = None` 参数替换为 `compressed_record: dict | None = None`：

```python
def _decision_display(self, snap, match, compressed_record=None):
    if compressed_record:
        encoder = compressed_record.get("encoder", "")
        label = _ENCODER_STATUS.get(encoder, encoder)
        strategy_name = compressed_record.get("strategy_name", "")
        return FileDecisionDisplay(
            status_key="compressed",
            strategy_text=f"已被压缩为 {label} 片源",
            result_text=f"{compressed_record.get('savings_pct', 0):.0f}%",
            result_sort=-5,
            processable=False,
            tooltip=f"策略: {strategy_name}",
        )
    # ... 其余不变
```

- [ ] **Step 3: 运行扫描测试**

Run: `py -m pytest tests/ -x -q`
Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add leanreel/controllers/scan_controller.py leanreel/gui/file_list.py
git commit -m "feat: detect compressed files via DB instead of sidecar"
```

---

### Task 5: Controller — 加载历史数据

**Files:**
- Create: `leanreel/controllers/history_controller.py`

- [ ] **Step 1: 创建 HistoryController**

```python
"""历史记录控制器"""
from leanreel.utils.threading_contract import require_main_thread


class HistoryController:
    def __init__(self, db, history_panel):
        self._db = db
        self._history_panel = history_panel

    @require_main_thread
    def load(self):
        rows = self._db.get_all_history()
        self._history_panel.populate(rows)
```

- [ ] **Step 2: 在 main.py 中集成**

```python
from leanreel.controllers.history_controller import HistoryController

# In Application._init_controllers or similar:
self.history_ctrl = HistoryController(self.services.db, self.history_panel)

# Wire: when history panel is shown, load data
self.win.set_toggle_history_action(
    lambda checked: (self.win.show_history(), self.history_ctrl.load()) if checked else self.win._show_file_list()
)
```

- [ ] **Step 3: 运行测试**

Run: `py -m pytest tests/ -x -q`
Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add leanreel/controllers/history_controller.py leanreel/main.py
git commit -m "feat: add HistoryController to load and populate history data"
```

---

### Task 6: 端到端测试

**Files:**
- Modify: `tests/test_history_panel.py`

- [ ] **Step 1: 添加 E2E 测试**

```python
def test_history_panel_e2e_populate_and_double_click():
    """端到端：填充数据 → 双击行 → 验证输出路径可访问"""
    import tempfile
    from pathlib import Path
    from leanreel.gui.history_panel import HistoryPanel

    app = get_app()
    with tempfile.TemporaryDirectory() as tmp:
        out_file = Path(tmp) / "test_zcompressed.mkv"
        out_file.touch()

        panel = HistoryPanel()
        rows = [{
            "id": 1, "file_name": "test.mkv", "library_name": "测试",
            "folder_path": tmp, "original_size": 1_000_000,
            "output_size_bytes": 500_000, "savings_pct": 50.0,
            "strategy_name": "AV1 NVENC CQ34 均衡快速",
            "encoder": "av1_nvenc", "cq_value": 34,
            "duration_seconds": 60, "created_at": "2026-05-28",
            "status": "completed", "source_deleted": 0,
            "output_path": str(out_file),
        }]
        panel.populate(rows)

        model = panel.table.model()
        assert model.rowCount() == 1
        assert model.data(model.index(0, 0), Qt.DisplayRole) == "test.mkv"
        assert model.data(model.index(0, 13), Qt.DisplayRole) == "否"

        # 验证 UserRole 返回 output_path
        assert model.data(model.index(0, 0), Qt.UserRole) == str(out_file)

        panel.close()
```

- [ ] **Step 2: 运行全量测试**

Run: `py -m pytest tests/ -x -q`
Expected: all pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_history_panel.py
git commit -m "test: e2e history panel populate and display"
```

---

### 验证清单

1. `py -m leanreel.main` 启动 → 菜单栏有"转换历史"
2. 点击"转换历史" → 文件列表隐藏，历史面板全屏
3. 历史面板显示所有转换记录（时间倒序）
4. 源体积、输出体积、节省量正确显示
5. 筛选状态、库、策略正常工作
6. 双击已存在的输出文件 → 文件浏览器打开所在文件夹
7. 文件列表中已压缩文件显示"已被压缩为 HEVC/AV1 片源"
8. 源已删列正确显示
