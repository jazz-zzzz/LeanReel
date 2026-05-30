use std::path::Path;
use tauri::State;
use crate::AppState;
use crate::services::worker::WorkerTask;
use crate::domain::models::{TaskStatus, HdrType};
use crate::domain::traits::SnapshotStore;

#[tauri::command]
pub fn start_encode(
    files: Vec<String>,
    strategy_name: String,
    worker_count: Option<i32>,
    delete_source: Option<bool>,
    state: State<AppState>,
) -> Result<String, String> {
    // 1. Get the full Strategy from the matcher (not Default::default())
    let matcher = state.matcher.lock().map_err(|e| e.to_string())?;
    let strategy = matcher
        .get_strategy(&strategy_name)
        .ok_or_else(|| format!("未找到策略: {}", strategy_name))?
        .clone();
    drop(matcher);

    let wc = worker_count.unwrap_or(2) as usize;
    let ds = delete_source.unwrap_or(false);

    // Update worker pool size if needed
    if wc != state.worker.max_workers() {
        state.worker.set_worker_count(wc);
    }

    // Generate a batch_id for this encode run
    let batch_id = uuid::Uuid::new_v4().to_string();

    // 2. Lock store and query for actual FileSnapshots matching those paths
    let store = state.store.lock().map_err(|e| e.to_string())?;

    let mut count = 0;
    for file_path in &files {
        let input = std::path::Path::new(file_path);

        // Query the store for the actual FileSnapshot (uses relative path)
        let snapshot = match store.get_by_path(input)? {
            Some(s) => s,
            None => return Err(format!("未找到文件快照: {}", file_path)),
        };

        // Resolve to absolute path — frontend sends relative paths but FFmpeg needs absolute.
        // Query the actual folder root path from the DB (not process CWD which may be unrelated).
        let folder_path = store.get_folder_path_by_id(snapshot.library_folder_id)?;
        let abs_input = Path::new(&folder_path).join(&snapshot.relative_path);

        let file_name = snapshot.file_name.clone();
        let file_stem = abs_input.file_stem().and_then(|s| s.to_str()).unwrap_or("unknown");
        let ext = abs_input.extension().and_then(|e| e.to_str()).unwrap_or("mkv");
        let output_path = abs_input.with_file_name(format!("{}_zcompressed.{}", file_stem, ext));

        // Detect Dolby Vision from the actual HDR type in the snapshot
        let has_dolby_vision = matches!(&snapshot.hdr_type, HdrType::DolbyVision { .. });

        // C1: Create compression_history record before submitting to worker
        let history_id = store.create_compression_record(
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
        ).map_err(|e| format!("创建压缩记录失败: {}", e))?;

        // H5: Backfill source library/folder/path columns from file_snapshot JOIN
        if snapshot.id.is_some() {
            store.backfill_history_sources(history_id, snapshot.id.unwrap())
                .map_err(|e| format!("回填历史源信息失败: {}", e))?;
        }

        // 4. Build proper WorkerTask with real Strategy and FileSnapshot
        let task = WorkerTask {
            id: format!("encode-{}", file_path),
            file_name,
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
        count += 1;
    }

    Ok(format!("已提交 {} 个编码任务", count))
}

#[tauri::command]
pub fn get_queue_status(state: State<AppState>) -> Result<serde_json::Value, String> {
    Ok(serde_json::json!({ "paused": state.worker.is_paused(), "cancelled": state.worker.is_cancelled() }))
}

#[tauri::command]
pub fn pause_encode(state: State<AppState>) -> Result<(), String> { state.worker.pause(); Ok(()) }
#[tauri::command]
pub fn resume_encode(state: State<AppState>) -> Result<(), String> { state.worker.resume(); Ok(()) }
#[tauri::command]
pub fn cancel_encode(state: State<AppState>) -> Result<(), String> { state.worker.cancel(); Ok(()) }
