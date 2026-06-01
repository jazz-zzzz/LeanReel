use crate::domain::models::*;
use std::path::{Path, PathBuf};

pub type JobId = String;

pub struct FinishCompressionParams<'a> {
    pub record_id: i64,
    pub status: &'a str,
    pub progress: f64,
    pub duration_seconds: i64,
    pub compressed_size: i64,
    pub error_message: &'a str,
    pub sidecar_path: &'a str,
    pub source_deleted: i32,
    pub ffmpeg_command: &'a str,
}

#[derive(Debug, Clone, PartialEq)]
pub enum ProgressEvent {
    StageStart {
        stage: String,
        total_stages: u8,
    },
    StageProgress {
        percent: f32,
        fps: f32,
        bitrate_kbps: u32,
    },
    StageComplete {
        stage: String,
        duration_ms: u64,
    },
    Warning {
        message: String,
    },
    Done {
        output: EncodeOutput,
    },
}

#[derive(Debug, Clone)]
pub struct EncodingJob {
    pub id: JobId,
    pub input_path: PathBuf,
    pub output_path: PathBuf,
    pub strategy: Strategy,
    pub has_dolby_vision: bool,
    pub snapshot: FileSnapshot,
}

#[derive(Debug, Clone, PartialEq)]
pub struct EncodeOutput {
    pub output_path: PathBuf,
    pub original_size: u64,
    pub compressed_size: u64,
    pub duration_ms: u64,
    /// The full ffmpeg command line used for this encode (space-joined args).
    pub command: String,
}

/// 文件快照持久化
pub trait SnapshotStore {
    fn upsert(&self, snapshots: &[FileSnapshot]) -> Result<usize, String>;
    fn query(&self, filter: &FileFilter) -> Result<Vec<FileSnapshot>, String>;
    fn mark_deleted(&self, folder_id: i64, path: &Path) -> Result<bool, String>;
    fn get_by_path(&self, path: &Path) -> Result<Option<FileSnapshot>, String>;
    /// 从数据库随机抽取一条记录（用于行为一致性验证）
    fn random_snapshot(&self) -> Result<Option<FileSnapshot>, String>;

    /// C2: Runtime status/progress update during encoding (mirrors Python `_update_runtime`).
    fn update_compression_runtime(
        &self,
        record_id: i64,
        status: &str,
        progress: f64,
        stage: &str,
        duration_seconds: i64,
    ) -> Result<(), String>;

    /// C2: Finalize a compression record on encode completion or failure.
    fn finish_compression(&self, params: FinishCompressionParams<'_>) -> Result<(), String>;
}

/// 媒体元数据探测
pub trait MediaProber {
    fn probe(&self, path: &Path) -> Result<VideoMetadata, String>;
    fn probe_batch(&self, paths: &[PathBuf]) -> Result<Vec<ProbeResult>, String>;
}

/// 编码执行器
pub trait Encoder {
    fn run(
        &self,
        job: &EncodingJob,
        on_progress: &(dyn Fn(ProgressEvent) + Send + Sync),
    ) -> Result<EncodeOutput, String>;
    fn cancel(&self, job_id: &JobId) -> Result<(), String>;
}
