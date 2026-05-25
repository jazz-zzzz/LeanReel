"""FFmpeg 命令构建 — 纯命令生成，不涉及 I/O"""
from dataclasses import dataclass
import subprocess
import threading

from leanreel.domain.models import FileSnapshot, HDRType
from leanreel.domain.models import Strategy
from leanreel.executor.resources import bundled_resource_path
from leanreel.executor._config import _config

_VERSION_TIMEOUT = 5
_HDR_TYPES = {HDRType.HDR10, HDRType.HDR10P, HDRType.DV_P5, HDRType.DV_P7, HDRType.DV_P8}
_NVENC_RC_VALUES = {"vbr", "cbr", "constqp"}
_NVENC_PRESETS = {"p1", "p2", "p3", "p4", "p5", "p6", "p7"}
_X265_PRESETS = {
    "ultrafast", "superfast", "veryfast", "faster", "fast",
    "medium", "slow", "slower", "veryslow", "placebo",
}


@dataclass(frozen=True)
class EncoderSpec:
    name: str
    kind: str
    quality_option: str = ""
    quality_min: int = 0
    quality_max: int = 0
    default_preset: str = ""
    default_pix_fmt: str = ""
    supports_hdr10plus: bool = False


ENCODER_SPECS = {
    "copy": EncoderSpec(name="copy", kind="copy"),
    "libx265": EncoderSpec(
        name="libx265",
        kind="x265",
        quality_option="crf",
        quality_min=0,
        quality_max=51,
        default_preset="slow",
        default_pix_fmt="yuv420p10le",
        supports_hdr10plus=True,
    ),
    "av1_nvenc": EncoderSpec(
        name="av1_nvenc",
        kind="nvenc",
        quality_option="cq",
        quality_min=0,
        quality_max=63,
        default_preset="p4",
    ),
    "hevc_nvenc": EncoderSpec(
        name="hevc_nvenc",
        kind="nvenc",
        quality_option="cq",
        quality_min=0,
        quality_max=51,
        default_preset="p4",
        supports_hdr10plus=True,
    ),
    "h264_nvenc": EncoderSpec(
        name="h264_nvenc",
        kind="nvenc",
        quality_option="cq",
        quality_min=0,
        quality_max=51,
        default_preset="p4",
    ),
}


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


def _append_hdr_color_metadata(cmd: list[str]) -> None:
    cmd.extend([
        "-color_primaries", "bt2020",
        "-color_trc", "smpte2084",
        "-colorspace", "bt2020nc",
    ])


def _supports_hdr10plus_flag(encoder: str) -> bool:
    return ENCODER_SPECS[encoder].supports_hdr10plus


def _clamp_int(value: object, minimum: int, maximum: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = minimum
    return max(minimum, min(maximum, n))


def _encoder_spec(encoder: str) -> EncoderSpec:
    if encoder not in ENCODER_SPECS:
        raise ValueError(f"Unsupported video encoder: {encoder}")
    return ENCODER_SPECS[encoder]


def _nvenc_preset(spec: EncoderSpec, value: str) -> str:
    preset = (value or "").lower()
    return preset if preset in _NVENC_PRESETS else spec.default_preset


def _nvenc_rc(value: str) -> str:
    rc = (value or "").lower()
    return rc if rc in _NVENC_RC_VALUES else "vbr"


def _nvenc_cq(spec: EncoderSpec, value: object) -> int:
    return _clamp_int(value, spec.quality_min, spec.quality_max)


def _x265_preset(spec: EncoderSpec, value: str) -> str:
    preset = (value or "").lower()
    return preset if preset in _X265_PRESETS else spec.default_preset


def _x265_crf(spec: EncoderSpec, value: object) -> int:
    return _clamp_int(value, spec.quality_min, spec.quality_max)


def _x265_pix_fmt(spec: EncoderSpec, value: str) -> str:
    return value or spec.default_pix_fmt


class FFmpegBuilder:
    """构建 FFmpeg 命令行参数 — 完整无损流保留"""

    @staticmethod
    def build(snapshot: FileSnapshot, strategy: Strategy,
              input_path: str, output_path: str) -> list[str]:
        v = strategy.video
        spec = _encoder_spec(v.encoder)
        encoder = spec.name

        cmd = [get_ffmpeg_path(), "-nostdin", "-y"]
        if spec.kind == "nvenc":
            cmd.extend(["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"])
        cmd.extend([
            "-thread_queue_size", "16384",
            "-buffer_size", "134217728",
            "-i", input_path,
        ])

        # --- 视频流：大写 V 排除内嵌封面 mjpeg ---
        cmd.extend(["-map", "0:V"])

        if spec.kind == "copy":
            cmd.extend(["-c:V", "copy"])
        elif spec.kind == "nvenc":
            cq = _nvenc_cq(spec, v.cq)
            cmd.extend([
                "-c:V", encoder,
                "-preset", _nvenc_preset(spec, v.nv_preset),
                "-rc", _nvenc_rc(v.rc),
                "-cq", str(cq),
            ])
            if encoder != "av1_nvenc":
                cmd.extend([
                    "-spatial-aq", "1",
                    "-temporal-aq", "1",
                    "-aq-strength", "8",
                ])
            if snapshot.hdr_type in _HDR_TYPES:
                _append_hdr_color_metadata(cmd)
                if snapshot.hdr_type == HDRType.HDR10P and _supports_hdr10plus_flag(encoder):
                    cmd.append("-hdr10+")
        else:
            cmd.extend([
                "-c:V", encoder,
                "-crf", str(_x265_crf(spec, v.crf)),
                "-preset", _x265_preset(spec, v.preset),
                "-pix_fmt", _x265_pix_fmt(spec, v.pix_fmt),
            ])
            if v.x265_params:
                cmd.extend(["-x265-params", v.x265_params])
            if snapshot.hdr_type in _HDR_TYPES:
                _append_hdr_color_metadata(cmd)
                if snapshot.hdr_type == HDRType.HDR10P and _supports_hdr10plus_flag(encoder):
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
                cmd.extend(["-map", "0:a?", "-c:a", "copy"])
        else:
            cmd.extend(["-map", "0:a?", "-c:a", "copy"])

        # --- 字幕 ---
        sub_mode = strategy.subtitle.mode
        subtitle_tracks = snapshot.subtitle_tracks
        if sub_mode == "remove_all":
            pass
        elif sub_mode == "keep_all":
            cmd.extend(["-map", "0:s?", "-c:s", "copy"])
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
        if progress_callback and "time=" in line:
            progress_callback(line)
        if cancel_event and cancel_event.is_set():
            proc.terminate()
            break
    exit_code = proc.wait()
    all_stderr = "".join(stderr_lines)
    if exit_code != 0:
        return exit_code, all_stderr
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
