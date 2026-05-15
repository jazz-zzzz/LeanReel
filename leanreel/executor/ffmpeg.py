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


class CancelledError(Exception):
    """编码被用户取消。"""


class FFmpegExecutor:
    """Executor adapter used by WorkerManager. 支持 Slotted Pipeline 阶段化编码。"""

    def __init__(self, progress_callback=None, temp_dir: Optional[str] = None):
        self.progress_callback = progress_callback
        self.temp_dir = temp_dir
        self._active_cancel_event: Optional[threading.Event] = None

    def _get_temp_dir(self) -> Path:
        if self.temp_dir:
            d = Path(self.temp_dir)
        else:
            d = Path(tempfile.gettempdir()) / "LeanReel"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def cancel(self):
        """终止正在运行的编码。只影响当前活跃的 encode() 调用。"""
        if self._active_cancel_event:
            self._active_cancel_event.set()

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
        local_input: Optional[Path] = None  # 复制到本地的源文件副本
        rpu_file: Optional[Path] = None
        dv_output: Optional[Path] = None

        snap = task.snapshot
        strategy = task.strategy

        # 每次 encode 创建独立的取消事件（防止多 worker 相互干扰）
        cancel_event = threading.Event()
        self._active_cancel_event = cancel_event

        # 如果临时文件已存在，先删除
        if temp_output.exists():
            temp_output.unlink()

        try:
            for i, stage in enumerate(plan.stages):
                if cancel_event.is_set():
                    raise CancelledError()

                plan.mark_stage_running(i)
                task.current_stage_index = i
                task.progress = plan.compute_overall_progress()
                self._emit_progress(task)

                slot_id = stage.slot.slot_id

                if slot_id == "prepare":
                    plan.mark_stage_completed(i)

                elif slot_id == "copy_in":
                    source_path = Path(task.input_path)
                    if source_path.exists():
                        total_bytes = source_path.stat().st_size
                        local_input = task_temp_dir / source_path.name
                        bytes_copied = 0

                        with open(source_path, "rb") as src, open(local_input, "wb") as dst:
                            while chunk := src.read(8 * 1024 * 1024):
                                if cancel_event.is_set():
                                    break
                                dst.write(chunk)
                                bytes_copied += len(chunk)
                                if total_bytes > 0:
                                    stage.internal_progress = bytes_copied / total_bytes
                                    task.progress = plan.compute_overall_progress()
                                    self._emit_progress(task)

                    if cancel_event.is_set():
                        raise CancelledError()
                    plan.mark_stage_completed(i)

                elif slot_id == "extract_rpu":
                    rpu_file = task_temp_dir / f"{final_output.stem}.rpu"
                    if rpu_file.exists():
                        rpu_file.unlink()
                    # 使用本地副本（如果已复制到本地）
                    extract_source = str(local_input) if local_input else task.input_path
                    if not DoviTool.extract_rpu(extract_source, str(rpu_file)):
                        raise RuntimeError(f"Dolby Vision RPU extraction failed: {task.file_name}")
                    plan.mark_stage_completed(i)

                elif slot_id == "transcode":
                    # 使用本地副本进行编码（如果已复制到本地，否则直接用源文件）
                    encode_input = str(local_input) if local_input else task.input_path

                    # 自适应 CQ：低比特率源 → 提高 CQ 避免体积反超
                    cq = strategy.video.cq if hasattr(strategy, "video") else 26
                    if snap and snap.size_bytes > 0 and snap.duration_seconds > 0:
                        src_mbps = (snap.size_bytes * 8) / (snap.duration_seconds * 1_000_000)
                        pixels = max(1, (snap.video_width or 1920) * (snap.video_height or 1080))
                        bpp = src_mbps * 1_000_000 / pixels
                        if bpp < 2.5:
                            cq = min(cq + 8, 35)   # 非常压缩 → 大幅提高 CQ
                        elif bpp < 5.0:
                            cq = min(cq + 4, 32)   # 较压缩
                        elif bpp < 8.0:
                            cq = min(cq + 2, 30)   # 轻微压缩
                        # bpp >= 8.0 → 保持原 CQ（高质量源，如 remux）

                    import copy
                    adjusted = copy.deepcopy(strategy)
                    adjusted.video.cq = cq
                    cmd = FFmpegBuilder.build(snap, adjusted, encode_input, str(temp_output))
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
                    def _transcode_progress(line: str):
                        nonlocal duration
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
                        elif temp_output.exists() and estimated_output > 0:
                            # 回退：输出文件大小 / 估算输出大小
                            try:
                                pct = min(temp_output.stat().st_size / estimated_output, 0.98)
                                stage.internal_progress = max(stage.internal_progress, pct)
                            except OSError:
                                pass
                        task.progress = plan.compute_overall_progress()
                        self._emit_progress(task)

                    exit_code, stderr_tail = run_ffmpeg(
                        cmd,
                        progress_callback=_transcode_progress,
                        cancel_event=cancel_event,
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
                    # 压缩后体积变大 → 丢弃结果，保留原文件
                    if task.compressed_size > 0 and task.original_size > 0 and task.compressed_size >= task.original_size:
                        if final_output.exists():
                            final_output.unlink()
                        task.compressed_size = task.original_size
                        stage.detail = f"跳过（输出 ≥ 原体积）"
                    plan.mark_stage_completed(i)

                task.progress = plan.compute_overall_progress()
                self._emit_progress(task)

        except CancelledError:
            current_idx = task.current_stage_index
            if current_idx >= 0:
                plan.skip_remaining(current_idx)
            task.status = TaskStatus.CANCELLED
            task.progress = plan.compute_overall_progress()
            self._emit_progress(task)
            raise
        except Exception as e:
            current_idx = task.current_stage_index
            if current_idx >= 0:
                plan.mark_stage_failed(current_idx, str(e))
                plan.skip_remaining(current_idx + 1)
            task.status = TaskStatus.FAILED
            task.error_message = str(e)
            task.progress = plan.compute_overall_progress()
            self._emit_progress(task)
            if temp_output.exists():
                temp_output.unlink()
            if dv_output and dv_output.exists() and dv_output != temp_output:
                try:
                    dv_output.unlink()
                except OSError:
                    pass
            raise
        finally:
            self._active_cancel_event = None
            if rpu_file and rpu_file.exists():
                rpu_file.unlink()
            if local_input and local_input.exists():
                try:
                    local_input.unlink()
                except OSError:
                    pass
            try:
                task_temp_dir.rmdir()
            except OSError:
                pass
