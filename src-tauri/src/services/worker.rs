use crate::domain::models::{FileSnapshot, Strategy, TaskStatus};
use crate::domain::traits::{
    Encoder, EncodingJob, FinishCompressionParams, MediaProber, ProgressEvent, SnapshotStore,
};
use crate::services::pipeline::{atomic_commit, cleanup_temp, temp_output_path, PipelinePlan};
use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;
use tauri::Emitter;

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

/// Callback for forwarding worker progress to an external UI layer.
pub type ProgressEmitter = Box<dyn Fn(&str, &str, f64, &str) + Send + Sync + 'static>;

/// A generic job that can be submitted for execution on the worker pool.
pub type Job = Box<dyn FnOnce() + Send + 'static>;

enum WorkerCommand {
    Submit(Box<WorkerTask>, usize),
    Shutdown,
}

/// RAII guard that returns a GPU encode slot to the pool on drop.
struct GpuToken {
    sender: mpsc::Sender<()>,
}

impl Drop for GpuToken {
    fn drop(&mut self) {
        let _ = self.sender.send(());
    }
}

/// Maximum concurrent NVENC encode sessions for consumer GPUs (driver-limited to 3).
const MAX_GPU_ENCODES: usize = 3;

pub struct WorkerManager {
    max_workers: AtomicUsize,
    sender: mpsc::Sender<WorkerCommand>,
    paused: Arc<AtomicBool>,
    cancelled: Arc<AtomicBool>,
    cancel_generation: Arc<AtomicUsize>,
    cancelled_jobs: Arc<Mutex<HashSet<String>>>,
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
    /// Optional UI adapter for forwarding progress events.
    pub progress_emitter: Arc<Mutex<Option<ProgressEmitter>>>,
    /// Token-based semaphore limiting concurrent GPU (NVENC) encodes.
    /// Consumer GPUs are driver-capped at 3 concurrent NVENC sessions.
    /// Fields are held only to keep the channel alive; tokens are exchanged
    /// via Arc clones held by worker threads.
    #[allow(dead_code)]
    gpu_token_tx: Arc<mpsc::Sender<()>>,
    #[allow(dead_code)]
    gpu_token_rx: Arc<Mutex<mpsc::Receiver<()>>>,
}

fn is_task_cancelled(
    cancel_generation: &AtomicUsize,
    task_generation: usize,
    cancelled_jobs: &Mutex<HashSet<String>>,
    job_id: &str,
) -> bool {
    cancel_generation.load(Ordering::Relaxed) != task_generation
        || cancelled_jobs
            .lock()
            .map(|jobs| jobs.contains(job_id))
            .unwrap_or(false)
}

fn clear_cancelled_task(cancelled_jobs: &Mutex<HashSet<String>>, job_id: &str) {
    if let Ok(mut jobs) = cancelled_jobs.lock() {
        jobs.remove(job_id);
    }
}

impl WorkerManager {
    pub fn new(max_workers: usize) -> Self {
        let max = if max_workers == 0 { 2 } else { max_workers };
        let paused = Arc::new(AtomicBool::new(false));
        let cancelled = Arc::new(AtomicBool::new(false));
        let cancel_generation = Arc::new(AtomicUsize::new(0));
        let cancelled_jobs = Arc::new(Mutex::new(HashSet::new()));
        let last_progress = Arc::new(Mutex::new(0.0f32));
        let executor: Arc<Mutex<Option<Arc<dyn Encoder + Send + Sync>>>> =
            Arc::new(Mutex::new(None));
        let prober: Arc<Mutex<Option<Box<dyn MediaProber + Send>>>> = Arc::new(Mutex::new(None));
        let store: Arc<Mutex<Option<Box<dyn SnapshotStore + Send>>>> = Arc::new(Mutex::new(None));
        let on_encode_progress: Arc<Mutex<Option<ProgressCallback>>> = Arc::new(Mutex::new(None));
        let progress_emitter: Arc<Mutex<Option<ProgressEmitter>>> = Arc::new(Mutex::new(None));
        let (tx, rx) = mpsc::channel::<WorkerCommand>();
        let rx = Arc::new(Mutex::new(rx));

        // GPU semaphore: channel with MAX_GPU_ENCODES pre-filled tokens.
        // Each GPU encode acquires one token (blocks if none available),
        // and the GpuToken guard returns it on drop.
        let (gpu_token_tx, gpu_token_rx) = mpsc::channel::<()>();
        for _ in 0..MAX_GPU_ENCODES {
            gpu_token_tx.send(()).unwrap();
        }
        let gpu_token_tx = Arc::new(gpu_token_tx);
        let gpu_token_rx = Arc::new(Mutex::new(gpu_token_rx));

        let mut handles = Vec::new();

        for _ in 0..max {
            let rx = rx.clone();
            let paused = paused.clone();
            let cancel_generation = cancel_generation.clone();
            let cancelled_jobs = cancelled_jobs.clone();
            let last_progress = last_progress.clone();
            let executor = executor.clone();
            let prober = prober.clone();
            let store = store.clone();
            let on_encode_progress = on_encode_progress.clone();
            let progress_emitter = progress_emitter.clone();
            let gpu_token_tx = gpu_token_tx.clone();
            let gpu_token_rx = gpu_token_rx.clone();
            let handle = thread::spawn(move || loop {
                let cmd = {
                    let lock = rx.lock().ok();
                    match lock {
                        Some(l) => l.recv(),
                        None => return,
                    }
                };
                match cmd {
                    Ok(WorkerCommand::Submit(task, task_generation)) => {
                        if is_task_cancelled(
                            &cancel_generation,
                            task_generation,
                            &cancelled_jobs,
                            &task.id,
                        ) {
                            finish_record(
                                &store,
                                FinishCompressionParams {
                                    record_id: task.history_id,
                                    status: "cancelled",
                                    progress: 0.0,
                                    duration_seconds: 0,
                                    compressed_size: 0,
                                    error_message: "",
                                    sidecar_path: "",
                                    source_deleted: 0,
                                    ffmpeg_command: "",
                                },
                            );
                            emit_progress(&progress_emitter, &task.id, "done", 100.0, "cancelled");
                            clear_cancelled_task(&cancelled_jobs, &task.id);
                            continue;
                        }
                        while paused.load(Ordering::Relaxed)
                            && !is_task_cancelled(
                                &cancel_generation,
                                task_generation,
                                &cancelled_jobs,
                                &task.id,
                            )
                        {
                            thread::sleep(Duration::from_millis(100));
                        }
                        if is_task_cancelled(
                            &cancel_generation,
                            task_generation,
                            &cancelled_jobs,
                            &task.id,
                        ) {
                            finish_record(
                                &store,
                                FinishCompressionParams {
                                    record_id: task.history_id,
                                    status: "cancelled",
                                    progress: 0.0,
                                    duration_seconds: 0,
                                    compressed_size: 0,
                                    error_message: "",
                                    sidecar_path: "",
                                    source_deleted: 0,
                                    ffmpeg_command: "",
                                },
                            );
                            emit_progress(&progress_emitter, &task.id, "done", 100.0, "cancelled");
                            clear_cancelled_task(&cancelled_jobs, &task.id);
                            continue;
                        }
                        let enc = {
                            executor
                                .lock()
                                .ok()
                                .and_then(|g| g.as_ref().map(Arc::clone))
                        };
                        if let Some(enc) = enc {
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
                            emit_progress(&progress_emitter, &task.id, "Prepare", 0.0, "running");
                            // Prepare step: ensure parent directory exists
                            if let Some(parent) = job.output_path.parent() {
                                if let Err(e) = std::fs::create_dir_all(parent) {
                                    plan.lock().unwrap().fail_stage(
                                        prepare_idx,
                                        format!("创建输出目录失败: {}", e),
                                    );
                                    plan.lock().unwrap().skip_remaining(prepare_idx + 1);
                                    finish_record(
                                        &store,
                                        FinishCompressionParams {
                                            record_id: task.history_id,
                                            status: "failed",
                                            progress: 0.0,
                                            duration_seconds: 0,
                                            compressed_size: 0,
                                            error_message: &format!("创建输出目录失败: {}", e),
                                            sidecar_path: "",
                                            source_deleted: 0,
                                            ffmpeg_command: "",
                                        },
                                    );
                                    emit_progress(
                                        &progress_emitter,
                                        &task.id,
                                        "done",
                                        100.0,
                                        "failed",
                                    );
                                    eprintln!("编码失败: {}", e);
                                    cleanup_temp(&final_output);
                                    continue;
                                }
                            }
                            plan.lock().unwrap().complete_stage(prepare_idx);

                            let transcode_idx = 1;

                            // ── Stage 3: Transcode ───────────────────────
                            plan.lock().unwrap().start_stage(transcode_idx);
                            // C2: Update DB — transcoding stage start
                            update_runtime(
                                &store,
                                task.history_id,
                                "running",
                                0.0,
                                "transcoding",
                                0,
                            );
                            emit_progress(&progress_emitter, &task.id, "Transcode", 0.0, "running");
                            let plan_for_callback = plan.clone();
                            let store_for_progress = store.clone();
                            let history_id = task.history_id;
                            let progress_emitter_for_cb = progress_emitter.clone();
                            let job_id_for_cb = task.id.clone();
                            // Acquire a GPU encode slot before spawning FFmpeg.
                            // Consumer NVENC drivers cap concurrent sessions at 3;
                            // CPU encodes skip the semaphore.
                            let _gpu_token: Option<GpuToken> = if task.strategy.video.is_gpu() {
                                match gpu_token_rx.lock().unwrap().recv() {
                                    Ok(()) => Some(GpuToken {
                                        sender: (*gpu_token_tx).clone(),
                                    }),
                                    Err(_) => None,
                                }
                            } else {
                                None
                            };
                            if is_task_cancelled(
                                &cancel_generation,
                                task_generation,
                                &cancelled_jobs,
                                &task.id,
                            ) {
                                finish_record(
                                    &store,
                                    FinishCompressionParams {
                                        record_id: task.history_id,
                                        status: "cancelled",
                                        progress: 0.0,
                                        duration_seconds: 0,
                                        compressed_size: 0,
                                        error_message: "",
                                        sidecar_path: "",
                                        source_deleted: 0,
                                        ffmpeg_command: "",
                                    },
                                );
                                emit_progress(
                                    &progress_emitter,
                                    &task.id,
                                    "done",
                                    100.0,
                                    "cancelled",
                                );
                                clear_cancelled_task(&cancelled_jobs, &task.id);
                                cleanup_temp(&final_output);
                                continue;
                            }
                            let result = enc.run(&job, &|event| {
                                match &event {
                                    ProgressEvent::StageStart { .. } => {}
                                    ProgressEvent::StageProgress { percent, .. } => {
                                        plan_for_callback
                                            .lock()
                                            .unwrap()
                                            .set_stage_progress(transcode_idx, *percent);
                                        if let Ok(mut lp) = last_progress.lock() {
                                            *lp = *percent;
                                        }
                                        // C2: Update DB progress periodically
                                        update_runtime(
                                            &store_for_progress,
                                            history_id,
                                            "running",
                                            *percent as f64,
                                            "transcoding",
                                            0,
                                        );
                                        // H-004: Fire external progress callback
                                        if let Ok(cb_guard) = on_encode_progress.lock() {
                                            if let Some(ref cb) = *cb_guard {
                                                cb(ProgressEvent::StageProgress {
                                                    percent: *percent,
                                                    fps: 0.0,
                                                    bitrate_kbps: 0,
                                                });
                                            }
                                        }
                                        // Task 4: Emit encode-progress event to frontend
                                        emit_progress(
                                            &progress_emitter_for_cb,
                                            &job_id_for_cb,
                                            "Transcode",
                                            *percent as f64 * 100.0,
                                            "running",
                                        );
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
                                    if is_task_cancelled(
                                        &cancel_generation,
                                        task_generation,
                                        &cancelled_jobs,
                                        &task.id,
                                    ) {
                                        let _ = std::fs::remove_file(&output.output_path);
                                        finish_record(
                                            &store,
                                            FinishCompressionParams {
                                                record_id: task.history_id,
                                                status: "cancelled",
                                                progress: 0.0,
                                                duration_seconds: 0,
                                                compressed_size: 0,
                                                error_message: "",
                                                sidecar_path: "",
                                                source_deleted: 0,
                                                ffmpeg_command: "",
                                            },
                                        );
                                        emit_progress(
                                            &progress_emitter,
                                            &task.id,
                                            "done",
                                            100.0,
                                            "cancelled",
                                        );
                                        clear_cancelled_task(&cancelled_jobs, &task.id);
                                        cleanup_temp(&final_output);
                                        continue;
                                    }
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
                                        eprintln!(
                                            "超大输出文件已删除: {}",
                                            output.output_path.display()
                                        );
                                        plan.lock()
                                            .unwrap()
                                            .fail_stage(transcode_idx, "输出大于源文件");
                                        plan.lock().unwrap().skip_remaining(transcode_idx + 1);
                                        // C2: Mark as discarded in DB
                                        finish_record(
                                            &store,
                                            FinishCompressionParams {
                                                record_id: task.history_id,
                                                status: "discarded",
                                                progress: 100.0,
                                                duration_seconds: (output.duration_ms / 1000)
                                                    as i64,
                                                compressed_size: output.compressed_size as i64,
                                                error_message: "",
                                                sidecar_path: "",
                                                source_deleted: 0,
                                                ffmpeg_command: &output.command,
                                            },
                                        );
                                        emit_progress(
                                            &progress_emitter,
                                            &task.id,
                                            "done",
                                            100.0,
                                            "discarded",
                                        );
                                        cleanup_temp(&final_output);
                                        continue;
                                    }
                                    plan.lock().unwrap().complete_stage(transcode_idx);

                                    let move_out_idx = 2;

                                    // ── Stage 5: Move Out (atomic commit with retry) ─
                                    let move_out_max_retries = {
                                        plan.lock()
                                            .unwrap()
                                            .stages
                                            .get(move_out_idx)
                                            .map(|s| s.max_retries)
                                            .unwrap_or(0)
                                    };
                                    plan.lock().unwrap().start_stage(move_out_idx);
                                    // C2: Update DB — moving_out stage
                                    update_runtime(
                                        &store,
                                        task.history_id,
                                        "running",
                                        0.0,
                                        "moving_out",
                                        0,
                                    );
                                    emit_progress(
                                        &progress_emitter,
                                        &task.id,
                                        "MoveOut",
                                        0.0,
                                        "running",
                                    );
                                    let mut move_out_ok = false;
                                    for attempt in 0..=move_out_max_retries {
                                        if is_task_cancelled(
                                            &cancel_generation,
                                            task_generation,
                                            &cancelled_jobs,
                                            &task.id,
                                        ) {
                                            break;
                                        }
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
                                                    plan.lock().unwrap().fail_stage(
                                                        move_out_idx,
                                                        format!(
                                                            "原子提交失败 (已重试{}次): {}",
                                                            move_out_max_retries, e
                                                        ),
                                                    );
                                                    plan.lock()
                                                        .unwrap()
                                                        .skip_remaining(move_out_idx + 1);
                                                    finish_record(
                                                        &store,
                                                        FinishCompressionParams {
                                                            record_id: task.history_id,
                                                            status: "failed",
                                                            progress: 0.0,
                                                            duration_seconds: 0,
                                                            compressed_size: 0,
                                                            error_message: &format!(
                                                                "原子提交失败 (已重试{}次): {}",
                                                                move_out_max_retries, e
                                                            ),
                                                            sidecar_path: "",
                                                            source_deleted: 0,
                                                            ffmpeg_command: "",
                                                        },
                                                    );
                                                    emit_progress(
                                                        &progress_emitter,
                                                        &task.id,
                                                        "done",
                                                        100.0,
                                                        "failed",
                                                    );
                                                    cleanup_temp(&final_output);
                                                    eprintln!("原子提交失败: {}", e);
                                                }
                                            }
                                        }
                                    }
                                    if !move_out_ok {
                                        if is_task_cancelled(
                                            &cancel_generation,
                                            task_generation,
                                            &cancelled_jobs,
                                            &task.id,
                                        ) {
                                            finish_record(
                                                &store,
                                                FinishCompressionParams {
                                                    record_id: task.history_id,
                                                    status: "cancelled",
                                                    progress: 0.0,
                                                    duration_seconds: 0,
                                                    compressed_size: 0,
                                                    error_message: "",
                                                    sidecar_path: "",
                                                    source_deleted: 0,
                                                    ffmpeg_command: "",
                                                },
                                            );
                                            emit_progress(
                                                &progress_emitter,
                                                &task.id,
                                                "done",
                                                100.0,
                                                "cancelled",
                                            );
                                            cleanup_temp(&final_output);
                                            clear_cancelled_task(&cancelled_jobs, &task.id);
                                        }
                                        continue;
                                    }

                                    // Write audit sidecar on successful encode
                                    let output_codec = &task.strategy.video.encoder;
                                    let audit = crate::services::audit::build_audit(
                                        crate::services::audit::BuildAuditParams {
                                            snapshot: &task.snapshot,
                                            output_path: &final_output,
                                            output_size: output.compressed_size,
                                            output_codec,
                                            strategy: &task.strategy,
                                            duration_ms: output.duration_ms,
                                            success: true,
                                            error: "",
                                            ffmpeg_command: &output.command,
                                        },
                                    );
                                    let sidecar_path =
                                        format!("{}.leanreel.json", final_output.display());
                                    if let Err(e) =
                                        crate::services::audit::write_sidecar(&final_output, &audit)
                                    {
                                        eprintln!("写入审计文件失败: {}", e);
                                    }

                                    // ── H-020: Post-encode file_snapshot sync ──
                                    // Re-probe the output file and insert/update file_snapshot
                                    let library_folder_id = task.snapshot.library_folder_id;
                                    sync_output_snapshot(
                                        &prober,
                                        &store,
                                        library_folder_id,
                                        &task.snapshot.relative_path,
                                        &final_output,
                                    );

                                    // ── H-021: Delete source file after successful encode ──
                                    let source_deleted_flag: i32 = if task.delete_source {
                                        match std::fs::remove_file(&task.input_path) {
                                            Ok(()) => {
                                                eprintln!(
                                                    "源文件已删除: {}",
                                                    task.input_path.display()
                                                );
                                                // Mark as deleted in the DB store
                                                if let Ok(store_guard) = store.lock() {
                                                    if let Some(ref s) = *store_guard {
                                                        if let Err(e) = s.mark_deleted(
                                                            task.snapshot.library_folder_id,
                                                            Path::new(&task.snapshot.relative_path),
                                                        ) {
                                                            eprintln!("DB 标记删除失败: {}", e);
                                                        }
                                                    }
                                                }
                                                1
                                            }
                                            Err(e) => {
                                                eprintln!(
                                                    "删除源文件失败 ({}): {}",
                                                    task.input_path.display(),
                                                    e
                                                );
                                                0
                                            }
                                        }
                                    } else {
                                        0
                                    };

                                    // C2: Mark compression record as completed
                                    finish_record(
                                        &store,
                                        FinishCompressionParams {
                                            record_id: task.history_id,
                                            status: "completed",
                                            progress: 100.0,
                                            duration_seconds: (output.duration_ms / 1000) as i64,
                                            compressed_size: output.compressed_size as i64,
                                            error_message: "",
                                            sidecar_path: &sidecar_path,
                                            source_deleted: source_deleted_flag,
                                            ffmpeg_command: &output.command,
                                        },
                                    );
                                    emit_progress(
                                        &progress_emitter,
                                        &task.id,
                                        "done",
                                        100.0,
                                        "completed",
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
                                    let status = if is_task_cancelled(
                                        &cancel_generation,
                                        task_generation,
                                        &cancelled_jobs,
                                        &task.id,
                                    ) {
                                        "cancelled"
                                    } else {
                                        "failed"
                                    };
                                    // The error string now contains the full FFmpeg command
                                    // (see ffmpeg.rs format: "ffmpeg 异常退出 (…): …\n命令: …")
                                    finish_record(
                                        &store,
                                        FinishCompressionParams {
                                            record_id: task.history_id,
                                            status,
                                            progress: 0.0,
                                            duration_seconds: 0,
                                            compressed_size: 0,
                                            error_message: &e,
                                            sidecar_path: "",
                                            source_deleted: 0,
                                            ffmpeg_command: &e,
                                        },
                                    );
                                    emit_progress(
                                        &progress_emitter,
                                        &task.id,
                                        "done",
                                        100.0,
                                        status,
                                    );
                                    cleanup_temp(&final_output);
                                    if status == "cancelled" {
                                        clear_cancelled_task(&cancelled_jobs, &task.id);
                                    }
                                    eprintln!("编码失败: {}", e);
                                }
                            }
                        }
                    }
                    Ok(WorkerCommand::Shutdown) | Err(_) => break,
                }
            });
            handles.push(handle);
        }
        Self {
            max_workers: AtomicUsize::new(max),
            sender: tx,
            paused,
            cancelled,
            cancel_generation,
            cancelled_jobs,
            executor,
            prober,
            store,
            join_handles: Mutex::new(handles),
            last_progress,
            on_encode_progress,
            progress_emitter,
            gpu_token_tx,
            gpu_token_rx,
        }
    }

    pub fn max_workers(&self) -> usize {
        self.max_workers.load(Ordering::Relaxed)
    }
    /// Update the worker count setting. Dynamic thread pool resize is not
    /// supported at runtime; this updates the recorded count for diagnostics
    /// and will take effect on the next app restart.
    pub fn set_worker_count(&self, count: usize) {
        self.max_workers
            .store(count.clamp(1, 16), Ordering::Relaxed);
    }
    pub fn set_executor(&self, enc: Arc<dyn Encoder + Send + Sync>) {
        if let Ok(mut guard) = self.executor.lock() {
            *guard = Some(enc);
        }
    }
    /// Set the prober for post-encode file_snapshot sync (H-020).
    pub fn set_prober(&self, p: Box<dyn MediaProber + Send>) {
        if let Ok(mut guard) = self.prober.lock() {
            *guard = Some(p);
        }
    }
    /// Set the snapshot store for post-encode file_snapshot sync (H-020).
    pub fn set_store(&self, s: Box<dyn SnapshotStore + Send>) {
        if let Ok(mut guard) = self.store.lock() {
            *guard = Some(s);
        }
    }
    /// Set the progress callback for encoding progress (H-004 pipeline).
    pub fn set_on_encode_progress(&self, cb: ProgressCallback) {
        if let Ok(mut guard) = self.on_encode_progress.lock() {
            *guard = Some(cb);
        }
    }

    /// Set the UI adapter for forwarding progress events.
    pub fn set_progress_emitter(&self, emitter: ProgressEmitter) {
        if let Ok(mut guard) = self.progress_emitter.lock() {
            *guard = Some(emitter);
        }
    }

    pub fn set_app_handle(&self, handle: tauri::AppHandle) {
        self.set_progress_emitter(Box::new(move |job_id, stage, progress, status| {
            let _ = handle.emit(
                "encode-progress",
                serde_json::json!({
                    "job_id": job_id, "stage": stage, "progress": progress, "status": status,
                }),
            );
        }));
    }
    pub fn submit(&self, task: WorkerTask) -> Result<(), String> {
        self.cancelled.store(false, Ordering::Relaxed);
        let generation = self.cancel_generation.load(Ordering::Relaxed);
        self.sender
            .send(WorkerCommand::Submit(Box::new(task), generation))
            .map_err(|e| format!("submit failed: {}", e))
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

    pub fn pause(&self) {
        self.paused.store(true, Ordering::Relaxed);
    }
    pub fn resume(&self) {
        self.paused.store(false, Ordering::Relaxed);
    }
    /// Cancel all pending and running tasks.
    ///
    /// Sets the cancelled flag so queued tasks will be skipped, and
    /// attempts to kill the currently running ffmpeg process via the
    /// encoder's cancel() method.
    pub fn cancel(&self) {
        self.cancelled.store(true, Ordering::Relaxed);
        self.cancel_generation.fetch_add(1, Ordering::Relaxed);
        self.paused.store(false, Ordering::Relaxed);
        // Try to cancel any running encode
        if let Ok(guard) = self.executor.try_lock() {
            if let Some(ref enc) = *guard {
                let _ = enc.cancel(&"".to_string());
            }
        }
    }
    pub fn cancel_task(&self, job_id: &str) -> Result<(), String> {
        self.cancelled_jobs
            .lock()
            .map_err(|_| "cancelled jobs lock poisoned".to_string())?
            .insert(job_id.to_string());
        let encoder = self
            .executor
            .lock()
            .map_err(|_| "encoder lock poisoned".to_string())?
            .as_ref()
            .map(Arc::clone);
        if let Some(enc) = encoder {
            let _ = enc.cancel(&job_id.to_string());
        }
        Ok(())
    }
    pub fn is_paused(&self) -> bool {
        self.paused.load(Ordering::Relaxed)
    }
    pub fn is_cancelled(&self) -> bool {
        self.cancelled.load(Ordering::Relaxed)
    }
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
    if history_id == 0 {
        return;
    }
    if let Ok(guard) = store.lock() {
        if let Some(ref s) = *guard {
            if let Err(e) =
                s.update_compression_runtime(history_id, status, progress, stage, duration_seconds)
            {
                eprintln!("DB 运行时更新失败 (id={}): {}", history_id, e);
            }
        }
    }
}

/// C2: Finalize a compression_history record at encode end.
/// No-op when the store is not set or history_id is 0.
fn finish_record(
    store: &Arc<Mutex<Option<Box<dyn SnapshotStore + Send>>>>,
    params: FinishCompressionParams<'_>,
) {
    let history_id = params.record_id;
    if history_id == 0 {
        return;
    }
    if let Ok(guard) = store.lock() {
        if let Some(ref s) = *guard {
            if let Err(e) = s.finish_compression(params) {
                eprintln!("DB 完成记录失败 (id={}): {}", history_id, e);
            }
        }
    }
}

/// Forward an encode-progress event to the UI adapter.
/// No-op when progress_emitter is not set.
fn emit_progress(
    progress_emitter: &Arc<Mutex<Option<ProgressEmitter>>>,
    job_id: &str,
    stage: &str,
    progress: f64,
    status: &str,
) {
    eprintln!("EMIT: {} {} {} {}", job_id, stage, progress, status);
    if let Ok(guard) = progress_emitter.lock() {
        if let Some(ref emit) = *guard {
            eprintln!("EMITTING to window");
            emit(job_id, stage, progress, status);
        } else {
            eprintln!("EMIT skipped: progress_emitter is None");
        }
    } else {
        eprintln!("EMIT skipped: lock failed");
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
        for _ in 0..self.max_workers.load(Ordering::Relaxed) {
            let _ = self.sender.send(WorkerCommand::Shutdown);
        }
        if let Ok(mut handles) = self.join_handles.lock() {
            while let Some(h) = handles.pop() {
                let _ = h.join();
            }
        }
    }
}
