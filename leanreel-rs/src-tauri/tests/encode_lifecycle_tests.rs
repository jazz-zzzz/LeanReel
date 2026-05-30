//! 端到端编码生命周期集成测试
//!
//! 模拟完整编码流程：库创建 → 文件夹添加 → 文件扫描 → 策略匹配 → 编码提交 →
//! 编码执行 → DB 状态更新 → 输出文件验证 → 审计记录验证。
//!
//! 使用 SpyEncoder 替代真实 FFmpeg，通过网络模拟 mock 验证整个调用链。

use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use leanreel_rs_lib::domain::models::*;
use leanreel_rs_lib::domain::traits::*;
use leanreel_rs_lib::infrastructure::db::SqliteSnapshotStore;
use leanreel_rs_lib::services::worker::{WorkerManager, WorkerTask, EncodeTask};

// =============================================================================
// 测试辅助：SpyEncoder - 记录调用并返回成功
// =============================================================================

struct SpyEncoder {
    last_job: Mutex<Option<EncodingJob>>,
    call_count: Mutex<usize>,
}

impl SpyEncoder {
    fn new() -> Self {
        Self {
            last_job: Mutex::new(None),
            call_count: Mutex::new(0),
        }
    }

    fn last_job(&self) -> Option<EncodingJob> {
        self.last_job.lock().unwrap().clone()
    }

    fn times_called(&self) -> usize {
        *self.call_count.lock().unwrap()
    }
}

impl Encoder for SpyEncoder {
    fn run(
        &self,
        job: &EncodingJob,
        _on_progress: &(dyn Fn(ProgressEvent) + Send + Sync),
    ) -> Result<EncodeOutput, String> {
        *self.call_count.lock().unwrap() += 1;
        *self.last_job.lock().unwrap() = Some(job.clone());

        // 模拟输出文件写入（写到 EncodingJob 指定的 output_path，即 temp 路径）
        if let Some(parent) = job.output_path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| format!("创建输出目录失败: {}", e))?;
        }
        std::fs::write(&job.output_path, b"compressed content here for leanreel lifecycle test")
            .map_err(|e| format!("写入输出文件失败: {}", e))?;

        let input_size = if job.input_path.exists() {
            job.input_path.metadata().map(|m| m.len()).unwrap_or(1_000_000)
        } else {
            job.snapshot.size_bytes as u64
        };

        Ok(EncodeOutput {
            output_path: job.output_path.clone(),
            original_size: input_size,
            compressed_size: 30,
            duration_ms: 500,
            command: "ffmpeg -y -i input.mkv -c:v av1_nvenc -cq 28 out.mkv".into(),
        })
    }

    fn cancel(&self, _job_id: &JobId) -> Result<(), String> {
        Ok(())
    }
}

// =============================================================================
// 测试辅助：构建测试用快照
// =============================================================================

fn make_test_snapshot(folder_id: i64, file_name: &str, codec: VideoCodec) -> FileSnapshot {
    FileSnapshot {
        id: None,
        library_folder_id: folder_id,
        relative_path: file_name.into(),
        file_name: file_name.into(),
        size_bytes: 1_000_000_000,
        video_codec: codec,
        video_width: 1920,
        video_height: 1080,
        hdr_type: HdrType::Sdr,
        audio_tracks: vec![
            AudioTrack {
                codec: "aac".into(),
                channels: 6,
                language: "eng".into(),
                title: "Surround".into(),
                is_commentary: false,
            },
            AudioTrack {
                codec: "aac".into(),
                channels: 2,
                language: "zho".into(),
                title: "".into(),
                is_commentary: false,
            },
        ],
        subtitle_tracks: vec![
            SubtitleTrack {
                codec: "subrip".into(),
                language: "eng".into(),
                title: "English".into(),
                is_forced: false,
            },
            SubtitleTrack {
                codec: "subrip".into(),
                language: "chs".into(),
                title: "简体中文".into(),
                is_forced: false,
            },
        ],
        duration_seconds: 5400.0,
        bitrate_bps: 2_500_000,
        file_mtime: 1716500000.0,
        probe_ok: true,
        probe_error: String::new(),
        scanned_at: "2026-05-30 12:00:00".into(),
        ..Default::default()
    }
}

fn make_av1_nvenc_strategy() -> Strategy {
    Strategy {
        name: "AV1 NVENC CQ28".into(),
        description: "测试策略 — AV1 NVENC CQ28".into(),
        is_preset: true,
        video: VideoConfig {
            encoder: "av1_nvenc".into(),
            crf: 0,
            preset: "p5".into(),
            pix_fmt: "yuv420p10le".into(),
            x265_params: String::new(),
            gpu: true,
            nv_preset: "p5".into(),
            rc: "vbr".into(),
            cq: 28,
        },
        hdr: HdrConfig {
            mode: "preserve_hdr10".into(),
            dv_handling: "reinject_rpu".into(),
        },
        audio: AudioConfig {
            mode: "keep_original".into(),
            remove_commentary: true,
            preferred_languages: vec!["chi".into(), "zho".into(), "eng".into()],
        },
        subtitle: SubtitleConfig {
            mode: "keep_all".into(),
        },
        filters: FilterConfig {
            skip_x265: true,
            min_size_gb: None,
            only_remux: false,
        },
        estimated_savings: "30-50%".into(),
        quality_impact: "视觉无损，文件缩小 30-50%".into(),
    }
}

fn make_hevc_strategy() -> Strategy {
    Strategy {
        name: "HEVC Medium".into(),
        description: "测试策略 — HEVC Medium".into(),
        is_preset: true,
        video: VideoConfig {
            encoder: "hevc_nvenc".into(),
            crf: 0,
            preset: "p5".into(),
            pix_fmt: "yuv420p10le".into(),
            x265_params: String::new(),
            gpu: true,
            nv_preset: "p5".into(),
            rc: "vbr".into(),
            cq: 28,
        },
        hdr: HdrConfig {
            mode: "sdr".into(),
            dv_handling: String::new(),
        },
        audio: AudioConfig {
            mode: "copy".into(),
            remove_commentary: false,
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
        quality_impact: String::new(),
    }
}

// =============================================================================
// 测试 1: 完整编码生命周期（submit_encode 路径）
// =============================================================================

#[test]
fn test_complete_encode_lifecycle_via_submit_encode() {
    // ── 准备阶段 ───────────────────────────────────────────────────────────
    // 1. 创建临时数据库文件（使用文件系统 DB，共享缓存）
    let tmp_dir = std::env::temp_dir().join("leanreel_lifecycle_test_1");
    let _ = std::fs::create_dir_all(&tmp_dir);
    let db_path = tmp_dir.join("test.db");
    let _ = std::fs::remove_file(&db_path);

    let store = SqliteSnapshotStore::open(&db_path).expect("打开数据库失败");

    // 2. 创建库和文件夹
    let lib_id = store.create_library("测试库").expect("创建库失败");
    let folder_id = store.add_folder(lib_id, "/test/movies").expect("添加文件夹失败");

    // 3. 创建源文件快照
    let snapshot = make_test_snapshot(folder_id, "test_video.mkv", VideoCodec::H264);
    store.upsert(&[snapshot.clone()]).expect("upsert 快照失败");

    // 获取快照 ID
    let snapshots = store.query(&FileFilter::default()).expect("查询快照失败");
    assert!(!snapshots.is_empty(), "快照表应有数据");
    let snap_id = snapshots[0].id.expect("快照应有 ID");

    // 4. 创建压缩历史记录
    let strategy = make_av1_nvenc_strategy();
    let output_dir = tmp_dir.join("output");
    std::fs::create_dir_all(&output_dir).expect("创建输出目录失败");
    let output_path = output_dir.join("test_video.mkv");

    let history_id = store
        .create_compression_record(
            snap_id,
            "test-batch-lifecycle-1",
            &strategy.name,
            snapshot.size_bytes,
            &output_path.to_string_lossy(),
            &strategy.video.encoder,
            strategy.video.cq,
            &strategy.video.preset,
            &strategy.video.pix_fmt,
            &strategy.audio.mode,
            &strategy.subtitle.mode,
        )
        .expect("创建压缩记录失败");
    assert!(history_id > 0, "history_id 应大于 0");

    // ── 编码阶段 ───────────────────────────────────────────────────────────
    // 5. 构建 WorkerManager + SpyEncoder
    let encoder = Arc::new(SpyEncoder::new());
    let wm = WorkerManager::new(1);
    wm.set_executor(encoder.clone() as Arc<dyn Encoder + Send + Sync>);
    wm.set_store(Box::new(store)); // 注意：store 所有权移入 WorkerManager

    // 6. 通过 submit_encode 提交任务
    let task = EncodeTask {
        id: "test-encode-lifecycle-1".into(),
        input_path: PathBuf::from("/test/movies/test_video.mkv"),
        output_dir: output_dir.clone(),
        strategy: strategy.clone(),
        snapshot: snapshot.clone(),
        has_dolby_vision: false,
        history_id,
        delete_source: false,
    };
    wm.submit_encode(task).expect("提交编码任务失败");

    // 等待 Worker 线程处理完成（Prepare → Transcode → MoveOut）
    std::thread::sleep(std::time::Duration::from_secs(2));

    // ── 验证阶段：Encoder 副作用 ──────────────────────────────────────────
    // 7. 验证 Encoder 被调用
    let call_count = encoder.times_called();
    assert!(call_count >= 1, "Encoder 应至少被调用 1 次，实际: {}", call_count);

    // 8. 验证 EncodingJob 内容正确
    let last_job = encoder
        .last_job()
        .expect("应捕获到编码任务");

    // strategy 字段
    assert_eq!(last_job.strategy.name, "AV1 NVENC CQ28");
    assert_eq!(last_job.strategy.video.encoder, "av1_nvenc");
    assert_eq!(last_job.strategy.video.cq, 28);
    assert_eq!(last_job.strategy.video.preset, "p5");
    assert!(last_job.strategy.video.is_gpu());

    // snapshot 字段
    assert_eq!(last_job.snapshot.file_name, "test_video.mkv");
    assert_eq!(last_job.snapshot.video_codec, VideoCodec::H264);
    assert!(!last_job.has_dolby_vision);

    // 输出路径应为 temp 路径（.tmp 后缀）
    let out_str = last_job.output_path.to_string_lossy();
    assert!(out_str.contains(".tmp"), "输出路径应包含 .tmp: {}", out_str);
    assert!(out_str.contains("test_video"), "输出路径应包含文件名");

    // ── 验证阶段：文件系统 ─────────────────────────────────────────────────
    // 9. 验证最终输出文件存在
    assert!(
        output_path.exists(),
        "最终输出文件应存在: {}",
        output_path.display()
    );
    let output_content = std::fs::read(&output_path).expect("读取输出文件失败");
    assert!(
        output_content.len() > 0,
        "输出文件不应为空"
    );

    // 10. 验证审计侧挂文件存在
    let sidecar_path = PathBuf::from(format!("{}.leanreel.json", output_path.display()));
    assert!(
        sidecar_path.exists(),
        "审计侧挂文件应存在: {}",
        sidecar_path.display()
    );

    // 验证审计 JSON 内容
    let audit_json =
        std::fs::read_to_string(&sidecar_path).expect("读取审计文件失败");
    assert!(
        audit_json.contains("AV1 NVENC CQ28"),
        "审计应包含策略名称"
    );
    assert!(
        audit_json.contains("av1_nvenc"),
        "审计应包含编码器名称"
    );

    // 11. 验证临时文件已清理
    let temp_path = {
        let mut s = output_path.as_os_str().to_os_string();
        s.push(".tmp");
        PathBuf::from(s)
    };
    let staging_path = {
        let mut s = output_path.as_os_str().to_os_string();
        s.push(".staging");
        PathBuf::from(s)
    };
    assert!(
        !temp_path.exists(),
        "临时文件 .tmp 应已清理: {}",
        temp_path.display()
    );
    assert!(
        !staging_path.exists(),
        "暂存文件 .staging 应已清理: {}",
        staging_path.display()
    );

    // ── 验证阶段：数据库 ──────────────────────────────────────────────────
    // 12. 通过新连接验证 compression_history 记录已更新
    drop(wm);

    let verify_store = SqliteSnapshotStore::open(&db_path).expect("打开验证数据库失败");
    let history = verify_store
        .get_compression_history()
        .expect("查询压缩历史失败");
    assert!(
        !history.is_empty(),
        "compression_history 应有记录"
    );

    // 找到我们的记录
    let record = history
        .iter()
        .find(|r| r.id == history_id)
        .expect("应找到压缩历史记录");

    assert_eq!(record.strategy_name, "AV1 NVENC CQ28");
    assert_eq!(record.encoder, "av1_nvenc");
    assert_eq!(record.status, "completed");
    assert!(record.success, "记录应标记为成功");
    // 输出大小应 > 0
    assert!(record.output_size_bytes > 0, "输出大小应 > 0");
    // 节约百分比应 > 0（因为 compressed=30 < original=1_000_000_000）
    assert!(record.savings_pct > 0.0, "应有正节约率");
    assert!(!record.ffmpeg_command.is_empty(), "应记录 ffmpeg 命令");

    // ── 清理 ────────────────────────────────────────────────────────────────
    drop(verify_store);
    let _ = std::fs::remove_dir_all(&tmp_dir);
}

// =============================================================================
// 测试 2: WorkerTask 直接提交路径（含 history_id）
// =============================================================================

#[test]
fn test_complete_encode_lifecycle_via_submit_direct() {
    let tmp_dir = std::env::temp_dir().join("leanreel_lifecycle_test_2");
    let _ = std::fs::create_dir_all(&tmp_dir);
    let db_path = tmp_dir.join("test2.db");
    let _ = std::fs::remove_file(&db_path);

    let store = SqliteSnapshotStore::open(&db_path).expect("打开数据库失败");
    let lib_id = store.create_library("测试库2").expect("创建库失败");
    let folder_id = store.add_folder(lib_id, "/test/movies").expect("添加文件夹失败");

    let snapshot = make_test_snapshot(folder_id, "movie_hevc.mkv", VideoCodec::H264);
    store.upsert(&[snapshot.clone()]).expect("upsert 快照失败");

    let snapshots = store.query(&FileFilter::default()).expect("查询快照失败");
    let snap_id = snapshots[0].id.expect("快照应有 ID");

    let strategy = make_hevc_strategy();
    let output_dir = tmp_dir.join("output");
    std::fs::create_dir_all(&output_dir).expect("创建输出目录失败");
    let output_path = output_dir.join("movie_hevc.mkv");

    // 创建 compression_history 记录，获取 history_id
    let history_id = store
        .create_compression_record(
            snap_id,
            "test-batch-lifecycle-2",
            &strategy.name,
            snapshot.size_bytes,
            &output_path.to_string_lossy(),
            &strategy.video.encoder,
            strategy.video.cq,
            &strategy.video.preset,
            &strategy.video.pix_fmt,
            &strategy.audio.mode,
            &strategy.subtitle.mode,
        )
        .expect("创建压缩记录失败");

    // 直接使用 WorkerTask（绕过 submit_encode 的转换）
    let encoder = Arc::new(SpyEncoder::new());
    let wm = WorkerManager::new(1);
    wm.set_executor(encoder.clone() as Arc<dyn Encoder + Send + Sync>);
    wm.set_store(Box::new(store));

    let worker_task = WorkerTask {
        id: "test-direct-1".into(),
        file_name: "movie_hevc.mkv".into(),
        input_path: PathBuf::from("/test/movies/movie_hevc.mkv"),
        output_path: output_path.clone(),
        strategy: strategy.clone(),
        snapshot: snapshot.clone(),
        status: TaskStatus::Pending,
        progress: 0.0,
        error_message: String::new(),
        history_id, // 非零值触发 DB 更新
        has_dolby_vision: false,
        delete_source: false,
    };
    wm.submit(worker_task).expect("提交 WorkerTask 失败");

    std::thread::sleep(std::time::Duration::from_secs(2));

    // ── 验证 ────────────────────────────────────────────────────────────────
    assert!(encoder.times_called() >= 1);
    let last_job = encoder.last_job().expect("应捕获到编码任务");
    assert_eq!(last_job.strategy.name, "HEVC Medium");
    assert_eq!(last_job.strategy.video.encoder, "hevc_nvenc");

    // 验证输出文件
    assert!(output_path.exists());

    // 验证审计侧挂文件
    let sidecar_path = PathBuf::from(format!("{}.leanreel.json", output_path.display()));
    assert!(sidecar_path.exists());

    // 验证 DB 记录
    drop(wm);
    let verify_store = SqliteSnapshotStore::open(&db_path).expect("打开验证数据库失败");
    let history = verify_store.get_compression_history().expect("查询压缩历史失败");
    let record = history
        .iter()
        .find(|r| r.id == history_id)
        .expect("应找到压缩历史记录");
    assert_eq!(record.status, "completed");
    assert!(record.success);
    // 非零 history_id 确保 DB 更新了
    assert!(record.output_size_bytes > 0);

    drop(verify_store);
    let _ = std::fs::remove_dir_all(&tmp_dir);
}

// =============================================================================
// 测试 3: 编码失败场景 —— 出错时状态为 failed
// =============================================================================

#[test]
fn test_encode_failure_updates_db_status() {
    struct FailingEncoder;
    impl Encoder for FailingEncoder {
        fn run(
            &self,
            _job: &EncodingJob,
            _on_progress: &(dyn Fn(ProgressEvent) + Send + Sync),
        ) -> Result<EncodeOutput, String> {
            Err("模拟 FFmpeg 崩溃: 无法打开编码器".into())
        }
        fn cancel(&self, _job_id: &JobId) -> Result<(), String> {
            Ok(())
        }
    }

    let tmp_dir = std::env::temp_dir().join("leanreel_lifecycle_test_3");
    let _ = std::fs::create_dir_all(&tmp_dir);
    let db_path = tmp_dir.join("test3.db");
    let _ = std::fs::remove_file(&db_path);

    let store = SqliteSnapshotStore::open(&db_path).expect("打开数据库失败");
    let lib_id = store.create_library("测试库3").expect("创建库失败");
    let folder_id = store.add_folder(lib_id, "/test/movies").expect("添加文件夹失败");

    let snapshot = make_test_snapshot(folder_id, "fail_video.mkv", VideoCodec::H264);
    store.upsert(&[snapshot.clone()]).expect("upsert 快照失败");
    let snapshots = store.query(&FileFilter::default()).expect("查询快照失败");
    let snap_id = snapshots[0].id.expect("快照应有 ID");

    let strategy = make_av1_nvenc_strategy();
    let output_dir = tmp_dir.join("output");
    std::fs::create_dir_all(&output_dir).expect("创建输出目录失败");
    let output_path = output_dir.join("fail_video.mkv");

    let history_id = store
        .create_compression_record(
            snap_id,
            "test-batch-fail",
            &strategy.name,
            snapshot.size_bytes,
            &output_path.to_string_lossy(),
            &strategy.video.encoder,
            strategy.video.cq,
            &strategy.video.preset,
            &strategy.video.pix_fmt,
            &strategy.audio.mode,
            &strategy.subtitle.mode,
        )
        .expect("创建压缩记录失败");

    let wm = WorkerManager::new(1);
    wm.set_executor(Arc::new(FailingEncoder) as Arc<dyn Encoder + Send + Sync>);
    wm.set_store(Box::new(store));

    let worker_task = WorkerTask {
        id: "test-fail-1".into(),
        file_name: "fail_video.mkv".into(),
        input_path: PathBuf::from("/test/movies/fail_video.mkv"),
        output_path: output_path.clone(),
        strategy: strategy.clone(),
        snapshot: snapshot.clone(),
        status: TaskStatus::Pending,
        progress: 0.0,
        error_message: String::new(),
        history_id,
        has_dolby_vision: false,
        delete_source: false,
    };
    wm.submit(worker_task).expect("提交任务失败");

    std::thread::sleep(std::time::Duration::from_secs(1));

    drop(wm);
    let verify_store = SqliteSnapshotStore::open(&db_path).expect("打开验证数据库失败");
    let history = verify_store.get_compression_history().expect("查询压缩历史失败");
    let record = history
        .iter()
        .find(|r| r.id == history_id)
        .expect("应找到失败记录");

    assert_eq!(record.status, "failed", "失败记录状态应为 failed");
    assert!(!record.success, "失败记录 success 应为 false");
    // 输出文件不应存在（失败后已清理）
    assert!(!output_path.exists(), "失败后输出文件不应存在");

    drop(verify_store);
    let _ = std::fs::remove_dir_all(&tmp_dir);
}

// =============================================================================
// 测试 4: Dolby Vision 编码任务
// =============================================================================

#[test]
fn test_encode_with_dolby_vision_flag() {
    let tmp_dir = std::env::temp_dir().join("leanreel_lifecycle_test_4");
    let _ = std::fs::create_dir_all(&tmp_dir);
    let db_path = tmp_dir.join("test4.db");
    let _ = std::fs::remove_file(&db_path);

    let store = SqliteSnapshotStore::open(&db_path).expect("打开数据库失败");
    let lib_id = store.create_library("测试库4").expect("创建库失败");
    let folder_id = store.add_folder(lib_id, "/test/movies").expect("添加文件夹失败");

    let mut dv_snapshot = make_test_snapshot(folder_id, "dv_movie.mkv", VideoCodec::Hevc);
    dv_snapshot.hdr_type = HdrType::DolbyVision {
        profile: DvProfile::Profile7,
    };
    store.upsert(&[dv_snapshot.clone()]).expect("upsert 快照失败");
    let snapshots = store.query(&FileFilter::default()).expect("查询快照失败");
    let snap_id = snapshots[0].id.expect("快照应有 ID");

    // 使用空 dv_handling 避免触发 RPU 提取（dovi_tool 可能不在环境 PATH 中）
    // has_dolby_vision 标志仍会正确传递到 Encoder
    let mut strategy = make_av1_nvenc_strategy();
    strategy.hdr.dv_handling = String::new();

    let output_dir = tmp_dir.join("output");
    std::fs::create_dir_all(&output_dir).expect("创建输出目录失败");
    let output_path = output_dir.join("dv_movie.mkv");

    let history_id = store
        .create_compression_record(
            snap_id,
            "test-batch-dv",
            &strategy.name,
            dv_snapshot.size_bytes,
            &output_path.to_string_lossy(),
            &strategy.video.encoder,
            strategy.video.cq,
            &strategy.video.preset,
            &strategy.video.pix_fmt,
            &strategy.audio.mode,
            &strategy.subtitle.mode,
        )
        .expect("创建压缩记录失败");

    let encoder = Arc::new(SpyEncoder::new());
    let wm = WorkerManager::new(1);
    wm.set_executor(encoder.clone() as Arc<dyn Encoder + Send + Sync>);
    wm.set_store(Box::new(store));

    let worker_task = WorkerTask {
        id: "test-dv-1".into(),
        file_name: "dv_movie.mkv".into(),
        input_path: PathBuf::from("/test/movies/dv_movie.mkv"),
        output_path: output_path.clone(),
        strategy: strategy.clone(),
        snapshot: dv_snapshot.clone(),
        status: TaskStatus::Pending,
        progress: 0.0,
        error_message: String::new(),
        history_id,
        has_dolby_vision: true,
        delete_source: false,
    };
    wm.submit(worker_task).expect("提交 DV 任务失败");

    std::thread::sleep(std::time::Duration::from_secs(2));

    // 验证 DV 标志传到了 Encoder
    let last_job = encoder.last_job().expect("应捕获 DV 编码任务");
    assert!(last_job.has_dolby_vision, "DV 任务应设置 has_dolby_vision=true");
    assert_eq!(last_job.snapshot.file_name, "dv_movie.mkv");
    // DV 源应该是 HEVC
    assert_eq!(last_job.snapshot.video_codec, VideoCodec::Hevc);

    // 输出文件应存在
    assert!(output_path.exists(), "DV 编码输出文件应存在");

    // DV 审计记录应包含 DV 标志
    let sidecar_path = PathBuf::from(format!("{}.leanreel.json", output_path.display()));
    assert!(sidecar_path.exists());
    let audit_json = std::fs::read_to_string(&sidecar_path).expect("读取审计文件失败");
    assert!(
        audit_json.contains("has_dolby_vision"),
        "审计应包含 Dolby Vision 信息"
    );

    // DB 验证
    drop(wm);
    let verify_store = SqliteSnapshotStore::open(&db_path).expect("打开验证数据库失败");
    let history = verify_store.get_compression_history().expect("查询压缩历史失败");
    let record = history.iter().find(|r| r.id == history_id).expect("应找到 DV 记录");
    assert_eq!(record.status, "completed");

    drop(verify_store);
    let _ = std::fs::remove_dir_all(&tmp_dir);
}

// =============================================================================
// 测试 5: 多个编码任务顺序执行
// =============================================================================

#[test]
fn test_multiple_encodes_in_sequence() {
    let tmp_dir = std::env::temp_dir().join("leanreel_lifecycle_test_5");
    let _ = std::fs::create_dir_all(&tmp_dir);
    let db_path = tmp_dir.join("test5.db");
    let _ = std::fs::remove_file(&db_path);

    let store = SqliteSnapshotStore::open(&db_path).expect("打开数据库失败");
    let lib_id = store.create_library("测试库5").expect("创建库失败");
    let folder_id = store.add_folder(lib_id, "/test/movies").expect("添加文件夹失败");

    let files = vec![
        ("episode_01.mkv", VideoCodec::H264),
        ("episode_02.mkv", VideoCodec::H264),
        ("episode_03.mkv", VideoCodec::Hevc),
    ];

    let mut snapshots = Vec::new();
    for (name, codec) in &files {
        snapshots.push(make_test_snapshot(folder_id, name, codec.clone()));
    }
    store.upsert(&snapshots).expect("批量 upsert 失败");

    let strategy = make_av1_nvenc_strategy();
    let output_dir = tmp_dir.join("output");
    std::fs::create_dir_all(&output_dir).expect("创建输出目录失败");

    let encoder = Arc::new(SpyEncoder::new());
    let wm = WorkerManager::new(1);
    wm.set_executor(encoder.clone() as Arc<dyn Encoder + Send + Sync>);
    wm.set_store(Box::new(store));

    // 提交所有任务
    for (i, (name, _)) in files.iter().enumerate() {
        let task = EncodeTask {
            id: format!("batch-task-{}", i),
            input_path: PathBuf::from(format!("/test/movies/{}", name)),
            output_dir: output_dir.clone(),
            strategy: strategy.clone(),
            snapshot: snapshots[i].clone(),
            has_dolby_vision: false,
            history_id: 0,
            delete_source: false,
        };
        wm.submit_encode(task).expect(&format!("提交任务 {} 失败", i));
    }

    // 等待所有任务完成
    std::thread::sleep(std::time::Duration::from_secs(5));

    let call_count = encoder.times_called();
    assert!(
        call_count >= files.len(),
        "Encoder 应至少被调用 {} 次，实际: {}",
        files.len(),
        call_count
    );

    // 验证每个输出文件都存在
    for (name, _) in &files {
        let out = output_dir.join(name);
        assert!(out.exists(), "输出文件应存在: {}", out.display());
    }

    drop(wm);
    let _ = std::fs::remove_dir_all(&tmp_dir);
}
