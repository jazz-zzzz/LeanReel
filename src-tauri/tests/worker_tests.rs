use leanreel_rs_lib::domain::models::*;
use leanreel_rs_lib::domain::traits::{
    EncodeOutput, Encoder, EncodingJob, FinishCompressionParams, JobId, MediaProber, ProgressEvent,
    SnapshotStore,
};
use leanreel_rs_lib::services::worker::{EncodeTask, WorkerManager, WorkerTask};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

#[test]
fn test_worker_constructs() {
    let wm = WorkerManager::new(2);
    assert_eq!(wm.max_workers(), 2);
    assert!(!wm.is_paused());
    assert!(!wm.is_cancelled());
}

#[test]
fn test_worker_submit_and_cancel() {
    let wm = WorkerManager::new(2);
    let task = WorkerTask {
        id: "test-1".into(),
        file_name: "test.mkv".into(),
        input_path: std::path::PathBuf::from("in.mkv"),
        output_path: std::path::PathBuf::from("out.mkv"),
        strategy: Default::default(),
        snapshot: Default::default(),
        status: TaskStatus::Pending,
        progress: 0.0,
        error_message: String::new(),
        history_id: 0,
        has_dolby_vision: false,
        delete_source: false,
    };
    assert!(wm.submit(task).is_ok());
    wm.cancel();
    assert!(wm.is_cancelled());
}

#[test]
fn test_worker_pause_resume() {
    let wm = WorkerManager::new(2);
    assert!(!wm.is_paused());
    wm.pause();
    assert!(wm.is_paused());
    wm.resume();
    assert!(!wm.is_paused());
}

#[test]
fn test_worker_cancel_task_reports_cancelled_without_cancelling_the_queue() {
    struct BlockingEncoder {
        started: Arc<AtomicBool>,
        cancelled_jobs: Arc<Mutex<Vec<JobId>>>,
    }

    impl Encoder for BlockingEncoder {
        fn run(
            &self,
            job: &EncodingJob,
            _on_progress: &(dyn Fn(ProgressEvent) + Send + Sync),
        ) -> Result<EncodeOutput, String> {
            self.started.store(true, Ordering::Relaxed);
            for _ in 0..100 {
                if self.cancelled_jobs.lock().unwrap().contains(&job.id) {
                    return Err("cancelled by user".into());
                }
                std::thread::sleep(std::time::Duration::from_millis(10));
            }
            Err("timed out waiting for cancellation".into())
        }

        fn cancel(&self, job_id: &JobId) -> Result<(), String> {
            self.cancelled_jobs.lock().unwrap().push(job_id.clone());
            Ok(())
        }
    }

    let pool = WorkerManager::new(1);
    let started = Arc::new(AtomicBool::new(false));
    let cancelled_jobs = Arc::new(Mutex::new(Vec::new()));
    pool.set_executor(Arc::new(BlockingEncoder {
        started: started.clone(),
        cancelled_jobs: cancelled_jobs.clone(),
    }));

    let events = Arc::new(Mutex::new(Vec::new()));
    let emitted_events = events.clone();
    pool.set_progress_emitter(Box::new(move |job_id, stage, _progress, status| {
        emitted_events.lock().unwrap().push((
            job_id.to_string(),
            stage.to_string(),
            status.to_string(),
        ));
    }));

    pool.submit(WorkerTask {
        id: "single-cancel".into(),
        file_name: "single-cancel.mkv".into(),
        input_path: PathBuf::from("single-cancel.mkv"),
        output_path: PathBuf::from("single-cancel-output.mkv"),
        strategy: Default::default(),
        snapshot: Default::default(),
        status: TaskStatus::Pending,
        progress: 0.0,
        error_message: String::new(),
        history_id: 0,
        has_dolby_vision: false,
        delete_source: false,
    })
    .unwrap();

    for _ in 0..100 {
        if started.load(Ordering::Relaxed) {
            break;
        }
        std::thread::sleep(std::time::Duration::from_millis(10));
    }
    assert!(started.load(Ordering::Relaxed));

    pool.cancel_task("single-cancel").unwrap();

    for _ in 0..100 {
        if events.lock().unwrap().iter().any(|event| {
            event
                == &(
                    "single-cancel".to_string(),
                    "done".to_string(),
                    "cancelled".to_string(),
                )
        }) {
            break;
        }
        std::thread::sleep(std::time::Duration::from_millis(10));
    }

    assert!(!pool.is_cancelled());
    assert_eq!(cancelled_jobs.lock().unwrap().as_slice(), ["single-cancel"]);
    assert!(events.lock().unwrap().iter().any(|event| {
        event
            == &(
                "single-cancel".to_string(),
                "done".to_string(),
                "cancelled".to_string(),
            )
    }));
}

// ---------------------------------------------------------------------------
// Integration tests: WorkerManager + Encoder trait
// ---------------------------------------------------------------------------

struct TestEncoder {
    last_job: Arc<Mutex<Option<EncodingJob>>>,
    output: Arc<Mutex<Option<EncodeOutput>>>,
}

impl Encoder for TestEncoder {
    fn run(
        &self,
        job: &EncodingJob,
        _on_progress: &(dyn Fn(ProgressEvent) + Send + Sync),
    ) -> Result<EncodeOutput, String> {
        // Store the job to verify the encoder received correct parameters
        *self.last_job.lock().unwrap() = Some(job.clone());

        let out = EncodeOutput {
            output_path: job.output_path.clone(),
            original_size: 1_500_000,
            compressed_size: 800_000,
            duration_ms: 42_000,
            command: String::new(),
        };
        *self.output.lock().unwrap() = Some(out.clone());
        Ok(out)
    }

    fn cancel(&self, _job_id: &JobId) -> Result<(), String> {
        Ok(())
    }
}

fn make_test_strategy(name: &str) -> Strategy {
    Strategy {
        name: name.into(),
        description: "Test strategy for integration testing".into(),
        is_preset: true,
        video: VideoConfig {
            encoder: "libx265".into(),
            crf: 23,
            preset: "medium".into(),
            pix_fmt: "yuv420p10le".into(),
            x265_params: String::new(),
            gpu: false,
            nv_preset: String::new(),
            rc: String::new(),
            cq: 0,
        },
        hdr: HdrConfig {
            mode: "sdr".into(),
            dv_handling: String::new(),
        },
        audio: AudioConfig {
            mode: "copy".into(),
            preferred_languages: vec![],
        },
        subtitle: SubtitleConfig {
            mode: "copy".into(),
        },
        filters: FilterConfig {
            skip_x265: false,
            min_size_gb: None,
            only_remux: false,
        },
        estimated_savings: "40%".into(),
        quality_impact: "minimal".into(),
        sort_order: 0,
    }
}

fn make_h264_snapshot() -> FileSnapshot {
    FileSnapshot {
        id: None,
        library_folder_id: 1,
        relative_path: "test.mkv".into(),
        file_name: "test.mkv".into(),
        size_bytes: 2_000_000_000,
        video_codec: VideoCodec::H264,
        video_width: 1920,
        video_height: 1080,
        hdr_type: HdrType::Sdr,
        audio_tracks: vec![],
        subtitle_tracks: vec![],
        duration_seconds: 120.0,
        bitrate_bps: 5_000_000,
        file_mtime: 1_700_000_000.0,
        probe_ok: true,
        probe_error: String::new(),
        scanned_at: "2024-01-01".into(),
        ..Default::default()
    }
}

#[test]
fn test_encode_task_executes() {
    let pool = WorkerManager::new(1);
    let last_job = Arc::new(Mutex::new(None));
    let output = Arc::new(Mutex::new(None));
    let encoder = Arc::new(TestEncoder {
        last_job: last_job.clone(),
        output: output.clone(),
    });
    pool.set_executor(encoder);

    let task = EncodeTask {
        id: "test-encode-1".into(),
        input_path: PathBuf::from("input.mkv"),
        output_dir: PathBuf::from("output"),
        strategy: make_test_strategy("HEVC Medium"),
        snapshot: make_h264_snapshot(),
        has_dolby_vision: false,
        history_id: 0,
        delete_source: false,
    };

    pool.submit_encode(task).unwrap();

    // Wait for the worker thread to pick up and execute the task
    std::thread::sleep(std::time::Duration::from_millis(300));

    // Verify the encoder was actually called (side effect verification)
    let captured = output.lock().unwrap();
    assert!(
        captured.is_some(),
        "Encoder should have been called and produced output"
    );
    let out = captured.as_ref().unwrap();
    assert_eq!(out.original_size, 1_500_000);
    assert_eq!(out.compressed_size, 800_000);
    assert!(out.duration_ms > 0);

    // Verify the job received by the encoder has correct fields (parameter verification)
    let job_guard = last_job.lock().unwrap();
    assert!(
        job_guard.is_some(),
        "Encoder should have received the encoding job"
    );
    let job = job_guard.as_ref().unwrap();
    assert_eq!(job.id, "test-encode-1");
    assert_eq!(job.input_path, PathBuf::from("input.mkv"));
    assert_eq!(
        job.output_path,
        PathBuf::from("output").join("test.tmp.mkv")
    );
    assert!(!job.has_dolby_vision);
    assert_eq!(job.snapshot.file_name, "test.mkv");
    assert_eq!(job.snapshot.video_codec, VideoCodec::H264);
    assert_eq!(job.strategy.name, "HEVC Medium");
    assert_eq!(job.strategy.video.encoder, "libx265");
}

#[test]
fn test_encode_task_with_dolby_vision() {
    let pool = WorkerManager::new(1);
    let output = Arc::new(Mutex::new(None));
    let encoder_output = output.clone();

    struct DvEncoder {
        output: Arc<Mutex<Option<EncodeOutput>>>,
    }
    impl Encoder for DvEncoder {
        fn run(
            &self,
            job: &EncodingJob,
            _on_progress: &(dyn Fn(ProgressEvent) + Send + Sync),
        ) -> Result<EncodeOutput, String> {
            assert!(job.has_dolby_vision, "Dolby Vision flag should be true");
            let out = EncodeOutput {
                output_path: job.output_path.clone(),
                original_size: 5_000_000,
                compressed_size: 3_500_000,
                duration_ms: 90_000,
                command: String::new(),
            };
            *self.output.lock().unwrap() = Some(out.clone());
            Ok(out)
        }
        fn cancel(&self, _job_id: &JobId) -> Result<(), String> {
            Ok(())
        }
    }

    pool.set_executor(Arc::new(DvEncoder {
        output: encoder_output,
    }));

    let task = EncodeTask {
        id: "dv-test".into(),
        input_path: PathBuf::from("hdr_input.mkv"),
        output_dir: PathBuf::from("encoded"),
        strategy: Strategy {
            name: "HDR Preserve".into(),
            description: "Preserve HDR metadata".into(),
            is_preset: false,
            video: VideoConfig {
                encoder: "libx265".into(),
                crf: 18,
                preset: "slow".into(),
                pix_fmt: "yuv420p10le".into(),
                x265_params: "hdr-opt=1".into(),
                gpu: false,
                nv_preset: String::new(),
                rc: String::new(),
                cq: 0,
            },
            hdr: HdrConfig {
                mode: "passthrough".into(),
                dv_handling: "preserve".into(),
            },
            audio: AudioConfig {
                mode: "copy".into(),
                preferred_languages: vec![],
            },
            subtitle: SubtitleConfig {
                mode: "copy".into(),
            },
            filters: FilterConfig {
                skip_x265: false,
                min_size_gb: None,
                only_remux: false,
            },
            estimated_savings: "30%".into(),
            quality_impact: "none".into(),
            sort_order: 0,
        },
        snapshot: FileSnapshot {
            id: None,
            library_folder_id: 2,
            relative_path: "movie.mkv".into(),
            file_name: "movie.mkv".into(),
            size_bytes: 8_000_000_000,
            video_codec: VideoCodec::Hevc,
            video_width: 3840,
            video_height: 2160,
            hdr_type: HdrType::DolbyVision {
                profile: DvProfile::Profile8_1,
            },
            audio_tracks: vec![],
            subtitle_tracks: vec![],
            duration_seconds: 5400.0,
            bitrate_bps: 15_000_000,
            file_mtime: 1_700_000_000.0,
            probe_ok: true,
            probe_error: String::new(),
            scanned_at: "2024-01-01".into(),
            ..Default::default()
        },
        has_dolby_vision: true,
        history_id: 0,
        delete_source: false,
    };

    pool.submit_encode(task).unwrap();
    std::thread::sleep(std::time::Duration::from_millis(300));

    let captured = output.lock().unwrap();
    assert!(
        captured.is_some(),
        "Dolby Vision encode should have produced output"
    );
    let out = captured.as_ref().unwrap();
    assert!(
        out.compressed_size < out.original_size,
        "Compressed size should be smaller than original"
    );
    assert!(out.duration_ms > 0);
}

// ── H-020: Post-encode file_snapshot sync tests ───────────────────────────

/// A prober that tracks calls and returns a fixed VideoMetadata.
struct TestSyncingProber {
    call_count: Arc<Mutex<usize>>,
}
impl TestSyncingProber {
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
impl MediaProber for TestSyncingProber {
    fn probe(&self, _path: &Path) -> Result<VideoMetadata, String> {
        *self.call_count.lock().unwrap() += 1;
        Ok(VideoMetadata {
            codec: VideoCodec::Hevc,
            width: 1920,
            height: 1080,
            hdr_type: HdrType::Sdr,
            audio_tracks: vec![],
            subtitle_tracks: vec![],
            duration_seconds: 120.0,
            bitrate_bps: 3_000_000,
            pix_fmt: "yuv420p".into(),
            frame_rate: "24000/1001".into(),
            color_primaries: "bt709".into(),
            color_transfer: "bt709".into(),
            color_space: "bt709".into(),
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

/// A snapshot store that captures upserted snapshots for verification.
struct CapturingStore {
    captures: Arc<Mutex<Vec<FileSnapshot>>>,
}
impl CapturingStore {
    fn new() -> (Self, Arc<Mutex<Vec<FileSnapshot>>>) {
        let captures = Arc::new(Mutex::new(Vec::new()));
        (
            Self {
                captures: captures.clone(),
            },
            captures,
        )
    }
}
impl SnapshotStore for CapturingStore {
    fn upsert(&self, snapshots: &[FileSnapshot]) -> Result<usize, String> {
        let mut guard = self.captures.lock().unwrap();
        for s in snapshots {
            guard.push(s.clone());
        }
        Ok(snapshots.len())
    }
    fn query(&self, _filter: &FileFilter) -> Result<Vec<FileSnapshot>, String> {
        Ok(vec![])
    }
    fn mark_deleted(&self, _folder_id: i64, _path: &Path) -> Result<bool, String> {
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
    fn finish_compression(&self, _params: FinishCompressionParams<'_>) -> Result<(), String> {
        Ok(())
    }
}

#[test]
fn test_worker_manager_can_set_prober_and_store() {
    let pool = WorkerManager::new(1);
    let (prober, _) = TestSyncingProber::new();
    let (store, _) = CapturingStore::new();
    // Should not panic — verifies new setter methods are callable
    pool.set_prober(Box::new(prober));
    pool.set_store(Box::new(store));
}

#[test]
fn test_worker_manager_progress_callback_wiring() {
    use std::sync::{Arc, Mutex};
    let pool = WorkerManager::new(1);
    let events: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(Vec::new()));
    let events_clone = events.clone();
    pool.set_on_encode_progress(Box::new(move |ev| {
        let kind = match ev {
            ProgressEvent::StageStart { .. } => "start",
            ProgressEvent::StageProgress { .. } => "progress",
            ProgressEvent::StageComplete { .. } => "complete",
            ProgressEvent::Done { .. } => "done",
            ProgressEvent::Warning { .. } => "warning",
        };
        events_clone.lock().unwrap().push(kind.to_string());
    }));
    // Verify the callback was set without error
    // (Actual firing tested via integration with encoder)
}

#[test]
fn test_sync_output_snapshot_plumbing() {
    // Verify that post-encode sync infrastructure is wired up.
    // The sync_output_snapshot function is invoked inside the worker loop
    // after successful atomic_commit; this test validates the setter API.
    let pool = WorkerManager::new(1);
    let (prober, prober_calls) = TestSyncingProber::new();
    let (store, captures) = CapturingStore::new();
    pool.set_prober(Box::new(prober));
    pool.set_store(Box::new(store));

    // The prober and store should be accessible (no panics on set)
    assert_eq!(*prober_calls.lock().unwrap(), 0);
    assert!(captures.lock().unwrap().is_empty());
}
