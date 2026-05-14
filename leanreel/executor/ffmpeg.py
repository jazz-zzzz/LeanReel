"""FFmpeg 命令构建 — 根据策略和文件元数据生成编码命令，支持 CPU 和 NVENC"""
import subprocess
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from leanreel.data.models import FileSnapshot, HDRType
from leanreel.core.strategy import Strategy
from leanreel.executor.resources import bundled_resource_path
from leanreel.executor.dovi import needs_dovi_processing, DoviTool

_FFMPEG_PATH = None


def get_ffmpeg_path() -> str:
    global _FFMPEG_PATH
    if _FFMPEG_PATH:
        return _FFMPEG_PATH
    builtin = bundled_resource_path("ffmpeg", "ffmpeg.exe")
    if builtin.exists():
        return str(builtin)
    return "ffmpeg"


def set_ffmpeg_path(path: str):
    global _FFMPEG_PATH
    _FFMPEG_PATH = path


class FFmpegBuilder:
    """构建 FFmpeg 命令行参数 — 完整无损流保留"""

    @staticmethod
    def build(snapshot: FileSnapshot, strategy: Strategy,
              input_path: str, output_path: str) -> list[str]:
        cmd = [get_ffmpeg_path(), "-n", "-i", input_path]

        v = strategy.video

        # --- 视频流：大写 V 排除内嵌封面 mjpeg ---
        cmd.extend(["-map", "0:V"])

        if v.encoder == "copy":
            cmd.extend(["-c:V", "copy"])
        elif v.is_gpu:
            cmd.extend([
                "-c:V", v.encoder,
                "-preset", v.nv_preset,
                "-rc", v.rc,
                "-cq", str(v.cq),
            ])
            if snapshot.hdr_type in (HDRType.HDR10, HDRType.HDR10P, HDRType.DV_P7, HDRType.DV_P8):
                cmd.extend([
                    "-color_primaries", "bt2020",
                    "-color_trc", "smpte2084",
                    "-colorspace", "bt2020nc",
                ])
                if snapshot.hdr_type == HDRType.HDR10P:
                    cmd.append("-hdr10+")
        else:
            cmd.extend([
                "-c:V", v.encoder,
                "-crf", str(v.crf),
                "-preset", v.preset,
                "-pix_fmt", v.pix_fmt,
            ])
            if snapshot.hdr_type in (HDRType.HDR10, HDRType.HDR10P, HDRType.DV_P7, HDRType.DV_P8):
                cmd.extend([
                    "-color_primaries", "bt2020",
                    "-color_trc", "smpte2084",
                    "-colorspace", "bt2020nc",
                ])
                if snapshot.hdr_type == HDRType.HDR10P:
                    cmd.append("-hdr10+")

        # --- 音频 ---
        audio_rule = strategy.audio
        audio_tracks = snapshot.audio_tracks
        if audio_tracks:
            remove_commentary = audio_rule.remove_commentary or audio_rule.mode == "strip_commentary"
            preferred = audio_rule.preferred_languages
            kept_audio = []
            for i, track in enumerate(audio_tracks):
                if remove_commentary and track.is_commentary:
                    continue
                if preferred and track.language not in preferred:
                    continue
                kept_audio.append(i)
            for idx in kept_audio:
                cmd.extend(["-map", f"0:a:{idx}"])
            if kept_audio:
                cmd.extend(["-c:a", "copy"])
        else:
            cmd.extend(["-map", "0:a", "-c:a", "copy"])

        # --- 字幕 ---
        sub_mode = strategy.subtitle.mode
        subtitle_tracks = snapshot.subtitle_tracks
        if sub_mode == "remove_all":
            pass
        elif sub_mode == "keep_all":
            cmd.extend(["-map", "0:s", "-c:s", "copy"])
        elif subtitle_tracks:
            if sub_mode == "keep_chinese":
                lang_whitelist = {"chi", "zho", "zh"}
            elif sub_mode == "keep_chinese_english":
                lang_whitelist = {"chi", "zho", "zh", "eng", "en"}
            else:
                lang_whitelist = None
            kept_subs = []
            for i, track in enumerate(subtitle_tracks):
                if lang_whitelist and track.language not in lang_whitelist:
                    continue
                kept_subs.append(i)
            for idx in kept_subs:
                cmd.extend(["-map", f"0:s:{idx}"])
            if kept_subs:
                cmd.extend(["-c:s", "copy"])
        else:
            cmd.extend(["-map", "0:s?", "-c:s", "copy"])

        # --- 附件（内嵌字体等）---
        cmd.extend(["-map", "0:t?", "-c:t", "copy"])

        # --- 数据轨 ---
        cmd.extend(["-map", "0:d?", "-c:d", "copy"])

        # --- 全局元数据和章节 ---
        cmd.extend(["-map_metadata", "0", "-map_chapters", "0"])

        # --- 未知轨兜底 ---
        cmd.append("-copy_unknown")

        cmd.append(output_path)
        return cmd


class FFmpegExecutor:
    """Executor adapter used by WorkerManager. 支持 I/O 分离（先输出到本地临时目录，完成后移至目标路径）。"""

    def __init__(self, progress_callback=None, temp_dir: Optional[str] = None):
        self.progress_callback = progress_callback
        self.temp_dir = temp_dir

    def _get_temp_dir(self) -> Path:
        if self.temp_dir:
            d = Path(self.temp_dir)
        else:
            d = Path(tempfile.gettempdir()) / "LeanReel"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def encode(self, task) -> None:
        if task.snapshot is None or task.strategy is None:
            raise ValueError("EncodeTask requires snapshot and strategy")

        final_output = Path(task.output_path)
        temp_dir = self._get_temp_dir()
        temp_output = temp_dir / final_output.name
        rpu_file: Optional[Path] = None

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
            exit_code, stderr_tail = run_ffmpeg(cmd, self.progress_callback)
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
            raise
        finally:
            if rpu_file and rpu_file.exists():
                rpu_file.unlink()


def run_ffmpeg(cmd: list[str], progress_callback=None) -> tuple[int, str]:
    """执行 FFmpeg 命令，返回 (exit_code, stderr_tail)"""
    proc = subprocess.Popen(
        cmd, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace"
    )
    stderr_lines: list[str] = []
    for line in proc.stderr:
        stderr_lines.append(line)
        if len(stderr_lines) > 50:
            stderr_lines.pop(0)
        if progress_callback and "time=" in line:
            progress_callback(line)
    exit_code = proc.wait()
    return exit_code, "".join(stderr_lines[-20:])
