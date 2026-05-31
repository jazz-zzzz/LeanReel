use leanreel_rs_lib::domain::models::*;
use leanreel_rs_lib::domain::traits::{MediaProber, SnapshotStore};
use leanreel_rs_lib::services::scanner::Scanner;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

struct CountingProber {
    call_count: Arc<Mutex<usize>>,
}
impl CountingProber {
    fn new() -> (Self, Arc<Mutex<usize>>) {
        let count = Arc::new(Mutex::new(0));
        (
            Self {
                call_count: count.clone(),
            },
            count,
        )
    }
}
impl MediaProber for CountingProber {
    fn probe(&self, _path: &Path) -> Result<VideoMetadata, String> {
        *self.call_count.lock().unwrap() += 1;
        Ok(VideoMetadata {
            codec: VideoCodec::H264,
            width: 1920,
            height: 1080,
            hdr_type: HdrType::Sdr,
            audio_tracks: vec![],
            subtitle_tracks: vec![],
            duration_seconds: 3600.0,
            bitrate_bps: 3_000_000,
            pix_fmt: String::new(),
            frame_rate: String::new(),
            color_primaries: String::new(),
            color_transfer: String::new(),
            color_space: String::new(),
        })
    }
    fn probe_batch(&self, paths: &[PathBuf]) -> Result<Vec<ProbeResult>, String> {
        Ok(paths
            .iter()
            .map(|p| {
                let meta = self.probe(p);
                ProbeResult {
                    path: p.clone(),
                    metadata: meta,
                }
            })
            .collect())
    }
}

struct CountingStore {
    upserted: Mutex<Vec<FileSnapshot>>,
    deleted: Arc<Mutex<Vec<String>>>,
}
impl CountingStore {
    fn new() -> (Self, Arc<Mutex<Vec<String>>>) {
        let deleted = Arc::new(Mutex::new(vec![]));
        (
            Self {
                upserted: Mutex::new(vec![]),
                deleted: deleted.clone(),
            },
            deleted,
        )
    }
}
impl SnapshotStore for CountingStore {
    fn upsert(&self, snapshots: &[FileSnapshot]) -> Result<usize, String> {
        self.upserted.lock().unwrap().extend_from_slice(snapshots);
        Ok(snapshots.len())
    }
    fn query(&self, _filter: &FileFilter) -> Result<Vec<FileSnapshot>, String> {
        Ok(self.upserted.lock().unwrap().clone())
    }
    fn mark_deleted(&self, _folder_id: i64, path: &Path) -> Result<bool, String> {
        self.deleted
            .lock()
            .unwrap()
            .push(path.to_string_lossy().to_string());
        Ok(true)
    }
    fn get_by_path(&self, _path: &Path) -> Result<Option<FileSnapshot>, String> {
        Ok(None)
    }
    fn random_snapshot(&self) -> Result<Option<FileSnapshot>, String> {
        Ok(None)
    }
    fn update_compression_runtime(
        &self,
        _record_id: i64,
        _status: &str,
        _progress: f64,
        _stage: &str,
        _duration_seconds: i64,
    ) -> Result<(), String> {
        Ok(())
    }
    fn finish_compression(
        &self,
        _record_id: i64,
        _status: &str,
        _progress: f64,
        _duration_seconds: i64,
        _compressed_size: i64,
        _error_message: &str,
        _sidecar_path: &str,
        _source_deleted: i32,
        _ffmpeg_command: &str,
    ) -> Result<(), String> {
        Ok(())
    }
}

#[test]
fn test_scanner_constructs() {
    let (prober, _) = CountingProber::new();
    let (store, _) = CountingStore::new();
    let scanner = Scanner::new(Box::new(prober), Box::new(store));
    assert!(scanner.store_borrow().is_ok());
}

#[test]
fn test_scanner_scan_nonexistent_dir() {
    let (prober, _) = CountingProber::new();
    let (store, _) = CountingStore::new();
    let scanner = Scanner::new(Box::new(prober), Box::new(store));
    let result = scanner.scan_directory(Path::new("nonexistent_12345"), 1);
    assert!(
        result.is_err(),
        "Unavailable roots must not be treated as empty scans"
    );
}

#[test]
fn test_scanner_scan_empty_dir() {
    let dir = std::env::temp_dir().join("leanreel_test_empty_scan");
    std::fs::create_dir_all(&dir).unwrap();
    let (prober, _) = CountingProber::new();
    let (store, _) = CountingStore::new();
    let scanner = Scanner::new(Box::new(prober), Box::new(store));
    let result = scanner.scan_directory(&dir, 1).unwrap();
    std::fs::remove_dir_all(&dir).ok();
    assert_eq!(result.total_files, 0);
    assert_eq!(result.probe_ok, 0);
}

#[test]
fn test_scanner_probes_and_stores_real_file() {
    let dir = std::env::temp_dir().join("leanreel_test_real_scan");
    std::fs::create_dir_all(&dir).unwrap();
    std::fs::write(dir.join("test_video.mkv"), b"fake video content").unwrap();
    let (prober, _) = CountingProber::new();
    let (store, _) = CountingStore::new();
    let scanner = Scanner::new(Box::new(prober), Box::new(store));
    let result = scanner.scan_directory(&dir, 1).unwrap();
    std::fs::remove_dir_all(&dir).ok();
    assert_eq!(result.total_files, 1);
    assert_eq!(result.probe_ok, 1);
    assert_eq!(result.probe_failed, 0);
    let upserted = scanner.store_borrow().unwrap();
    assert_eq!(upserted.len(), 1);
    assert!(upserted[0].size_bytes > 0, "Should have real file size");
    assert!(upserted[0].file_mtime > 0.0, "Should have real mtime");
    assert_eq!(upserted[0].file_name, "test_video.mkv");
    assert_eq!(upserted[0].probe_ok, true);
}

#[test]
fn test_scanner_skips_unchanged_files_on_second_scan() {
    let dir = std::env::temp_dir().join("leanreel_test_second_scan");
    std::fs::create_dir_all(&dir).unwrap();
    std::fs::write(dir.join("movie.mkv"), b"some content").unwrap();
    let (prober, probe_count) = CountingProber::new();
    let (store, _) = CountingStore::new();
    let scanner = Scanner::new(Box::new(prober), Box::new(store));
    let result1 = scanner.scan_directory(&dir, 1).unwrap();
    assert_eq!(result1.total_files, 1);
    assert_eq!(result1.probe_ok, 1);
    let count_after_first = *probe_count.lock().unwrap();
    let result2 = scanner.scan_directory(&dir, 1).unwrap();
    assert_eq!(result2.total_files, 1);
    assert_eq!(result2.probe_ok, 1);
    assert_eq!(
        *probe_count.lock().unwrap(),
        count_after_first,
        "Should NOT re-probe unchanged files"
    );
    std::fs::remove_dir_all(&dir).ok();
}

#[test]
fn test_scanner_cleans_orphans() {
    let dir = std::env::temp_dir().join("leanreel_test_orphan_clean");
    std::fs::create_dir_all(&dir).unwrap();
    std::fs::write(dir.join("movie1.mkv"), b"content a").unwrap();
    std::fs::write(dir.join("movie2.mkv"), b"content b").unwrap();
    let (prober, _) = CountingProber::new();
    let (store, deleted_paths) = CountingStore::new();
    let scanner = Scanner::new(Box::new(prober), Box::new(store));
    let result1 = scanner.scan_directory(&dir, 1).unwrap();
    assert_eq!(result1.total_files, 2);
    std::fs::remove_file(dir.join("movie2.mkv")).unwrap();
    let result2 = scanner.scan_directory(&dir, 1).unwrap();
    assert_eq!(result2.total_files, 1);
    let deleted = deleted_paths.lock().unwrap();
    assert!(
        deleted.iter().any(|p| p.contains("movie2.mkv")),
        "Orphan should be deleted: {:?}",
        *deleted
    );
    std::fs::remove_dir_all(&dir).ok();
}

// ── H-004: Scanner per-file result callback tests ─────────────────────────

#[test]
fn test_scanner_on_result_fires_for_each_file() {
    use std::sync::{Arc, Mutex};
    let dir = std::env::temp_dir().join("leanreel_test_on_result");
    std::fs::create_dir_all(&dir).unwrap();
    std::fs::write(dir.join("movie_a.mkv"), b"content a").unwrap();
    std::fs::write(dir.join("movie_b.mkv"), b"content b").unwrap();
    let (prober, _) = CountingProber::new();
    let (store, _) = CountingStore::new();

    let results: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(Vec::new()));
    let results_clone = results.clone();
    let scanner = Scanner::new(Box::new(prober), Box::new(store)).with_on_result(Box::new(
        move |snap: &FileSnapshot| {
            results_clone.lock().unwrap().push(snap.file_name.clone());
        },
    ));

    let _ = scanner.scan_directory(&dir, 1).unwrap();
    std::fs::remove_dir_all(&dir).ok();

    let captured = results.lock().unwrap();
    assert_eq!(
        captured.len(),
        4,
        "on_result should emit a placeholder and final result for each file"
    );
    assert!(captured.iter().any(|n| n == "movie_a.mkv"));
    assert!(captured.iter().any(|n| n == "movie_b.mkv"));
}

#[test]
fn test_scanner_on_result_fires_for_cached_files_on_second_scan() {
    use std::sync::{Arc, Mutex};
    let dir = std::env::temp_dir().join("leanreel_test_on_result_cached2");
    std::fs::create_dir_all(&dir).unwrap();
    std::fs::write(dir.join("keep.mkv"), b"content").unwrap();

    let (prober, probe_count) = CountingProber::new();
    let (store, _) = CountingStore::new();
    let results: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(Vec::new()));
    let results_clone = results.clone();

    let scanner = Scanner::new(Box::new(prober), Box::new(store)).with_on_result(Box::new(
        move |snap: &FileSnapshot| {
            results_clone.lock().unwrap().push(snap.file_name.clone());
        },
    ));

    // First scan — probes and saves
    let _ = scanner.scan_directory(&dir, 1).unwrap();

    // Second scan — same scanner, should use cache
    // Clear results to track second scan's callbacks separately
    results.lock().unwrap().clear();
    let _ = scanner.scan_directory(&dir, 1).unwrap();

    std::fs::remove_dir_all(&dir).ok();

    // on_result should fire for the cached file on the second scan
    let captured = results.lock().unwrap();
    assert_eq!(
        captured.len(),
        1,
        "on_result should fire for cached files too"
    );
    assert_eq!(captured[0], "keep.mkv");
    // The probe count should NOT have increased on the second scan
    // (one probe total from first scan, unchanged on second)
    assert_eq!(
        *probe_count.lock().unwrap(),
        1,
        "Cached files should not be re-probed"
    );
}

#[test]
fn test_scanner_on_result_receives_probe_metadata() {
    use std::sync::{Arc, Mutex};
    let dir = std::env::temp_dir().join("leanreel_test_on_result_meta");
    std::fs::create_dir_all(&dir).unwrap();
    std::fs::write(dir.join("video.mkv"), b"video content").unwrap();
    let (prober, _) = CountingProber::new();
    let (store, _) = CountingStore::new();

    let snaps: Arc<Mutex<Vec<FileSnapshot>>> = Arc::new(Mutex::new(Vec::new()));
    let snaps_clone = snaps.clone();
    let scanner = Scanner::new(Box::new(prober), Box::new(store)).with_on_result(Box::new(
        move |snap: &FileSnapshot| {
            snaps_clone.lock().unwrap().push(snap.clone());
        },
    ));

    let _ = scanner.scan_directory(&dir, 1).unwrap();
    std::fs::remove_dir_all(&dir).ok();

    let captured = snaps.lock().unwrap();
    assert_eq!(captured.len(), 2);
    // Verify probe metadata is present
    assert!(
        !captured[0].probe_ok,
        "First callback should expose a pending placeholder"
    );
    let final_snapshot = captured.last().unwrap();
    assert_eq!(final_snapshot.video_codec, VideoCodec::H264);
    assert_eq!(final_snapshot.video_width, 1920);
    assert_eq!(final_snapshot.video_height, 1080);
    assert!(final_snapshot.probe_ok);
    // H-029: New extended fields should be present (CountingProber returns empty strings)
    assert_eq!(final_snapshot.pix_fmt, "");
}
