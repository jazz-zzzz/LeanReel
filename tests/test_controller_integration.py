"""控制器集成测试 — 验证 _populate_file_list → Store → 表格可见"""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableView, QApplication


def _text(table, row, col):
    m = table.model()
    return str(m.data(m.index(row, col), Qt.DisplayRole) or "")


def _check(table, row, col):
    m = table.model()
    val = m.data(m.index(row, col), Qt.CheckStateRole)
    if isinstance(val, int):
        return Qt.CheckState(val)
    return val


def _qapp():
    return QApplication.instance() or QApplication([])


def _snap(**kw):
    from leanreel.data.models import FileSnapshot, HDRType
    defaults = dict(library_folder_id=7, relative_path="a.mkv",
                    file_name="a.mkv", size_bytes=1024, video_codec="h264",
                    hdr_type=HDRType.SDR, probe_ok=True)
    defaults.update(kw)
    return FileSnapshot(**defaults)


# ── _populate_file_list → Store → 表格可见 ──

def test_populate_file_list_shows_table_with_data(qtbot):
    """_populate_file_list → Store → FlatAdapter → 表格可见且有数据"""
    _qapp()
    from leanreel.data.file_store import FileTableStore, FileRow, MatchResult, FileDecisionDisplay
    from leanreel.gui.adapters.flat_adapter import FlatAdapter
    from leanreel.gui.file_list import FileListPanel

    panel = FileListPanel()
    qtbot.addWidget(panel)
    store = FileTableStore()
    panel._store = store
    panel._flat_adapter = FlatAdapter(store, panel.table)

    snapshots = [_snap(relative_path="x.mkv", file_name="x.mkv"),
                 _snap(relative_path="y.mkv", file_name="y.mkv")]

    # 模拟 _populate_file_list 的核心路径
    rows = []
    for s in snapshots:
        d = FileDecisionDisplay(status_key="processable", strategy_text="均衡",
                                result_text="50%", result_sort=50, processable=True, tooltip="均衡")
        rows.append(FileRow(snap=s, match=MatchResult(strategy="均衡"), decision=d))
    store.rebuild(rows)
    panel._show_table()

    assert store.count() == 2
    assert panel.stack.currentWidget() is panel.table
    assert panel.table.model().rowCount() == 2
    assert _text(panel.table, 0, 1) == "x.mkv"
    assert _text(panel.table, 1, 1) == "y.mkv"
    panel.close()


def test_populate_file_list_empty_shows_table(qtbot):
    """空列表时 _show_table 仍切换到表格（探测进行中）"""
    _qapp()
    from leanreel.data.file_store import FileTableStore
    from leanreel.gui.adapters.flat_adapter import FlatAdapter
    from leanreel.gui.file_list import FileListPanel

    panel = FileListPanel()
    qtbot.addWidget(panel)
    store = FileTableStore()
    panel._store = store
    panel._flat_adapter = FlatAdapter(store, panel.table)

    store.rebuild([])
    panel._show_table()

    assert store.count() == 0
    assert panel.stack.currentWidget() is panel.table
    assert panel.table.model().rowCount() == 0
    panel.close()


# ── Store → FlatAdapter 信号链 ──

def test_store_rebuild_triggers_flat_adapter(qtbot):
    """store.rebuild 应触发 FlatAdapter 更新表格"""
    from leanreel.data.file_store import FileTableStore, FileRow
    from leanreel.gui.adapters.flat_adapter import FlatAdapter
    
    store = FileTableStore()
    table = QTableView()
    adapter = FlatAdapter(store, table)

    snap = _snap(video_codec="h264")
    from leanreel.gui.file_list import MatchResult, FileDecisionDisplay
    d = FileDecisionDisplay(status_key="processable", strategy_text="均衡",
                            result_text="50%", result_sort=50, processable=True,
                            tooltip="均衡")
    row = FileRow(snap=snap, match=MatchResult(strategy="均衡"), decision=d)
    store.rebuild([row])

    assert table.model().rowCount() == 1
    assert _text(table, 0, 1) == "a.mkv"
    assert "h264" in _text(table, 0, 3)


def test_store_update_row_triggers_flat_adapter(qtbot):
    """store.update_row 应更新表格对应单元格"""
    from leanreel.data.file_store import FileTableStore, FileRow
    from leanreel.gui.adapters.flat_adapter import FlatAdapter
    
    store = FileTableStore()
    table = QTableView()
    adapter = FlatAdapter(store, table)

    old = _snap(video_codec="", probe_ok=False)
    from leanreel.gui.file_list import FileDecisionDisplay
    d = FileDecisionDisplay(status_key="probe_failed", strategy_text="探测失败",
                            result_text="无法估算", result_sort=-3, processable=False,
                            tooltip="探测失败")
    store.rebuild([FileRow(snap=old, decision=d)])

    new_snap = _snap(video_codec="h264", probe_ok=True)
    store.update_row((7, "a.mkv"), new_snap)

    assert "h264" in _text(table, 0, 3)


def test_store_checked_propagates_to_both_adapters(qtbot):
    """store.set_checked 应同步更新 FlatAdapter 和 TreeAdapter"""
    from leanreel.data.file_store import FileTableStore, FileRow
    from leanreel.gui.adapters.flat_adapter import FlatAdapter
    from leanreel.gui.adapters.tree_adapter import TreeAdapter
    from PySide6.QtWidgets import QTableWidget, QTreeWidget
    from leanreel.gui.file_list import FileDecisionDisplay

    store = FileTableStore()
    table = QTableView()
    tree = QTreeWidget()
    tree.setColumnCount(6)
    fa = FlatAdapter(store, table)
    ta = TreeAdapter(store, tree)

    snap = _snap(video_codec="h264")
    d = FileDecisionDisplay(status_key="processable", strategy_text="均衡",
                            result_text="50%", result_sort=50, processable=True,
                            tooltip="均衡")
    store.rebuild([FileRow(snap=snap, decision=d)])

    # 初始未勾选
    assert _check(table, 0, 0) == Qt.Unchecked
    # 通过 Store 勾选
    store.set_checked((7, "a.mkv"), True)
    assert _check(table, 0, 0) == Qt.Checked
    # 树视图也同步
    child = tree.topLevelItem(0).child(0)
    assert child.checkState(0) == Qt.Checked


# ── 栈视图切换 ──

def test_stack_switches_to_table_on_populate(qtbot):
    """populate 应切换到表格，populate([]) 应切换到空状态"""
    from leanreel.gui.file_list import FileListPanel

    panel = FileListPanel()
    panel._show_empty()
    assert panel.stack.currentWidget() is panel.empty_label

    panel._show_table()
    assert panel.stack.currentWidget() is panel.table

    panel._show_tree()
    assert panel.stack.currentWidget() is panel.tree
    panel.close()


# ── 回归保护：stack 未被切换时测试必须失败 ──

def test_stack_visible_after_store_rebuild_anti_regression(qtbot):
    """自检：store.rebuild 后如果没调 _show_table，stack 仍指向 empty_label"""
    _qapp()
    from leanreel.data.file_store import FileTableStore, FileRow, FileDecisionDisplay
    from leanreel.gui.file_list import FileListPanel

    # 场景：store.rebuild 完成了，但忘记调 _show_table（回归）
    panel = FileListPanel()
    qtbot.addWidget(panel)
    store = FileTableStore()
    panel._store = store

    snap = _snap()
    d = FileDecisionDisplay(status_key="processable", strategy_text="均衡",
                            result_text="50%", result_sort=50, processable=True, tooltip="均衡")
    store.rebuild([FileRow(snap=snap, decision=d)])
    # 刻意不调 _show_table — 模拟回归
    assert panel.stack.currentWidget() is not panel.table  # 表格不可见!
    assert panel.stack.currentWidget() is panel.empty_label  # 还停在空状态

    # 修复：调 _show_table 之后应可见
    panel._show_table()
    assert panel.stack.currentWidget() is panel.table
    panel.close()
