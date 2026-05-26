"""EncodingController 单元测试 — 全面覆盖初始化、启动、暂停/继续、取消、进度更新、编码完成"""
from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch, ANY, call

import pytest

from leanreel.controllers.encoding_controller import EncodingController, build_encode_tasks
from leanreel.executor.worker import EncodeTask
from leanreel.domain.models import TaskStatus, FileSnapshot
from leanreel.domain.models import Strategy


# ──────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────

@pytest.fixture
def qapp():
    """提供 QApplication 实例供涉及 Qt 信号的测试使用"""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def default_strategy():
    """非平凡真实策略 — 均衡压缩"""
    return Strategy.from_dict({
        "name": "均衡压缩",
        "description": "通用 H.265 均衡压缩",
        "video": {"encoder": "libx265", "crf": 20, "preset": "slow", "pix_fmt": "yuv420p10le"},
        "filters": {},
    })


@pytest.fixture
def hq_strategy():
    """非平凡替代策略 — 高质量压缩"""
    return Strategy.from_dict({
        "name": "高质量压缩",
        "description": "高质量低失真压缩",
        "video": {"encoder": "libx265", "crf": 16, "preset": "slower", "pix_fmt": "yuv420p10le"},
        "filters": {},
    })


@pytest.fixture
def sample_snapshots():
    """真实文件快照 — 非平凡数据"""
    return [
        FileSnapshot(
            library_folder_id=1,
            relative_path="Movies/Action.mkv",
            file_name="Action.mkv",
            size_bytes=8_500_000_000,
            video_codec="h264",
            video_width=1920,
            video_height=1080,
            duration_seconds=7200.0,
            bitrate_bps=9_400_000,
        ),
        FileSnapshot(
            library_folder_id=1,
            relative_path="Movies/Comedy.mkv",
            file_name="Comedy.mkv",
            size_bytes=6_200_000_000,
            video_codec="h265",
            video_width=3840,
            video_height=2160,
            duration_seconds=5400.0,
            bitrate_bps=9_200_000,
        ),
        FileSnapshot(
            library_folder_id=2,
            relative_path="TV/Drama.mkv",
            file_name="Drama.mkv",
            size_bytes=3_100_000_000,
            video_codec="h264",
            video_width=1280,
            video_height=720,
            duration_seconds=3600.0,
            bitrate_bps=6_900_000,
        ),
    ]


@pytest.fixture
def sample_folder_paths():
    """多个库文件夹映射 — 非平凡数据"""
    return {1: "D:/Media/Movies", 2: "E:/TV Shows"}


@pytest.fixture
def mock_strategy_panel(default_strategy):
    """模拟的策略面板"""
    sp = MagicMock()
    sp.current_preset_strategy = None
    sp.current_strategy = default_strategy
    sp._encode_lock = MagicMock()
    sp.worker_count = 3
    sp.delete_source = False
    return sp


@pytest.fixture
def mock_win():
    """模拟的主窗口"""
    win = MagicMock()
    win.set_status = MagicMock()
    win.show_queue = MagicMock()
    return win


@pytest.fixture
def mock_queue_panel():
    """模拟的队列面板"""
    qp = MagicMock()
    qp.clear_tasks = MagicMock()
    qp.add_task_row = MagicMock()
    qp.update_task_row = MagicMock()
    qp.update_progress = MagicMock()
    qp.pause_btn = MagicMock()
    return qp


@pytest.fixture
def mock_notifier():
    """模拟的通知器 — 所有属性均为 MagicMock，支持链式 .emit() 调用"""
    n = MagicMock()
    n.task_updated = MagicMock()
    n.encoding_done = MagicMock()
    return n


@pytest.fixture
def controller(mock_strategy_panel, mock_win, mock_queue_panel, mock_notifier):
    """标准 EncodingController 实例"""
    return EncodingController(mock_strategy_panel, mock_win, mock_queue_panel, mock_notifier)


# ──────────────────────────────────────────
# __init__ 测试
# ──────────────────────────────────────────

class TestEncodingControllerInit:
    """初始化测试 — 验证依赖存储与初始状态"""

    def test_init_stores_all_dependencies(self, mock_strategy_panel, mock_win, mock_queue_panel, mock_notifier):
        """正向用例 1：初始化后所有依赖被正确存储"""
        ctrl = EncodingController(mock_strategy_panel, mock_win, mock_queue_panel, mock_notifier)
        assert ctrl._strategy_panel is mock_strategy_panel
        assert ctrl._win is mock_win
        assert ctrl._queue_panel is mock_queue_panel
        assert ctrl._notifier is mock_notifier

    def test_init_sets_initial_state(self, controller):
        """正向用例 2：初始状态正确 — active_manager 为 None，encoding_in_progress 为 False"""
        assert controller.active_manager is None
        assert controller.encoding_in_progress is False

    def test_init_creates_lock(self, controller):
        """正向用例 3：初始化时创建 _encode_lock（threading.Lock 实例）"""
        assert isinstance(controller._encode_lock, type(threading.Lock()))


# ──────────────────────────────────────────
# start() 测试
# ──────────────────────────────────────────

class TestEncodingControllerStart:
    """start() 方法测试 — 编码入口"""

    def test_start_creates_pending_history_before_worker_start(
        self, controller, mock_strategy_panel, mock_win, mock_queue_panel,
        sample_snapshots, sample_folder_paths,
    ):
        """正向用例：有 DB 时先创建 pending 历史记录，再启动 worker。"""
        events = []

        class FakeDb:
            def __init__(self):
                self.calls = []

            def execute(self, sql, params=None):
                return []  # No snapshot lookup result — fsid falls back to 0

            def create_compression_record(self, **kwargs):
                events.append(("db", kwargs["output_path"]))
                self.calls.append(kwargs)
                return 1000 + len(self.calls)

        class FakeManager:
            def __init__(self, *_args, **_kwargs):
                self.started_tasks = []

            def start(self, tasks):
                events.append(("start", [task.history_id for task in tasks]))
                self.started_tasks = list(tasks)

        class ImmediateThread:
            def __init__(self, target, daemon=False):
                self.target = target
                self.daemon = daemon

            def start(self):
                self.target()

        fake_db = FakeDb()
        controller._db = fake_db

        with patch('leanreel.controllers.encoding_controller.WorkerManager', FakeManager), \
             patch('leanreel.controllers.encoding_controller.threading.Thread', ImmediateThread):
            result = controller.start(sample_snapshots, sample_folder_paths, None)

        assert result is True
        assert len(fake_db.calls) == 2
        assert events[0][0] == "db"
        assert events[1][0] == "db"
        assert events[2] == ("start", [1001, 1002])

        added_tasks = [call_args[0][0] for call_args in mock_queue_panel.add_task_row.call_args_list]
        assert {task.history_id for task in added_tasks} == {1001, 1002}
        assert len({task.batch_id for task in added_tasks}) == 1
        assert all(task.batch_id for task in added_tasks)

        first_call = fake_db.calls[0]
        assert first_call["batch_id"] == added_tasks[0].batch_id
        assert first_call["strategy_name"] == "均衡压缩"
        assert first_call["original_size"] == 8_500_000_000
        assert first_call["encoder"] == "libx265"
        assert first_call["cq_value"] == 23  # VideoRule.cq defaults to 23 when not specified
        assert first_call["preset"] == "p1"  # nv_preset defaults to p1 and takes priority over preset
        assert first_call["pix_fmt"] == "yuv420p10le"
        assert first_call["audio_mode"] == "keep_original"
        assert first_call["sub_mode"] == "keep_chinese"

    @patch('leanreel.controllers.encoding_controller.threading.Thread')
    @patch('leanreel.controllers.encoding_controller.WorkerManager')
    def test_start_does_not_start_worker_when_pending_history_creation_fails(
        self, mock_worker_mgr, mock_thread,
        controller, mock_win, sample_snapshots, sample_folder_paths,
    ):
        """负向用例：pending 历史记录创建失败时不启动任何 worker/thread。"""
        fake_db = MagicMock()
        fake_db.create_compression_record.side_effect = RuntimeError("history db locked")
        controller._db = fake_db

        result = controller.start(sample_snapshots, sample_folder_paths, None)

        assert result is False
        assert controller.encoding_in_progress is False
        mock_worker_mgr.assert_not_called()
        mock_thread.assert_not_called()
        mock_win.set_status.assert_called_with("创建历史记录失败")

    @patch('leanreel.controllers.encoding_controller.threading.Thread')
    @patch('leanreel.controllers.encoding_controller.WorkerManager')
    @patch('leanreel.controllers.encoding_controller.FFmpegExecutor')
    def test_start_builds_tasks_and_returns_true(
        self, mock_ffmpeg, mock_worker_mgr, mock_thread,
        controller, mock_strategy_panel, mock_win, mock_queue_panel,
        sample_snapshots, sample_folder_paths, default_strategy,
    ):
        """正向用例 1：完整编码启动流程 — 构建任务、清空队列、创建管理器、启动线程"""
        result = controller.start(sample_snapshots, sample_folder_paths, None)

        assert result is True
        # 验证队列被清空
        mock_queue_panel.clear_tasks.assert_called_once()
        # HEVC/H.265 优质片源默认完全跳过，3 个快照 -> 2 个任务
        assert mock_queue_panel.add_task_row.call_count == 2
        # 验证队列被显示
        mock_win.show_queue.assert_called_once()
        mock_ffmpeg.assert_called_once()
        assert "temp_dir" not in mock_ffmpeg.call_args[1]
        # 验证 WorkerManager 用正确的 worker_count 创建
        assert mock_worker_mgr.call_count == 1
        wm_args = mock_worker_mgr.call_args
        assert wm_args[0][1] == 3  # 第二个位置参数是 worker_count
        assert callable(wm_args[1].get('progress_callback'))
        # 验证后台线程被启动
        mock_thread.assert_called_once()
        assert mock_thread.call_args[1].get('daemon') is True
        # 验证 Thread.start() 被调用
        mock_thread.return_value.start.assert_called_once()
        # 验证 encoding_in_progress 为 True
        assert controller.encoding_in_progress is True

    @patch('leanreel.controllers.encoding_controller.threading.Thread')
    @patch('leanreel.controllers.encoding_controller.WorkerManager')
    @patch('leanreel.controllers.encoding_controller.FFmpegExecutor')
    def test_start_with_strategy_overrides_builds_correct_tasks(
        self, mock_ffmpeg, mock_worker_mgr, mock_thread,
        controller, mock_strategy_panel, mock_win, mock_queue_panel,
        sample_snapshots, sample_folder_paths, default_strategy, hq_strategy,
    ):
        """正向用例 2：per-file 策略覆盖 — 覆盖策略的文件使用对应策略，其余用默认"""
        overrides = {(1, "Movies/Action.mkv"): hq_strategy}
        result = controller.start(sample_snapshots, sample_folder_paths, overrides)

        assert result is True
        # HEVC/H.265 优质片源默认完全跳过
        assert mock_queue_panel.add_task_row.call_count == 2

        # 提取所有添加的任务
        added_tasks = [
            call_args[0][0] for call_args in mock_queue_panel.add_task_row.call_args_list
        ]
        # 按文件名查找
        tasks_by_name = {t.file_name: t for t in added_tasks}
        assert "Action.mkv" in tasks_by_name
        assert "Comedy.mkv" not in tasks_by_name
        assert "Drama.mkv" in tasks_by_name

        # Action.mkv 使用了覆盖策略
        assert tasks_by_name["Action.mkv"].strategy_name == "高质量压缩"
        assert tasks_by_name["Action.mkv"].strategy is hq_strategy
        # Drama.mkv 使用默认策略
        assert tasks_by_name["Drama.mkv"].strategy_name == "均衡压缩"

    def test_build_encode_tasks_ignores_bare_relative_path_override_when_file_key_absent(
        self, default_strategy, hq_strategy,
    ):
        """边界用例：不同库同名相对路径不能被裸 relative_path 覆盖串联。"""
        snapshots = [
            FileSnapshot(library_folder_id=1, relative_path="movie.mkv", file_name="movie.mkv", video_codec="h264"),
            FileSnapshot(library_folder_id=2, relative_path="movie.mkv", file_name="movie.mkv", video_codec="h264"),
        ]

        tasks = build_encode_tasks(
            snapshots,
            {1: "C:/one", 2: "C:/two"},
            default_strategy,
            {"movie.mkv": hq_strategy},
        )

        assert [task.strategy_name for task in tasks] == ["均衡压缩", "均衡压缩"]

    def test_build_encode_tasks_uses_mkv_output_for_av1_ts_source(self):
        """AV1 输出强制使用 MKV，避免沿用 TS 等弱容器。"""
        strategy = Strategy.from_dict({
            "name": "AV1 NVENC CQ34 均衡快速",
            "video": {"encoder": "av1_nvenc", "gpu": True},
            "filters": {},
        })
        snapshots = [
            FileSnapshot(
                library_folder_id=7,
                relative_path="Movie.ts",
                file_name="Movie.ts",
                video_codec="h264",
            )
        ]

        tasks = build_encode_tasks(snapshots, {7: "D:/Movies"}, strategy)

        assert len(tasks) == 1
        assert tasks[0].output_path == str(Path("D:/Movies") / "Movie_zcompressed.mkv")

    def test_start_returns_false_when_already_encoding(self, controller, sample_snapshots, sample_folder_paths):
        """负向用例 1：编码进行中时再次调用 start() 返回 False"""
        controller.encoding_in_progress = True
        result = controller.start(sample_snapshots, sample_folder_paths, None)
        assert result is False

    def test_start_returns_false_when_already_encoding_sets_status(
        self, controller, mock_win, sample_snapshots, sample_folder_paths,
    ):
        """负向用例 2：重复编码时通过 set_status 提示用户"""
        controller.encoding_in_progress = True
        controller.start(sample_snapshots, sample_folder_paths, None)
        mock_win.set_status.assert_called_once_with("编码正在进行中，请等待完成")

    def test_start_returns_false_when_no_strategy(
        self, controller, mock_strategy_panel, mock_win,
        sample_snapshots, sample_folder_paths,
    ):
        """负向用例 3：无预设策略且无当前策略时返回 False"""
        mock_strategy_panel.current_preset_strategy = None
        mock_strategy_panel.current_strategy = None
        result = controller.start(sample_snapshots, sample_folder_paths, None)
        assert result is False
        mock_win.set_status.assert_called_once_with("没有可用策略")

    def test_start_returns_false_when_no_tasks(
        self, controller, mock_win, sample_folder_paths, default_strategy,
    ):
        """边界用例：空快照列表 — build_encode_tasks 返回 [] 时不启动编码"""
        result = controller.start([], sample_folder_paths, None)
        assert result is False
        mock_win.set_status.assert_called_once_with("没有可压缩文件")

    def test_start_returns_false_when_folder_paths_dont_match(
        self, controller, mock_win, sample_snapshots,
    ):
        """边界用例：folder_paths 不匹配任何快照时返回 False"""
        # folder_paths 的 key 和 snapshot 的 library_folder_id 不匹配
        result = controller.start(sample_snapshots, {99: "Z:/Unknown"}, None)
        assert result is False
        mock_win.set_status.assert_called_once_with("没有可压缩文件")

    @patch('leanreel.controllers.encoding_controller.threading.Thread')
    @patch('leanreel.controllers.encoding_controller.WorkerManager')
    @patch('leanreel.controllers.encoding_controller.FFmpegExecutor')
    def test_start_sets_encoding_in_progress_before_work(
        self, mock_ffmpeg, mock_worker_mgr, mock_thread,
        controller, sample_snapshots, sample_folder_paths,
    ):
        """正向用例 3：启动后 encoding_in_progress 置为 True"""
        controller.start(sample_snapshots, sample_folder_paths, None)
        assert controller.encoding_in_progress is True

    @patch('leanreel.controllers.encoding_controller.threading.Thread')
    @patch('leanreel.controllers.encoding_controller.WorkerManager')
    @patch('leanreel.controllers.encoding_controller.FFmpegExecutor')
    def test_start_active_manager_is_set(
        self, mock_ffmpeg, mock_worker_mgr, mock_thread,
        controller, sample_snapshots, sample_folder_paths,
    ):
        """正向用例 4：启动后 active_manager 引用已创建的 WorkerManager"""
        controller.start(sample_snapshots, sample_folder_paths, None)
        assert controller.active_manager is mock_worker_mgr.return_value

    @patch('leanreel.controllers.encoding_controller.threading.Thread')
    @patch('leanreel.controllers.encoding_controller.WorkerManager')
    @patch('leanreel.controllers.encoding_controller.FFmpegExecutor')
    def test_start_progress_callback_emits_task_updated(
        self, mock_ffmpeg, mock_worker_mgr, mock_thread,
        controller, mock_notifier, sample_snapshots, sample_folder_paths,
    ):
        """正向用例 5：进度回调 lambda 正确调用 notifier.task_updated.emit()"""
        controller.start(sample_snapshots, sample_folder_paths, None)

        # 提取创建 WorkerManager 时传入的 progress_callback
        wm_kwargs = mock_worker_mgr.call_args[1]
        progress_cb = wm_kwargs.get('progress_callback')
        assert progress_cb is not None
        assert callable(progress_cb)

        # 模拟一个任务传入回调
        fake_task = EncodeTask(
            file_name="Test.mkv", input_path="/in/Test.mkv",
            output_path="/out/Test.mkv", status=TaskStatus.RUNNING,
        )
        progress_cb(fake_task)

        # 验证 emit 被调用并传入了正确的 task
        mock_notifier.task_updated.emit.assert_called_once_with(fake_task)

    @patch('leanreel.controllers.encoding_controller.threading.Thread')
    @patch('leanreel.controllers.encoding_controller.WorkerManager')
    @patch('leanreel.controllers.encoding_controller.FFmpegExecutor')
    def test_start_handles_exception_gracefully(
        self, mock_ffmpeg, mock_worker_mgr, mock_thread,
        controller, mock_win, sample_snapshots, sample_folder_paths,
    ):
        """负向用例：内部异常时重置 encoding_in_progress 并显示错误"""
        # 让 WorkerManager 构造抛出异常
        mock_worker_mgr.side_effect = RuntimeError("磁盘空间不足")

        result = controller.start(sample_snapshots, sample_folder_paths, None)
        assert result is False
        assert controller.encoding_in_progress is False
        mock_win.set_status.assert_called_with("错误：磁盘空间不足")

    @patch('leanreel.controllers.encoding_controller.threading.Thread')
    @patch('leanreel.controllers.encoding_controller.WorkerManager')
    @patch('leanreel.controllers.encoding_controller.FFmpegExecutor')
    def test_start_prefers_preset_strategy_over_current(
        self, mock_ffmpeg, mock_worker_mgr, mock_thread,
        controller, mock_strategy_panel, mock_queue_panel,
        sample_snapshots, sample_folder_paths, hq_strategy,
    ):
        """正向用例 6：current_preset_strategy 优先级高于 current_strategy"""
        # 同时设置 preset 和 current，preset 应被优先使用
        mock_strategy_panel.current_preset_strategy = hq_strategy
        # current_strategy 保持默认（均衡压缩）

        controller.start(sample_snapshots, sample_folder_paths, None)

        # 验证任务使用的是 preset 策略
        added_tasks = [
            call_args[0][0] for call_args in mock_queue_panel.add_task_row.call_args_list
        ]
        for task in added_tasks:
            assert task.strategy_name == "高质量压缩"


# ──────────────────────────────────────────
# toggle_pause() 测试
# ──────────────────────────────────────────

class TestEncodingControllerTogglePause:
    """toggle_pause() 方法测试 — 暂停/继续切换"""

    def test_toggle_pause_pauses_running_manager(self, controller, mock_win, mock_queue_panel):
        """正向用例 1：从运行状态切换到暂停 — 调用 manager.pause() 并更新 UI"""
        mock_mgr = MagicMock()
        mock_mgr.is_paused = False
        controller.active_manager = mock_mgr

        controller.toggle_pause()

        mock_mgr.pause.assert_called_once()
        mock_mgr.resume.assert_not_called()
        mock_win.set_status.assert_called_once_with("编码已暂停（等待当前任务完成）")
        mock_queue_panel.pause_btn.setText.assert_called_once_with("继续")

    def test_toggle_pause_resumes_paused_manager(self, controller, mock_win, mock_queue_panel):
        """正向用例 2：从暂停状态恢复到运行 — 调用 manager.resume() 并更新 UI"""
        mock_mgr = MagicMock()
        mock_mgr.is_paused = True
        controller.active_manager = mock_mgr

        controller.toggle_pause()

        mock_mgr.resume.assert_called_once()
        mock_mgr.pause.assert_not_called()
        mock_win.set_status.assert_called_once_with("编码已恢复")
        mock_queue_panel.pause_btn.setText.assert_called_once_with("暂停")

    def test_toggle_pause_noop_when_no_active_manager(self, controller, mock_win, mock_queue_panel):
        """边界用例：无 active_manager 时 toggle_pause() 无任何操作"""
        controller.active_manager = None
        controller.toggle_pause()

        mock_win.set_status.assert_not_called()
        mock_queue_panel.pause_btn.setText.assert_not_called()


# ──────────────────────────────────────────
# cancel() 测试
# ──────────────────────────────────────────

class TestEncodingControllerCancel:
    """cancel() 方法测试 — 取消编码"""

    def test_cancel_calls_manager_cancel_and_updates_status(self, controller, mock_win):
        """正向用例 1：有 active_manager 时调用 cancel() 并更新状态"""
        mock_mgr = MagicMock()
        controller.active_manager = mock_mgr

        controller.cancel()

        mock_mgr.cancel.assert_called_once()
        mock_win.set_status.assert_called_once_with("正在取消编码...")

    def test_cancel_accepts_optional_idx_argument(self, controller, mock_win):
        """正向用例 2：cancel(_idx) 接受可选索引参数（来自信号签名）"""
        mock_mgr = MagicMock()
        controller.active_manager = mock_mgr

        # 模拟 QueuePanel 的 cancel_requested Signal(int) 传入索引
        controller.cancel(5)

        mock_mgr.cancel.assert_called_once()
        mock_win.set_status.assert_called_once_with("正在取消编码...")

    def test_cancel_noop_when_no_active_manager(self, controller, mock_win):
        """边界用例：无 active_manager 时 cancel() 无任何操作"""
        controller.active_manager = None
        controller.cancel()

        mock_win.set_status.assert_not_called()


# ──────────────────────────────────────────
# on_task_updated() 测试
# ──────────────────────────────────────────

class TestEncodingControllerOnTaskUpdated:
    """on_task_updated() 方法测试 — 单任务进度更新"""

    def test_on_task_updated_updates_row_and_progress_for_running_task(
        self, controller, mock_queue_panel, mock_win,
    ):
        """正向用例 1：RUNNING 状态任务 — 更新行和进度"""
        mock_mgr = MagicMock()
        mock_mgr.get_progress.return_value = {
            "total": 3, "completed": 1, "failed": 0,
            "skipped": 0, "pending": 2, "percentage": 33.3,
        }
        controller.active_manager = mock_mgr

        task = EncodeTask(
            file_name="Action.mkv", input_path="D:/Media/Movies/Action.mkv",
            output_path="D:/Media/Movies/Action_SS.mkv",
            status=TaskStatus.RUNNING, progress=45.0,
            original_size=8_500_000_000,
        )
        controller.on_task_updated(task)

        mock_queue_panel.update_task_row.assert_called_once_with(task)
        mock_mgr.get_progress.assert_called_once()
        mock_queue_panel.update_progress.assert_called_once_with({
            "total": 3, "completed": 1, "failed": 0,
            "skipped": 0, "pending": 2, "percentage": 33.3,
        })
        mock_win.set_status.assert_called_once_with("编码中：1/3")

    def test_on_task_updated_updates_row_for_completed_task(
        self, controller, mock_queue_panel, mock_win,
    ):
        """正向用例 2：COMPLETED 状态任务 — 进度中已算上该完成项"""
        mock_mgr = MagicMock()
        mock_mgr.get_progress.return_value = {
            "total": 2, "completed": 2, "failed": 0,
            "skipped": 0, "pending": 0, "percentage": 100.0,
        }
        controller.active_manager = mock_mgr

        task = EncodeTask(
            file_name="Comedy.mkv", input_path="D:/Media/Movies/Comedy.mkv",
            output_path="D:/Media/Movies/Comedy_SS.mkv",
            status=TaskStatus.COMPLETED, progress=100.0,
            original_size=6_200_000_000, compressed_size=2_100_000_000,
        )
        controller.on_task_updated(task)

        mock_queue_panel.update_task_row.assert_called_once_with(task)
        mock_win.set_status.assert_called_once_with("编码中：2/2")

    def test_on_task_updated_noop_progress_when_no_active_manager(
        self, controller, mock_queue_panel, mock_win,
    ):
        """边界用例：无 active_manager 时仅更新行，不更新进度和状态"""
        controller.active_manager = None

        task = EncodeTask(
            file_name="Drama.mkv", input_path="E:/TV Shows/TV/Drama.mkv",
            output_path="E:/TV Shows/TV/Drama_SS.mkv",
            status=TaskStatus.FAILED, error_message="编码器崩溃",
        )
        controller.on_task_updated(task)

        # 行的更新应该仍然发生
        mock_queue_panel.update_task_row.assert_called_once_with(task)
        # 但进度和状态不应该被更新
        mock_queue_panel.update_progress.assert_not_called()
        mock_win.set_status.assert_not_called()

    def test_on_task_updated_shows_failed_count_in_status(
        self, controller, mock_win,
    ):
        """正向用例 3：包含失败任务时，状态栏显示失败数"""
        mock_mgr = MagicMock()
        mock_mgr.get_progress.return_value = {
            "total": 3, "completed": 1, "failed": 1,
            "skipped": 0, "pending": 1, "percentage": 66.7,
        }
        controller.active_manager = mock_mgr

        task = EncodeTask(
            file_name="Drama.mkv", input_path="E:/TV Shows/TV/Drama.mkv",
            output_path="E:/TV Shows/TV/Drama_SS.mkv",
            status=TaskStatus.FAILED, error_message="编码失败",
        )
        controller.on_task_updated(task)

        mock_win.set_status.assert_called_once_with("编码中：2/3")


# ──────────────────────────────────────────
# on_encoding_done() 测试
# ──────────────────────────────────────────

class TestEncodingControllerOnEncodingDone:
    """on_encoding_done() 方法测试 — 编码完成处理"""

    def test_on_encoding_done_resets_flag_and_reports_all_success(
        self, controller, mock_win,
    ):
        """正向用例 1：所有任务完成 — 重置标志并显示成功统计"""
        results = [
            EncodeTask(file_name="Action.mkv", input_path="/in/Action.mkv",
                       output_path="/out/Action_SS.mkv",
                       status=TaskStatus.COMPLETED,
                       original_size=8_500_000_000, compressed_size=2_800_000_000),
            EncodeTask(file_name="Comedy.mkv", input_path="/in/Comedy.mkv",
                       output_path="/out/Comedy_SS.mkv",
                       status=TaskStatus.COMPLETED,
                       original_size=6_200_000_000, compressed_size=1_900_000_000),
            EncodeTask(file_name="Drama.mkv", input_path="/in/Drama.mkv",
                       output_path="/out/Drama_SS.mkv",
                       status=TaskStatus.COMPLETED,
                       original_size=3_100_000_000, compressed_size=1_050_000_000),
        ]
        mock_mgr = MagicMock()
        mock_mgr.get_results.return_value = results
        controller.active_manager = mock_mgr
        controller.encoding_in_progress = True

        controller.on_encoding_done()

        assert controller.encoding_in_progress is False
        mock_mgr.get_results.assert_called_once()
        mock_win.set_status.assert_called_once_with("编码完成：成功 3")

    def test_on_encoding_done_reports_mixed_results(
        self, controller, mock_win,
    ):
        """正向用例 2：混合结果 — 包含成功和失败的任务"""
        results = [
            EncodeTask(file_name="Action.mkv", input_path="/in/Action.mkv",
                       output_path="/out/Action_SS.mkv",
                       status=TaskStatus.COMPLETED,
                       original_size=8_500_000_000, compressed_size=2_800_000_000),
            EncodeTask(file_name="Comedy.mkv", input_path="/in/Comedy.mkv",
                       output_path="/out/Comedy_SS.mkv",
                       status=TaskStatus.FAILED, error_message="GPU 内存不足",
                       original_size=6_200_000_000),
            EncodeTask(file_name="Drama.mkv", input_path="/in/Drama.mkv",
                       output_path="/out/Drama_SS.mkv",
                       status=TaskStatus.COMPLETED,
                       original_size=3_100_000_000, compressed_size=1_050_000_000),
            EncodeTask(file_name="Extra.mkv", input_path="/in/Extra.mkv",
                       output_path="/out/Extra_SS.mkv",
                       status=TaskStatus.FAILED, error_message="文件损坏",
                       original_size=2_000_000_000),
        ]
        mock_mgr = MagicMock()
        mock_mgr.get_results.return_value = results
        controller.active_manager = mock_mgr
        controller.encoding_in_progress = True

        controller.on_encoding_done()

        assert controller.encoding_in_progress is False
        mock_win.set_status.assert_called_once_with("编码完成：成功 2 ｜ 失败 2")

    def test_on_encoding_done_skips_skipped_tasks_in_done_count(
        self, controller, mock_win,
    ):
        """正向用例 3：跳过的任务不计入 done """
        results = [
            EncodeTask(file_name="Action.mkv", input_path="/in/Action.mkv",
                       output_path="/out/Action_SS.mkv",
                       status=TaskStatus.COMPLETED,
                       original_size=8_500_000_000, compressed_size=2_800_000_000),
            EncodeTask(file_name="Comedy.mkv", input_path="/in/Comedy.mkv",
                       output_path="/out/Comedy_SS.mkv",
                       status=TaskStatus.SKIPPED,
                       original_size=6_200_000_000),
        ]
        mock_mgr = MagicMock()
        mock_mgr.get_results.return_value = results
        controller.active_manager = mock_mgr
        controller.encoding_in_progress = True

        controller.on_encoding_done()

        assert controller.encoding_in_progress is False
        mock_win.set_status.assert_called_once_with("编码完成：成功 1")

    def test_on_encoding_done_resets_flag_when_no_active_manager(
        self, controller, mock_win,
    ):
        """边界用例：无 active_manager 时仍重置 encoding_in_progress，但不更新状态"""
        controller.active_manager = None
        controller.encoding_in_progress = True

        controller.on_encoding_done()

        assert controller.encoding_in_progress is False
        mock_win.set_status.assert_not_called()

    def test_on_encoding_done_with_no_completed_task_reports_zero(
        self, controller, mock_win,
    ):
        """边界用例：全部失败 — done=0 """
        results = [
            EncodeTask(file_name="Bad1.mkv", input_path="/in/Bad1.mkv",
                       output_path="/out/Bad1_SS.mkv",
                       status=TaskStatus.FAILED, error_message="编码器崩溃",
                       original_size=5_000_000_000),
            EncodeTask(file_name="Bad2.mkv", input_path="/in/Bad2.mkv",
                       output_path="/out/Bad2_SS.mkv",
                       status=TaskStatus.FAILED, error_message="输出不可写",
                       original_size=3_000_000_000),
        ]
        mock_mgr = MagicMock()
        mock_mgr.get_results.return_value = results
        controller.active_manager = mock_mgr
        controller.encoding_in_progress = True

        controller.on_encoding_done()

        assert controller.encoding_in_progress is False
        mock_win.set_status.assert_called_once_with("编码完成：成功 0 ｜ 失败 2")


# ──────────────────────────────────────────
# 集成场景测试
# ──────────────────────────────────────────

class TestEncodingControllerIntegrationScenarios:
    """跨方法联动场景"""

    @patch('leanreel.controllers.encoding_controller.threading.Thread')
    @patch('leanreel.controllers.encoding_controller.WorkerManager')
    @patch('leanreel.controllers.encoding_controller.FFmpegExecutor')
    def test_start_then_on_encoding_done_sequence(
        self, mock_ffmpeg, mock_worker_mgr, mock_thread,
        controller, mock_win, sample_snapshots, sample_folder_paths,
    ):
        """场景：启动编码，然后手动触发 on_encoding_done 完成"""
        # 阶段 1: start()
        controller.start(sample_snapshots, sample_folder_paths, None)
        assert controller.encoding_in_progress is True
        assert controller.active_manager is not None

        # 阶段 2: on_encoding_done() — 模拟后台线程完成后发出信号
        completed_tasks = [
            EncodeTask(file_name="Action.mkv", input_path="/in/Action.mkv",
                       output_path="/out/Action_SS.mkv",
                       status=TaskStatus.COMPLETED,
                       original_size=8_500_000_000, compressed_size=2_800_000_000),
            EncodeTask(file_name="Comedy.mkv", input_path="/in/Comedy.mkv",
                       output_path="/out/Comedy_SS.mkv",
                       status=TaskStatus.COMPLETED,
                       original_size=6_200_000_000, compressed_size=1_900_000_000),
            EncodeTask(file_name="Drama.mkv", input_path="/in/Drama.mkv",
                       output_path="/out/Drama_SS.mkv",
                       status=TaskStatus.COMPLETED,
                       original_size=3_100_000_000, compressed_size=1_050_000_000),
        ]
        controller.active_manager.get_results.return_value = completed_tasks
        controller.on_encoding_done()

        assert controller.encoding_in_progress is False

    def test_start_pause_resume_cancel_flow(
        self, controller, mock_win, mock_strategy_panel,
        sample_snapshots, sample_folder_paths,
    ):
        """场景：完整的操作流程 — 启动 -> 暂停 -> 恢复 -> 取消"""
        # 手动注入 mock manager 以跳过 threading/WorkerManager 创建
        mock_mgr = MagicMock()
        mock_mgr.is_paused = False
        controller.active_manager = mock_mgr
        controller.encoding_in_progress = True

        # 暂停
        controller.toggle_pause()
        mock_mgr.pause.assert_called_once()
        assert mock_win.set_status.call_args[0][0] == "编码已暂停（等待当前任务完成）"

        # 恢复到非暂停状态
        mock_mgr.is_paused = True
        mock_mgr.reset_mock()
        mock_win.set_status.reset_mock()
        controller.toggle_pause()
        mock_mgr.resume.assert_called_once()
        assert mock_win.set_status.call_args[0][0] == "编码已恢复"

        # 取消
        mock_mgr.reset_mock()
        mock_win.set_status.reset_mock()
        controller.cancel()
        mock_mgr.cancel.assert_called_once()
        assert mock_win.set_status.call_args[0][0] == "正在取消编码..."
