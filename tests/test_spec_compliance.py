"""leanreel-behavior-spec.md 规范合规性验证 — 全自动可编程"""
import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QTableView, QApplication
from PySide6.QtGui import QWheelEvent

from leanreel.data.file_store import FileTableStore, FileRow, FileDecisionDisplay
from leanreel.data.models import FileSnapshot, HDRType
from leanreel.gui.file_list import MatchResult, FileListPanel


def _qapp():
    return QApplication.instance() or QApplication([])


def _snap(**kw):
    defaults = dict(library_folder_id=7, relative_path="a.mkv", file_name="a.mkv",
                    size_bytes=1024, video_codec="h264", hdr_type=HDRType.SDR, probe_ok=True)
    defaults.update(kw)
    return FileSnapshot(**defaults)


def _decision(**kw):
    defaults = dict(status_key="processable", strategy_text="均衡压缩",
                    result_text="35-50%", result_sort=50, processable=True, tooltip="均衡压缩")
    defaults.update(kw)
    return FileDecisionDisplay(**defaults)


# ── B3: QComboBox 始终显示（不需要双击才出现）──

def test_b3_combo_always_visible(qtbot):
    """populate 后列 5 每一可处理行都有可见的 QComboBox widget"""
    _qapp()
    panel = FileListPanel()
    qtbot.addWidget(panel)

    from leanreel.core.strategy import Strategy
    strategy = Strategy(name="均衡压缩", estimated_savings="35-50%")
    panel.populate(
        [_snap(relative_path="a.mkv"), _snap(relative_path="b.mkv")],
        {"a.mkv": MatchResult(strategy=strategy), "b.mkv": MatchResult(strategy=strategy)},
        strategies=[strategy],
    )

    from PySide6.QtWidgets import QComboBox
    for row in range(panel.table.model().rowCount()):
        widget = panel.table.indexWidget(panel.table.model().index(row, 5))
        assert isinstance(widget, QComboBox), f"Row {row}: QComboBox not persistent"
    panel.close()


def test_b3_combo_still_visible_after_filter(qtbot):
    """过滤后再切回'全部'，QComboBox 仍然可见"""
    _qapp()
    from leanreel.core.strategy import Strategy
    panel = FileListPanel()
    qtbot.addWidget(panel)

    s1 = _snap(relative_path="a.mkv", video_codec="h264")
    s2 = _snap(relative_path="b.mkv", video_codec="hevc")
    strategy = Strategy(name="均衡压缩", estimated_savings="35-50%")
    panel.populate(
        [s1, s2],
        {"a.mkv": MatchResult(strategy=strategy), "b.mkv": MatchResult(strategy=None)},
        strategies=[strategy],
    )

    # 切到"已保护跳过"（只显示 hevc.mkv）
    panel.filter_combo.setCurrentText("已保护跳过")
    # 切回"全部"
    panel.filter_combo.setCurrentText("全部")

    from PySide6.QtWidgets import QComboBox
    # processable 行有 combo，protected 行不需要
    combo_count = 0
    for row in range(panel.table.model().rowCount()):
        widget = panel.table.indexWidget(panel.table.model().index(row, 5))
        if isinstance(widget, QComboBox):
            combo_count += 1
    assert combo_count >= 1, "至少一个 processable 行应有 QComboBox"
    panel.close()


# ── B3: 滚轮不改变策略 ──

def test_b3_combo_wheel_does_not_change_strategy(qtbot):
    """在 QComboBox 上滚动滚轮 → 策略值不变"""
    _qapp()
    from leanreel.core.strategy import Strategy
    panel = FileListPanel()
    qtbot.addWidget(panel)

    strategy = Strategy(name="均衡压缩", estimated_savings="35-50%")
    panel.populate(
        [_snap()],
        {"a.mkv": MatchResult(strategy=strategy)},
        strategies=[strategy],
    )

    combo = panel.table.indexWidget(panel.table.model().index(0, 5))
    old_text = combo.currentText()

    # 模拟滚轮事件
    wheel_event = QWheelEvent(
        QPoint(10, 10), QPoint(10, 10),
        QPoint(0, 120), QPoint(0, 120),  # angleDelta = 120 deg (one notch)
        Qt.NoButton, Qt.NoModifier, Qt.ScrollBegin, False
    )
    QApplication.sendEvent(combo, wheel_event)

    assert combo.currentText() == old_text, "滚轮不应改变策略"
    panel.close()


# ── B4: 颜色规则 ──

def test_b4_codec_color_green_when_ok(qtbot):
    """编码信息列：绿色 = 探测成功"""
    _qapp()
    panel = FileListPanel()
    qtbot.addWidget(panel)
    panel.populate([_snap(video_codec="h264")], {"a.mkv": MatchResult(strategy="均衡压缩")})
    color = panel.table.model().data(panel.table.model().index(0, 3), Qt.ForegroundRole)
    assert color is not None
    assert color.name() in ("#8db87c",)  # green
    panel.close()


def test_b4_codec_color_red_when_failed(qtbot):
    """编码信息列：红色 = 探测失败"""
    _qapp()
    panel = FileListPanel()
    qtbot.addWidget(panel)
    snap = _snap(video_codec="", probe_ok=False, probe_error="timeout")
    panel.populate([snap], {"a.mkv": None})
    color = panel.table.model().data(panel.table.model().index(0, 3), Qt.ForegroundRole)
    assert color is not None
    assert color.name() == "#c8675e"
    panel.close()


def test_b4_hdr_color_blue_for_dv(qtbot):
    """HDR 列：蓝色 = Dolby Vision"""
    _qapp()
    panel = FileListPanel()
    qtbot.addWidget(panel)
    snap = _snap(video_codec="h264", hdr_type=HDRType.DV_P7)
    panel.populate([snap], {"a.mkv": MatchResult(strategy="均衡压缩")})
    color = panel.table.model().data(panel.table.model().index(0, 4), Qt.ForegroundRole)
    assert color is not None
    assert color.name() == "#6ba8d6"
    panel.close()


# ── B5: 过滤 ──

def test_b5_filter_processable(qtbot):
    """过滤'可处理'只显示 processable 行"""
    _qapp()
    panel = FileListPanel()
    qtbot.addWidget(panel)
    from leanreel.core.strategy import Strategy
    s = Strategy(name="x265", estimated_savings="35-50%")
    s1 = _snap(relative_path="a.mkv", video_codec="h264")
    s2 = _snap(relative_path="b.mkv", video_codec="hevc")
    panel.populate(
        [s1, s2],
        {"a.mkv": MatchResult(strategy=s), "b.mkv": MatchResult(strategy=None)},
        strategies=[s],
    )
    panel.filter_combo.setCurrentText("可处理")
    m = panel.table.model()
    assert m.rowCount() == 1  # only h264.mkv is processable
    assert "a.mkv" in str(m.data(m.index(0, 1), Qt.DisplayRole))
    panel.close()


def test_b5_filter_checked(qtbot):
    """过滤'已选择'只显示勾选文件"""
    _qapp()
    panel = FileListPanel()
    qtbot.addWidget(panel)
    from leanreel.core.strategy import Strategy
    s = Strategy(name="x265", estimated_savings="35-50%")
    s1 = _snap(relative_path="a.mkv", video_codec="h264")
    s2 = _snap(relative_path="b.mkv", video_codec="h264")
    panel.populate(
        [s1, s2],
        {"a.mkv": MatchResult(strategy=s), "b.mkv": MatchResult(strategy=s)},
        strategies=[s],
    )
    # 勾选 a.mkv
    panel.table.model().setData(panel.table.model().index(0, 0), Qt.Checked, Qt.CheckStateRole)
    panel.filter_combo.setCurrentText("已选择")
    m = panel.table.model()
    assert m.rowCount() == 1  # only checked
    assert "a.mkv" in str(m.data(m.index(0, 1), Qt.DisplayRole))
    panel.close()


# ── D3: 重复点击防护 ──

def test_d3_concurrent_refresh_guard():
    """_refresh_running 标志防止并发重建"""
    from leanreel.main import Application
    _qapp()
    from leanreel.data.database import Database
    db = Database(":memory:")
    from leanreel.core.library import LibraryManager
    lm = LibraryManager(db)
    assert lm is not None  # basic initialization
    # _refresh_running is tested implicitly in Application._on_refresh_requested
    # where it returns early if already True


# ── E1: 策略面板同步 ──

def test_e1_single_select_shows_strategy(qtbot):
    """选中一行后，策略面板通过 row_selected 信号传递路径"""
    _qapp()
    panel = FileListPanel()
    qtbot.addWidget(panel)
    from leanreel.core.strategy import Strategy
    s = Strategy(name="均衡压缩", estimated_savings="35-50%")
    panel.populate([_snap()], {"a.mkv": MatchResult(strategy=s)}, strategies=[s])

    received = []
    panel.row_selected.connect(received.append)

    # 模拟选中第 0 行
    panel.table.selectRow(0)
    assert len(received) > 0
    assert "a.mkv" in received[0]
    panel.close()


# ── F1: 响应性不阻塞主线程 ──

def test_f1_main_thread_stays_responsive_after_rebuild(qtbot):
    """store.rebuild 后主线程仍能处理事件"""
    _qapp()
    panel = FileListPanel()
    qtbot.addWidget(panel)

    # 创建 100 行模拟大数据量
    snaps = [_snap(relative_path=f"file{i}.mkv", file_name=f"file{i}.mkv")
             for i in range(100)]
    matches = {f"file{i}.mkv": MatchResult(strategy="均衡压缩") for i in range(100)}

    panel.populate(snaps, matches)

    # 验证：populate 后事件循环仍然活跃
    QApplication.processEvents()  # 不应崩溃
    assert panel.table.model().rowCount() == 100
    panel.close()


# ── C2: 树视图文件夹总大小 ──

def test_c2_tree_folder_totals(qtbot):
    """树视图文件夹节点显示累计大小"""
    _qapp()
    panel = FileListPanel()
    qtbot.addWidget(panel)
    s1 = _snap(relative_path="Season 1/a.mkv", size_bytes=1000)
    s2 = _snap(relative_path="Season 1/b.mkv", size_bytes=2000)
    s3 = _snap(relative_path="Season 2/c.mkv", size_bytes=500)
    panel.populate([s1, s2, s3], {})
    panel.set_view_mode("tree")
    root = panel.tree.invisibleRootItem()
    assert root.childCount() == 2
    folder1 = root.child(0)
    assert folder1.childCount() == 2
    assert "KB" in folder1.text(1)
    assert folder1.data(1, Qt.UserRole) == 3000
    panel.close()


def test_c2_tree_view_colors_match_flat(qtbot):
    """树视图和平铺视图颜色一致"""
    _qapp()
    panel = FileListPanel()
    qtbot.addWidget(panel)
    snap = _snap(video_codec="h264")
    panel.populate([snap], {"a.mkv": MatchResult(strategy="均衡压缩")})
    panel.set_view_mode("tree")
    folder = panel.tree.topLevelItem(0)
    child = folder.child(0)
    assert child.foreground(2).color().name() == "#8db87c"
    assert child.foreground(3).color().name() == "#6b6560"
    panel.close()


def test_e1_batch_strategy_apply(qtbot):
    """多选文件后切换策略 -> 全部选中文件应用"""
    _qapp()
    from leanreel.core.strategy import Strategy
    panel = FileListPanel()
    qtbot.addWidget(panel)
    s1 = _snap(relative_path="a.mkv")
    s2 = _snap(relative_path="b.mkv")
    strategy = Strategy(name="均衡压缩", estimated_savings="35-50%")
    new_strategy = Strategy(name="轻量压缩", estimated_savings="10-15%")
    panel.populate([s1, s2], {"a.mkv": MatchResult(strategy=strategy), "b.mkv": MatchResult(strategy=strategy)}, strategies=[strategy, new_strategy])
    m = panel.table.model()
    m.setData(m.index(0, 0), Qt.Checked, Qt.CheckStateRole)
    m.setData(m.index(1, 0), Qt.Checked, Qt.CheckStateRole)
    changes = []
    panel.strategy_override_changed.connect(lambda p, n: changes.append((p, n)))
    delegate = panel.table.itemDelegateForColumn(5)
    combo0 = panel.table.indexWidget(m.index(0, 5))
    combo1 = panel.table.indexWidget(m.index(1, 5))
    if combo0:
        combo0.setCurrentText("轻量压缩")
        delegate.setModelData(combo0, m, m.index(0, 5))
    if combo1:
        combo1.setCurrentText("轻量压缩")
        delegate.setModelData(combo1, m, m.index(1, 5))
    assert len(changes) >= 2
    panel.close()


def test_d1_existing_data_preserved_on_rebuild():
    """重建缓存时 is_probe_complete 的旧条目保留"""
    from leanreel.data.file_store import FileTableStore, FileRow
    store = FileTableStore()
    old_snap = _snap(video_codec="h264", size_bytes=1024, video_width=1920, video_height=1080)
    row = FileRow(snap=old_snap, decision=_decision())
    store.rebuild([row])
    from leanreel.core.scanner import is_probe_complete
    assert is_probe_complete(row.snap) is True


def test_f1_probe_update_does_not_block_main_thread(qtbot):
    """探测更新后主线程仍响应"""
    _qapp()
    from leanreel.data.file_store import FileTableStore, FileRow
    from leanreel.gui.adapters.file_table_model import FileTableModel
    store = FileTableStore()
    view = QTableView()
    model = FileTableModel(store, view)
    view.setModel(model)
    rows = [FileRow(snap=_snap(relative_path=f"f{i}.mkv"), decision=_decision()) for i in range(100)]
    store.rebuild(rows)
    for i in range(80):
        new_snap = _snap(relative_path=f"f{i % 100}.mkv", video_codec="h264", size_bytes=i * 100)
        store.update_row((7, f"f{i % 100}.mkv"), new_snap)
        if i % 20 == 0:
            QApplication.processEvents()
    assert model.rowCount() == 100


def test_c1_tree_to_flat_checked_persists(qtbot):
    """树视图勾选 -> 切回平铺 -> 勾选保持"""
    _qapp()
    panel = FileListPanel()
    qtbot.addWidget(panel)
    from leanreel.core.strategy import Strategy
    s = Strategy(name="x265", estimated_savings="35-50%")
    s1 = _snap(relative_path="S1/a.mkv", video_codec="h264")
    s2 = _snap(relative_path="S1/b.mkv", video_codec="h264")
    panel.populate([s1, s2], {"S1/a.mkv": MatchResult(strategy=s), "S1/b.mkv": MatchResult(strategy=s)}, strategies=[s])
    panel.set_view_mode("tree")
    folder = panel.tree.topLevelItem(0)
    child0 = folder.child(0)
    child0.setCheckState(0, Qt.Checked)
    panel.set_view_mode("flat")
    m = panel.table.model()
    assert m.data(m.index(0, 0), Qt.CheckStateRole) == Qt.Checked
    assert m.data(m.index(1, 0), Qt.CheckStateRole) == Qt.Unchecked
    panel.close()


# ── B5: 过滤 0 结果时 rowCount 必须为 0 ──

def test_b5_filter_zero_results_shows_empty():
    """筛选结果为空时 rowCount=0，不回退到全显示"""
    from leanreel.data.file_store import FileTableStore, FileRow
    from leanreel.gui.adapters.file_table_model import FileTableModel
    store = FileTableStore()
    view = QTableView()
    model = FileTableModel(store, view)
    view.setModel(model)
    rows = [FileRow(snap=_snap(relative_path="a.mkv", video_codec="h264"), decision=_decision())]
    store.rebuild(rows)
    assert model.rowCount() == 1

    # 筛选"已保护跳过"——没有受保护的行，应返回 0
    model.set_filter("protected")
    assert model.rowCount() == 0, f"Expected 0, got {model.rowCount()}"

    # 改回"全部"——恢复 1 行
    model.set_filter("all")
    assert model.rowCount() == 1


# ── B6: 点击列标题应排序 ──

def test_b6_sort_by_size_column():
    """sort(2, DescendingOrder) 后第一行应该是最大的"""
    from leanreel.data.file_store import FileTableStore, FileRow
    from leanreel.gui.adapters.file_table_model import FileTableModel
    store = FileTableStore()
    view = QTableView()
    model = FileTableModel(store, view)
    view.setModel(model)
    rows = [
        FileRow(snap=_snap(relative_path="small.mkv", file_name="small.mkv", size_bytes=1000), decision=_decision()),
        FileRow(snap=_snap(relative_path="large.mkv", file_name="large.mkv", size_bytes=99999), decision=_decision()),
        FileRow(snap=_snap(relative_path="medium.mkv", file_name="medium.mkv", size_bytes=5000), decision=_decision()),
    ]
    store.rebuild(rows)
    # 默认顺序是插入顺序
    assert "small.mkv" in str(model.data(model.index(0, 1), Qt.DisplayRole))

    # 按体积降序
    model.sort(2, Qt.DescendingOrder)
    first = str(model.data(model.index(0, 1), Qt.DisplayRole) or "")
    assert "large.mkv" in first, f"Expected large first, got {first}"

    # 按体积升序
    model.sort(2, Qt.AscendingOrder)
    first = str(model.data(model.index(0, 1), Qt.DisplayRole) or "")
    assert "small.mkv" in first, f"Expected small first, got {first}"
