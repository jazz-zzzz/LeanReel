use leanreel_core::api;
use leanreel_core::AppState;
use serde::Serialize;
use std::sync::Arc;
use tauri::{Emitter, Manager, State};

// ── Thin Tauri command wrappers ──

#[tauri::command]
fn get_library_files(library_id: i64, state: State<AppState>) -> Result<api::scan::ScanCommandResult, String> {
    api::scan::get_library_files(library_id, &state)
}

#[tauri::command]
fn get_folder_files(folder_id: i64, state: State<AppState>) -> Result<api::scan::ScanCommandResult, String> {
    api::scan::get_folder_files(folder_id, &state)
}

#[tauri::command]
async fn scan_directory(path: String, folder_id: i64, state: State<'_, AppState>) -> Result<api::scan::ScanCommandResult, String> {
    let state_arc = state.inner().clone();
    // Use Arc-wrapped state for spawn_blocking compatibility
    let app_state = Arc::new(AppState {
        store: state_arc.store.clone(),
        prober: state_arc.prober.clone(),
        ffmpeg: state_arc.ffmpeg.clone(),
        scanner: state_arc.scanner.clone(),
        matcher: state_arc.matcher.clone(),
        worker: state_arc.worker.clone(),
    });
    api::scan::scan_directory(path, folder_id, app_state).await
}

#[tauri::command]
fn create_library(name: String, state: State<AppState>) -> Result<i64, String> {
    api::library::create_library(&name, &state)
}

#[tauri::command]
fn delete_library(id: i64, state: State<AppState>) -> Result<bool, String> {
    api::library::delete_library(id, &state)
}

#[tauri::command]
fn list_libraries(state: State<AppState>) -> Result<Vec<leanreel_core::domain::models::LibraryInfo>, String> {
    api::library::list_libraries(&state)
}

#[tauri::command]
fn add_folder(library_id: i64, path: String, state: State<AppState>) -> Result<i64, String> {
    api::library::add_folder(library_id, &path, &state)
}

#[tauri::command]
fn remove_folder(library_id: i64, folder_id: i64, state: State<AppState>) -> Result<bool, String> {
    api::library::remove_folder(library_id, folder_id, &state)
}

#[tauri::command]
fn get_folders(library_id: i64, state: State<AppState>) -> Result<Vec<leanreel_core::domain::models::FolderInfo>, String> {
    api::library::get_folders(library_id, &state)
}

#[tauri::command]
fn load_strategies(state: State<AppState>) -> Result<api::strategy::StrategyListResult, String> {
    api::strategy::load_strategies(&state)
}

#[tauri::command]
fn save_strategy(name: String, strategy_json: String, state: State<AppState>) -> Result<(), String> {
    api::strategy::save_strategy(&name, &strategy_json, &state)
}

#[tauri::command]
fn delete_strategy(name: String, state: State<AppState>) -> Result<(), String> {
    api::strategy::delete_strategy(&name, &state)
}

#[tauri::command]
fn save_strategy_order(order: Vec<api::strategy::SortOrderEntry>, state: State<AppState>) -> Result<(), String> {
    api::strategy::save_strategy_order(&order, &state)
}

#[derive(Debug, Clone, Serialize)]
struct StartEncodeResult {
    message: String,
    jobs: Vec<api::encode::SubmittedQueueItem>,
}

#[tauri::command]
fn start_encode(
    files: Vec<String>,
    strategy_name: String,
    delete_source: Option<bool>,
    worker_count: Option<i32>,
    custom_strategy: Option<api::encode::CustomStrategyRequest>,
    state: State<AppState>,
) -> Result<StartEncodeResult, String> {
    let result = api::encode::start_encode(
        files,
        &strategy_name,
        delete_source,
        worker_count,
        custom_strategy,
        &state,
    )?;
    Ok(StartEncodeResult {
        message: result.message,
        jobs: result.jobs,
    })
}

#[tauri::command]
fn get_queue_status(state: State<AppState>) -> Result<serde_json::Value, String> {
    api::encode::get_queue_status(&state)
}

#[tauri::command]
fn pause_encode(state: State<AppState>) -> Result<(), String> {
    api::encode::pause_encode(&state)
}

#[tauri::command]
fn resume_encode(state: State<AppState>) -> Result<(), String> {
    api::encode::resume_encode(&state)
}

#[tauri::command]
fn cancel_encode(state: State<AppState>) -> Result<(), String> {
    api::encode::cancel_encode(&state)
}

#[tauri::command]
fn cancel_task(job_id: String, state: State<AppState>) -> Result<(), String> {
    api::encode::cancel_task(&job_id, &state)
}

#[tauri::command]
fn get_history(state: State<AppState>) -> Result<Vec<leanreel_core::domain::models::HistoryEntry>, String> {
    api::history::get_history(&state)
}

#[tauri::command]
fn get_settings(state: State<AppState>) -> Result<api::settings::AppSettings, String> {
    api::settings::get_settings(&state)
}

#[tauri::command]
fn test_tool(path: String) -> Result<bool, String> {
    api::settings::test_tool(&path)
}

#[tauri::command]
fn save_settings(
    ffprobe_path: Option<String>,
    ffmpeg_path: Option<String>,
    state: State<AppState>,
) -> Result<api::settings::AppSettings, String> {
    api::settings::save_settings(
        ffprobe_path.as_deref(),
        ffmpeg_path.as_deref(),
        &state,
    )
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let state = leanreel_core::create_app_state().expect("Failed to create app state");

    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(state)
        .invoke_handler(tauri::generate_handler![
            get_library_files,
            get_folder_files,
            scan_directory,
            create_library,
            delete_library,
            list_libraries,
            add_folder,
            remove_folder,
            get_folders,
            load_strategies,
            save_strategy,
            delete_strategy,
            save_strategy_order,
            start_encode,
            get_queue_status,
            pause_encode,
            resume_encode,
            cancel_encode,
            cancel_task,
            get_history,
            get_settings,
            test_tool,
            save_settings,
        ])
        .setup(|app| {
            let state = app.state::<AppState>();

            // Load strategies from disk
            if let Ok(strategies) = api::strategy::load_strategies_from_disk() {
                if !strategies.is_empty() {
                    if let Ok(mut matcher) = state.matcher.lock() {
                        *matcher = leanreel_core::services::matcher::StrategyMatcher::new(strategies);
                    }
                }
            }

            // Wire worker progress emitter to Tauri events
            let handle = app.handle().clone();
            state.worker.set_progress_emitter(Box::new(move |job_id, stage, progress, status| {
                let _ = handle.emit(
                    "encode-progress",
                    serde_json::json!({
                        "job_id": job_id, "stage": stage, "progress": progress, "status": status,
                    }),
                );
            }));

            // Wire scanner callbacks to Tauri events
            let app_handle = app.handle().clone();
            let result_handle = app.handle().clone();
            let matcher = state.matcher.clone();
            if let Ok(mut scanner) = state.scanner.lock() {
                scanner.on_progress = Some(Box::new(move |done, total| {
                    let _ = app_handle.emit(
                        "scan-progress",
                        serde_json::json!({ "done": done, "total": total }),
                    );
                }));
                scanner.on_result = Some(Box::new(move |snapshot| {
                    if let Ok(matcher) = matcher.lock() {
                        let entry = api::scan::build_entry(snapshot, &matcher);
                        let _ = result_handle.emit("scan-result", entry);
                    }
                }));
            }

            // Load stored ffmpeg/ffprobe paths from config
            if let Ok(store) = state.store.lock() {
                state.prober.load_from_config(&store);
                state.ffmpeg.load_from_config(&store);
                let ffp_ok = state.prober.has_ffprobe().is_ok();
                let ffm_ok = state.ffmpeg.has_ffmpeg().is_ok();
                if !ffp_ok || !ffm_ok {
                    let msg = match (ffp_ok, ffm_ok) {
                        (false, false) => "ffprobe 和 ffmpeg 未找到，请检查设置",
                        (false, _) => "ffprobe 未找到，请检查设置",
                        (_, false) => "ffmpeg 未找到，请检查设置",
                        _ => "",
                    };
                    if !msg.is_empty() {
                        let _ = app.handle().emit("tool-status", msg);
                    }
                }
            }

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
