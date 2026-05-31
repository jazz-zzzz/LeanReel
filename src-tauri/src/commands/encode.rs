use crate::domain::models::{HdrType, TaskStatus};
use crate::services::worker::WorkerTask;
use crate::AppState;
use serde::{Deserialize, Serialize};
use std::path::Path;
use tauri::State;

#[derive(Debug, Clone, Serialize)]
pub struct SubmittedQueueItem {
    pub id: String,
    pub file_key: String,
    pub file_name: String,
    pub strategy_name: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct StartEncodeResult {
    pub message: String,
    pub jobs: Vec<SubmittedQueueItem>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CustomStrategyRequest {
    pub encoder: String,
    pub cq: i32,
    pub crf: i32,
    pub preset: String,
    pub audio: String,
    pub sub: String,
}

#[tauri::command]
pub fn start_encode(
    files: Vec<String>,
    strategy_name: String,
    delete_source: Option<bool>,
    worker_count: Option<i32>,
    custom_strategy: Option<CustomStrategyRequest>,
    state: State<AppState>,
) -> Result<StartEncodeResult, String> {
    state
        .worker
        .set_worker_count(worker_count.unwrap_or(2).min(16).max(1) as usize);
    // 1. Get the full Strategy from the matcher (not Default::default())
    let matcher = state.matcher.lock().map_err(|e| e.to_string())?;
    let mut strategy = matcher
        .get_strategy(&strategy_name)
        .ok_or_else(|| format!("未找到策略: {}", strategy_name))?
        .clone();
    drop(matcher);

    let ds = delete_source.unwrap_or(false);
    if let Some(custom) = custom_strategy {
        strategy.name = "自定义".into();
        strategy.video.encoder = custom.encoder.clone();
        strategy.video.cq = custom.cq;
        strategy.video.crf = custom.crf;
        strategy.video.preset = custom.preset.clone();
        strategy.video.nv_preset = custom.preset;
        strategy.video.gpu = matches!(
            custom.encoder.as_str(),
            "hevc_nvenc" | "h264_nvenc" | "av1_nvenc"
        );
        strategy.audio.mode = custom.audio;
        strategy.subtitle.mode = custom.sub;
    }

    // Generate a batch_id for this encode run
    let batch_id = uuid::Uuid::new_v4().to_string();

    // 2. Lock store and query for actual FileSnapshots matching those paths
    let store = state.store.lock().map_err(|e| e.to_string())?;

    let mut jobs = Vec::new();
    for file_key in &files {
        let relative_path = parse_file_key(file_key)?;
        let input = std::path::Path::new(&relative_path);

        let snapshot = match store.get_by_folder_path(0, input)? {
            Some(s) => s,
            None => return Err(format!("未找到文件快照: {}", file_key)),
        };

        let decision = state
            .matcher
            .lock()
            .map_err(|e| e.to_string())?
            .match_for(&snapshot);
        if !matches!(
            decision,
            crate::domain::models::StrategyResult::Encode { .. }
        ) {
            return Err(format!("文件不可处理: {}", snapshot.relative_path));
        }

        // Resolve to absolute path — frontend sends relative paths but FFmpeg needs absolute.
        // Query the actual folder root path from the DB (not process CWD which may be unrelated).
        let folder_path = store.get_folder_path_by_id(snapshot.library_folder_id)?;
        let abs_input = Path::new(&folder_path).join(&snapshot.relative_path);

        let file_name = snapshot.file_name.clone();
        let file_stem = abs_input
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("unknown");
        let ext = abs_input
            .extension()
            .and_then(|e| e.to_str())
            .unwrap_or("mkv");
        let output_path = abs_input.with_file_name(format!("{}_zcompressed.{}", file_stem, ext));

        // Detect Dolby Vision from the actual HDR type in the snapshot
        let has_dolby_vision = matches!(&snapshot.hdr_type, HdrType::DolbyVision { .. });

        // C1: Create compression_history record before submitting to worker
        let history_id = store
            .create_compression_record(
                snapshot.id.unwrap_or(0),
                &batch_id,
                &strategy.name,
                snapshot.size_bytes,
                &output_path.to_string_lossy(),
                &strategy.video.encoder,
                strategy.video.cq,
                &strategy.video.preset,
                &snapshot.pix_fmt,
                &strategy.audio.mode,
                &strategy.subtitle.mode,
            )
            .map_err(|e| format!("创建压缩记录失败: {}", e))?;

        // H5: Backfill source library/folder/path columns from file_snapshot JOIN
        if snapshot.id.is_some() {
            store
                .backfill_history_sources(history_id, snapshot.id.unwrap())
                .map_err(|e| format!("回填历史源信息失败: {}", e))?;
        }

        // 4. Build proper WorkerTask with real Strategy and FileSnapshot
        let job_id = format!("encode-{}", file_key);
        let task = WorkerTask {
            id: job_id.clone(),
            file_name: file_name.clone(),
            input_path: abs_input,
            output_path,
            strategy: strategy.clone(),
            snapshot,
            status: TaskStatus::Pending,
            progress: 0.0,
            error_message: String::new(),
            history_id,
            has_dolby_vision,
            delete_source: ds,
        };

        // 5. Submit to worker
        state.worker.submit(task).map_err(|e| e.to_string())?;
        jobs.push(SubmittedQueueItem {
            id: job_id,
            file_key: file_key.clone(),
            file_name,
            strategy_name: strategy.name.clone(),
        });
    }

    Ok(StartEncodeResult {
        message: format!("已提交 {} 个编码任务", jobs.len()),
        jobs,
    })
}

fn parse_file_key(file_key: &str) -> Result<String, String> {
    Ok(file_key.replace('\\', "/"))
}

#[tauri::command]
pub fn get_queue_status(state: State<AppState>) -> Result<serde_json::Value, String> {
    Ok(
        serde_json::json!({ "paused": state.worker.is_paused(), "cancelled": state.worker.is_cancelled() }),
    )
}

#[tauri::command]
pub fn pause_encode(state: State<AppState>) -> Result<(), String> {
    state.worker.pause();
    Ok(())
}
#[tauri::command]
pub fn resume_encode(state: State<AppState>) -> Result<(), String> {
    state.worker.resume();
    Ok(())
}
#[tauri::command]
pub fn cancel_encode(state: State<AppState>) -> Result<(), String> {
    // Kill ffmpeg directly — worker's executor lock is held during encode, so
    // we cannot acquire it in cancel(). Instead, access the shared FfmpegRunner.
    state.ffmpeg.cancel().ok();
    state.worker.cancel();
    Ok(())
}
