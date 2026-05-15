"""数据模型 — 纯 dataclass，无外部依赖"""
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Optional


class HDRType(StrEnum):
    SDR = "SDR"
    HDR10 = "HDR10"
    HDR10P = "HDR10+"
    DV_P5 = "DV_P5"
    DV_P7 = "DV_P7"
    DV_P8 = "DV_P8"


class TaskStatus(StrEnum):
    """任务/压缩记录的统一状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AudioTrack:
    codec: str
    channels: int
    language: str
    title: str = ""
    is_commentary: bool = False


@dataclass
class SubtitleTrack:
    codec: str
    language: str
    title: str = ""
    is_forced: bool = False


@dataclass
class Library:
    id: Optional[int] = None
    name: str = ""


@dataclass
class LibraryFolder:
    id: Optional[int] = None
    library_id: int = 0
    path: str = ""


@dataclass
class FileSnapshot:
    id: Optional[int] = None
    library_folder_id: int = 0
    relative_path: str = ""
    file_name: str = ""
    size_bytes: int = 0
    video_codec: str = ""
    video_width: int = 0
    video_height: int = 0
    hdr_type: HDRType = HDRType.SDR
    audio_tracks: list[AudioTrack] = field(default_factory=list)
    subtitle_tracks: list[SubtitleTrack] = field(default_factory=list)
    duration_seconds: float = 0.0
    bitrate_bps: int = 0
    file_mtime: float = 0.0
    probe_ok: bool = False
    scanned_at: str = ""


@dataclass
class CompressionRecord:
    id: Optional[int] = None
    file_snapshot_id: int = 0
    strategy_name: str = ""
    original_size: int = 0
    compressed_size: int = 0
    status: TaskStatus = TaskStatus.PENDING
    duration_seconds: int = 0
    error_message: str = ""
    created_at: str = ""
