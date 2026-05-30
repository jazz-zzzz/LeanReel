use std::path::{Path, PathBuf};
use std::sync::mpsc;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use crate::domain::models::{FileSnapshot, Strategy, TaskStatus};
use crate::domain::traits::{Encoder, EncodingJob, MediaProber, ProgressEvent, SnapshotStore};
use crate::services::pipeline::{PipelinePlan, temp_output_path, atomic_commit, cleanup_temp};

#[derive(Debug, Clone)]
pub struct WorkerTask {
    pub id: String,
    pub file_name: String,
    pub input_path: PathBuf,
    pub output_path: PathBuf,
    pub strategy: Strategy,
    pub snapshot: FileSnapshot,
    pub status: TaskStatus,
    pub progress: f32,
    pub error_message: String,
    pub history_id: i64,
    pub has_dolby_vision: bool,
    pub delete_source: bool,
}

/// Encoding-specific task submitted to the worker pool.
/// Differs from WorkerTask in using `output_dir` (resolved to output path internally).
#[derive(Debug, Clone)]
pub struct EncodeTask {
    pub id: String,
    pub input_path: PathBuf,
    pub output_dir: PathBuf,
    pub strategy: Strategy,
    pub snapshot: FileSnapshot,
    pub has_dolby_vision: bool,
    /// ID of the compression_history record created before submission.
    /// Non-zero values enable DB runtime progress updates during encoding.
    pub history_id: i64,
    /// If true, delete the source file after successful encode.
    pub delete_source: bool,
}

/// Callback for progress events during encoding.
pub type ProgressCallback = Box<dyn Fn(ProgressEvent) + Send + 'static>;

/// A generic job that can be submitted for execution on the worker pool.
pub type Job = Box<dyn FnOnce() + Send + 'static>;

enum WorkerCommand {
    Submit(WorkerTask),
    Shutdown,
}

pub struct WorkerManager {
    max_workers: AtomicUsize,
    sender: mpsc::Sender<WorkerCommand>,
    paused: Arc<AtomicBool>,
    cancelled: Arc<AtomicBool>,
    executor: Arc<Mutex<Option<Arc<dyn Encoder + Send + Sync>>>>,
    /// Optional probe runner for post-encode file_snapshot sync (H-020)
    prober: Arc<Mutex<Option<Box<dyn MediaProber + Send>>>>,
    /// Optional snapshot store for post-encode file_snapshot sync (H-020)
    store: Arc<Mutex<Option<Box<dyn SnapshotStore + Send>>>>,
    join_handles: Mutex<Vec<thread::JoinHandle<()>>>,
    /// Last recorded progress value (0.0–1.0). Updated from encode progress callbacks.
    pub last_progress: Arc<Mutex<f32>>,
    /// Optional external progress callback during encoding
    pub on_encode_progress: Arc<Mutex<Option<ProgressCallback>>>,
}

impl WorkerManager {
    pub fn new(max_workers: usize) -> Self {
        let max = if max_workers == 0 { 2 } else { max_workers };
        let paused = Arc::new(AtomicBool::new(false));
        let cancelled = Arc::new(AtomicBool::new(false));
        let last_progress = Arc::new(Mutex::new(0.0f32));
        let executor: Arc<Mutex<Option<Arc<dyn Encoder + Send + Sync>>>> =
            Arc::new(Mutex::new(None));
        let prober: Arc<Mutex<Option<Box<dyn MediaProber + Send>>>> =
            Arc::new(Mutex::new(None));
        let store: Arc<Mutex<Option<Box<dyn SnapshotStore + Send>>>> =
            Arc::new(Mutex::new(None));
        let on_encode_progress: Arc<Mutex<Option<ProgressCallback>>> =
            Arc::new(Mutex::new(None));
        let (tx, rx) = mpsc::channel::<WorkerCommand>();
        let rx = Arc::new(Mutex::new(rx));
        let mut handles = Vec::new();

        for _ in 0..max {
            let rx = rx.clone();
            let paused = paused.clone();
            let cancelled = cancelled.clone();
            let last_progress = last_progress.clone();
            let executor = executor.clone();
            let prober = prober.clone();
            let store = store.clone();
            let on_encode_progress = on_encode_progress.clone();
            let handle = thread::spawn(move || loop {
                if cancelled.load(Ordering::Relaxed) { break; }
                let cmd = {
                    let lock = rx.lock().ok();
                    match lock {
                        Some(l) => l.recv(),
                        None => return,
                    }
                };
                match cmd {
                    Ok(WorkerCommand::Submit(task)) => {
                        while paused.load(Ordering::Relaxed) && !cancelled.load(Ordering::Relaxed) {
                            thread::sleep(Duration::from_millis(100));
                        }
                        if cancelled.load(Ordering::Relaxed) { break; }
                        if let Ok(guard) = executor.lock() {
                            if let Some(ref enc) = *guard {
                                let final_output = task.output_path.clone();
                                let temp_output = temp_output_path(&final_output);

                                let job = EncodingJob {
                                    id: task.id.clone(),
                                    input_path: task.input_path.clone(),
                                    output_path: temp_output.clone(),
                                    strategy: task.strategy.clone(),
                                    has_dolby_vision: task.has_dolby_vision,
                                    snapshot: task.snapshot.clone(),
                                };

                                // Build the multi-stage pipeline plan
                                let plan = Arc::new(Mutex::new(PipelinePlan::build(&job)));
                                let _num_stages = plan.lock().unwrap().len();

                                // ── Stage 1: Prepare ─────────────────────────
                                let prepare_idx = 0;
                                plan.lock().unwrap().start_stage(prepare_idx);
                                // C2: Update DB — preparing stage
                                update_runtime(&store, task.history_id, "running", 0.0, "preparing", 0);
                                // Prepare step: ensure parent directory exists
                                if let Some(parent) = job.output_path.parent() {
                                    if let Err(e) = std::fs::create_dir_all(parent) {
                                        plan.lock().unwrap().fail_stage(prepare_idx, format!("创建输出目录失败: {}", e));
                                        plan.lock().unwrap().skip_remaining(prepare_idx + 1);
                                        finish_record(&store, task.history_id, "failed", 0.0, 0, 0, &format!("创建输出目录失败: {}", e), "", 0, "");
                                        eprintln!("编码失败: {}", e);
                                        cleanup_temp(&final_output);
                                        continue;
                                    }
                                }
                                plan.lock().unwrap().complete_stage(prepare_idx);

                                // ── Stage 2: Extract RPU (DV only, with retry) ─
                                let mut rpu_file: Option<PathBuf> = None;
                                let transcode_idx;
                                if job.has_dolby_vision && plan.lock().unwrap().stages.len() > 3 {
                                    let extract_idx = 1;
                                    let extract_max_retries = {
                                        plan.lock().unwrap().stages.get(extract_idx)
                                            .map(|s| s.max_retries).unwrap_or(0)
                                    };
                                    plan.lock().unwrap().start_stage(extract_idx);
                                    // C2: Update DB — extracting_rpu stage
                                    update_runtime(&store, task.history_id, "running", 0.0, "extracting_rpu", 0);
                                    let rpu_path = job.output_path.with_extension("rpu");
                                    let mut extract_ok = false;
                                    for attempt in 0..=extract_max_retries {
                                        if cancelled.load(Ordering::Relaxed) { break; }
                                        if attempt > 0 {
                                            std::thread::sleep(Duration::from_millis(200));
                                        }
                                        match crate::infrastructure::dovi::DoviTool::extract_rpu(
                                            &job.input_path.to_string_lossy(),
                                            &rpu_path.to_string_lossy(),
                                        ) {
                                            Ok(()) => {
                                                rpu_file = Some(rpu_path);
                                                plan.lock().unwrap().complete_stage(extract_idx);
                                                extract_ok = true;
                                                break;
                                            }
                                            Err(e) => {
                                                if attempt < extract_max_retries {
                                                    eprintln!("RPU 提取失败，将重试 (第 {} 次): {}", attempt + 1, e);
                                                } else {
                                                    plan.lock().unwrap().fail_stage(extract_idx, e);
                                                    plan.lock().unwrap().skip_remaining(extract_idx + 1);
                                                    finish_record(&store, task.history_id, "failed", 0.0, 0, 0, "RPU 提取失败", "", 0, "");
                                                    eprintln!("RPU 提取失败");
                                                    cleanup_temp(&final_output);
                                                }
                                            }
                                        }
                                    }
                                    if !extract_ok { continue; }
                                    transcode_idx = 2;
                                } else {
                                    transcode_idx = 1;
                                }

                                // ── Stage 3: Transcode ───────────────────────
                                plan.lock().unwrap().start_stage(transcode_idx);
                                // C2: Update DB — transcoding stage start
                                update_runtime(&store, task.history_id, "running", 0.0, "transcoding", 0);
                                let plan_for_callback = plan.clone();
                                let store_for_progress = store.clone();
                                let history_id = task.history_id;
                                let result = enc.run(&job, &|event| {
                                    match &event {
                                        ProgressEvent::StageStart { .. } => {}
                                        ProgressEvent::StageProgress { percent, .. } => {
                                            plan_for_callback.lock().unwrap().set_stage_progress(transcode_idx, *percent);
                                            if let Ok(mut lp) = last_progress.lock() {
                                                *lp = *percent;
                                            }
                                            // C2: Update DB progress periodically
                                            update_runtime(&store_for_progress, history_id, "running", *percent as f64, "transcoding", 0);
                                            // H-004: Fire external progress callback
                                            if let Ok(cb_guard) = on_encode_progress.lock() {
                                                if let Some(ref cb) = *cb_guard {
                                                    cb(ProgressEvent::StageProgress { percent: *percent, fps: 0.0, bitrate_kbps: 0 });
                                                }
                                            }
                                        }
                                        ProgressEvent::StageComplete { .. } => {}
                                        ProgressEvent::Done { .. } => {}
                                        ProgressEvent::Warning { message } => {
                                            eprintln!("编码警告: {}", message);
                                        }
                                    }
                                });

                                match result {
                                    Ok(output) => {
                                        // C19: Oversize guard — discard output when compressed >= original
                                        if output.compressed_size >= output.original_size {
                                            eprintln!(
                                                "输出大于源文件，已丢弃: {} -> {} ({} -> {} bytes)",
                                                task.input_path.display(),
                                                output.output_path.display(),
                                                output.original_size,
                                                output.compressed_size,
                                            );
                                            let _ = std::fs::remove_file(&output.output_path);
                                            eprintln!("超大输出文件已删除: {}", output.output_path.display());
                                            plan.lock().unwrap().fail_stage(transcode_idx, "输出大于源文件");
                                            plan.lock().unwrap().skip_remaining(transcode_idx + 1);
                                            // C2: Mark as discarded in DB
                                            finish_record(&store, task.history_id, "discarded", 100.0, (output.duration_ms / 1000) as i64, output.compressed_size as i64, "", "", 0, &output.command);
                                            cleanup_temp(&final_output);
                                            continue;
                                        }
                                        plan.lock().unwrap().complete_stage(transcode_idx);

                                        // ── Stage 4: Inject RPU (DV only, with retry) ─
                                        let move_out_idx;
                                        if let Some(ref rpu_path) = rpu_file {
                                            let inject_idx = transcode_idx + 1;
                                            let inject_max_retries = {
                                                plan.lock().unwrap().stages.get(inject_idx)
                                                    .map(|s| s.max_retries).unwrap_or(0)
                                            };
                                            plan.lock().unwrap().start_stage(inject_idx);
                                            // C2: Update DB — injecting_rpu stage
                                            update_runtime(&store, task.history_id, "running", 0.0, "injecting_rpu", 0);
                                            let injected_path = job.output_path.with_extension("injected.mkv");
                                            let mut inject_ok = false;
                                            for attempt in 0..=inject_max_retries {
                                                if cancelled.load(Ordering::Relaxed) { break; }
                                                if attempt > 0 {
                                                    std::thread::sleep(Duration::from_millis(200));
                                                    // Clean up any leftover injected file from previous attempt
                                                    let _ = std::fs::remove_file(&injected_path);
                                                }
                                                match crate::infrastructure::dovi::DoviTool::inject_rpu(
                                                    &job.output_path.to_string_lossy(),
                                                    &rpu_path.to_string_lossy(),
                                                    &injected_path.to_string_lossy(),
                                                ) {
                                                    Ok(()) => {
                                                        // Replace transcoded temp with injected output
                                                        let _ = std::fs::remove_file(&job.output_path);
                                                        if let Err(e) = std::fs::rename(&injected_path, &job.output_path) {
                                                            if attempt < inject_max_retries {
                                                                eprintln!("重命名注入文件失败，将重试: {}", e);
                                                                continue;
                                                            }
                                                            plan.lock().unwrap().fail_stage(inject_idx, format!("重命名注入文件失败: {}", e));
                                                            plan.lock().unwrap().skip_remaining(inject_idx + 1);
                                                            finish_record(&store, task.history_id, "failed", 0.0, 0, 0, &format!("重命名注入文件失败: {}", e), "", 0, "");
                                                            cleanup_temp(&final_output);
                                                            continue;
                                                        }
                                                        plan.lock().unwrap().complete_stage(inject_idx);
                                                        inject_ok = true;
                                                        break;
                                                    }
                                                    Err(e) => {
                                                        if attempt < inject_max_retries {
                                                            eprintln!("RPU 注入失败，将重试 (第 {} 次): {}", attempt + 1, e);
                                                        } else {
                                                            plan.lock().unwrap().fail_stage(inject_idx, e);
                                                            plan.lock().unwrap().skip_remaining(inject_idx + 1);
                                                            finish_record(&store, task.history_id, "failed", 0.0, 0, 0, "RPU 注入失败", "", 0, "");
                                                            cleanup_temp(&final_output);
                                                        }
                                                    }
                                                }
                                            }
                                            if !inject_ok { continue; }
                                            // Clean up RPU file
                                            let _ = std::fs::remove_file(rpu_path);
                                            move_out_idx = inject_idx + 1;
                                        } else {
                                            move_out_idx = transcode_idx + 1;
                                        }

                                        // ── Stage 5: Move Out (atomic commit with retry) ─
                                        let move_out_max_retries = {
                                            plan.lock().unwrap().stages.get(move_out_idx)
                                                .map(|s| s.max_retries).unwrap_or(0)
                                        };
                                        plan.lock().unwrap().start_stage(move_out_idx);
                                        // C2: Update DB — moving_out stage
                                        update_runtime(&store, task.history_id, "running", 0.0, "moving_out", 0);
                                        let mut move_out_ok = false;
                                        for attempt in 0..=move_out_max_retries {
                                            if cancelled.load(Ordering::Relaxed) { break; }
                                            if attempt > 0 {
                                                std::thread::sleep(Duration::from_millis(300));
                                                eprintln!("重试原子提交 (第 {} 次)", attempt);
                                            }
                                            match atomic_commit(&job.output_path, &final_output) {
                                                Ok(()) => {
                                                    plan.lock().unwrap().complete_stage(move_out_idx);
                                                    move_out_ok = true;
                                                    break;
                                                }
                                                Err(e) => {
                                                    if attempt < move_out_max_retries {
                                                        eprintln!("原子提交失败，将重试: {}", e);
                                                    } else {
                                                        plan.lock().unwrap().fail_stage(move_out_idx, format!("原子提交失败 (已重试{}次): {}", move_out_max_retries, e));
                                                        plan.lock().unwrap().skip_remaining(move_out_idx + 1);
                                                        finish_record(&store, task.history_id, "failed", 0.0, 0, 0, &format!("原子提交失败 (已重试{}次): {}", move_out_max_retries, e), "", 0, "");
                                                        cleanup_temp(&final_output);
                                                        eprintln!("原子提交失败: {}", e);
                                                    }
                                                }
                                            }
                                        }
                                        if !move_out_ok { continue; }

                                        // Write audit sidecar on successful encode
                                        let output_codec = &task.strategy.video.encoder;
                                        let audit = crate::services::audit::build_audit(
                                            &task.snapshot,
                                            &final_output,
                                            output.compressed_size,
                                            output_codec,
                                            &task.strategy,
                                            output.duration_ms,
                                            true,
                                            "",
                                            &output.command,
                                        );
                                        let sidecar_path = format!("{}.audit.json", final_output.display());
                                        if let Err(e) = crate::services::audit::write_sidecar(&final_output, &audit) {
                                            eprintln!("写入审计文件失败: {}", e);
                                        }

                                        // ── H-020: Post-encode file_snapshot sync ──
                                        // Re-probe the output file and insert/update file_snapshot
                                        let library_folder_id = task.snapshot.library_folder_id;
                                        sync_output_snapshot(
                                            &prober, &store, library_folder_id,
                                            &task.snapshot.relative_path, &final_output,
                                        );

                                        // C2: Mark compression record as completed
                                        finish_record(
                                            &store, task.history_id, "completed", 100.0,
                                            (output.duration_ms / 1000) as i64,
                                            output.compressed_size as i64,
                                            "", &sidecar_path, 0, &output.command,
                                        );

                                        eprintln!(
                                            "编码完成: {} -> {} ({} -> {} bytes) [progress: {:.1}%]",
                                            task.input_path.display(),
                                            final_output.display(),
                                            output.original_size,
                                            output.compressed_size,
                                            plan.lock().unwrap().overall_progress() * 100.0,
                                        );
                                    }
                                    Err(e) => {
                                        plan.lock().unwrap().fail_stage(transcode_idx, e.clone());
                                        plan.lock().unwrap().skip_remaining(transcode_idx + 1);
                                        // C2: Mark compression record as failed
                                        finish_record(&store, task.history_id, "failed", 0.0, 0, 0, &e, "", 0, "");
                                        cleanup_temp(&final_output);
                                        eprintln!("编码失败: {}", e);
                                    }
                                }
                            }
                        }
                    }
                    Ok(WorkerCommand::Shutdown) | Err(_) => break,
                }
            });
            handles.push(handle);
        }
        Self { max_workers: AtomicUsize::new(max), sender: tx, paused, cancelled, executor, prober, store, join_handles: Mutex::new(handles), last_progress, on_encode_progress }
    }

    pub fn max_workers(&self) -> usize { self.max_workers.load(Ordering::Relaxed) }
    /// Update the worker count setting. Dynamic thread pool resize is not
    /// supported at runtime; this updates the recorded count for diagnostics
    /// and will take effect on the next app restart.
    pub fn set_worker_count(&self, count: usize) {
        self.max_workers.store(count.max(1).min(16), Ordering::Relaxed);
    }
    pub fn set_executor(&self, enc: Arc<dyn Encoder + Send + Sync>) {
        if let Ok(mut guard) = self.executor.lock() { *guard = Some(enc); }
    }
    /// Set the prober for post-encode file_snapshot sync (H-020).
    pub fn set_prober(&self, p: Box<dyn MediaProber + Send>) {
        if let Ok(mut guard) = self.prober.lock() { *guard = Some(p); }
    }
    /// Set the snapshot store for post-encode file_snapshot sync (H-020).
    pub fn set_store(&self, s: Box<dyn SnapshotStore + Send>) {
        if let Ok(mut guard) = self.store.lock() { *guard = Some(s); }
    }
    /// Set the progress callback for encoding progress (H-004 pipeline).
    pub fn set_on_encode_progress(&self, cb: ProgressCallback) {
        if let Ok(mut guard) = self.on_encode_progress.lock() { *guard = Some(cb); }
    }
    pub fn submit(&self, task: WorkerTask) -> Result<(), String> {
        self.sender.send(WorkerCommand::Submit(task)).map_err(|e| format!("submit failed: {}", e))
    }

    /// Submit an encoding task. Derives the output path from output_dir and the snapshot file name,
    /// then delegates to the internal channel.
    pub fn submit_encode(&self, task: EncodeTask) -> Result<(), String> {
        let output_path = task.output_dir.join(&task.snapshot.file_name);
        let worker_task = WorkerTask {
            id: task.id,
            file_name: task.snapshot.file_name.clone(),
            input_path: task.input_path,
            output_path,
            strategy: task.strategy,
            snapshot: task.snapshot,
            status: TaskStatus::Pending,
            progress: 0.0,
            error_message: String::new(),
            history_id: task.history_id,
            has_dolby_vision: task.has_dolby_vision,
            delete_source: task.delete_source,
        };
        self.submit(worker_task)
    }

    pub fn pause(&self) { self.paused.store(true, Ordering::Relaxed); }
    pub fn resume(&self) { self.paused.store(false, Ordering::Relaxed); }
    /// Cancel all pending and running tasks.
    ///
    /// Sets the cancelled flag so queued tasks will be skipped, and
    /// attempts to kill the currently running ffmpeg process via the
    /// encoder's cancel() method.
    pub fn cancel(&self) {
        self.cancelled.store(true, Ordering::Relaxed);
        self.paused.store(false, Ordering::Relaxed);
        // Try to cancel any running encode
        if let Ok(guard) = self.executor.lock() {
            if let Some(ref enc) = *guard {
                let _ = enc.cancel(&"".to_string());
            }
        }
    }
    pub fn is_paused(&self) -> bool { self.paused.load(Ordering::Relaxed) }
    pub fn is_cancelled(&self) -> bool { self.cancelled.load(Ordering::Relaxed) }
}

/// C2: Update compression_history runtime status during encoding.
/// No-op when the store is not set or history_id is 0.
fn update_runtime(
    store: &Arc<Mutex<Option<Box<dyn SnapshotStore + Send>>>>,
    history_id: i64,
    status: &str,
    progress: f64,
    stage: &str,
    duration_seconds: i64,
) {
    if history_id == 0 { return; }
    if let Ok(guard) = store.lock() {
        if let Some(ref s) = *guard {
            if let Err(e) = s.update_compression_runtime(history_id, status, progress, stage, duration_seconds) {
                eprintln!("DB 运行时更新失败 (id={}): {}", history_id, e);
            }
        }
    }
}

/// C2: Finalize a compression_history record at encode end.
/// No-op when the store is not set or history_id is 0.
fn finish_record(
    store: &Arc<Mutex<Option<Box<dyn SnapshotStore + Send>>>>,
    history_id: i64,
    status: &str,
    progress: f64,
    duration_seconds: i64,
    compressed_size: i64,
    error_message: &str,
    sidecar_path: &str,
    source_deleted: i32,
    ffmpeg_command: &str,
) {
    if history_id == 0 { return; }
    if let Ok(guard) = store.lock() {
        if let Some(ref s) = *guard {
            if let Err(e) = s.finish_compression(history_id, status, progress, duration_seconds, compressed_size, error_message, sidecar_path, source_deleted, ffmpeg_command) {
                eprintln!("DB 完成记录失败 (id={}): {}", history_id, e);
            }
        }
    }
}

/// H-020: Post-encode file_snapshot sync.
///
/// After a successful encode, re-probe the output file and insert/update the
/// file_snapshot table so that subsequent scans can recognize the new file.
/// Mirrors Python `FFmpegExecutor._sync_file_snapshot`.
fn sync_output_snapshot(
    prober: &Arc<Mutex<Option<Box<dyn MediaProber + Send>>>>,
    store: &Arc<Mutex<Option<Box<dyn SnapshotStore + Send>>>>,
    library_folder_id: i64,
    source_relative_path: &str,
    final_output: &Path,
) {
    if library_folder_id == 0 {
        return;
    }

    let prober_guard = match prober.lock() {
        Ok(g) => g,
        Err(_) => return,
    };
    let prober = match prober_guard.as_ref() {
        Some(p) => p,
        None => return,
    };

    // Compute the output relative_path (same directory as source)
    let source_dir = std::path::Path::new(source_relative_path)
        .parent()
        .and_then(|p| p.to_str())
        .unwrap_or("");
    let output_name = final_output
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("unknown");
    let output_rel = if source_dir.is_empty() {
        output_name.to_string()
    } else {
        format!("{}/{}", source_dir, output_name)
    };

    // Probe the output file
    let metadata = match prober.probe(final_output) {
        Ok(m) => m,
        Err(e) => {
            eprintln!("输出文件探测失败 ({}): {}", final_output.display(), e);
            return;
        }
    };

    let file_mtime = std::fs::metadata(final_output)
        .ok()
        .and_then(|m| m.modified().ok())
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0);

    let size = std::fs::metadata(final_output)
        .ok()
        .map(|m| m.len() as i64)
        .unwrap_or(0);

    let snap = FileSnapshot {
        id: None,
        library_folder_id,
        relative_path: output_rel.replace('\\', "/"),
        file_name: output_name.to_string(),
        size_bytes: size,
        video_codec: metadata.codec,
        video_width: metadata.width,
        video_height: metadata.height,
        hdr_type: metadata.hdr_type,
        audio_tracks: metadata.audio_tracks,
        subtitle_tracks: metadata.subtitle_tracks,
        duration_seconds: metadata.duration_seconds,
        bitrate_bps: metadata.bitrate_bps,
        file_mtime,
        probe_ok: true,
        probe_error: String::new(),
        scanned_at: crate::services::time_utils::local_now(),
        pix_fmt: metadata.pix_fmt,
        frame_rate: metadata.frame_rate,
        color_primaries: metadata.color_primaries,
        color_transfer: metadata.color_transfer,
        color_space: metadata.color_space,
    };

    let store_guard = match store.lock() {
        Ok(g) => g,
        Err(_) => return,
    };
    let store = match store_guard.as_ref() {
        Some(s) => s,
        None => return,
    };

    if let Err(e) = store.upsert(&[snap]) {
        eprintln!("保存输出快照失败: {}", e);
    }
}

impl Drop for WorkerManager {
    fn drop(&mut self) {
        for _ in 0..self.max_workers.load(Ordering::Relaxed) { let _ = self.sender.send(WorkerCommand::Shutdown); }
        if let Ok(mut handles) = self.join_handles.lock() {
            while let Some(h) = handles.pop() { let _ = h.join(); }
        }
    }
}
