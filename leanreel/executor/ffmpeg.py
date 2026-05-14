"""FFmpeg 命令构建 — 根据策略和文件元数据生成编码命令"""
import subprocess
import os
from pathlib import Path
from typing import Optional

from leanreel.data.models import FileSnapshot, HDRType
from leanreel.core.strategy import Strategy

_FFMPEG_PATH = None


def get_ffmpeg_path() -> str:
    global _FFMPEG_PATH
    if _FFMPEG_PATH:
        return _FFMPEG_PATH
    builtin = Path(__file__).parent.parent / "resources" / "ffmpeg" / "ffmpeg.exe"
    if builtin.exists():
        return str(builtin)
    return "ffmpeg"


def set_ffmpeg_path(path: str):
    global _FFMPEG_PATH
    _FFMPEG_PATH = path


class FFmpegBuilder:
    """构建 FFmpeg 命令行参数"""

    @staticmethod
    def build(snapshot: FileSnapshot, strategy: Strategy,
              input_path: str, output_path: str) -> list[str]:
        cmd = [get_ffmpeg_path(), "-y", "-i", input_path]

        # 映射流
        cmd.extend(["-map", "0:v"])
        # 视频编码
        v = strategy.video
        if v.encoder == "copy":
            cmd.extend(["-c:v", "copy"])
        else:
            cmd.extend([
                "-c:v", v.encoder,
                "-crf", str(v.crf),
                "-preset", v.preset,
                "-pix_fmt", v.pix_fmt,
            ])
            # HDR 色彩参数
            if snapshot.hdr_type in (HDRType.HDR10, HDRType.HDR10P, HDRType.DV_P7, HDRType.DV_P8):
                cmd.extend([
                    "-color_primaries", "bt2020",
                    "-color_trc", "smpte2084",
                    "-colorspace", "bt2020nc",
                ])
                if snapshot.hdr_type == HDRType.HDR10P:
                    cmd.append("-hdr10+")

        # 音频 — 保持原样
        audio_mode = strategy.audio.mode
        if audio_mode == "keep_original":
            cmd.extend(["-map", "0:a", "-c:a", "copy"])
        elif audio_mode == "strip_commentary":
            # 需要外部传入要保留的音频流索引
            cmd.extend(["-map", "0:a:0", "-c:a", "copy"])

        # 字幕
        sub_mode = strategy.subtitle.mode
        if sub_mode in ("keep_chinese", "keep_chinese_english"):
            cmd.extend(["-map", "0:s?", "-c:s", "copy"])
        elif sub_mode == "keep_all":
            cmd.extend(["-map", "0:s", "-c:s", "copy"])

        cmd.append(output_path)
        return cmd


def run_ffmpeg(cmd: list[str], progress_callback=None) -> int:
    """执行 FFmpeg 命令，返回 exit code"""
    proc = subprocess.Popen(
        cmd, stderr=subprocess.PIPE, universal_newlines=True,
        encoding="utf-8", errors="replace"
    )
    for line in proc.stderr:
        if progress_callback and "time=" in line:
            progress_callback(line)
    return proc.wait()
