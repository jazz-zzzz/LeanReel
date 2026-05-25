"""编码控制器 — 管理编码生命周期（开始/暂停/取消/完成）"""
import threading
from pathlib import Path

from leanreel.domain.models import Strategy, is_protected_source, TaskStatus
from leanreel.executor.ffmpeg import FFmpegExecutor
from leanreel.executor.worker import EncodeTask, WorkerManager


def make_output_path(source: Path) -> Path:
    return source.with_name(f"{source.stem}_zcompressed{source.suffix}")


def compute_encode_summary(results: list[EncodeTask]) -> tuple[int, int, int]:
    """从编码结果中统计完成数、失败数、取消数。返回 (done, failed, cancelled)。"""
    done = sum(1 for t in results if t.status == TaskStatus.COMPLETED)
    failed = sum(1 for t in results if t.status == TaskStatus.FAILED)
    cancelled = sum(1 for t in results if t.status == TaskStatus.CANCELLED)
    return done, failed, cancelled


def build_encode_tasks(
    snapshots,
    folder_paths: dict[int, str],
    strategy: Strategy,
    strategy_overrides: dict[tuple[int, str], Strategy] | None = None,
) -> list[EncodeTask]:
    tasks: list[EncodeTask] = []
    strategy_overrides = strategy_overrides or {}
    for snap in snapshots:
        if is_protected_source(snap):
            continue
        folder_path = folder_paths.get(snap.library_folder_id)
        if not folder_path:
            continue
        file_key = (int(snap.library_folder_id or 0), str(snap.relative_path))
        selected_strategy = strategy_overrides.get(file_key, strategy)
        input_path = Path(folder_path) / snap.relative_path
        tasks.append(EncodeTask(
            file_name=snap.file_name,
            input_path=str(input_path),
            output_path=str(make_output_path(input_path)),
            strategy_name=selected_strategy.name,
            strategy=selected_strategy,
            snapshot=snap,
            original_size=snap.size_bytes,
        ))
    return tasks


class EncodingController:
    """编码控制器 — 管理编码生命周期（开始/暂停/取消/完成）"""

    def __init__(self, strategy_panel, win, queue_panel, notifier, db=None):
        self._strategy_panel = strategy_panel
        self._win = win
        self._queue_panel = queue_panel
        self._notifier = notifier
        self._db = db
        self.active_manager: WorkerManager | None = None
        self.encoding_in_progress = False
        self._encode_lock = threading.Lock()

    def start(self, snapshots, folder_paths, strategy_overrides):
        """启动编码。返回 True 表示编码已成功启动。"""
        with self._encode_lock:
            if self.encoding_in_progress:
                self._win.set_status("编码正在进行中，请等待完成")
                return False
            self.encoding_in_progress = True

        try:
            default_strategy = self._strategy_panel.current_preset_strategy or self._strategy_panel.current_strategy
            if default_strategy is None:
                self._win.set_status("没有可用策略")
                with self._encode_lock:
                    self.encoding_in_progress = False
                return False

            tasks = build_encode_tasks(
                snapshots,
                folder_paths,
                default_strategy,
                strategy_overrides,
            )
            if not tasks:
                self._win.set_status("没有可压缩文件")
                with self._encode_lock:
                    self.encoding_in_progress = False
                return False

            self._queue_panel.clear_tasks()
            for task in tasks:
                self._queue_panel.add_task_row(task)

            self._win.show_queue()
            self.active_manager = WorkerManager(
                FFmpegExecutor(
                    temp_dir=self._strategy_panel.temp_dir,
                    progress_callback=lambda t: self._notifier.task_updated.emit(t),
                    sync_output=self._strategy_panel.sync_output,
                    keep_temp=self._strategy_panel.keep_temp,
                    delete_source=self._strategy_panel.delete_source,
                    db=self._db,
                ),
                self._strategy_panel.worker_count,
                progress_callback=lambda t: self._notifier.task_updated.emit(t),
            )

            def _run_encode():
                try:
                    self.active_manager.start(tasks)
                finally:
                    self._notifier.encoding_done.emit()

            t = threading.Thread(target=_run_encode, daemon=True)
            t.start()
            return True
        except Exception as e:
            with self._encode_lock:
                self.encoding_in_progress = False
            self._win.set_status(f"错误：{e}")
            return False

    def toggle_pause(self):
        """切换暂停/继续状态。"""
        if self.active_manager is None:
            return
        if self.active_manager.is_paused:
            self.active_manager.resume()
            self._win.set_status("编码已恢复")
            self._queue_panel.pause_btn.setText("暂停")
        else:
            self.active_manager.pause()
            self._win.set_status("编码已暂停（等待当前任务完成）")
            self._queue_panel.pause_btn.setText("继续")

    def cancel(self, _idx=None):
        """取消当前编码。"""
        if self.active_manager is None:
            return
        self.active_manager.cancel()
        self._win.set_status("正在取消编码...")

    def on_task_updated(self, task):
        """单个任务状态更新时由 WorkerManager 回调触发。"""
        self._queue_panel.update_task_row(task)
        if self.active_manager is None:
            return
        progress = self.active_manager.get_progress()
        self._queue_panel.update_progress(progress)

        # 构建包含阶段信息的状态栏消息
        stage = getattr(task, 'current_stage', None)
        if stage and task.status == TaskStatus.RUNNING:
            stage_text = stage.slot.display_name
            if stage.progress_type.value == "estimated":
                stage_text += f" {stage.internal_progress:.0%}"
            self._win.set_status(
                f"{stage_text} ｜ {task.file_name} ｜ "
                f"已处理 {progress['completed'] + progress['failed']}/{progress['total']}"
                + (f" ・ 失败 {progress['failed']}" if progress['failed'] else "")
            )
        else:
            self._win.set_status(
                f"编码中：{progress['completed'] + progress['failed']}/{progress['total']}"
            )

    def on_encoding_done(self):
        """所有编码任务完成后由后台线程触发。"""
        with self._encode_lock:
            self.encoding_in_progress = False
        if self.active_manager is None:
            return
        results = self.active_manager.get_results()
        done, failed, cancelled = compute_encode_summary(results)
        parts = [f"编码完成：成功 {done}"]
        if failed:
            parts.append(f"失败 {failed}")
        if cancelled:
            parts.append(f"取消 {cancelled}")
        self._win.set_status(" ｜ ".join(parts))
