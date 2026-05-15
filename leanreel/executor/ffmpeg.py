"""FFmpeg 执行器 — 编码编排，I/O 分离、临时文件管理、Dolby Vision 流程"""
import hashlib
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Optional

from leanreel.core.pipeline import build_pipeline
from leanreel.data.models import TaskStatus
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


class FFmpegExecutor:
    """Executor adapter used by WorkerManager. 支持 Slotted Pipeline 阶段化编码。"""

    def __init__(self, progress_callback=None, temp_dir: Optional[str] = None):
        self.progress_callback = progress_callback
        self.temp_dir = temp_dir
        self._cancel_event = threading.Event()

    def _get_temp_dir(self) -> Path:
        if self.temp_dir:
            d = Path(self.temp_dir)
        else:
            d = Path(tempfile.gettempdir()) / "LeanReel"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def cancel(self):
        """终止正在运行的 ffmpeg 子进程。"""
        self._cancel_event.set()

    def _emit_progress(self, task):
        """触发外部进度回调（如果已设置）。"""
        if self.progress_callback:
            self.progress_callback(task)

    def encode(self, task) -> None:
        if task.snapshot is None or task.strategy is None:
            raise ValueError("EncodeTask requires snapshot and strategy")

        plan = build_pipeline(task)
        task.pipeline_plan = plan

        final_output = Path(task.output_path)
        temp_dir = self._get_temp_dir()
        output_key = hashlib.sha1(str(final_output.resolve()).encode("utf-8")).hexdigest()[:12]
        task_temp_dir = temp_dir / output_key
        task_temp_dir.mkdir(parents=True, exist_ok=True)
        temp_output = task_temp_dir / final_output.name
        rpu_file: Optional[Path] = None
        dv_output: Optional[Path] = None

        snap = task.snapshot
        strategy = task.strategy

        # 每次 encode 前重置取消事件
        self._cancel_event.clear()

        # 如果临时文件已存在，先删除（避免 -n 跳过）
        if temp_output.exists():
            temp_output.unlink()

        try:
            for i, stage in enumerate(plan.stages):
                if self._cancel_event.is_set():
                    plan.skip_remaining(i)
                    break

                plan.mark_stage_running(i)
                task.current_stage_index = i
                task.progress = plan.compute_overall_progress()
                self._emit_progress(task)

                slot_id = stage.slot.slot_id

                if slot_id == "prepare":
                    plan.mark_stage_completed(i)

                elif slot_id == "copy_in":
                    # 对于本地文件，"复制入"阶段验证源文件存在性
                    source_path = Path(task.input_path)
                    if source_path.exists():
                        stage.internal_progress = 1.0
                    plan.mark_stage_completed(i)

                elif slot_id == "extract_rpu":
                    rpu_file = task_temp_dir / f"{final_output.stem}.rpu"
                    if rpu_file.exists():
                        rpu_file.unlink()
                    if not DoviTool.extract_rpu(task.input_path, str(rpu_file)):
                        raise RuntimeError(f"Dolby Vision RPU extraction failed: {task.file_name}")
                    plan.mark_stage_completed(i)

                elif slot_id == "transcode":
                    cmd = FFmpegBuilder.build(snap, strategy, task.input_path, str(temp_output))
                    duration = snap.duration_seconds if snap else 0.0

                    def _transcode_progress(line: str):
                        if "time=" not in line or duration <= 0:
                            return
                        try:
                            time_str = line.split("time=")[1].split()[0]
                            parts = time_str.split(":")
                            hours = int(parts[0])
                            minutes = int(parts[1])
                            seconds = float(parts[2])
                            elapsed = hours * 3600 + minutes * 60 + seconds
                            pct = min(elapsed / duration, 1.0)
                            stage.internal_progress = pct
                            task.progress = plan.compute_overall_progress()
                            self._emit_progress(task)
                        except (ValueError, IndexError):
                            pass

                    exit_code, stderr_tail = run_ffmpeg(
                        cmd,
                        progress_callback=_transcode_progress,
                        cancel_event=self._cancel_event,
                    )
                    if exit_code != 0:
                        if temp_output.exists():
                            temp_output.unlink()
                        raise RuntimeError(f"FFmpeg failed ({exit_code}): {task.file_name}\n{stderr_tail.strip()}")
                    plan.mark_stage_completed(i)

                elif slot_id == "inject_rpu":
                    dv_output = task_temp_dir / f"{final_output.stem}_dv{final_output.suffix}"
                    if dv_output.exists():
                        dv_output.unlink()
                    if not DoviTool.inject_rpu(str(temp_output), str(rpu_file), str(dv_output)):
                        raise RuntimeError(f"Dolby Vision RPU injection failed: {task.file_name}")
                    if temp_output.exists():
                        temp_output.unlink()
                    temp_output = dv_output
                    plan.mark_stage_completed(i)

                elif slot_id == "move_out":
                    # 如果临时输出和目标路径相同（temp_dir == 目标目录），跳过移动
                    if temp_output.resolve() == final_output.resolve():
                        if final_output.exists():
                            task.compressed_size = final_output.stat().st_size
                    else:
                        final_output.parent.mkdir(parents=True, exist_ok=True)
                        if final_output.exists():
                            final_output.unlink()
                        shutil.move(str(temp_output), str(final_output))
                        if final_output.exists():
                            task.compressed_size = final_output.stat().st_size
                    plan.mark_stage_completed(i)

                task.progress = plan.compute_overall_progress()
                self._emit_progress(task)

        except Exception as e:
            current_idx = task.current_stage_index
            if current_idx >= 0:
                plan.mark_stage_failed(current_idx, str(e))
                plan.skip_remaining(current_idx + 1)
            task.status = TaskStatus.FAILED
            task.error_message = str(e)
            task.progress = plan.compute_overall_progress()
            self._emit_progress(task)
            # 清理临时输出文件
            if temp_output.exists():
                temp_output.unlink()
            if dv_output and dv_output.exists() and dv_output != temp_output:
                try:
                    dv_output.unlink()
                except OSError:
                    pass
            raise
        finally:
            if rpu_file and rpu_file.exists():
                rpu_file.unlink()
            try:
                task_temp_dir.rmdir()
            except OSError:
                pass
