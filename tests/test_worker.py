"""Worker 管理器测试"""
import pytest
import time
import threading
from leanreel.executor.worker import WorkerManager, EncodeTask
from leanreel.data.models import TaskStatus


class FakeExecutor:
    """模拟编码执行"""
    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on or set()

    def encode(self, task: EncodeTask):
        self.calls.append(task.file_name)
        if task.file_name in self.fail_on:
            raise RuntimeError(f"模拟失败: {task.file_name}")
        time.sleep(0.01)
        return True


def test_worker_manager_runs_tasks():
    tasks = [
        EncodeTask(file_name="a.mkv", input_path="/t/a.mkv", output_path="/o/a.mkv"),
        EncodeTask(file_name="b.mkv", input_path="/t/b.mkv", output_path="/o/b.mkv"),
        EncodeTask(file_name="c.mkv", input_path="/t/c.mkv", output_path="/o/c.mkv"),
    ]
    executor = FakeExecutor()
    mgr = WorkerManager(executor, max_workers=2)
    mgr.start(tasks)
    assert mgr.total_tasks == 3
    assert len(executor.calls) == 3


def test_worker_manager_reports_completion():
    tasks = [EncodeTask(file_name="x.mkv", input_path="/t/x.mkv", output_path="/o/x.mkv")]
    executor = FakeExecutor()
    mgr = WorkerManager(executor, max_workers=1)
    mgr.start(tasks)
    assert mgr.completed_count == 1


def test_worker_manager_handles_failure():
    tasks = [
        EncodeTask(file_name="good.mkv", input_path="/t/good.mkv", output_path="/o/good.mkv"),
        EncodeTask(file_name="bad.mkv", input_path="/t/bad.mkv", output_path="/o/bad.mkv"),
    ]
    executor = FakeExecutor(fail_on={"bad.mkv"})
    mgr = WorkerManager(executor, max_workers=1)
    mgr.start(tasks)
    assert mgr.completed_count == 1
    assert mgr.failed_count == 1
    failed = [t for t in mgr.get_results() if t.status == TaskStatus.FAILED]
    assert len(failed) == 1
    assert failed[0].error_message


def test_pass_through_filter_no_encoding():
    """pass_through 任务直接标记为完成"""
    tasks = [
        EncodeTask(file_name="skip.mkv", input_path="/t/skip.mkv", output_path="/o/skip.mkv",
                   pass_through=True),
    ]
    executor = FakeExecutor()
    mgr = WorkerManager(executor, max_workers=1)
    mgr.start(tasks)
    assert mgr.completed_count == 1
    assert mgr.skipped_count == 1


def test_pause_resume_toggles_state():
    mgr = WorkerManager(FakeExecutor())
    assert not mgr.is_paused
    mgr.pause()
    assert mgr.is_paused
    mgr.resume()
    assert not mgr.is_paused


def test_cancel_sets_flag_and_marks_pending_cancelled():
    tasks = [
        EncodeTask(file_name="a.mkv", input_path="/t/a.mkv", output_path="/o/a.mkv"),
        EncodeTask(file_name="b.mkv", input_path="/t/b.mkv", output_path="/o/b.mkv"),
    ]
    mgr = WorkerManager(FakeExecutor())
    mgr._tasks = tasks  # 直接注入，不走 start()
    mgr.cancel()
    assert mgr.is_cancelled
    assert all(t.status == TaskStatus.CANCELLED for t in tasks)


def test_cancel_also_resumes_paused_state():
    mgr = WorkerManager(FakeExecutor())
    mgr.pause()
    assert mgr.is_paused
    mgr.cancel()
    assert not mgr.is_paused  # 取消时必须解除暂停，否则线程死锁


def test_get_progress_returns_correct_counts():
    tasks = [
        EncodeTask(file_name="a.mkv", input_path="/t/a.mkv", output_path="/o/a.mkv"),
        EncodeTask(file_name="b.mkv", input_path="/t/b.mkv", output_path="/o/b.mkv"),
        EncodeTask(file_name="c.mkv", input_path="/t/c.mkv", output_path="/o/c.mkv"),
    ]
    tasks[0].status = TaskStatus.COMPLETED
    tasks[1].status = TaskStatus.RUNNING
    tasks[2].status = TaskStatus.PENDING

    mgr = WorkerManager(FakeExecutor())
    mgr._tasks = tasks
    progress = mgr.get_progress()
    assert progress["total"] == 3
    assert progress["completed"] == 1  # COMPLETED + SKIPPED
    assert progress["failed"] == 0
    assert progress["pending"] == 2  # total - (completed_count + failed_count)
    assert progress["percentage"] == pytest.approx(100 / 3)


def test_get_progress_counts_cancelled_as_terminal():
    from leanreel.executor.worker import WorkerManager, EncodeTask
    from leanreel.data.models import TaskStatus

    manager = WorkerManager(FakeExecutor())
    manager._tasks = [
        EncodeTask(file_name="done.mkv", input_path="", output_path="", status=TaskStatus.COMPLETED),
        EncodeTask(file_name="cancelled.mkv", input_path="", output_path="", status=TaskStatus.CANCELLED),
        EncodeTask(file_name="pending.mkv", input_path="", output_path="", status=TaskStatus.PENDING),
    ]

    progress = manager.get_progress()

    assert progress["completed"] == 1
    assert progress["cancelled"] == 1
    assert progress["pending"] == 1
    assert progress["percentage"] == pytest.approx((2 / 3) * 100)
