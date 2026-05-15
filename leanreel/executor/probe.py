"""FFprobe 封装 — 提取视频文件元数据"""
import json
import math
import subprocess
import os
from pathlib import Path
from typing import Optional

from leanreel.data.models import FileSnapshot, AudioTrack, SubtitleTrack, HDRType
from leanreel.executor.resources import bundled_resource_path

# FFprobe 二进制路径（打包时替换为相对路径）
_FFPROBE_PATH = None


def get_ffprobe_path() -> str:
    """获取 ffprobe 路径，优先使用内置版本"""
    global _FFPROBE_PATH
    if _FFPROBE_PATH:
        return _FFPROBE_PATH
    # 开发环境：从资源目录找
    builtin = bundled_resource_path("ffmpeg", "ffprobe.exe")
    if builtin.exists():
        return str(builtin)
    return "ffprobe"


def set_ffprobe_path(path: str):
    global _FFPROBE_PATH
    _FFPROBE_PATH = path


def detect_hdr_type_from_ffprobe(video_stream: dict) -> HDRType:
    """根据 FFprobe 视频流信息判断 HDR 类型

    优先通过 side_data_list 检测 DV（需要 ffprobe 支持 -show_side_data），
    其次通过 color_transfer/color_primaries 检测 HDR10/HDR10+，
    最后通过编码标签和像素格式做推断。
    """
    side_data = video_stream.get("side_data_list", [])
    dv_info = next((s for s in side_data if s.get("side_data_type", "").startswith("Dolby Vision")), None)
    if dv_info:
        profile = int(dv_info.get("dv_profile", 7))
        if profile == 5:
            return HDRType.DV_P5
        elif profile == 7:
            return HDRType.DV_P7
        elif profile == 8:
            return HDRType.DV_P8

    color_tr = video_stream.get("color_transfer", "")
    color_pr = video_stream.get("color_primaries", "")

    if color_tr == "smpte2084" and color_pr == "bt2020":
        for sd in side_data:
            if sd.get("side_data_type") == "HDR Dynamic Metadata":
                return HDRType.HDR10P
        return HDRType.HDR10

    # 回退推断：无 side_data / color_primaries 时通过编码标签和像素格式检测
    pix_fmt = video_stream.get("pix_fmt", "")
    codec = video_stream.get("codec_name", "")
    codec_tag = video_stream.get("codec_tag_string", "")
    profile_str = str(video_stream.get("profile", ""))

    if codec_tag and any(tag in codec_tag.lower() for tag in ("dvh", "dvhe", "dav1")):
        return HDRType.DV_P8

    if color_tr or color_pr:
        return HDRType.SDR

    if "10" in profile_str or "10" in pix_fmt:
        if codec in ("hevc", "h265"):
            return HDRType.HDR10

    return HDRType.SDR


def parse_ffprobe_output(data: dict, library_folder_id: int) -> FileSnapshot:
    """解析 FFprobe JSON 输出为 FileSnapshot"""
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    video = next((s for s in streams if s["codec_type"] == "video"), {})
    audio_streams = [s for s in streams if s["codec_type"] == "audio"]
    subtitle_streams = [s for s in streams if s["codec_type"] == "subtitle"]

    filename = os.path.basename(fmt.get("filename", ""))
    size = max(0, int(fmt.get("size", 0)))
    duration = float(fmt.get("duration", 0))
    if math.isnan(duration) or math.isinf(duration):
        duration = 0.0
    bitrate = int(fmt.get("bit_rate", 0))
    if bitrate < 0:
        bitrate = 0

    hdr_type = detect_hdr_type_from_ffprobe(video)

    audio_tracks = [
        AudioTrack(
            codec=s.get("codec_name", ""),
            channels=s.get("channels", 0),
            language=(s.get("tags") or {}).get("language", "und"),
            title=(s.get("tags") or {}).get("title", ""),
            is_commentary=bool(s.get("disposition", {}).get("comment", 0)),
        )
        for s in audio_streams
    ]

    subtitle_tracks = [
        SubtitleTrack(
            codec=s.get("codec_name", ""),
            language=(s.get("tags") or {}).get("language", "und"),
            title=(s.get("tags") or {}).get("title", ""),
            is_forced=bool(s.get("disposition", {}).get("forced", 0)),
        )
        for s in subtitle_streams
    ]

    return FileSnapshot(
        library_folder_id=library_folder_id,
        relative_path=fmt.get("filename", ""),
        file_name=filename,
        size_bytes=size,
        video_codec=video.get("codec_name", ""),
        video_width=video.get("width", 0),
        video_height=video.get("height", 0),
        hdr_type=hdr_type,
        audio_tracks=audio_tracks,
        subtitle_tracks=subtitle_tracks,
        duration_seconds=duration,
        bitrate_bps=bitrate,
    )


class FFprobeRunner:
    """FFprobe 命令行调用器"""

    def __init__(self, ffprobe_path: Optional[str] = None):
        self.ffprobe = ffprobe_path or get_ffprobe_path()

    def probe(self, file_path: str, library_folder_id: int = 0) -> FileSnapshot:
        """对单个文件运行 FFprobe，返回 FileSnapshot

        先尝试带 ``-show_side_data``（检测 Dolby Vision profile 需要），
        如果失败则回退到不带 ``-show_side_data`` 的基本探测。
        限制 probesize/analyzeduration 避免 NAS 上过度读取。
        """
        file_path = os.path.normpath(file_path)
        base_cmd = [
            self.ffprobe,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            "-probesize", "2M",
            "-analyzeduration", "500000",
        ]

        data = None
        for extra_flags in (["-show_side_data"], []):
            result = subprocess.run(base_cmd + extra_flags + [file_path],
                                   capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=30)
            if result.returncode == 0:
                try:
                    data = json.loads(result.stdout)
                    if data.get("streams"):
                        break
                except json.JSONDecodeError:
                    continue

        if data is None:
            raise RuntimeError(
                f"FFprobe 失败：无法解析输出"
            )

        return parse_ffprobe_output(data, library_folder_id)
