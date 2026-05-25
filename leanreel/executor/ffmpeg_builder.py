"""FFmpeg 命令构建 — 纯命令生成，不涉及 I/O"""
import subprocess
import threading

from leanreel.domain.models import FileSnapshot, HDRType
from leanreel.domain.models import Strategy
from leanreel.executor.resources import bundled_resource_path
from leanreel.executor._config import _config

_VERSION_TIMEOUT = 5


def get_ffmpeg_path() -> str:
    """获取 ffmpeg 路径，优先使用内置版本"""
    if _config.ffmpeg_path:
        return _config.ffmpeg_path
    builtin = bundled_resource_path("ffmpeg", "ffmpeg.exe")
    if builtin.exists():
        return str(builtin)
    return "ffmpeg"


def set_ffmpeg_path(path: str):
    _config.ffmpeg_path = path


class FFmpegBuilder:
    """构建 FFmpeg 命令行参数 — 完整无损流保留"""

    @staticmethod
    def build(snapshot: FileSnapshot, strategy: Strategy,
              input_path: str, output_path: str) -> list[str]:
        cmd = [get_ffmpeg_path(), "-nostdin", "-y", "-i", input_path]

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
                "-spatial_aq", "1",
                "-temporal_aq", "1",
                "-aq-strength", "8",
            ])
            if snapshot.hdr_type in (HDRType.HDR10, HDRType.HDR10P, HDRType.DV_P5, HDRType.DV_P7, HDRType.DV_P8):
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
            if snapshot.hdr_type in (HDRType.HDR10, HDRType.HDR10P, HDRType.DV_P5, HDRType.DV_P7, HDRType.DV_P8):
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
            filter_languages = audio_rule.mode == "strip_non_preferred"
            preferred = audio_rule.preferred_languages
            kept_audio = []
            for i, track in enumerate(audio_tracks):
                if remove_commentary and track.is_commentary:
                    continue
                if filter_languages and preferred and track.language not in preferred:
                    continue
                kept_audio.append(i)
            for idx in kept_audio:
                cmd.extend(["-map", f"0:a:{idx}"])
            if kept_audio:
                cmd.extend(["-c:a", "copy"])
            elif audio_rule.mode == "keep_original":
                cmd.extend(["-map", "0:a", "-c:a", "copy"])
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


def run_ffmpeg(cmd: list[str], progress_callback=None,
               cancel_event: threading.Event | None = None) -> tuple[int, str]:
    """执行 FFmpeg 命令，返回 (exit_code, stderr_tail)

    Args:
        cmd: FFmpeg 命令行参数列表
        progress_callback: 可选，收到含 "time=" 的 stderr 行时调用，传入原始行
        cancel_event: 可选，设置时终止子进程并返回
    """
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
        if cancel_event and cancel_event.is_set():
            proc.terminate()
            break
    exit_code = proc.wait()
    return exit_code, "".join(stderr_lines[-20:])


def get_ffmpeg_version() -> str:
    """返回 FFmpeg 版本字符串，例如 'ffmpeg version 7.1...'"""
    try:
        proc = subprocess.run(
            [get_ffmpeg_path(), "-version"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=_VERSION_TIMEOUT,
        )
        return proc.stdout.strip().split("\n")[0] if proc.returncode == 0 else "unknown"
    except Exception:
        return "unknown"
