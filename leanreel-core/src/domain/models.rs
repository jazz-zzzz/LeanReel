use serde::{Deserialize, Serialize};

/// HDR type — uses serde tagged enum for clean JSON serialization.
/// DB storage still uses Python-compatible string format via manual conversion in db.rs.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(tag = "type")]
pub enum HdrType {
    #[default]
    Sdr,
    Hdr10,
    #[serde(rename = "HDR10+")]
    Hdr10Plus,
    DolbyVision {
        profile: DvProfile,
    },
}

/// Task status (7 states matching Python TaskStatus enum).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum TaskStatus {
    #[default]
    Pending,
    Running,
    Completed,
    Skipped,
    Failed,
    Cancelled,
    Discarded,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum DvProfile {
    #[default]
    Profile8_1,
    Profile5,
    Profile7,
    Profile8_4,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum VideoCodec {
    #[default]
    H264,
    Hevc,
    Av1,
    Vp9,
    Mpeg2,
    Vc1,
    #[serde(untagged)]
    Unknown(String),
}

impl VideoCodec {
    pub fn from_codec(s: &str) -> Self {
        match s.to_lowercase().as_str() {
            "h264" | "h.264" | "avc" => Self::H264,
            "hevc" | "h265" | "h.265" => Self::Hevc,
            "av1" | "av01" => Self::Av1,
            "vp9" | "vp09" => Self::Vp9,
            "mpeg2video" | "mpeg2" | "mpeg-2" => Self::Mpeg2,
            "vc1" | "vc-1" => Self::Vc1,
            other => Self::Unknown(other.to_string()),
        }
    }

    /// Check if codec is empty or unknown.
    pub fn is_empty_or_unknown(&self) -> bool {
        matches!(self, VideoCodec::Unknown(s) if s.is_empty() || s == "unknown")
    }
}

/// Confidence-bounded savings estimate matching Python's range-based model.
/// `estimated_min_bytes` / `estimated_max_bytes` bound the expected output size
/// (not the bytes saved). `percentage` is the human-readable savings range.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SavingsEstimate {
    /// Human-readable savings range, e.g. "45-55%"
    pub percentage: String,
    /// Lower bound of expected output size (best-case compression)
    pub estimated_min_bytes: u64,
    /// Upper bound of expected output size (worst-case compression)
    pub estimated_max_bytes: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum StrategyResult {
    Encode {
        strategy_name: String,
        estimated_saving: SavingsEstimate,
    },
    SkipProtected {
        reason: SkipReason,
    },
    SkipNoMatch {
        reason: String,
    },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum SkipReason {
    HevcSource,
    Av1Source,
    Hdr10,
    Hdr10Plus,
    Hdr10PlusSource,
    DolbyVision,
}

impl SkipReason {
    pub fn display(&self) -> &str {
        match self {
            Self::HevcSource => "跳过：HEVC/H.265 片源",
            Self::Av1Source => "跳过：AV1 片源",
            Self::Hdr10 => "跳过：HDR10 片源",
            Self::Hdr10Plus => "跳过：HDR10+ 片源",
            Self::Hdr10PlusSource => "跳过：HDR10+ 片源",
            Self::DolbyVision => "跳过：Dolby Vision 片源",
        }
    }
}
/// Audio track metadata.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AudioTrack {
    pub codec: String,
    pub channels: i32,
    pub language: String,
    pub title: String,
    pub is_commentary: bool,
}

/// Subtitle track metadata.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SubtitleTrack {
    pub codec: String,
    pub language: String,
    pub title: String,
    pub is_forced: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct FileSnapshot {
    pub id: Option<i64>,
    pub library_folder_id: i64,
    pub relative_path: String,
    pub file_name: String,
    pub size_bytes: i64,
    pub video_codec: VideoCodec,
    pub video_width: i32,
    pub video_height: i32,
    pub hdr_type: HdrType,
    pub audio_tracks: Vec<AudioTrack>,
    pub subtitle_tracks: Vec<SubtitleTrack>,
    pub duration_seconds: f64,
    pub bitrate_bps: i64,
    pub file_mtime: f64,
    pub probe_ok: bool,
    pub probe_error: String,
    pub scanned_at: String,
    /// Source pixel format from ffprobe (e.g. "yuv420p10le")
    #[serde(default)]
    pub pix_fmt: String,
    /// Source frame rate from ffprobe (e.g. "24000/1001")
    #[serde(default)]
    pub frame_rate: String,
    /// Source color primaries from ffprobe (e.g. "bt2020")
    #[serde(default)]
    pub color_primaries: String,
    /// Source color transfer characteristics (e.g. "smpte2084")
    #[serde(default)]
    pub color_transfer: String,
    /// Source color space (e.g. "bt2020nc")
    #[serde(default)]
    pub color_space: String,
}

impl FileSnapshot {
    /// Check if this snapshot has complete probe info.
    pub fn probe_complete(&self) -> bool {
        self.probe_ok
            && !self.video_codec.is_empty_or_unknown()
            && self.video_width > 0
            && self.video_height > 0
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct VideoMetadata {
    pub codec: VideoCodec,
    pub width: i32,
    pub height: i32,
    pub hdr_type: HdrType,
    pub audio_tracks: Vec<AudioTrack>,
    pub subtitle_tracks: Vec<SubtitleTrack>,
    pub duration_seconds: f64,
    pub bitrate_bps: i64,
    #[serde(default)]
    pub pix_fmt: String,
    #[serde(default)]
    pub frame_rate: String,
    #[serde(default)]
    pub color_primaries: String,
    #[serde(default)]
    pub color_transfer: String,
    #[serde(default)]
    pub color_space: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Strategy {
    pub name: String,
    pub description: String,
    pub is_preset: bool,
    pub video: VideoConfig,
    pub hdr: HdrConfig,
    pub audio: AudioConfig,
    pub subtitle: SubtitleConfig,
    pub filters: FilterConfig,
    pub estimated_savings: String,
    pub quality_impact: String,
    #[serde(default)]
    pub sort_order: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct VideoConfig {
    pub encoder: String,
    pub crf: i32,
    pub preset: String,
    pub pix_fmt: String,
    #[serde(default)]
    pub x265_params: String,
    pub gpu: bool,
    #[serde(default)]
    pub nv_preset: String,
    #[serde(default)]
    pub rc: String,
    #[serde(default)]
    pub cq: i32,
}

impl VideoConfig {
    /// True when either `gpu` flag is set or the encoder is a known NVENC type.
    /// Mirror of Python `VideoRule.is_gpu`.
    pub fn is_gpu(&self) -> bool {
        self.gpu
            || self.encoder == "hevc_nvenc"
            || self.encoder == "h264_nvenc"
            || self.encoder == "av1_nvenc"
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct HdrConfig {
    pub mode: String,
    pub dv_handling: String,
}

fn default_preferred_languages() -> Vec<String> {
    vec!["chi".into(), "zho".into(), "eng".into()]
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AudioConfig {
    pub mode: String,
    #[serde(default = "default_preferred_languages")]
    pub preferred_languages: Vec<String>,
}

impl Default for AudioConfig {
    fn default() -> Self {
        Self {
            mode: "keep_original".into(),
            preferred_languages: default_preferred_languages(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SubtitleConfig {
    pub mode: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct FilterConfig {
    #[serde(default)]
    pub skip_x265: bool,
    #[serde(default)]
    pub min_size_gb: Option<f64>,
    #[serde(default)]
    pub only_remux: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct FileFilter {
    pub library_id: Option<i64>,
    pub folder_id: Option<i64>,
    pub probe_ok_only: Option<bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LibraryInfo {
    pub id: i64,
    pub name: String,
    pub created_at: String,
    #[serde(default)]
    pub folders: Vec<FolderInfo>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FolderInfo {
    pub id: i64,
    pub library_id: i64,
    pub path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProbeResult {
    pub path: std::path::PathBuf,
    pub metadata: Result<VideoMetadata, String>,
}

/// Comprehensive compression audit record covering version/tool info,
/// source/output metadata, strategy details, execution metrics, and environment data.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CompressionAudit {
    // Version & tools
    pub leanreel_version: String,
    pub ffmpeg_version: String,
    pub dovi_tool_version: String,

    // Source file info
    pub source_path: String,
    pub source_size_bytes: u64,
    pub source_codec: String,
    pub source_width: i32,
    pub source_height: i32,
    pub source_hdr: String,
    pub source_duration_seconds: f64,
    pub source_bitrate_bps: i64,
    pub source_audio_count: usize,
    pub source_subtitle_count: usize,
    /// Source pixel format (e.g. "yuv420p10le")
    #[serde(default)]
    pub source_pix_fmt: String,
    /// Source frame rate (e.g. "24000/1001")
    #[serde(default)]
    pub source_frame_rate: String,
    /// Source color primaries (e.g. "bt2020")
    #[serde(default)]
    pub source_color_primaries: String,
    /// Source color transfer (e.g. "smpte2084")
    #[serde(default)]
    pub source_color_transfer: String,
    /// Source color space (e.g. "bt2020nc")
    #[serde(default)]
    pub source_color_space: String,
    /// Source file modification time (Unix epoch seconds)
    #[serde(default)]
    pub source_mtime: f64,

    // Output file info
    pub output_path: String,
    pub output_size_bytes: u64,
    pub output_codec: String,
    pub savings_pct: f64,
    pub size_delta_bytes: i64,

    // Strategy details
    pub strategy_name: String,
    pub encoder: String,
    pub cq_value: i32,
    pub crf_value: i32,
    pub preset: String,
    pub pix_fmt: String,
    pub audio_mode: String,
    pub sub_mode: String,

    // Execution
    pub duration_ms: u64,
    pub success: bool,
    pub error_message: String,
    pub ffmpeg_command: String,
    pub status: String,
    pub stage: String,
    pub progress: f64,
    /// Adaptive CQ — original value before adjustment
    #[serde(default)]
    pub adaptive_cq_original: i32,
    /// Adaptive CQ — adjusted value after bitrate analysis
    #[serde(default)]
    pub adaptive_cq_adjusted: i32,
    /// Adaptive CQ — reason for adjustment
    #[serde(default)]
    pub adaptive_cq_reason: String,

    // Environment
    pub timestamp: String,
    pub completed_at: String,
    pub source_deleted: bool,
    pub has_dolby_vision: bool,
    pub dv_handling: String,
    pub batch_id: String,
    /// OS platform string (e.g. "Windows-11-10.0.26200")
    #[serde(default)]
    pub platform: String,
}

/// Comprehensive history entry matching Python CompressionRecord fields.
/// Returned to the frontend history panel with full encoding details.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HistoryEntry {
    pub id: i64,
    pub source_path: String,
    pub output_path: String,
    pub source_size_bytes: i64,
    pub output_size_bytes: i64,
    pub savings_pct: f64,
    pub strategy_name: String,
    pub encoder: String,
    pub status: String,
    pub duration_ms: i64,
    pub completed_at: String,
    pub success: bool,
    // ── Expanded fields (M8 fix) ──────────────────────────────────────
    pub cq_value: i32,
    pub preset: String,
    pub pix_fmt: String,
    pub audio_mode: String,
    pub sub_mode: String,
    pub ffmpeg_command: String,
    pub leanreel_version: String,
    pub batch_id: String,
    pub stage: String,
    pub started_at: String,
    pub source_deleted: bool,
    #[serde(default)]
    pub error_message: String,
    #[serde(default)]
    pub performance_metrics: String,
}
