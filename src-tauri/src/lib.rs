pub mod commands;
pub mod domain;
pub mod infrastructure;
pub mod services;

use crate::domain::traits::Encoder;
use infrastructure::db::SqliteSnapshotStore;
use infrastructure::ffmpeg::FfmpegRunner;
use infrastructure::ffprobe::FfprobeRunner;
use services::matcher::StrategyMatcher;
use services::scanner::Scanner;
use services::worker::WorkerManager;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use tauri::{Emitter, Manager};

pub struct AppState {
    pub store: Arc<Mutex<SqliteSnapshotStore>>,
    pub prober: Arc<FfprobeRunner>,
    pub ffmpeg: Arc<FfmpegRunner>,
    pub scanner: Arc<Mutex<Scanner>>,
    pub matcher: Arc<Mutex<StrategyMatcher>>,
    pub worker: Arc<WorkerManager>,
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let db_path = get_db_path();
    let store = Arc::new(Mutex::new(
        SqliteSnapshotStore::open(&db_path).expect("Failed to open database"),
    ));
    let prober = Arc::new(FfprobeRunner::new(None));
    let ffmpeg = Arc::new(FfmpegRunner::new(None));

    let scanner_store = SqliteSnapshotStore::open(&db_path).expect("Failed to open scanner DB");
    let scanner = Arc::new(Mutex::new(Scanner::new(
        Box::new((*prober).clone()),
        Box::new(scanner_store),
    )));

    let matcher = Arc::new(Mutex::new(StrategyMatcher::new(vec![])));
    let wm = WorkerManager::new(16);
    wm.set_executor(ffmpeg.clone() as Arc<dyn Encoder + Send + Sync>);
    wm.set_prober(Box::new((*prober).clone()));
    let worker_store = SqliteSnapshotStore::open(&db_path).expect("Failed to open worker DB");
    wm.set_store(Box::new(worker_store));
    let worker = Arc::new(wm);

    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(AppState {
            store: store.clone(),
            prober: prober.clone(),
            ffmpeg: ffmpeg.clone(),
            scanner: scanner.clone(),
            matcher: matcher.clone(),
            worker: worker.clone(),
        })
        .invoke_handler(tauri::generate_handler![
            commands::scan::get_library_files,
            commands::scan::get_folder_files,
            commands::scan::scan_directory,
            commands::library::create_library,
            commands::library::delete_library,
            commands::library::list_libraries,
            commands::library::add_folder,
            commands::library::remove_folder,
            commands::library::get_folders,
            commands::strategy::load_strategies,
            commands::strategy::save_strategy,
            commands::strategy::delete_strategy,
            commands::strategy::save_strategy_order,
            commands::encode::start_encode,
            commands::encode::get_queue_status,
            commands::encode::pause_encode,
            commands::encode::resume_encode,
            commands::encode::cancel_encode,
            commands::encode::cancel_task,
            commands::history::get_history,
            commands::settings::get_settings,
            commands::settings::test_tool,
            commands::settings::save_settings,
        ])
        .setup(|app| {
            let state = app.state::<AppState>();
            if let Ok(strategies) = crate::commands::strategy::load_strategies_from_disk() {
                if !strategies.is_empty() {
                    if let Ok(mut matcher) = state.matcher.lock() {
                        *matcher = crate::services::matcher::StrategyMatcher::new(strategies);
                    }
                }
            }

            state.worker.set_app_handle(app.handle().clone());

            // Wire scanner progress callbacks to Tauri events.
            let phase_handle = app.handle().clone();
            let progress_handle = app.handle().clone();
            let result_handle = app.handle().clone();
            let matcher = state.matcher.clone();
            if let Ok(mut scanner) = state.scanner.lock() {
                scanner.on_phase = Some(Box::new(move |event| {
                    let _ = phase_handle.emit("scan-phase", event);
                }));
                scanner.on_progress = Some(Box::new(move |event| {
                    let _ = progress_handle.emit("scan-progress", event);
                }));
                scanner.on_result = Some(Box::new(move |snapshot| {
                    if let Ok(matcher) = matcher.lock() {
                        let entry = crate::commands::scan::build_entry(snapshot, &matcher);
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

fn get_db_path() -> PathBuf {
    let mut path = dirs::data_dir().unwrap_or_else(|| PathBuf::from("."));
    path.push("LeanReel");
    std::fs::create_dir_all(&path).ok();
    path.push("leanreel.db");
    path
}
