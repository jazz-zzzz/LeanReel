"""Worker 管理器 — 并行编码任务调度"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import Optional, Callable
import time


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class EncodeTask:
    file_name: str
    input_path: str
    output_path: str
    pass_through: bool = False
    strategy_name: str = ""
    strategy: object | None = None
    snapshot: object | None = None
    status: TaskStatus = TaskStatus.PENDING
    progress: float = 0.0
    error_message: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    original_size: int = 0
    compressed_size: int = 0


class WorkerManager:
    """并行编码 Worker 管理器"""

    def __init__(self, executor, max_workers: int = 4,
                 progress_callback: Optional[Callable] = None):
        self.executor = executor
        self.max_workers = max_workers
        self.progress_callback = progress_callback
        self._tasks: list[EncodeTask] = []
        self._lock = Lock()
        self._cancelled = False

    @property
    def total_tasks(self) -> int:
        return len(self._tasks)

    @property
    def completed_count(self) -> int:
        return sum(1 for t in self._tasks if t.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED))

    @property
    def failed_count(self) -> int:
        return sum(1 for t in self._tasks if t.status == TaskStatus.FAILED)

    @property
    def skipped_count(self) -> int:
        return sum(1 for t in self._tasks if t.status == TaskStatus.SKIPPED)

    def start(self, tasks: list[EncodeTask]):
        self._tasks = tasks
        active = [t for t in tasks if not t.pass_through]
        skipped = [t for t in tasks if t.pass_through]
        for t in skipped:
            t.status = TaskStatus.SKIPPED
            t.completed_at = time.time()

        if not active:
            return

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {pool.submit(self._run_one, t): t for t in active}
            for future in as_completed(futures):
                if self._cancelled:
                    for f in futures:
                        f.cancel()
                    break
                try:
                    future.result()
                except Exception:
                    pass

    def _run_one(self, task: EncodeTask):
        with self._lock:
            if self._cancelled:
                return
            task.status = TaskStatus.RUNNING
            task.started_at = time.time()
            if self.progress_callback:
                self.progress_callback(task)

        try:
            self.executor.encode(task)
            with self._lock:
                task.status = TaskStatus.COMPLETED
        except Exception as e:
            with self._lock:
                task.status = TaskStatus.FAILED
                task.error_message = str(e)
        finally:
            task.completed_at = time.time()
            if self.progress_callback:
                self.progress_callback(task)

    def cancel(self):
        self._cancelled = True

    def get_results(self) -> list[EncodeTask]:
        return list(self._tasks)

    def get_progress(self) -> dict:
        completed = self.completed_count + self.failed_count
        return {
            "total": self.total_tasks,
            "completed": self.completed_count,
            "failed": self.failed_count,
            "skipped": self.skipped_count,
            "pending": self.total_tasks - completed,
            "percentage": (completed / max(self.total_tasks, 1)) * 100,
        }
