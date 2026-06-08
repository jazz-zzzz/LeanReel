use crate::domain::models::{HdrType, Strategy, TaskStatus};
use crate::domain::traits::CreateCompressionRecordParams;
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

/// Resolve the strategy for encoding — from the matcher by name, with optional
/// custom strategy override from the frontend request.
fn resolve_encode_strategy(
    matcher: &crate::services::matcher::StrategyMatcher,
    strategy_name: &str,
    custom_strategy: Option<&CustomStrategyRequest>,
) -> Result<Strategy, String> {
    let mut strategy = matcher
        .get_strategy(strategy_name)
        .ok_or_else(|| format!("未找到策略: {}", strategy_name))?
        .clone();

    if let Some(custom) = custom_strategy {
        strategy.name = "自定义".into();
        strategy.video.encoder = custom.encoder.clone();
        strategy.video.cq = custom.cq;
        strategy.video.crf = custom.crf;
        strategy.video.preset = custom.preset.clone();
        strategy.video.nv_preset = custom.preset.clone();
        strategy.video.gpu = matches!(
            custom.encoder.as_str(),
            "hevc_nvenc" | "h264_nvenc" | "av1_nvenc"
        );
        strategy.audio.mode = custom.audio.clone();
        strategy.subtitle.mode = custom.sub.clone();
    }
    Ok(strategy)
}

/// Build a single WorkerTask from a file key, resolving paths and creating
/// the compression_history record. Returns the task, its job_id, and the
/// display file_name for the frontend SubmittedQueueItem.
fn build_encode_task(
    file_key: &str,
    strategy: &Strategy,
    batch_id: &str,
    delete_source: bool,
    store: &crate::infrastructure::db::SqliteSnapshotStore,
) -> Result<(WorkerTask, String, String), String> {
    let relative_path = parse_file_key(file_key)?;
    let input = Path::new(&relative_path);

    let snapshot = match store.get_by_folder_path(0, input)? {
        Some(s) => s,
        None => return Err(format!("未找到文件快照: {}", file_key)),
    };

    // Resolve to absolute path
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

    let has_dolby_vision = matches!(&snapshot.hdr_type, HdrType::DolbyVision { .. });

    let history_id = store
        .create_compression_record(CreateCompressionRecordParams {
            file_snapshot_id: snapshot.id.unwrap_or(0),
            batch_id,
            strategy_name: &strategy.name,
            original_size: snapshot.size_bytes,
            output_path: &output_path.to_string_lossy(),
            encoder: &strategy.video.encoder,
            cq_value: strategy.video.cq,
            preset: &strategy.video.preset,
            pix_fmt: &snapshot.pix_fmt,
            audio_mode: &strategy.audio.mode,
            sub_mode: &strategy.subtitle.mode,
        })
        .map_err(|e| format!("创建压缩记录失败: {}", e))?;

    // H5: Backfill source info
    if let Some(snapshot_id) = snapshot.id {
        store
            .backfill_history_sources(history_id, snapshot_id)
            .map_err(|e| format!("回填历史源信息失败: {}", e))?;
    }

    let job_id = make_job_id(file_key);
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
        delete_source,
    };

    Ok((task, job_id, file_name))
}

#[tauri::command]
pub fn start_encode(
    files: Vec<String>,
    strategy_name: String,
    delete_source: Option<bool>,
    #[allow(unused)] worker_count: Option<i32>,
    custom_strategy: Option<CustomStrategyRequest>,
    state: State<AppState>,
) -> Result<StartEncodeResult, String> {
    let matcher = state.matcher.lock().map_err(|e| e.to_string())?;
    let strategy = resolve_encode_strategy(&matcher, &strategy_name, custom_strategy.as_ref())?;
    drop(matcher);

    let ds = delete_source.unwrap_or(false);
    let batch_id = uuid::Uuid::new_v4().to_string();

    let store = state.store.lock().map_err(|e| e.to_string())?;

    let mut jobs = Vec::new();
    for file_key in &files {
        // Decision check: verify the file is processable before building the task
        let relative_path = parse_file_key(file_key)?;
        let input = Path::new(&relative_path);
        let snapshot_check = store
            .get_by_folder_path(0, input)?
            .ok_or_else(|| format!("未找到文件快照: {}", file_key))?;
        let decision = state
            .matcher
            .lock()
            .map_err(|e| e.to_string())?
            .match_for(&snapshot_check);
        if !matches!(
            decision,
            crate::domain::models::StrategyResult::Encode { .. }
        ) {
            return Err(format!("文件不可处理: {}", snapshot_check.relative_path));
        }

        let (task, job_id, file_name) =
            build_encode_task(file_key, &strategy, &batch_id, ds, &store)?;

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
    // Frontend sends "folder_id:relative/path" or just "relative/path".
    // Strip the folder_id prefix if present — we search by path only.
    let s = file_key.replace('\\', "/");
    Ok(if let Some((_folder_id, path)) = s.split_once(':') {
        path.to_string()
    } else {
        s
    })
}

fn make_job_id(file_key: &str) -> String {
    format!("encode-{}-{}", file_key, uuid::Uuid::new_v4())
}

#[cfg(test)]
mod tests {
    use super::make_job_id;

    #[test]
    fn job_ids_are_unique_for_repeated_submissions_of_the_same_file() {
        assert_ne!(make_job_id("1:movie.mkv"), make_job_id("1:movie.mkv"));
    }
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
    state.ffmpeg.cancel().ok();
    state.worker.cancel();
    Ok(())
}

#[tauri::command]
pub fn cancel_task(job_id: String, state: State<AppState>) -> Result<(), String> {
    state.worker.cancel_task(&job_id)
}
