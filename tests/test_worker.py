"""Worker 管理器测试"""
import pytest
import time
import threading
from leanreel.executor.worker import WorkerManager, EncodeTask, TaskStatus


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
