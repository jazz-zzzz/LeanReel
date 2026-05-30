pub mod domain;
pub mod infrastructure;
pub mod services;
pub mod commands;

use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use tauri::{Manager, Emitter};
use infrastructure::db::SqliteSnapshotStore;
use infrastructure::ffprobe::FfprobeRunner;
use infrastructure::ffmpeg::FfmpegRunner;
use crate::domain::traits::Encoder;
use services::scanner::Scanner;
use services::matcher::StrategyMatcher;
use services::worker::WorkerManager;

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
        Box::new(FfprobeRunner::new(None)),
        Box::new(scanner_store),
    )));

    let matcher = Arc::new(Mutex::new(StrategyMatcher::new(vec![])));
    let wm = WorkerManager::new(2);
    wm.set_executor(ffmpeg.clone() as Arc<dyn Encoder + Send + Sync>);
    let worker_store = SqliteSnapshotStore::open(&db_path).expect("Failed to open worker DB");
    wm.set_store(Box::new(worker_store));
    let worker = Arc::new(wm);

    tauri::Builder::default()
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
            commands::encode::start_encode,
            commands::encode::get_queue_status,
            commands::encode::pause_encode,
            commands::encode::resume_encode,
            commands::encode::cancel_encode,
            commands::history::get_history,
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

            // Task 4: Set app handle on worker for encode-progress events
            state.worker.set_app_handle(app.handle().clone());

            // Task 6: Wire scanner progress callback to Tauri events
            let app_handle = app.handle().clone();
            if let Ok(mut scanner) = state.scanner.lock() {
                scanner.on_progress = Some(Box::new(move |done, total| {
                    let _ = app_handle.emit("scan-progress", serde_json::json!({
                        "done": done,
                        "total": total,
                    }));
                }));
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
