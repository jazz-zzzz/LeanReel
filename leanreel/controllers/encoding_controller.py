"""编码控制器 — 管理编码生命周期（开始/暂停/取消/完成）"""
import threading
import uuid
from pathlib import Path

from leanreel.controllers.events import TaskProgressEvent
from leanreel.domain.models import Strategy, is_protected_source, TaskStatus
from leanreel.executor.ffmpeg import FFmpegExecutor
from leanreel.executor.worker import EncodeTask, WorkerManager
from leanreel.ui_text import UI_TEXT


def make_output_path(source: Path, strategy: Strategy | None = None) -> Path:
    suffix = ".mkv" if getattr(getattr(strategy, "video", None), "encoder", "") == "av1_nvenc" else source.suffix
    return source.with_name(f"{source.stem}_zcompressed{suffix}")


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
            output_path=str(make_output_path(input_path, selected_strategy)),
            strategy_name=selected_strategy.name,
            strategy=selected_strategy,
            snapshot=snap,
            original_size=snap.size_bytes,
        ))
    return tasks


def attach_history_records(db, tasks: list, batch_id: str) -> None:
    if db is None:
        return
    for task in tasks:
        snap = task.snapshot
        fsid = getattr(snap, "id", 0) or 0
        if not fsid:
            rows = db.execute(
                "SELECT id FROM file_snapshot WHERE library_folder_id=? AND relative_path=?",
                [snap.library_folder_id, snap.relative_path],
            )
            fsid = rows[0]["id"] if rows else 0
        video = getattr(task.strategy, "video", None)
        audio = getattr(task.strategy, "audio", None)
        subtitle = getattr(task.strategy, "subtitle", None)
        task.batch_id = batch_id
        task.history_id = db.create_compression_record(
            file_snapshot_id=fsid,
            batch_id=batch_id,
            strategy_name=task.strategy_name or getattr(task.strategy, "name", ""),
            original_size=task.original_size,
            output_path=task.output_path,
            encoder=getattr(video, "encoder", ""),
            cq_value=getattr(video, "cq", 0) or getattr(video, "crf", 0),
            preset=getattr(video, "nv_preset", "") or getattr(video, "preset", ""),
            pix_fmt=getattr(video, "pix_fmt", ""),
            audio_mode=getattr(audio, "mode", ""),
            sub_mode=getattr(subtitle, "mode", ""),
        )


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
        self._progress_sequence = 0

    def _emit_task_progress(self, task):
        self._progress_sequence += 1
        event = TaskProgressEvent.from_task(task, sequence=self._progress_sequence)
        if hasattr(self._notifier, "task_progress"):
            self._notifier.task_progress.emit(event)
        if hasattr(self._notifier, "task_updated"):
            self._notifier.task_updated.emit(task)

    def start(self, snapshots, folder_paths, strategy_overrides):
        """启动编码。返回 True 表示编码已成功启动。"""
        with self._encode_lock:
            if self.encoding_in_progress:
                self._win.set_status(UI_TEXT.ENCODE_IN_PROGRESS)
                return False
            self.encoding_in_progress = True

        try:
            default_strategy = self._strategy_panel.current_preset_strategy or self._strategy_panel.current_strategy
            if default_strategy is None:
                self._win.set_status(UI_TEXT.NO_STRATEGY)
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
                self._win.set_status(UI_TEXT.NO_ENCODABLE_FILES)
                with self._encode_lock:
                    self.encoding_in_progress = False
                return False

            try:
                batch_id = uuid.uuid4().hex
                attach_history_records(self._db, tasks, batch_id)
                self._active_batch_id = batch_id
            except Exception:
                self._win.set_status("创建历史记录失败")
                with self._encode_lock:
                    self.encoding_in_progress = False
                return False

            self._queue_panel.clear_tasks()
            for task in tasks:
                self._queue_panel.add_task_row(task)

            self._win.show_queue()
            self.active_manager = WorkerManager(
                FFmpegExecutor(
                    progress_callback=self._emit_task_progress,
                    delete_source=self._strategy_panel.delete_source,
                    db=self._db,
                ),
                self._strategy_panel.worker_count,
                progress_callback=self._emit_task_progress,
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
            self._win.set_status(UI_TEXT.error(e))
            return False

    def toggle_pause(self):
        """切换暂停/继续状态。"""
        if self.active_manager is None:
            return
        if self.active_manager.is_paused:
            self.active_manager.resume()
            self._win.set_status(UI_TEXT.ENCODE_RESUMED)
            self._queue_panel.pause_btn.setText(UI_TEXT.PAUSE)
        else:
            self.active_manager.pause()
            self._win.set_status(UI_TEXT.ENCODE_PAUSED)
            self._queue_panel.pause_btn.setText(UI_TEXT.RESUME)

    def cancel(self, _idx=None):
        """取消当前编码。"""
        if self.active_manager is None:
            return
        self.active_manager.cancel()
        self._win.set_status(UI_TEXT.ENCODE_CANCELING)

    def on_task_updated(self, task):
        """单个任务状态更新时由 WorkerManager 回调触发。"""
        self._queue_panel.update_task_row(task)
        if self.active_manager is None:
            return
        progress = self.active_manager.get_progress()
        self._queue_panel.update_progress(progress)

        # 构建包含阶段信息的状态栏消息
        stage = getattr(task, 'current_stage', None)
        stage_name = getattr(task, "stage_name", "")
        if (stage or stage_name) and task.status == TaskStatus.RUNNING:
            if stage:
                stage_text = stage.slot.display_name
                if stage.progress_type.value == "estimated":
                    stage_text += f" {stage.internal_progress:.0%}"
            else:
                stage_text = stage_name
                if getattr(task, "stage_progress", 0.0):
                    stage_text += f" {task.stage_progress:.0%}"
            self._win.set_status(
                UI_TEXT.encoding_stage_status(
                    stage_text=stage_text,
                    file_name=task.file_name,
                    done=progress["completed"] + progress["failed"],
                    total=progress["total"],
                    failed=progress["failed"],
                )
            )
        else:
            self._win.set_status(
                UI_TEXT.encoding_progress(
                    progress["completed"] + progress["failed"],
                    progress["total"],
                )
            )

    def on_encoding_done(self):
        """所有编码任务完成后由后台线程触发。"""
        with self._encode_lock:
            self.encoding_in_progress = False
        if self.active_manager is None:
            return
        results = self.active_manager.get_results()
        done, failed, cancelled = compute_encode_summary(results)
        self._win.set_status(UI_TEXT.encoding_summary(done, failed, cancelled))
