"""FFmpeg 执行器 — 编码编排，I/O 分离、临时文件管理、Dolby Vision 流程"""
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Optional

from leanreel.executor.dovi import needs_dovi_processing, DoviTool
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
    """Executor adapter used by WorkerManager. 支持 I/O 分离（先输出到本地临时目录，完成后移至目标路径）。"""

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

    def _make_progress_cb(self, task):
        """创建进度回调：解析 ffmpeg stderr 中的 time= 行，更新 task.progress。"""
        duration = task.snapshot.duration_seconds if task.snapshot else 0.0

        def _on_progress(line: str):
            if "time=" not in line:
                return
            try:
                time_str = line.split("time=")[1].split()[0]
                parts = time_str.split(":")
                hours = int(parts[0])
                minutes = int(parts[1])
                seconds = float(parts[2])
                elapsed = hours * 3600 + minutes * 60 + seconds
                if duration > 0:
                    task.progress = min(elapsed / duration, 1.0)
            except (ValueError, IndexError):
                pass
            if self.progress_callback:
                self.progress_callback(task)

        return _on_progress

    def encode(self, task) -> None:
        if task.snapshot is None or task.strategy is None:
            raise ValueError("EncodeTask requires snapshot and strategy")

        final_output = Path(task.output_path)
        temp_dir = self._get_temp_dir()
        temp_output = temp_dir / final_output.name
        rpu_file: Optional[Path] = None
        dv_output: Optional[Path] = None

        # 每次 encode 前重置取消事件
        self._cancel_event.clear()

        # 如果临时文件已存在，先删除（避免 -n 跳过）
        if temp_output.exists():
            temp_output.unlink()

        dv_mode = needs_dovi_processing(task.snapshot, task.strategy)

        try:
            if dv_mode:
                rpu_file = temp_dir / f"{final_output.stem}.rpu"
                if rpu_file.exists():
                    rpu_file.unlink()
                if not DoviTool.extract_rpu(task.input_path, str(rpu_file)):
                    raise RuntimeError(f"Dolby Vision RPU extraction failed: {task.file_name}")

            cmd = FFmpegBuilder.build(
                task.snapshot,
                task.strategy,
                task.input_path,
                str(temp_output),
            )
            exit_code, stderr_tail = run_ffmpeg(
                cmd,
                progress_callback=self._make_progress_cb(task),
                cancel_event=self._cancel_event,
            )
            if exit_code != 0:
                if temp_output.exists():
                    temp_output.unlink()
                raise RuntimeError(f"FFmpeg failed ({exit_code}): {task.file_name}\n{stderr_tail.strip()}")

            if dv_mode and rpu_file and rpu_file.exists():
                dv_output = temp_dir / f"{final_output.stem}_dv{final_output.suffix}"
                if dv_output.exists():
                    dv_output.unlink()
                if not DoviTool.inject_rpu(str(temp_output), str(rpu_file), str(dv_output)):
                    raise RuntimeError(f"Dolby Vision RPU injection failed: {task.file_name}")
                temp_output.unlink()
                temp_output = dv_output

            # 如果临时输出和目标路径相同（temp_dir == 目标目录），跳过移动
            if temp_output.resolve() == final_output.resolve():
                return

            # 确保目标目录存在
            final_output.parent.mkdir(parents=True, exist_ok=True)

            # 如果目标已存在，先删除（WorkerManager 已处理 skip 逻辑，此处为兜底）
            if final_output.exists():
                final_output.unlink()

            shutil.move(str(temp_output), str(final_output))
        except Exception:
            if temp_output.exists():
                temp_output.unlink()
            # Issue 4: 清理 inject_rpu 失败时残留的 dv_output
            if dv_output and dv_output.exists():
                dv_output.unlink()
            raise
        finally:
            if rpu_file and rpu_file.exists():
                rpu_file.unlink()
