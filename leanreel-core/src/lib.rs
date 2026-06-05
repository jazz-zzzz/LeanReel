pub mod api;
pub mod domain;
pub mod infrastructure;
pub mod services;

use domain::traits::Encoder;
use infrastructure::db::SqliteSnapshotStore;
use infrastructure::ffmpeg::FfmpegRunner;
use infrastructure::ffprobe::FfprobeRunner;
use services::matcher::StrategyMatcher;
use services::scanner::Scanner;
use services::worker::WorkerManager;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

pub struct AppState {
    pub store: Arc<Mutex<SqliteSnapshotStore>>,
    pub prober: Arc<FfprobeRunner>,
    pub ffmpeg: Arc<FfmpegRunner>,
    pub scanner: Arc<Mutex<Scanner>>,
    pub matcher: Arc<Mutex<StrategyMatcher>>,
    pub worker: Arc<WorkerManager>,
}

pub fn get_db_path() -> PathBuf {
    let mut path = dirs::data_dir().unwrap_or_else(|| PathBuf::from("."));
    path.push("LeanReel");
    std::fs::create_dir_all(&path).ok();
    path.push("leanreel.db");
    path
}

pub fn create_app_state() -> Result<AppState, String> {
    let db_path = get_db_path();
    let store = Arc::new(Mutex::new(
        SqliteSnapshotStore::open(&db_path).map_err(|e| format!("Failed to open database: {}", e))?,
    ));
    let prober = Arc::new(FfprobeRunner::new(None));
    let ffmpeg = Arc::new(FfmpegRunner::new(None));

    let scanner_store =
        SqliteSnapshotStore::open(&db_path).map_err(|e| format!("Failed to open scanner DB: {}", e))?;
    let scanner = Arc::new(Mutex::new(Scanner::new(
        Box::new((*prober).clone()),
        Box::new(scanner_store),
    )));

    let matcher = Arc::new(Mutex::new(StrategyMatcher::new(vec![])));
    let wm = WorkerManager::new(16);
    wm.set_executor(ffmpeg.clone() as Arc<dyn Encoder + Send + Sync>);
    wm.set_prober(Box::new((*prober).clone()));
    let worker_store =
        SqliteSnapshotStore::open(&db_path).map_err(|e| format!("Failed to open worker DB: {}", e))?;
    wm.set_store(Box::new(worker_store));
    let worker = Arc::new(wm);

    Ok(AppState {
        store,
        prober,
        ffmpeg,
        scanner,
        matcher,
        worker,
    })
}
