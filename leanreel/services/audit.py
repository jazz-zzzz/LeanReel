"""压缩审计服务 — 构建、写入、读取 sidecar 文件"""
from __future__ import annotations

import datetime
import json
import platform
from pathlib import Path
from typing import Optional

from leanreel.domain.models import CompressionAudit


_LEANREEL_VERSION = "0.1.0"


def build_audit(
    task,
    ffmpeg_command: list[str],
    adaptive_cq_original: int = 0,
    adaptive_cq_adjusted: int = 0,
    adaptive_cq_reason: str = "",
) -> CompressionAudit:
    """从编码任务和策略构建完整审计快照。"""
    snap = task.snapshot
    strategy = task.strategy

    original = task.original_size if task.original_size > 0 else 1
    savings_bytes = task.original_size - task.compressed_size if task.compressed_size > 0 else 0
    savings_pct = round(savings_bytes / original * 100, 1) if original > 0 else 0.0

    video = getattr(strategy, "video", None)
    audio = getattr(strategy, "audio", None)
    sub = getattr(strategy, "subtitle", None)

    # 源文件音轨信息
    source_audio = []
    for i, a in enumerate(getattr(snap, "audio_tracks", []) or []):
        source_audio.append({
            "index": i,
            "codec": getattr(a, "codec", ""),
            "channels": getattr(a, "channels", 0),
            "language": getattr(a, "language", ""),
            "title": getattr(a, "title", ""),
            "is_commentary": getattr(a, "is_commentary", False),
        })

    # 源文件字幕信息
    source_subtitle = []
    for i, s in enumerate(getattr(snap, "subtitle_tracks", []) or []):
        source_subtitle.append({
            "index": i,
            "codec": getattr(s, "codec", ""),
            "language": getattr(s, "language", ""),
            "title": getattr(s, "title", ""),
            "is_forced": getattr(s, "is_forced", False),
        })

    # HDR 类型
    hdr_type = getattr(snap, "hdr_type", None)
    if hdr_type is not None and hasattr(hdr_type, "value"):
        source_hdr = hdr_type.value
    else:
        source_hdr = "SDR"

    # 计算实际持续时间
    started = getattr(task, "started_at", 0) or 0
    completed = getattr(task, "completed_at", 0) or 0
    if completed and started:
        task_duration = round(completed - started, 1)
    else:
        task_duration = 0.0

    # 状态
    task_status = getattr(task, "status", None)
    if task_status is not None and hasattr(task_status, "value"):
        status_str = task_status.value
    else:
        status_str = str(task_status) if task_status else "pending"

    return CompressionAudit(
        library_folder_id=getattr(snap, "library_folder_id", 0),
        relative_path=getattr(snap, "relative_path", ""),
        source_path=task.input_path,
        source_size_bytes=getattr(snap, "size_bytes", 0),
        source_mtime=getattr(snap, "file_mtime", 0.0),
        source_codec=getattr(snap, "video_codec", ""),
        source_width=getattr(snap, "video_width", 0),
        source_height=getattr(snap, "video_height", 0),
        source_pix_fmt=getattr(snap, "pix_fmt", ""),
        source_bitrate_bps=getattr(snap, "bitrate_bps", 0),
        source_duration_seconds=getattr(snap, "duration_seconds", 0.0),
        source_frame_rate=getattr(snap, "frame_rate", ""),
        source_hdr=source_hdr,
        source_audio=source_audio,
        source_subtitle=source_subtitle,

        output_path=task.output_path,
        output_size_bytes=task.compressed_size,
        savings_bytes=savings_bytes,
        savings_pct=savings_pct,

        strategy_name=getattr(strategy, "name", task.strategy_name),
        encoder=getattr(video, "encoder", "") if video else "",
        crf=getattr(video, "crf", 0) if video else 0,
        cq=getattr(video, "cq", 0) if video else 0,
        preset=getattr(video, "preset", "") if video else "",
        pix_fmt=getattr(video, "pix_fmt", "") if video else "",
        audio_mode=getattr(audio, "mode", "") if audio else "",
        sub_mode=getattr(sub, "mode", "") if sub else "",

        ffmpeg_command=list(ffmpeg_command),
        adaptive_cq_original=adaptive_cq_original,
        adaptive_cq_adjusted=adaptive_cq_adjusted,
        adaptive_cq_reason=adaptive_cq_reason,
        started_at=_iso(task.started_at) if started else "",
        completed_at=_iso(task.completed_at) if completed else "",
        duration_seconds=task_duration,
        status=status_str,

        ffmpeg_version=_ffmpeg_version(),
        dovi_tool_version=_dovi_version(),
        leanreel_version=_LEANREEL_VERSION,
        platform=platform.platform(),
    )


def _iso(timestamp: float) -> str:
    if not timestamp:
        return ""
    return datetime.datetime.fromtimestamp(timestamp).isoformat()


def _ffmpeg_version() -> str:
    from leanreel.executor.ffmpeg_builder import get_ffmpeg_version
    return get_ffmpeg_version()


def _dovi_version() -> str:
    from leanreel.executor.dovi import get_dovi_tool_version
    return get_dovi_tool_version()


def write_sidecar(audit: CompressionAudit) -> str:
    """将审计快照写入 sidecar JSON 文件。返回写入的路径。失败时返回空字符串。"""
    sidecar_path = _sidecar_path(audit.output_path)
    data = _audit_to_dict(audit)
    try:
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        sidecar_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(sidecar_path)
    except Exception:
        import traceback
        traceback.print_exc()
        return ""


def read_sidecar(filepath: str) -> Optional[CompressionAudit]:
    """从 sidecar JSON 文件读取审计快照。失败返回 None。"""
    try:
        data = json.loads(Path(filepath).read_text(encoding="utf-8"))
        return _dict_to_audit(data)
    except Exception:
        return None


def find_sidecars_for_source(source_path: str) -> list[str]:
    """在源文件同目录下查找对应的 sidecar 文件。"""
    source = Path(source_path)
    pattern = f"{source.stem}_zcompressed.*.leanreel.json"
    return sorted(
        str(p) for p in source.parent.glob(pattern)
        if p.is_file()
    )


def _sidecar_path(output_path: str) -> Path:
    return Path(output_path + ".leanreel.json")


def _audit_to_dict(audit: CompressionAudit) -> dict:
    result = {
        "version": "1.0",
        "tool": f"LeanReel {audit.leanreel_version}",
        "source": {
            "path": audit.source_path,
            "file_name": Path(audit.source_path).name if audit.source_path else "",
            "size_bytes": audit.source_size_bytes,
            "mtime": audit.source_mtime,
            "video": {
                "codec": audit.source_codec,
                "width": audit.source_width,
                "height": audit.source_height,
                "pix_fmt": audit.source_pix_fmt,
                "bitrate_bps": audit.source_bitrate_bps,
                "duration_seconds": audit.source_duration_seconds,
                "frame_rate": audit.source_frame_rate,
                "hdr_type": audit.source_hdr,
                "color_primaries": audit.source_color_primaries,
                "color_transfer": audit.source_color_transfer,
                "color_space": audit.source_color_space,
            },
            "audio": audit.source_audio,
            "subtitle": audit.source_subtitle,
        },
        "output": {
            "path": audit.output_path,
            "size_bytes": audit.output_size_bytes,
            "savings_bytes": audit.savings_bytes,
            "savings_pct": audit.savings_pct,
        },
        "strategy": {
            "name": audit.strategy_name,
            "video": {
                "encoder": audit.encoder,
                "crf": audit.crf or audit.cq,
                "preset": audit.preset,
                "pix_fmt": audit.pix_fmt,
            },
            "audio": {"mode": audit.audio_mode},
            "subtitle": {"mode": audit.sub_mode},
        },
        "execution": {
            "command": audit.ffmpeg_command,
            "adaptive_cq": {
                "original": audit.adaptive_cq_original,
                "adjusted": audit.adaptive_cq_adjusted,
                "reason": audit.adaptive_cq_reason,
            } if audit.adaptive_cq_original else {},
            "started_at": audit.started_at,
            "completed_at": audit.completed_at,
            "duration_seconds": audit.duration_seconds,
            "status": audit.status,
        },
        "environment": {
            "ffmpeg_version": audit.ffmpeg_version,
            "dovi_tool_version": audit.dovi_tool_version,
            "leanreel_version": audit.leanreel_version,
            "platform": audit.platform,
        },
    }
    return result


def _dict_to_audit(data: dict) -> CompressionAudit:
    src = data.get("source", {})
    src_video = src.get("video", {})
    out = data.get("output", {})
    strat = data.get("strategy", {})
    strat_video = strat.get("video", {})
    exe = data.get("execution", {})
    adaptive_cq = exe.get("adaptive_cq", {})
    env = data.get("environment", {})

    # 策略视频参数中 crf/cq 二选一
    cq_val = strat_video.get("crf", strat_video.get("cq", 0))

    return CompressionAudit(
        source_path=src.get("path", ""),
        source_size_bytes=src.get("size_bytes", 0),
        source_mtime=src.get("mtime", 0.0),
        source_codec=src_video.get("codec", ""),
        source_width=src_video.get("width", 0),
        source_height=src_video.get("height", 0),
        source_pix_fmt=src_video.get("pix_fmt", ""),
        source_bitrate_bps=src_video.get("bitrate_bps", 0),
        source_duration_seconds=src_video.get("duration_seconds", 0.0),
        source_frame_rate=src_video.get("frame_rate", ""),
        source_hdr=src_video.get("hdr_type", "SDR"),
        source_audio=src.get("audio", []),
        source_subtitle=src.get("subtitle", []),
        output_path=out.get("path", ""),
        output_size_bytes=out.get("size_bytes", 0),
        savings_bytes=out.get("savings_bytes", 0),
        savings_pct=out.get("savings_pct", 0.0),
        strategy_name=strat.get("name", ""),
        encoder=strat_video.get("encoder", ""),
        cq=cq_val,
        preset=strat_video.get("preset", ""),
        pix_fmt=strat_video.get("pix_fmt", ""),
        audio_mode=strat.get("audio", {}).get("mode", ""),
        sub_mode=strat.get("subtitle", {}).get("mode", ""),
        ffmpeg_command=exe.get("command", []),
        adaptive_cq_original=adaptive_cq.get("original", 0) if adaptive_cq else 0,
        adaptive_cq_adjusted=adaptive_cq.get("adjusted", 0) if adaptive_cq else 0,
        adaptive_cq_reason=adaptive_cq.get("reason", "") if adaptive_cq else "",
        started_at=exe.get("started_at", ""),
        completed_at=exe.get("completed_at", ""),
        duration_seconds=exe.get("duration_seconds", 0.0),
        status=exe.get("status", "pending"),
        ffmpeg_version=env.get("ffmpeg_version", ""),
        dovi_tool_version=env.get("dovi_tool_version", ""),
        leanreel_version=env.get("leanreel_version", ""),
        platform=env.get("platform", ""),
    )
