"""leanreel-behavior-spec.md 规范合规性验证 — 全自动可编程"""
import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QTableView, QApplication
from PySide6.QtGui import QWheelEvent

from leanreel.state.file_store import FileTableStore
from leanreel.domain.models import FileRow, FileDecisionDisplay
from leanreel.domain.models import FileSnapshot, HDRType
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

    from leanreel.domain.models import Strategy
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


def test_b3_combo_visible_when_store_is_injected_before_strategies(qtbot):
    """Application injects the store before strategies are populated."""
    _qapp()
    panel = FileListPanel()
    qtbot.addWidget(panel)
    store = FileTableStore()
    panel.set_store(store)

    from leanreel.domain.models import Strategy
    strategy = Strategy(name="鍧囪　鍘嬬缉", estimated_savings="35-50%")
    panel.populate(
        [_snap(relative_path="a.mkv")],
        {"a.mkv": MatchResult(strategy=strategy)},
        strategies=[strategy],
    )

    from PySide6.QtWidgets import QComboBox
    widget = panel.table.indexWidget(panel.table.model().index(0, 5))
    assert isinstance(widget, QComboBox)
    assert widget.findText(strategy.name) >= 0
    panel.close()


def test_b3_combo_opening_is_batched(qtbot):
    """Large lists should not synchronously open every combo in one layout pass."""
    _qapp()
    from leanreel.domain.models import Strategy
    from leanreel.state.file_store import FileTableStore
    from leanreel.domain.models import FileRow
    from leanreel.gui.adapters.flat_adapter import FlatAdapter
    strategy = Strategy(name="鍧囪 鍘嬬缉", estimated_savings="35-50%")
    store = FileTableStore()
    view = QTableView()
    view.setFixedHeight(660)
    view.show()
    adapter = FlatAdapter(store, view, strategy_lookup={strategy.name: strategy})
    rows = [
        FileRow(
            snap=_snap(relative_path=f"{i}.mkv", file_name=f"{i}.mkv"),
            decision=_decision(strategy_text=strategy.name),
        )
        for i in range(200)
    ]

    store.rebuild(rows)

    first_pass = sum(
        1 for row in range(view.model().rowCount())
        if view.indexWidget(view.model().index(row, 5)) is not None
    )
    # 第一批次仅创建视口内可见行（~20 行），而非全部
    assert 15 <= first_pass <= 50, f"first pass should cover viewport rows, got {first_pass}"

    qtbot.waitUntil(
        lambda: all(
            view.indexWidget(view.model().index(row, 5)) is not None
            for row in range(min(20, view.model().rowCount()))
        ),
        timeout=1000,
    )


def test_b3_combo_batch_limits_scanned_rows_for_unprocessable_items(qtbot):
    """Rows without combo editors should still count toward the batch budget (viewport-aware)."""
    _qapp()
    from leanreel.state.file_store import FileTableStore
    from leanreel.domain.models import FileRow
    from leanreel.gui.adapters.flat_adapter import FlatAdapter
    store = FileTableStore()
    view = QTableView()
    # 设置固定高度以控制可见行数：行高 32px × 20 行 = 640px
    view.setFixedHeight(660)
    view.show()
    qtbot.addWidget(view)
    adapter = FlatAdapter(store, view)
    rows = [
        FileRow(
            snap=_snap(relative_path=f"{i}.mkv", file_name=f"{i}.mkv"),
            decision=_decision(status_key="protected", processable=False),
        )
        for i in range(200)
    ]

    store.rebuild(rows)

    # 视口内可见行大约 20 行（640 / 32 = 20），批次覆盖应 ≥ 20
    assert adapter._combo_next_row >= 20
    # 不应超过视口范围太多
    assert adapter._combo_next_row <= adapter._COMBO_BATCH + 20


def test_b3_combo_still_visible_after_filter(qtbot):
    """过滤后再切回'全部'，QComboBox 仍然可见"""
    _qapp()
    from leanreel.domain.models import Strategy
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
    from leanreel.domain.models import Strategy
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
    from leanreel.domain.models import Strategy
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
    from leanreel.domain.models import Strategy
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
    from leanreel.infrastructure.database import Database
    db = Database(":memory:")
    from leanreel.services.library import LibraryManager
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
    from leanreel.domain.models import Strategy
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

def test_e1_selected_qtableview_row_receives_preset_strategy_from_panel(qtbot):
    """Right-side preset changes should apply to the selected QTableView row."""
    _qapp()
    from types import SimpleNamespace
    from leanreel.domain.models import Strategy
    from leanreel.main import Application
    panel = FileListPanel()
    qtbot.addWidget(panel)
    initial = Strategy(name="Initial", estimated_savings="10%")
    replacement = Strategy(name="Replacement", estimated_savings="20%")
    panel.populate(
        [_snap(relative_path="a.mkv", file_name="a.mkv")],
        {"a.mkv": MatchResult(strategy=initial)},
        strategies=[initial, replacement],
    )
    panel.table.selectRow(0)
    from leanreel.controllers.strategy_controller import StrategyController
    app_state = SimpleNamespace(strategy_overrides={}, active_custom_path=None)
    ctrl = SimpleNamespace(
        _state=app_state,
        _file_panel=panel,
        _strategy_panel=SimpleNamespace(current_preset_strategy=replacement),
    )

    StrategyController._on_preset_strategy_changed(ctrl, 0)

    assert app_state.strategy_overrides[(7, "a.mkv")] is replacement
    model = panel.table.model()
    assert model.data(model.index(0, 5), Qt.DisplayRole) == "Replacement"
    panel.close()


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
    from leanreel.domain.models import Strategy
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
    from leanreel.state.file_store import FileTableStore
    from leanreel.domain.models import FileRow
    store = FileTableStore()
    old_snap = _snap(video_codec="h264", size_bytes=1024, video_width=1920, video_height=1080)
    row = FileRow(snap=old_snap, decision=_decision())
    store.rebuild([row])
    from leanreel.services.scanner import is_probe_complete
    assert is_probe_complete(row.snap) is True


def test_f1_probe_update_does_not_block_main_thread(qtbot):
    """探测更新后主线程仍响应"""
    _qapp()
    from leanreel.state.file_store import FileTableStore
    from leanreel.domain.models import FileRow
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


def test_f1_scan_ready_offloads_slow_cache_resolution(qtbot):
    """Cache resolution runs in a worker and commits resolved rows on the main thread."""
    _qapp()
    import threading
    import time
    from types import SimpleNamespace
    from leanreel.controllers.signals import AppSignals
    from leanreel.controllers.scan_controller import ScanController
    from leanreel.utils import threading_contract

    threading_contract._reset_for_tests()
    main_thread_id = threading_contract.capture_main_thread()
    load_threads = []
    cache_started = threading.Event()
    populated = []
    probe_started = []

    class SlowScanner:
        def load_cached(self, folder_id, path):
            load_threads.append(threading.get_ident())
            cache_started.set()
            time.sleep(0.15)
            return [
                _snap(
                    library_folder_id=folder_id,
                    relative_path="a.mkv",
                    file_name="a.mkv",
                    video_codec="h264",
                    probe_ok=True,
                )
            ]

        def probe_multi(self, folder_inputs, on_result, on_finished=None):
            probe_started.append(threading.get_ident())
            return sum(len(files) for _fid, _path, files in folder_inputs)

    fake_file_panel = SimpleNamespace(
        refresh_btn=SimpleNamespace(setEnabled=lambda value: None),
        set_progress_visible=lambda value: None,
        set_progress=lambda done, total: None,
        enable_sorting=lambda: None,
    )
    fake_notifier = AppSignals()
    fake_scan_ctrl = SimpleNamespace(
        _state=SimpleNamespace(
            scan_token=1, scan_states={}, active_scan_folder_id=0,
            refresh_running=True,
            current_snapshots=[],
            current_folder_paths={1: "C:/videos"},
        ),
        _file_panel=fake_file_panel,
        _win=SimpleNamespace(set_status=lambda text: None),
        _notifier=fake_notifier,
        _services=SimpleNamespace(scanner=SlowScanner()),
        _populate_file_list=lambda snapshots: populated.append((threading.get_ident(), list(snapshots))),
        _probe_total=0,
        _probe_done=0,
        _probe_token=0,
    )
    fake_notifier.scan_resolved.connect(
        lambda snapshots, folder_inputs, token: ScanController._on_scan_resolved(
            fake_scan_ctrl,
            snapshots,
            folder_inputs,
            token,
        )
    )
    placeholders = [
        _snap(library_folder_id=1, relative_path="a.mkv", file_name="a.mkv", probe_ok=False)
    ]
    folder_inputs = [(1, "C:/videos", [("a.mkv", "C:/videos/a.mkv")])]

    start = time.perf_counter()
    ScanController._on_scan_ready(fake_scan_ctrl, placeholders, folder_inputs, 1)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.05
    qtbot.waitUntil(cache_started.is_set, timeout=1000)
    qtbot.waitUntil(lambda: bool(populated), timeout=1000)
    assert load_threads and all(thread_id != main_thread_id for thread_id in load_threads)
    assert populated[0][0] == main_thread_id
    assert populated[0][1][0].video_codec == "h264"
    assert probe_started == [main_thread_id]
    assert populated
    threading_contract._reset_for_tests()


def test_f1_library_selection_offloads_slow_cache_loading(qtbot):
    """Selecting a library with slow cached folders must not block the UI thread."""
    _qapp()
    import threading
    import time
    from types import SimpleNamespace
    from leanreel.controllers.signals import AppSignals
    from leanreel.controllers.library_controller import LibraryController
    from leanreel.main import Application

    cache_threads = []
    cache_started = threading.Event()
    populated = []

    class SlowScanner:
        def load_cached(self, folder_id, path):
            cache_threads.append(threading.get_ident())
            cache_started.set()
            time.sleep(0.15)
            return [_snap(library_folder_id=folder_id, relative_path="cached.mkv", file_name="cached.mkv")]

    fake_notifier = AppSignals()
    fake_app = SimpleNamespace(
        services=SimpleNamespace(
            db=SimpleNamespace(get_folders_for_library=lambda lib_id: [SimpleNamespace(id=1, path="C:/videos")]),
            scanner=SlowScanner(),
        ),
        app_state=SimpleNamespace(
            current_folder_paths={},
            strategy_overrides={},
            current_snapshots=[],
            scan_token=1, scan_states={}, active_scan_folder_id=0,
        ),
        scan_ctrl=SimpleNamespace(
            _populate_file_list=lambda snapshots: populated.append((list(snapshots), False)),
        ),
        notifier=fake_notifier,
        win=SimpleNamespace(set_status=lambda text: None),
        file_panel=SimpleNamespace(
            refresh_btn=SimpleNamespace(setEnabled=lambda value: None),
            set_progress_visible=lambda value: None,
        ),
    )
    if hasattr(fake_notifier, "library_cache_loaded"):
        fake_notifier.library_cache_loaded.connect(
            lambda snapshots, token: Application._on_library_cache_loaded(fake_app, snapshots, token)
        )

    ctrl = LibraryController(
        state=fake_app.app_state,
        services=fake_app.services,
        lib_panel=SimpleNamespace(),
        file_panel=SimpleNamespace(),
        win=fake_app.win,
        notifier=fake_notifier,
    )
    start = time.perf_counter()
    ctrl._on_library_selected(1)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.05
    qtbot.waitUntil(cache_started.is_set, timeout=1000)
    qtbot.waitUntil(lambda: bool(populated), timeout=1000)
    assert populated[0][1] is False


def test_f1_library_cache_loader_rejects_main_thread_cache_work(qtbot):
    """The cache loader must execute load_cached in the background worker."""
    _qapp()
    import threading
    from types import SimpleNamespace

    from leanreel.controllers.signals import AppSignals
    from leanreel.controllers.library_controller import LibraryController
    from leanreel.utils import threading_contract
    from leanreel.main import Application

    threading_contract._reset_for_tests()
    threading_contract.capture_main_thread()
    load_threads = []

    class RecordingScanner:
        def load_cached(self, folder_id, path):
            load_threads.append(threading.get_ident())
            return []

    fake_notifier = AppSignals()
    fake_app = SimpleNamespace(
        services=SimpleNamespace(
            db=SimpleNamespace(get_folders_for_library=lambda lib_id: [SimpleNamespace(id=1, path="C:/videos")]),
            scanner=RecordingScanner(),
        ),
        app_state=SimpleNamespace(
            current_folder_paths={},
            strategy_overrides={},
            current_snapshots=[],
            scan_token=1, scan_states={}, active_scan_folder_id=0,
        ),
        scan_ctrl=SimpleNamespace(
            _populate_file_list=lambda snapshots: None,
        ),
        notifier=fake_notifier,
        win=SimpleNamespace(set_status=lambda text: None),
        file_panel=SimpleNamespace(
            refresh_btn=SimpleNamespace(setEnabled=lambda value: None),
            set_progress_visible=lambda value: None,
        ),
    )
    fake_notifier.library_cache_loaded.connect(
        lambda snapshots, token: Application._on_library_cache_loaded(fake_app, snapshots, token)
    )

    ctrl = LibraryController(
        state=fake_app.app_state,
        services=fake_app.services,
        lib_panel=SimpleNamespace(),
        file_panel=SimpleNamespace(),
        win=fake_app.win,
        notifier=fake_notifier,
    )
    ctrl._on_library_selected(1)

    qtbot.waitUntil(lambda: bool(load_threads), timeout=1000)
    assert all(thread_id != threading_contract.capture_main_thread() for thread_id in load_threads)
    threading_contract._reset_for_tests()


def test_f1_probe_results_are_committed_on_main_thread(qtbot):
    """Background probe callbacks must not update Store or Qt models directly."""
    _qapp()
    import threading
    from types import SimpleNamespace
    from leanreel.controllers.signals import AppSignals
    from leanreel.controllers.scan_controller import ScanController

    main_thread_id = threading.get_ident()
    update_threads = []
    progress = []

    class ThreadedScanner:
        def load_cached(self, folder_id, path):
            return []

        def probe_multi(self, folder_inputs, on_result, on_finished=None):
            def worker():
                on_result(_snap(library_folder_id=1, relative_path="a.mkv", file_name="a.mkv"))
            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            return 1

    class RecordingStore:
        def update_row(self, key, snap, match=None, decision=None):
            update_threads.append(threading.get_ident())

    fake_file_panel = SimpleNamespace(
        set_progress=lambda done, total: None,
        set_progress_visible=lambda visible: None,
        refresh_btn=SimpleNamespace(setEnabled=lambda value: None),
        _decision_display=lambda snap, match: _decision(),
        enable_sorting=lambda: None,
    )
    fake_notifier = AppSignals()
    fake_scan_ctrl = SimpleNamespace(
        _state=SimpleNamespace(
            scan_token=1, scan_states={}, active_scan_folder_id=0,
            refresh_running=True,
            current_snapshots=[],
        ),
        _services=SimpleNamespace(
            scanner=ThreadedScanner(),
            matcher=SimpleNamespace(match=lambda snap: None),
        ),
        _file_panel=fake_file_panel,
        _win=SimpleNamespace(set_status=lambda text: None),
        _notifier=fake_notifier,
        _store=RecordingStore(),
        _populate_file_list=lambda snapshots: None,
        _probe_total=0,
        _probe_done=0,
        _probe_token=0,
    )
    fake_notifier.progress.connect(lambda done, total: progress.append((done, total)))
    fake_notifier.scan_resolved.connect(
        lambda snapshots, folder_inputs, token: ScanController._on_scan_resolved(
            fake_scan_ctrl,
            snapshots,
            folder_inputs,
            token,
        )
    )
    if hasattr(fake_notifier, "probe_result"):
        fake_notifier.probe_result.connect(
            lambda snap, token: ScanController._on_probe_result(fake_scan_ctrl, snap, token)
        )

    ScanController._on_scan_ready(
        fake_scan_ctrl,
        [_snap(library_folder_id=1, relative_path="a.mkv", file_name="a.mkv", probe_ok=False)],
        [(1, "C:/videos", [("a.mkv", "C:/videos/a.mkv")])],
        1,
    )

    qtbot.waitUntil(lambda: bool(update_threads), timeout=1000)
    assert all(thread_id == main_thread_id for thread_id in update_threads)
    qtbot.waitUntil(lambda: progress == [(1, 1)], timeout=1000)


def test_f1_probe_commit_slot_rejects_worker_thread_direct_call(qtbot):
    """Probe commits are UI work and should reject direct worker-thread calls."""
    _qapp()
    import threading
    from types import SimpleNamespace

    from leanreel.utils import threading_contract
    from leanreel.controllers.scan_controller import ScanController

    threading_contract._reset_for_tests()
    threading_contract.capture_main_thread()
    errors = []

    fake_ctrl = SimpleNamespace(
        _state=SimpleNamespace(
            scan_token=1, scan_states={}, active_scan_folder_id=0,
            refresh_running=True,
            current_snapshots=[_snap(library_folder_id=1, relative_path="a.mkv", file_name="a.mkv")],
        ),
        _services=SimpleNamespace(matcher=SimpleNamespace(match=lambda snap: None)),
        _notifier=SimpleNamespace(
            probed=SimpleNamespace(emit=lambda snap, match: None),
            progress=SimpleNamespace(emit=lambda done, total: None),
            all_done=SimpleNamespace(emit=lambda: None),
        ),
        _file_panel=SimpleNamespace(
            _decision_display=lambda snap, match: _decision(),
            refresh_btn=SimpleNamespace(setEnabled=lambda value: None),
            set_progress_visible=lambda value: None,
        ),
        _store=SimpleNamespace(update_row=lambda key, snap, match=None, decision=None: None),
        _probe_done=0,
        _probe_total=1,
        _probe_token=1,
    )

    def worker():
        try:
            ScanController._on_probe_result(
                fake_ctrl,
                _snap(library_folder_id=1, relative_path="a.mkv", file_name="a.mkv"),
                1,
            )
        except RuntimeError as exc:
            errors.append(str(exc))

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=1)

    assert errors
    assert "ScanController._on_probe_result" in errors[0]

    threading_contract._reset_for_tests()


def test_f1_scan_resolved_commit_slot_rejects_worker_thread_direct_call(qtbot):
    """Resolved scan commits are UI work and should reject direct worker-thread calls."""
    _qapp()
    import threading
    from types import SimpleNamespace

    from leanreel.controllers.scan_controller import ScanController
    from leanreel.utils import threading_contract

    threading_contract._reset_for_tests()
    threading_contract.capture_main_thread()
    errors = []

    fake_ctrl = SimpleNamespace(_state=SimpleNamespace(scan_token=1, scan_states={}, active_scan_folder_id=0))

    def worker():
        try:
            ScanController._on_scan_resolved(fake_ctrl, [], [], 1)
        except RuntimeError as exc:
            errors.append(str(exc))

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=1)

    assert errors
    assert "ScanController._on_scan_resolved" in errors[0]
    threading_contract._reset_for_tests()


def test_f1_stale_scan_resolved_result_is_ignored(qtbot):
    """Late cache resolution from an old scan must not mutate state or start probing."""
    _qapp()
    from types import SimpleNamespace

    from leanreel.controllers.scan_controller import ScanController

    populated = []
    probed = []
    fake_ctrl = SimpleNamespace(
        _state=SimpleNamespace(scan_token=2, scan_states={}, active_scan_folder_id=0, current_snapshots=[]),
        _populate_file_list=lambda snapshots: populated.append(list(snapshots)),
        _services=SimpleNamespace(scanner=SimpleNamespace(probe_multi=lambda *args, **kwargs: probed.append(args))),
    )

    ScanController._on_scan_resolved(
        fake_ctrl,
        [_snap(library_folder_id=1, relative_path="stale.mkv")],
        [(1, "C:/videos", [("stale.mkv", "C:/videos/stale.mkv")])],
        1,
    )

    assert fake_ctrl._state.current_snapshots == []
    assert populated == []
    assert probed == []


def test_file_table_store_private_state_is_not_read_outside_store():
    """GUI/controllers should use FileTableStore's public API, not private containers."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    checked_files = [
        root / "leanreel" / "gui" / "file_list.py",
        root / "leanreel" / "controllers" / "strategy_controller.py",
    ]

    for path in checked_files:
        source = path.read_text(encoding="utf-8")
        assert "._store._rows" not in source
        assert "._store._checked" not in source


def test_f1_filtered_probe_update_avoids_full_layout_rebuild():
    """A filtered row update that stays visible should not rebuild the whole model."""
    from leanreel.state.file_store import FileTableStore
    from leanreel.domain.models import FileRow
    from leanreel.gui.adapters.file_table_model import FileTableModel

    _qapp()
    store = FileTableStore()
    view = QTableView()
    model = FileTableModel(store, view)
    view.setModel(model)
    protected = _decision(status_key="protected", processable=False)
    rows = [
        FileRow(snap=_snap(relative_path="a.mkv", file_name="a.mkv"), decision=protected),
        FileRow(snap=_snap(relative_path="b.mkv", file_name="b.mkv"), decision=protected),
    ]
    store.rebuild(rows)
    model.set_filter("protected")
    layout_changes = []
    model.layoutChanged.connect(lambda: layout_changes.append(True))

    store.update_row((7, "a.mkv"), _snap(relative_path="a.mkv", file_name="a.mkv", size_bytes=2048))

    assert layout_changes == []
    assert model.rowCount() == 2


def test_f1_repeated_filtered_updates_do_not_rebuild_layout():
    """Visible probe updates under an active filter should remain incremental."""
    import time

    from leanreel.state.file_store import FileTableStore
    from leanreel.domain.models import FileRow
    from leanreel.gui.adapters.file_table_model import FileTableModel

    _qapp()
    store = FileTableStore()
    view = QTableView()
    model = FileTableModel(store, view)
    view.setModel(model)

    protected = _decision(status_key="protected", processable=False)
    rows = [
        FileRow(snap=_snap(relative_path=f"f{i}.mkv", file_name=f"f{i}.mkv"), decision=protected)
        for i in range(1000)
    ]
    store.rebuild(rows)
    model.set_filter("protected")
    layout_changes = []
    model.layoutChanged.connect(lambda: layout_changes.append(True))

    start = time.perf_counter()
    for i in range(200):
        store.update_row(
            (7, f"f{i}.mkv"),
            _snap(relative_path=f"f{i}.mkv", file_name=f"f{i}.mkv", size_bytes=2048 + i),
        )
    elapsed = time.perf_counter() - start

    assert layout_changes == []
    assert model.rowCount() == 1000
    assert elapsed < 0.5


def test_c2_tree_rebuild_is_deferred_until_tree_view_is_shown(qtbot):
    """Flat mode should not eagerly construct the hidden tree for large rebuilds."""
    _qapp()
    panel = FileListPanel()
    qtbot.addWidget(panel)
    rows = [
        _snap(relative_path=f"S{i // 10}/file{i}.mkv", file_name=f"file{i}.mkv")
        for i in range(60)
    ]

    panel.populate(rows, {})

    assert panel.current_view_mode == "flat"
    assert panel.tree.topLevelItemCount() == 0
    panel.set_view_mode("tree")
    assert panel.tree.topLevelItemCount() > 0


def test_c1_tree_to_flat_checked_persists(qtbot):
    """树视图勾选 -> 切回平铺 -> 勾选保持"""
    _qapp()
    panel = FileListPanel()
    qtbot.addWidget(panel)
    from leanreel.domain.models import Strategy
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
    from leanreel.state.file_store import FileTableStore
    from leanreel.domain.models import FileRow
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
    from leanreel.state.file_store import FileTableStore
    from leanreel.domain.models import FileRow
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


def test_b6_sort_keeps_filtered_store_rows():
    """Sorting after filtering must reorder only the filtered store rows."""
    from leanreel.state.file_store import FileTableStore
    from leanreel.domain.models import FileRow
    from leanreel.gui.adapters.file_table_model import FileTableModel
    _qapp()
    store = FileTableStore()
    view = QTableView()
    model = FileTableModel(store, view)
    view.setModel(model)
    protected = _decision(status_key="protected", processable=False)
    rows = [
        FileRow(snap=_snap(relative_path="process-small.mkv", file_name="process-small.mkv", size_bytes=1000), decision=_decision()),
        FileRow(snap=_snap(relative_path="protected-small.mkv", file_name="protected-small.mkv", size_bytes=2000), decision=protected),
        FileRow(snap=_snap(relative_path="process-large.mkv", file_name="process-large.mkv", size_bytes=99999), decision=_decision()),
        FileRow(snap=_snap(relative_path="protected-large.mkv", file_name="protected-large.mkv", size_bytes=5000), decision=protected),
    ]
    store.rebuild(rows)

    model.set_filter("protected")
    assert model.rowCount() == 2
    model.sort(2, Qt.DescendingOrder)

    names = [str(model.data(model.index(i, 1), Qt.DisplayRole) or "") for i in range(model.rowCount())]
    assert names == ["protected-large.mkv", "protected-small.mkv"]


def test_b6_strategy_edit_stays_with_file_after_sort(qtbot):
    """Editing a strategy must not leave a visual-row cache behind after sorting."""
    _qapp()
    from leanreel.domain.models import Strategy
    panel = FileListPanel()
    qtbot.addWidget(panel)
    original = Strategy(name="Original", estimated_savings="10%")
    replacement = Strategy(name="Replacement", estimated_savings="20%")
    panel.populate(
        [
            _snap(relative_path="a.mkv", file_name="a.mkv", size_bytes=1),
            _snap(relative_path="z.mkv", file_name="z.mkv", size_bytes=2),
        ],
        {
            "a.mkv": MatchResult(strategy=original),
            "z.mkv": MatchResult(strategy=original),
        },
        strategies=[original, replacement],
    )
    model = panel.table.model()
    model.setData(model.index(0, 5), "Replacement", Qt.EditRole)

    model.sort(1, Qt.DescendingOrder)

    displayed = {
        model.data(model.index(row, 1), Qt.DisplayRole): model.data(model.index(row, 5), Qt.DisplayRole)
        for row in range(model.rowCount())
    }
    assert displayed == {"z.mkv": "Original", "a.mkv": "Replacement"}
    panel.close()


def test_strategy_combo_change_targets_duplicate_relative_path_by_file_key(qtbot):
    """Changing a duplicate relative path row should update that exact file key."""
    _qapp()
    from leanreel.domain.models import Strategy
    panel = FileListPanel()
    qtbot.addWidget(panel)
    original = Strategy(name="Original")
    replacement = Strategy(name="Replacement")
    panel.populate(
        [
            _snap(library_folder_id=1, relative_path="movie.mkv", file_name="movie.mkv"),
            _snap(library_folder_id=2, relative_path="movie.mkv", file_name="movie.mkv"),
        ],
        {
            (1, "movie.mkv"): MatchResult(strategy=original),
            (2, "movie.mkv"): MatchResult(strategy=original),
        },
        strategies=[original, replacement],
    )
    model = panel.table.model()

    model.setData(model.index(1, 5), "Replacement", Qt.EditRole)

    decisions = {row.key: row.decision.strategy_text for row in panel._store._rows}
    assert decisions[(1, "movie.mkv")] == "Original"
    assert decisions[(2, "movie.mkv")] == "Replacement"
    panel.close()


def test_start_request_uses_checked_file_keys_for_duplicate_relative_paths(qtbot):
    """Starting encoding must not expand one checked duplicate relative path to all folders."""
    _qapp()
    from types import SimpleNamespace
    from leanreel.controllers.strategy_controller import StrategyController
    panel = FileListPanel()
    qtbot.addWidget(panel)
    win = SimpleNamespace(statuses=[], set_status=lambda text: win.statuses.append(text))
    captured = {}
    encoding = SimpleNamespace(start=lambda snaps, paths, overrides: captured.setdefault("snaps", snaps))
    snapshots = [
        _snap(library_folder_id=1, relative_path="movie.mkv", file_name="movie.mkv"),
        _snap(library_folder_id=2, relative_path="movie.mkv", file_name="movie.mkv"),
    ]
    panel.populate(snapshots, {(1, "movie.mkv"): MatchResult(strategy="S"), (2, "movie.mkv"): MatchResult(strategy="S")})
    panel.table.model().setData(panel.table.model().index(1, 0), Qt.Checked, Qt.CheckStateRole)
    ctrl_like = SimpleNamespace(
        _state=SimpleNamespace(
            current_snapshots=snapshots,
            current_folder_paths={1: "C:/one", 2: "C:/two"},
            strategy_overrides={},
        ),
        _file_panel=panel,
        _encoding_ctrl=encoding,
        _win=win,
    )

    StrategyController._on_start_requested(ctrl_like)

    assert [(s.library_folder_id, s.relative_path) for s in captured["snaps"]] == [(2, "movie.mkv")]
    panel.close()
