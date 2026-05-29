"""FFmpeg 执行器 — 编码编排、Dolby Vision 流程、审计双写"""
import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
import time as _time
from pathlib import Path
from typing import Optional

from leanreel.services.pipeline import build_pipeline
from leanreel.domain.models import TaskStatus
from leanreel.executor.dovi import DoviTool
from leanreel.executor.ffmpeg_builder import (
    FFmpegBuilder,
    get_ffmpeg_path,
    run_ffmpeg,
    set_ffmpeg_path,
)

# 向后兼容：重新导出 ffmpeg_builder 中的公共 API
__all__ = [
    "FFmpegBuilder",
    "FFmpegExecutor",
    "get_ffmpeg_path",
    "run_ffmpeg",
    "set_ffmpeg_path",
]


def _delete_source_file(filepath: str):
    """删除源文件，失败静默处理。"""
    try:
        p = Path(filepath)
        if p.exists():
            p.chmod(0o777)
            p.unlink()
    except Exception:
        pass


def _task_duration_seconds(task) -> int:
    if getattr(task, "started_at", 0) and getattr(task, "completed_at", 0):
        return max(0, int(task.completed_at - task.started_at))
    if getattr(task, "started_at", 0):
        return max(0, int(_time.time() - task.started_at))
    return 0


def _update_runtime(task, *, status: str, progress: float, stage: str) -> None:
    db = getattr(task, "_db", None)
    history_id = getattr(task, "history_id", 0)
    if db is None or not history_id or not hasattr(db, "update_compression_runtime"):
        return
    try:
        db.update_compression_runtime(
            history_id,
            status=status,
            progress=progress,
            stage=stage,
            duration_seconds=_task_duration_seconds(task),
        )
    except Exception:
        pass


def _finish_task(
    task,
    *,
    status: str,
    progress: float,
    error_message: str = "",
    sidecar_path: str = "",
    source_deleted: int | None = None,
    ffmpeg_command: str = "",
) -> None:
    db = getattr(task, "_db", None)
    history_id = getattr(task, "history_id", 0)
    if db is None or not history_id or not hasattr(db, "finish_compression"):
        return
    try:
        original = max(int(getattr(task, "original_size", 0) or 0), 1)
        compressed = int(getattr(task, "compressed_size", 0) or 0)
        savings_pct = round((original - compressed) / original * 100, 1) if compressed else 0.0
        db.finish_compression(
            history_id,
            status=status,
            progress=progress,
            duration_seconds=_task_duration_seconds(task),
            compressed_size=compressed,
            output_size_bytes=compressed,
            savings_pct=savings_pct,
            error_message=error_message,
            sidecar_path=sidecar_path,
            source_deleted=source_deleted,
            ffmpeg_command=ffmpeg_command,
        )
    except Exception:
        pass


class CancelledError(Exception):
    """编码被用户取消。"""


class FFmpegExecutor:
    """Executor adapter used by WorkerManager. 支持 Slotted Pipeline 阶段化编码。"""

    def __init__(self, progress_callback=None, temp_dir: Optional[str] = None,
                 db=None, delete_source: bool = False):
        self.progress_callback = progress_callback
        self.temp_dir = temp_dir
        self._delete_source = delete_source
        self._db = db
        self._cancel_events: dict[str, threading.Event] = {}
        self._cancel_lock = threading.Lock()

    def _get_temp_dir(self) -> Path:
        if self.temp_dir:
            d = Path(self.temp_dir)
        else:
            d = Path(tempfile.gettempdir()) / "LeanReel"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def cancel(self):
        """终止所有正在运行的编码。"""
        with self._cancel_lock:
            for event in list(self._cancel_events.values()):
                event.set()

    def _emit_progress(self, task):
        """触发外部进度回调（如果已设置）。"""
        if self.progress_callback:
            self.progress_callback(task)

    def encode(self, task) -> None:
        if task.snapshot is None or task.strategy is None:
            raise ValueError("EncodeTask requires snapshot and strategy")

        plan = build_pipeline(task)
        task.pipeline_plan = plan
        task._db = self._db
        task._delete_source = self._delete_source

        final_output = Path(task.output_path)
        temp_dir = self._get_temp_dir()
        output_key = hashlib.sha1(str(final_output.resolve()).encode("utf-8")).hexdigest()[:12]
        task_temp_dir = temp_dir / output_key
        task_temp_dir.mkdir(parents=True, exist_ok=True)
        staging_output = final_output.with_name(f"{final_output.stem}.staging{final_output.suffix}")
        rpu_file: Optional[Path] = None
        dv_output: Optional[Path] = None

        snap = task.snapshot
        strategy = task.strategy

        # 每次 encode 创建独立的取消事件（防止多 worker 相互干扰）
        cancel_event = threading.Event()
        with self._cancel_lock:
            self._cancel_events[task.input_path] = cancel_event

        # 如果暂存文件已存在，先删除
        if staging_output.exists():
            staging_output.unlink()

        try:
            for i, stage in enumerate(plan.stages):
                if cancel_event.is_set():
                    raise CancelledError()

                plan.mark_stage_running(i)
                task.current_stage_index = i
                task.progress = plan.compute_overall_progress()
                self._emit_progress(task)

                stage_label = stage.slot.display_name
                _update_runtime(
                    task,
                    status=TaskStatus.RUNNING.value,
                    progress=float(task.progress),
                    stage=stage_label,
                )

                slot_id = stage.slot.slot_id

                if slot_id == "prepare":
                    plan.mark_stage_completed(i)

                elif slot_id == "extract_rpu":
                    rpu_file = task_temp_dir / f"{final_output.stem}.rpu"
                    if rpu_file.exists():
                        try:
                            rpu_file.unlink()
                        except OSError:
                            pass
                    extract_source = task.input_path
                    ok, stderr = DoviTool.extract_rpu(extract_source, str(rpu_file))
                    if not ok:
                        raise RuntimeError(f"Dolby Vision RPU extraction failed: {task.file_name}\n{stderr[:500]}")
                    plan.mark_stage_completed(i)

                elif slot_id == "transcode":
                    # 使用本地副本进行编码（如果已复制到本地，否则直接用源文件）
                    encode_input = task.input_path

                    cmd = FFmpegBuilder.build(snap, strategy, encode_input, str(staging_output))
                    # Store for audit
                    task._ffmpeg_command = list(cmd)
                    duration = snap.duration_seconds if snap else 0.0
                    input_size = snap.size_bytes if snap else 0

                    # 估算输出大小（取预计节省范围的中间值）
                    savings_str = getattr(strategy, "estimated_savings", "") if strategy else ""
                    savings_mid = 0.35  # 默认估算 35%
                    if savings_str:
                        import re
                        nums = re.findall(r"\d+", savings_str)
                        if len(nums) >= 2:
                            savings_mid = (int(nums[0]) + int(nums[1])) / 200.0
                    estimated_output = int(input_size * (1 - savings_mid)) if input_size > 0 else 0

                    # 混合进度源：优先 time= 解析，回退到输出文件大小
                    last_history_update = 0.0
                    def _transcode_progress(line: str):
                        nonlocal duration, last_history_update
                        if "time=" in line and duration > 0:
                            try:
                                time_str = line.split("time=")[1].split()[0]
                                parts = time_str.split(":")
                                hours = int(parts[0])
                                minutes = int(parts[1])
                                seconds = float(parts[2])
                                elapsed = hours * 3600 + minutes * 60 + seconds
                                pct = min(elapsed / duration, 0.98)
                                stage.internal_progress = max(stage.internal_progress, pct)
                            except (ValueError, IndexError):
                                pass
                        elif staging_output.exists() and estimated_output > 0:
                            # 回退：输出文件大小 / 估算输出大小
                            try:
                                pct = min(staging_output.stat().st_size / estimated_output, 0.98)
                                stage.internal_progress = max(stage.internal_progress, pct)
                            except OSError:
                                pass
                        task.progress = plan.compute_overall_progress()
                        self._emit_progress(task)
                        now = _time.time()
                        if now - last_history_update >= 1.0:
                            last_history_update = now
                            _update_runtime(
                                task,
                                status=TaskStatus.RUNNING.value,
                                progress=float(task.progress),
                                stage="转码",
                            )

                    exit_code, stderr_tail = run_ffmpeg(
                        cmd,
                        progress_callback=_transcode_progress,
                        cancel_event=cancel_event,
                    )
                    if exit_code != 0:
                        if staging_output.exists():
                            staging_output.unlink()
                        raise RuntimeError(f"FFmpeg failed ({exit_code}): {task.file_name}\n{stderr_tail.strip()}")
                    plan.mark_stage_completed(i)

                elif slot_id == "inject_rpu":
                    dv_output = Path(str(staging_output) + ".dv_tmp")
                    if dv_output.exists():
                        try:
                            dv_output.unlink()
                        except OSError:
                            pass
                    ok, stderr = DoviTool.inject_rpu(str(staging_output), str(rpu_file), str(dv_output))
                    if not ok:
                        raise RuntimeError(f"Dolby Vision RPU injection failed: {task.file_name}\n{stderr[:500]}")
                    staging_output.unlink()
                    os.replace(str(dv_output), str(staging_output))
                    plan.mark_stage_completed(i)

                elif slot_id == "move_out":
                    if staging_output.exists():
                        task.compressed_size = staging_output.stat().st_size
                    plan.mark_stage_completed(i)

                task.progress = plan.compute_overall_progress()
                self._emit_progress(task)

            # ── 体积反超检查（写完输出后再判断） ──
            if staging_output.exists():
                task.compressed_size = staging_output.stat().st_size

            if task.compressed_size > 0 and task.original_size > 0 and task.compressed_size >= task.original_size:
                if staging_output.exists():
                    staging_output.unlink()
                task.compressed_size = task.original_size
                if plan.stages:
                    for s in plan.stages:
                        if s.slot.slot_id == "move_out":
                            s.detail = "跳过（输出 ≥ 原体积）"
                            break
                task._output_discarded = True
                task.status = TaskStatus.DISCARDED
                task.error_message = "输出体积不小于源文件，已丢弃"
                task.completed_at = task.completed_at or _time.time()
                _finish_task(
                    task,
                    status=TaskStatus.DISCARDED.value,
                    progress=100.0,
                    error_message=task.error_message,
                )
            else:
                # 原子提交：将暂存文件移动到最终位置
                final_output.parent.mkdir(parents=True, exist_ok=True)
                os.replace(str(staging_output), str(final_output))

            # ── 审计双写（仅当输出未被丢弃） ──
            if not getattr(task, "_output_discarded", False):
                try:
                    from leanreel.services.audit import build_audit, write_sidecar
                    cmd = getattr(task, "_ffmpeg_command", [])
                    cmd_str = subprocess.list2cmdline(cmd) if cmd else ""
                    audit = build_audit(
                        task=task,
                        ffmpeg_command=cmd,
                    )
                    db = getattr(task, "_db", None)
                    audit.db_record_id = getattr(task, "history_id", 0) or 0
                    sidecar_path = write_sidecar(audit)
                    if db is not None and sidecar_path:
                        _finish_task(
                            task,
                            status=TaskStatus.COMPLETED.value,
                            progress=100.0,
                            sidecar_path=sidecar_path,
                            ffmpeg_command=cmd_str,
                        )

                    if getattr(task, "_delete_source", False) and 0 < task.compressed_size < task.original_size:
                        _delete_source_file(task.input_path)
                        _finish_task(task, status=TaskStatus.COMPLETED.value, progress=100.0, source_deleted=1, ffmpeg_command=cmd_str)
                except Exception:
                    import traceback
                    traceback.print_exc()

        except CancelledError:
            current_idx = task.current_stage_index
            if current_idx >= 0:
                plan.skip_remaining(current_idx)
            task.completed_at = task.completed_at or _time.time()
            _finish_task(
                task,
                status=TaskStatus.CANCELLED.value,
                progress=max(0.0, min(99.0, float(task.progress or 0))),
                error_message="用户取消",
            )
            task.status = TaskStatus.CANCELLED
            task.progress = plan.compute_overall_progress()
            self._emit_progress(task)
            if staging_output.exists():
                staging_output.unlink()
            raise
        except Exception as e:
            current_idx = task.current_stage_index
            if current_idx >= 0:
                plan.mark_stage_failed(current_idx, str(e))
                plan.skip_remaining(current_idx + 1)
            task.status = TaskStatus.FAILED
            task.error_message = str(e)
            task.completed_at = task.completed_at or _time.time()
            _finish_task(
                task,
                status=TaskStatus.FAILED.value,
                progress=max(0.0, min(99.0, float(task.progress or 0))),
                error_message=str(e),
            )
            task.progress = plan.compute_overall_progress()
            self._emit_progress(task)
            if staging_output.exists():
                staging_output.unlink()
            if dv_output and dv_output.exists() and dv_output != staging_output:
                try:
                    dv_output.unlink()
                except OSError:
                    pass
            raise
        finally:
            with self._cancel_lock:
                self._cancel_events.pop(task.input_path, None)
            if rpu_file and rpu_file.exists():
                try:
                    rpu_file.unlink()
                except OSError:
                    pass
            shutil.rmtree(str(task_temp_dir), ignore_errors=True)
