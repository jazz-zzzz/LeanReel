use leanreel_rs_lib::domain::models::FileFilter;
use leanreel_rs_lib::domain::traits::SnapshotStore;
use leanreel_rs_lib::infrastructure::db::SqliteSnapshotStore;
use leanreel_rs_lib::infrastructure::ffmpeg::FfmpegRunner;
use leanreel_rs_lib::infrastructure::ffprobe::FfprobeRunner;
use leanreel_rs_lib::services::matcher::StrategyMatcher;
use leanreel_rs_lib::services::scanner::Scanner;
use leanreel_rs_lib::services::worker::WorkerManager;
use leanreel_rs_lib::AppState;
use std::sync::{Arc, Mutex};

fn make_test_state() -> AppState {
    AppState {
        store: Arc::new(Mutex::new(SqliteSnapshotStore::open_in_memory().unwrap())),
        prober: Arc::new(FfprobeRunner::new(None)),
        ffmpeg: Arc::new(FfmpegRunner::new(None)),
        scanner: Arc::new(Mutex::new(Scanner::new(
            Box::new(FfprobeRunner::new(None)),
            Box::new(SqliteSnapshotStore::open_in_memory().unwrap()),
        ))),
        matcher: Arc::new(Mutex::new(StrategyMatcher::new(vec![]))),
        worker: Arc::new(WorkerManager::new(1)),
    }
}

#[test]
fn test_app_state_store_works() {
    let state = make_test_state();
    let filter = FileFilter {
        library_id: None,
        folder_id: None,
        probe_ok_only: None,
    };
    let store = state.store.lock().unwrap();
    let result = store.query(&filter);
    assert!(result.is_ok());
}

#[test]
fn test_app_state_scanner_handles_bad_path() {
    let state = make_test_state();
    let scanner = state.scanner.lock().unwrap();
    let result =
        scanner.scan_directory(std::path::Path::new("nonexistent_dir_xyz"), 1, "test-scan");
    assert!(
        result.is_err(),
        "Bad path must abort scanning so cached rows are preserved"
    );
}
