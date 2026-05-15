"""FFmpeg 命令构建 — 纯命令生成，不涉及 I/O"""
import subprocess

from leanreel.data.models import FileSnapshot, HDRType
from leanreel.core.strategy import Strategy
from leanreel.executor.resources import bundled_resource_path

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


def run_ffmpeg(cmd: list[str], progress_callback=None) -> tuple[int, str]:
    """执行 FFmpeg 命令，返回 (exit_code, stderr_tail)"""
    try:
        proc = subprocess.Popen(
            cmd, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace"
        )
    except FileNotFoundError:
        raise RuntimeError(f"FFmpeg executable not found in command: {' '.join(cmd)}")
    stderr_lines: list[str] = []
    for line in proc.stderr:
        stderr_lines.append(line)
        if len(stderr_lines) > 50:
            stderr_lines.pop(0)
        if progress_callback and "time=" in line:
            progress_callback(line)
    exit_code = proc.wait()
    return exit_code, "".join(stderr_lines[-20:])
