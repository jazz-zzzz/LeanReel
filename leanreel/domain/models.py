"""数据模型 — 纯 dataclass，无外部依赖"""
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Optional


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
    probe_error: str = ""
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
    output_path: str = ""
    output_size_bytes: int = 0
    savings_pct: float = 0.0
    encoder: str = ""
    cq_value: int = 0
    preset: str = ""
    pix_fmt: str = ""
    audio_mode: str = ""
    sub_mode: str = ""
    ffmpeg_command: str = ""
    sidecar_path: str = ""
    leanreel_version: str = ""


@dataclass
class CompressionAudit:
    """编码完成后的完整审计快照 — DB 和 Sidecar 的唯一数据源"""
    library_folder_id: int = 0
    relative_path: str = ""
    source_path: str = ""
    source_size_bytes: int = 0
    source_mtime: float = 0.0
    source_codec: str = ""
    source_width: int = 0
    source_height: int = 0
    source_pix_fmt: str = ""
    source_bitrate_bps: int = 0
    source_duration_seconds: float = 0.0
    source_frame_rate: str = ""
    source_hdr: str = "SDR"
    source_color_primaries: str = ""
    source_color_transfer: str = ""
    source_color_space: str = ""
    source_audio: list[dict] = field(default_factory=list)
    source_subtitle: list[dict] = field(default_factory=list)

    output_path: str = ""
    output_size_bytes: int = 0
    savings_bytes: int = 0
    savings_pct: float = 0.0

    strategy_name: str = ""
    encoder: str = ""
    crf: int = 0
    cq: int = 0
    preset: str = ""
    pix_fmt: str = ""
    audio_mode: str = ""
    sub_mode: str = ""

    ffmpeg_command: list[str] = field(default_factory=list)
    adaptive_cq_original: int = 0
    adaptive_cq_adjusted: int = 0
    adaptive_cq_reason: str = ""
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: float = 0.0
    status: str = "pending"

    ffmpeg_version: str = ""
    dovi_tool_version: str = ""
    leanreel_version: str = ""
    platform: str = ""

    db_record_id: int = 0


# ── 策略模型 ──


@dataclass
class VideoRule:
    encoder: str = "libx265"
    crf: int = 20
    preset: str = "slow"
    pix_fmt: str = "yuv420p10le"
    gpu: bool = False
    nv_preset: str = "p1"
    rc: str = "vbr"
    cq: int = 23

    @property
    def is_gpu(self) -> bool:
        return self.gpu or self.encoder in ("hevc_nvenc", "h264_nvenc", "av1_nvenc")

    def to_dict(self) -> dict:
        return {
            "encoder": self.encoder, "crf": self.crf,
            "preset": self.preset, "pix_fmt": self.pix_fmt,
            "gpu": self.gpu, "nv_preset": self.nv_preset,
            "rc": self.rc, "cq": self.cq,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "VideoRule":
        return cls(
            encoder=d.get("encoder", "libx265"),
            crf=d.get("crf", 20),
            preset=d.get("preset", "slow"),
            pix_fmt=d.get("pix_fmt", "yuv420p10le"),
            gpu=d.get("gpu", False),
            nv_preset=d.get("nv_preset", "p1"),
            rc=d.get("rc", "vbr"),
            cq=d.get("cq", 23),
        )


@dataclass
class HDRRule:
    mode: str = "preserve_hdr10"
    dv_handling: str = "reinject_rpu"

    def to_dict(self) -> dict:
        return {"mode": self.mode, "dv_handling": self.dv_handling}

    @classmethod
    def from_dict(cls, d: dict) -> "HDRRule":
        return cls(mode=d.get("mode", "preserve_hdr10"),
                   dv_handling=d.get("dv_handling", "reinject_rpu"))


@dataclass
class AudioRule:
    mode: str = "keep_original"
    preferred_languages: list[str] = field(default_factory=lambda: ["chi", "zho", "eng"])
    remove_commentary: bool = True

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "preferred_languages": list(self.preferred_languages),
            "remove_commentary": self.remove_commentary,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AudioRule":
        return cls(
            mode=d.get("mode", "keep_original"),
            preferred_languages=list(d.get("preferred_languages", ["chi", "zho", "eng"])),
            remove_commentary=d.get("remove_commentary", True),
        )


@dataclass
class SubtitleRule:
    mode: str = "keep_chinese"

    def to_dict(self) -> dict:
        return {"mode": self.mode}

    @classmethod
    def from_dict(cls, d: dict) -> "SubtitleRule":
        return cls(mode=d.get("mode", "keep_chinese"))


@dataclass
class FilterRule:
    skip_x265: bool = False
    min_size_gb: Optional[float] = None
    only_remux: bool = False

    def to_dict(self) -> dict:
        return {"skip_x265": self.skip_x265, "min_size_gb": self.min_size_gb,
                "only_remux": self.only_remux}

    @classmethod
    def from_dict(cls, d: dict) -> "FilterRule":
        return cls(
            skip_x265=d.get("skip_x265", False),
            min_size_gb=d.get("min_size_gb"),
            only_remux=d.get("only_remux", False),
        )


@dataclass
class Strategy:
    name: str = ""
    description: str = ""
    is_preset: bool = False
    video: VideoRule = field(default_factory=VideoRule)
    hdr: HDRRule = field(default_factory=HDRRule)
    audio: AudioRule = field(default_factory=AudioRule)
    subtitle: SubtitleRule = field(default_factory=SubtitleRule)
    filters: FilterRule = field(default_factory=FilterRule)
    estimated_savings: str = ""
    quality_impact: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name, "description": self.description,
            "is_preset": self.is_preset,
            "video": self.video.to_dict(), "hdr": self.hdr.to_dict(),
            "audio": self.audio.to_dict(), "subtitle": self.subtitle.to_dict(),
            "filters": self.filters.to_dict(),
            "estimated_savings": self.estimated_savings,
            "quality_impact": self.quality_impact,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Strategy":
        return cls(
            name=d.get("name", ""), description=d.get("description", ""),
            is_preset=d.get("is_preset", False),
            video=VideoRule.from_dict(d.get("video", {})),
            hdr=HDRRule.from_dict(d.get("hdr", {})),
            audio=AudioRule.from_dict(d.get("audio", {})),
            subtitle=SubtitleRule.from_dict(d.get("subtitle", {})),
            filters=FilterRule.from_dict(d.get("filters", {})),
            estimated_savings=d.get("estimated_savings", ""),
            quality_impact=d.get("quality_impact", ""),
        )


# ── 行数据容器 ──


@dataclass
class MatchResult:
    """匹配结果 — 策略及其估算节省空间"""
    strategy: Any = None          # Strategy | str | None
    estimate: dict | None = None


@dataclass(frozen=True)
class FileDecisionDisplay:
    """预计算的单行显示状态"""
    status_key: str
    strategy_text: str
    result_text: str
    result_sort: int | float
    processable: bool
    tooltip: str


FileKey = tuple[int, str]
DirectoryKey = tuple[int, str]


@dataclass
class FileRow:
    """文件表格中的一行数据。

    ``key`` 是 (library_folder_id, relative_path) 元组，
    由 ``snap`` 自动推导。
    """
    snap: FileSnapshot
    match: MatchResult | None = field(default=None, repr=False)
    decision: FileDecisionDisplay | None = field(default=None, repr=False)

    @property
    def key(self) -> FileKey:
        return (int(self.snap.library_folder_id or 0), str(self.snap.relative_path))

    @property
    def directory_key(self) -> DirectoryKey:
        return (int(self.snap.library_folder_id or 0), self.folder_name)

    @property
    def folder_name(self) -> str:
        path = str(self.snap.relative_path).replace("\\", "/")
        parts = path.rsplit("/", 1)
        return parts[0] if len(parts) > 1 else "."


# ── 跳过原因判断（纯函数，仅依赖 domain 类型）──

PROTECTED_CODECS = {"hevc", "h265"}
PROTECTED_HDR_TYPES = {HDRType.HDR10, HDRType.HDR10P, HDRType.DV_P5, HDRType.DV_P7, HDRType.DV_P8}


def is_protected_source(snapshot: FileSnapshot) -> bool:
    """HEVC/H.265 和 HDR/Dolby Vision 被视为优质片源，默认完全不处理。"""
    return get_skip_reason(snapshot) is not None


def get_skip_reason(snapshot: FileSnapshot) -> str | None:
    codec = (snapshot.video_codec or "").lower()
    if codec in PROTECTED_CODECS:
        return "跳过：HEVC/H.265 片源"
    hdr_type = snapshot.hdr_type
    if hdr_type not in PROTECTED_HDR_TYPES:
        return None
    if hdr_type == HDRType.HDR10:
        return "跳过：HDR10 片源"
    if hdr_type == HDRType.HDR10P:
        return "跳过：HDR10+ 片源"
    return "跳过：Dolby Vision 片源"
