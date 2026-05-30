# LeanReel-rs Batch 1: 地基 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建 LeanReel-rs 项目骨架：初始化 Tauri + Svelte 项目，实现 domain 层全部类型和 Trait，实现 SQLite 基础设施层，复制策略 JSON 文件。

**Architecture:** Tauri 2.x 作为 Rust 后端 + Svelte 前端壳。本批次聚焦抽象层 (domain) 和实现层 (infrastructure/db)，不涉及 services 和前端功能。

**Tech Stack:** Rust 1.80+, Tauri 2.x, Svelte 5, rusqlite, serde, walkdir

---

## Task 1: 初始化 Tauri + Svelte 项目

**Files:**
- Create: `leanreel-rs/` (完整项目目录)
- Create: `leanreel-rs/src-tauri/Cargo.toml`
- Create: `leanreel-rs/src-tauri/tauri.conf.json`
- Create: `leanreel-rs/src-tauri/src/main.rs`
- Create: `leanreel-rs/src/` (Svelte 前端目录)
- Create: `leanreel-rs/strategies/` (策略 JSON 目录)

- [ ] **Step 1: 运行 Tauri 脚手架创建项目**

```bash
cd "C:\Users\groun\Desktop\Vide Coding\LeanReel"
# 使用 npm create tauri-app 创建项目
npm create tauri-app@latest leanreel-rs -- --template svelte --manager pnpm
```

Expected: 在 `leanreel-rs/` 下生成完整的 Tauri + Svelte 项目骨架。

- [ ] **Step 2: 添加 Rust 依赖到 Cargo.toml**

编辑 `leanreel-rs/src-tauri/Cargo.toml`，在 `[dependencies]` 中添加：

```toml
[dependencies]
tauri = { version = "2", features = [] }
tauri-plugin-shell = "2"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
rusqlite = { version = "0.31", features = ["bundled"] }
walkdir = "2"
thiserror = "1"
```

- [ ] **Step 3: 验证项目可编译**

```bash
cd leanreel-rs
cd src-tauri && cargo build
```

Expected: 编译成功，无错误。

- [ ] **Step 4: 创建策略目录**

```bash
mkdir -p leanreel-rs/strategies
```

- [ ] **Step 5: 从 Python 版复制策略 JSON 文件**

```bash
cp leanreel/resources/strategies/*.json leanreel-rs/strategies/
```

Expected: `leanreel-rs/strategies/` 下有三个策略 JSON 文件。

- [ ] **Step 6: Commit**

```bash
git add leanreel-rs/
git commit -m "feat: init Tauri + Svelte project skeleton for LeanReel-rs

Generated with Claude Code
via Happy

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Happy <yesreply@happy.engineering>"
```

---

## Task 2: Domain 层 — 核心数据类型

**Files:**
- Create: `leanreel-rs/src-tauri/src/domain/mod.rs`
- Create: `leanreel-rs/src-tauri/src/domain/models.rs`
- Test: `leanreel-rs/src-tauri/tests/domain_models.rs` (作为集成测试)

- [ ] **Step 1: 创建 domain 模块**

创建 `leanreel-rs/src-tauri/src/domain/mod.rs`：

```rust
pub mod models;
pub mod traits;
```

- [ ] **Step 2: 编写 models.rs 类型测试（TDD）**

创建 `leanreel-rs/src-tauri/tests/domain_models.rs`：

```rust
use leanreel_rs::domain::models::*;

#[test]
fn test_hdr_type_equality() {
    // 验证 HDR 类型正确区分
    assert_ne!(HdrType::Sdr, HdrType::Hdr10);
    assert_ne!(HdrType::Hdr10, HdrType::Hdr10Plus);
    // DolbyVision 携带 profile 数据
    let dv5 = HdrType::DolbyVision { profile: DvProfile::Profile5 };
    let dv7 = HdrType::DolbyVision { profile: DvProfile::Profile7 };
    assert_ne!(dv5, dv7);
}

#[test]
fn test_video_codec_from_string() {
    // 从 FFprobe 输出的字符串映射到 enum
    assert_eq!(VideoCodec::from_str("hevc"), VideoCodec::Hevc);
    assert_eq!(VideoCodec::from_str("h264"), VideoCodec::H264);
    assert_eq!(VideoCodec::from_str("av1"), VideoCodec::Av1);
    assert_eq!(VideoCodec::from_str("mpeg2video"), VideoCodec::Mpeg2);
    // 未知编码归入 Unknown 变体
    assert!(matches!(
        VideoCodec::from_str("vp9"),
        VideoCodec::Unknown(_)
    ));
}

#[test]
fn test_strategy_result_variants() {
    // 验证策略匹配结果的穷举性
    let encode = StrategyResult::Encode {
        strategy_name: "x265 HEVC CRF 20".into(),
        estimated_saving: 524_288_000,
    };
    let skip = StrategyResult::SkipProtected {
        reason: SkipReason::HevcSource,
    };

    assert!(matches!(encode, StrategyResult::Encode { .. }));
    assert!(matches!(skip, StrategyResult::SkipProtected { .. }));
}

#[test]
fn test_file_snapshot_serde_roundtrip() {
    let snap = FileSnapshot {
        id: None,
        library_folder_id: 1,
        relative_path: "movies/example.mkv".into(),
        file_name: "example.mkv".into(),
        size_bytes: 2_147_483_648,
        video_codec: VideoCodec::H264,
        video_width: 1920,
        video_height: 1080,
        hdr_type: HdrType::Sdr,
        audio_tracks: vec!["aac".into(), "ac3".into()],
        subtitle_tracks: vec!["eng".into(), "chs".into()],
        duration_seconds: 5400.0,
        bitrate_bps: 3_200_000,
        file_mtime: 1716500000.0,
        probe_ok: true,
        probe_error: String::new(),
        scanned_at: "2026-05-30 12:00:00".into(),
    };

    let json = serde_json::to_string(&snap).unwrap();
    let restored: FileSnapshot = serde_json::from_str(&json).unwrap();
    assert_eq!(snap.file_name, restored.file_name);
    assert_eq!(snap.video_codec, restored.video_codec);
}
```

- [ ] **Step 3: 运行测试，确认全部失败**

```bash
cd leanreel-rs/src-tauri && cargo test --test domain_models
```

Expected: 全部 FAIL，因为类型尚未定义。

- [ ] **Step 4: 实现 models.rs**

创建 `leanreel-rs/src-tauri/src/domain/models.rs`：

```rust
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum HdrType {
    #[serde(rename = "SDR")]
    Sdr,
    #[serde(rename = "HDR10")]
    Hdr10,
    #[serde(rename = "HDR10+")]
    Hdr10Plus,
    #[serde(rename = "DolbyVision")]
    DolbyVision { profile: DvProfile },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum DvProfile {
    Profile5,
    Profile7,
    Profile8_1,
    Profile8_4,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum VideoCodec {
    H264,
    Hevc,
    Av1,
    Mpeg2,
    Vc1,
    #[serde(untagged)]
    Unknown(String),
}

impl VideoCodec {
    pub fn from_str(s: &str) -> Self {
        match s.to_lowercase().as_str() {
            "h264" | "h.264" | "avc" => Self::H264,
            "hevc" | "h265" | "h.265" => Self::Hevc,
            "av1" => Self::Av1,
            "mpeg2video" | "mpeg2" | "mpeg-2" => Self::Mpeg2,
            "vc1" | "vc-1" => Self::Vc1,
            other => Self::Unknown(other.to_string()),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum StrategyResult {
    Encode {
        strategy_name: String,
        estimated_saving: u64,
    },
    SkipProtected {
        reason: SkipReason,
    },
    SkipNoMatch {
        reason: String,
    },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum SkipReason {
    HevcSource,
    Hdr10,
    Hdr10Plus,
    DolbyVision,
}

impl SkipReason {
    pub fn display(&self) -> &str {
        match self {
            Self::HevcSource => "跳过：HEVC/H.265 片源",
            Self::Hdr10 => "跳过：HDR10 片源",
            Self::Hdr10Plus => "跳过：HDR10+ 片源",
            Self::DolbyVision => "跳过：Dolby Vision 片源",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct FileSnapshot {
    pub id: Option<i64>,
    pub library_folder_id: i64,
    pub relative_path: String,
    pub file_name: String,
    pub size_bytes: i64,
    pub video_codec: VideoCodec,
    pub video_width: i32,
    pub video_height: i32,
    pub hdr_type: HdrType,
    pub audio_tracks: Vec<String>,
    pub subtitle_tracks: Vec<String>,
    pub duration_seconds: f64,
    pub bitrate_bps: i64,
    pub file_mtime: f64,
    pub probe_ok: bool,
    pub probe_error: String,
    pub scanned_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VideoMetadata {
    pub codec: VideoCodec,
    pub width: i32,
    pub height: i32,
    pub hdr_type: HdrType,
    pub audio_tracks: Vec<String>,
    pub subtitle_tracks: Vec<String>,
    pub duration_seconds: f64,
    pub bitrate_bps: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Strategy {
    pub name: String,
    pub encoder: String,
    pub target_codec: String,
    pub params: StrategyParams,
    pub rules: StrategyRules,
    pub enabled: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StrategyParams {
    pub crf: Option<i32>,
    pub cq: Option<i32>,
    pub preset: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StrategyRules {
    pub max_bitrate: Option<i64>,
    pub source_codecs: Vec<String>,
    pub exclude_hdr: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileFilter {
    pub library_id: Option<i64>,
    pub folder_id: Option<i64>,
    pub probe_ok_only: Option<bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProbeResult {
    pub path: std::path::PathBuf,
    pub metadata: Result<VideoMetadata, String>,
}
```

- [ ] **Step 5: 更新 main.rs 声明 domain 模块**

在 `leanreel-rs/src-tauri/src/main.rs` 中添加：

```rust
mod domain;
```

- [ ] **Step 6: 运行测试确认通过**

```bash
cd leanreel-rs/src-tauri && cargo test --test domain_models
```

Expected: 4 个测试全部 PASS。

- [ ] **Step 7: Commit**

```bash
git add leanreel-rs/src-tauri/src/domain/ leanreel-rs/src-tauri/tests/domain_models.rs leanreel-rs/src-tauri/src/main.rs
git commit -m "feat: implement domain layer with core types (models.rs)

HdrType, VideoCodec, StrategyResult as exhaustive enums.
FileSnapshot, Strategy, FileFilter as serde-compatible structs.
4 TDD tests covering equality, parsing, serde roundtrip.

Generated with Claude Code
via Happy

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Happy <yesreply@happy.engineering>"
```

---

## Task 3: Domain 层 — Trait 接口定义

**Files:**
- Create: `leanreel-rs/src-tauri/src/domain/traits.rs`
- Test: `leanreel-rs/src-tauri/tests/domain_traits.rs`

- [ ] **Step 1: 编写 traits.rs 测试（TDD）**

创建 `leanreel-rs/src-tauri/tests/domain_traits.rs`：

```rust
use std::path::{Path, PathBuf};
use leanreel_rs::domain::traits::*;
use leanreel_rs::domain::models::*;

// 验证 Trait 是 object-safe 的（可以作为 Box<dyn Trait> 使用）
// 这是为了确保依赖注入可以工作

struct MockStore;
impl SnapshotStore for MockStore {
    fn upsert(&self, _snapshots: &[FileSnapshot]) -> Result<usize, String> {
        Ok(0)
    }
    fn query(&self, _filter: &FileFilter) -> Result<Vec<FileSnapshot>, String> {
        Ok(vec![])
    }
    fn mark_deleted(&self, _path: &Path) -> Result<bool, String> {
        Ok(true)
    }
    fn get_by_path(&self, _path: &Path) -> Result<Option<FileSnapshot>, String> {
        Ok(None)
    }
    fn random_snapshot(&self) -> Result<Option<FileSnapshot>, String> {
        Ok(None)
    }
}

struct MockProber;
impl MediaProber for MockProber {
    fn probe(&self, _path: &Path) -> Result<VideoMetadata, String> {
        Err("not implemented".into())
    }
    fn probe_batch(&self, _paths: &[PathBuf]) -> Result<Vec<ProbeResult>, String> {
        Ok(vec![])
    }
}

struct MockEncoder;
impl Encoder for MockEncoder {
    fn run(&self, _job: &EncodingJob, _on_progress: Box<dyn Fn(ProgressEvent)>) -> Result<EncodeOutput, String> {
        Err("not implemented".into())
    }
    fn cancel(&self, _job_id: &JobId) -> Result<(), String> {
        Ok(())
    }
}

#[test]
fn test_traits_are_object_safe() {
    // 验证 Trait 可以作为 trait object 使用
    let _store: Box<dyn SnapshotStore> = Box::new(MockStore);
    let _prober: Box<dyn MediaProber> = Box::new(MockProber);
    let _encoder: Box<dyn Encoder> = Box::new(MockEncoder);
}

#[test]
fn test_mock_store_upsert_returns_count() {
    let store = MockStore;
    let snapshots = vec![];
    let result = store.upsert(&snapshots);
    assert!(result.is_ok());
    assert_eq!(result.unwrap(), 0);
}

#[test]
fn test_mock_prober_returns_empty_batch() {
    let prober = MockProber;
    let paths = vec![];
    let result = prober.probe_batch(&paths);
    assert!(result.is_ok());
    assert_eq!(result.unwrap().len(), 0);
}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd leanreel-rs/src-tauri && cargo test --test domain_traits
```

Expected: 全部 FAIL，Trait 未定义。

- [ ] **Step 3: 实现 traits.rs**

创建 `leanreel-rs/src-tauri/src/domain/traits.rs`：

```rust
use std::path::{Path, PathBuf};
use crate::domain::models::*;

pub type JobId = String;

#[derive(Debug, Clone)]
pub enum ProgressEvent {
    StageStart { stage: String, total_stages: u8 },
    StageProgress { percent: f32, fps: f32, bitrate_kbps: u32 },
    StageComplete { stage: String, duration_ms: u64 },
    Warning { message: String },
    Done { output: EncodeOutput },
}

#[derive(Debug, Clone)]
pub struct EncodingJob {
    pub id: JobId,
    pub input_path: PathBuf,
    pub output_dir: PathBuf,
    pub strategy: Strategy,
    pub has_dolby_vision: bool,
}

#[derive(Debug, Clone)]
pub struct EncodeOutput {
    pub output_path: PathBuf,
    pub original_size: u64,
    pub compressed_size: u64,
    pub duration_ms: u64,
}

/// 文件快照持久化
pub trait SnapshotStore {
    fn upsert(&self, snapshots: &[FileSnapshot]) -> Result<usize, String>;
    fn query(&self, filter: &FileFilter) -> Result<Vec<FileSnapshot>, String>;
    fn mark_deleted(&self, path: &Path) -> Result<bool, String>;
    fn get_by_path(&self, path: &Path) -> Result<Option<FileSnapshot>, String>;
    /// 从数据库随机抽取一条记录（用于行为一致性验证）
    fn random_snapshot(&self) -> Result<Option<FileSnapshot>, String>;
}

/// 媒体元数据探测
pub trait MediaProber {
    fn probe(&self, path: &Path) -> Result<VideoMetadata, String>;
    fn probe_batch(&self, paths: &[PathBuf]) -> Result<Vec<ProbeResult>, String>;
}

/// 编码执行器
pub trait Encoder {
    fn run(
        &self,
        job: &EncodingJob,
        on_progress: Box<dyn Fn(ProgressEvent)>,
    ) -> Result<EncodeOutput, String>;
    fn cancel(&self, job_id: &JobId) -> Result<(), String>;
}
```

- [ ] **Step 4: 更新 domain/mod.rs**

编辑 `leanreel-rs/src-tauri/src/domain/mod.rs`：

```rust
pub mod models;
pub mod traits;
```

- [ ] **Step 5: 运行测试确认通过**

```bash
cd leanreel-rs/src-tauri && cargo test --test domain_traits
```

Expected: 3 个测试全部 PASS。

- [ ] **Step 6: Commit**

```bash
git add leanreel-rs/src-tauri/src/domain/traits.rs leanreel-rs/src-tauri/tests/domain_traits.rs leanreel-rs/src-tauri/src/domain/mod.rs
git commit -m "feat: define domain trait interfaces (SnapshotStore, MediaProber, Encoder)

Object-safe traits for dependency injection. Mock implementations verify
the traits compile as Box<dyn Trait>. Includes random_snapshot() method
on SnapshotStore for cross-version behavioral verification.

Generated with Claude Code
via Happy

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Happy <yesreply@happy.engineering>"
```

---

## Task 4: Infrastructure 层 — SQLite 实现

**Files:**
- Create: `leanreel-rs/src-tauri/src/infrastructure/mod.rs`
- Create: `leanreel-rs/src-tauri/src/infrastructure/db.rs`
- Test: `leanreel-rs/src-tauri/tests/infrastructure_db.rs`

- [ ] **Step 1: 创建 infrastructure 模块**

创建 `leanreel-rs/src-tauri/src/infrastructure/mod.rs`：

```rust
pub mod db;
```

更新 `leanreel-rs/src-tauri/src/main.rs`，在 `mod domain;` 后添加：

```rust
mod infrastructure;
```

- [ ] **Step 2: 编写 db.rs 测试（TDD）**

创建 `leanreel-rs/src-tauri/tests/infrastructure_db.rs`：

```rust
use std::path::Path;
use leanreel_rs::domain::models::*;
use leanreel_rs::domain::traits::SnapshotStore;
use leanreel_rs::infrastructure::db::SqliteSnapshotStore;

fn make_test_snapshot(path: &str, codec: VideoCodec, hdr: HdrType) -> FileSnapshot {
    FileSnapshot {
        id: None,
        library_folder_id: 1,
        relative_path: path.into(),
        file_name: path.split('/').last().unwrap_or(path).into(),
        size_bytes: 1_000_000_000,
        video_codec: codec,
        video_width: 1920,
        video_height: 1080,
        hdr_type: hdr,
        audio_tracks: vec!["aac".into()],
        subtitle_tracks: vec![],
        duration_seconds: 3600.0,
        bitrate_bps: 2_200_000,
        file_mtime: 1716500000.0,
        probe_ok: true,
        probe_error: String::new(),
        scanned_at: "2026-05-30 12:00:00".into(),
    }
}

#[test]
fn test_upsert_and_query() {
    let store = SqliteSnapshotStore::open_in_memory().unwrap();

    let snapshots = vec![
        make_test_snapshot("movies/a.mkv", VideoCodec::H264, HdrType::Sdr),
        make_test_snapshot("movies/b.mkv", VideoCodec::Hevc, HdrType::Hdr10),
        make_test_snapshot("tv/c.mkv", VideoCodec::Av1, HdrType::Sdr),
    ];

    let count = store.upsert(&snapshots).unwrap();
    assert_eq!(count, 3);

    let filter = FileFilter { library_id: None, folder_id: None, probe_ok_only: None };
    let results = store.query(&filter).unwrap();
    assert_eq!(results.len(), 3);
}

#[test]
fn test_upsert_dedup_by_path() {
    let store = SqliteSnapshotStore::open_in_memory().unwrap();

    let snap1 = make_test_snapshot("movies/x.mkv", VideoCodec::H264, HdrType::Sdr);
    store.upsert(&[snap1]).unwrap();

    // 同路径再次 upsert 应更新而非新增
    let snap2 = make_test_snapshot("movies/x.mkv", VideoCodec::Hevc, HdrType::Sdr);
    store.upsert(&[snap2]).unwrap();

    let filter = FileFilter { library_id: None, folder_id: None, probe_ok_only: None };
    let results = store.query(&filter).unwrap();
    assert_eq!(results.len(), 1);
    assert_eq!(results[0].video_codec, VideoCodec::Hevc);
}

#[test]
fn test_mark_deleted() {
    let store = SqliteSnapshotStore::open_in_memory().unwrap();
    let snap = make_test_snapshot("movies/to_delete.mkv", VideoCodec::H264, HdrType::Sdr);
    store.upsert(&[snap]).unwrap();

    let result = store.mark_deleted(Path::new("movies/to_delete.mkv")).unwrap();
    assert!(result);

    let filter = FileFilter { library_id: None, folder_id: None, probe_ok_only: None };
    let results = store.query(&filter).unwrap();
    assert!(results.is_empty());
}

#[test]
fn test_random_snapshot() {
    let store = SqliteSnapshotStore::open_in_memory().unwrap();
    let snapshots = vec![
        make_test_snapshot("a.mkv", VideoCodec::H264, HdrType::Sdr),
        make_test_snapshot("b.mkv", VideoCodec::Hevc, HdrType::Hdr10),
    ];
    store.upsert(&snapshots).unwrap();

    let random = store.random_snapshot().unwrap();
    assert!(random.is_some());
    let snap = random.unwrap();
    assert!(snap.file_name == "a.mkv" || snap.file_name == "b.mkv");
}

#[test]
fn test_empty_store_random_returns_none() {
    let store = SqliteSnapshotStore::open_in_memory().unwrap();
    let result = store.random_snapshot().unwrap();
    assert!(result.is_none());
}

#[test]
fn test_filter_by_folder_id() {
    let store = SqliteSnapshotStore::open_in_memory().unwrap();

    let mut snap1 = make_test_snapshot("folder_a/file1.mkv", VideoCodec::H264, HdrType::Sdr);
    snap1.library_folder_id = 1;
    let mut snap2 = make_test_snapshot("folder_b/file2.mkv", VideoCodec::Hevc, HdrType::Sdr);
    snap2.library_folder_id = 2;

    store.upsert(&[snap1, snap2]).unwrap();

    let filter = FileFilter { library_id: None, folder_id: Some(1), probe_ok_only: None };
    let results = store.query(&filter).unwrap();
    assert_eq!(results.len(), 1);
    assert_eq!(results[0].file_name, "file1.mkv");
}
```

- [ ] **Step 3: 运行测试确认失败**

```bash
cd leanreel-rs/src-tauri && cargo test --test infrastructure_db
```

Expected: 全部 FAIL，SqliteSnapshotStore 未实现。

- [ ] **Step 4: 添加 fastrand 依赖**

在 `leanreel-rs/src-tauri/Cargo.toml` 的 `[dependencies]` 中添加：

```toml
fastrand = "2"
```

- [ ] **Step 5: 实现 db.rs**

创建 `leanreel-rs/src-tauri/src/infrastructure/db.rs`：

```rust
use std::path::Path;
use rusqlite::{params, Connection};
use crate::domain::models::*;
use crate::domain::traits::SnapshotStore;

pub struct SqliteSnapshotStore {
    conn: Connection,
}

impl SqliteSnapshotStore {
    pub fn open(path: &Path) -> Result<Self, String> {
        let conn = Connection::open(path).map_err(|e| e.to_string())?;
        let store = Self { conn };
        store.create_tables()?;
        Ok(store)
    }

    pub fn open_in_memory() -> Result<Self, String> {
        let conn = Connection::open_in_memory().map_err(|e| e.to_string())?;
        let store = Self { conn };
        store.create_tables()?;
        Ok(store)
    }

    pub fn open_readonly(path: &Path) -> Result<Self, String> {
        let conn = Connection::open_with_flags(
            path,
            rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY,
        )
        .map_err(|e| e.to_string())?;
        Ok(Self { conn })
    }

    fn create_tables(&self) -> Result<(), String> {
        self.conn
            .execute_batch(
                "
            CREATE TABLE IF NOT EXISTS library (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS library_folder (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                library_id INTEGER NOT NULL REFERENCES library(id) ON DELETE CASCADE,
                path TEXT NOT NULL,
                UNIQUE(library_id, path)
            );
            CREATE TABLE IF NOT EXISTS file_snapshot (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                library_folder_id INTEGER NOT NULL REFERENCES library_folder(id) ON DELETE CASCADE,
                relative_path TEXT NOT NULL,
                file_name TEXT NOT NULL,
                size_bytes INTEGER DEFAULT 0,
                video_codec TEXT DEFAULT '',
                video_width INTEGER DEFAULT 0,
                video_height INTEGER DEFAULT 0,
                hdr_type TEXT DEFAULT 'SDR',
                audio_tracks TEXT DEFAULT '[]',
                subtitle_tracks TEXT DEFAULT '[]',
                duration_seconds REAL DEFAULT 0,
                bitrate_bps INTEGER DEFAULT 0,
                file_mtime REAL DEFAULT 0,
                probe_ok INTEGER DEFAULT 0,
                probe_error TEXT DEFAULT '',
                scanned_at TEXT DEFAULT (datetime('now','localtime')),
                UNIQUE(library_folder_id, relative_path)
            );
            CREATE TABLE IF NOT EXISTS compression_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_snapshot_id INTEGER REFERENCES file_snapshot(id) ON DELETE SET NULL,
                strategy_name TEXT NOT NULL,
                original_size INTEGER DEFAULT 0,
                compressed_size INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                duration_seconds INTEGER DEFAULT 0,
                error_message TEXT DEFAULT '',
                output_path TEXT DEFAULT '',
                output_size_bytes INTEGER DEFAULT 0,
                savings_pct REAL DEFAULT 0,
                encoder TEXT DEFAULT '',
                cq_value INTEGER DEFAULT 0,
                preset TEXT DEFAULT '',
                pix_fmt TEXT DEFAULT '',
                audio_mode TEXT DEFAULT '',
                sub_mode TEXT DEFAULT '',
                ffmpeg_command TEXT DEFAULT '',
                sidecar_path TEXT DEFAULT '',
                leanreel_version TEXT DEFAULT '',
                source_deleted INTEGER DEFAULT 0,
                progress REAL DEFAULT 0,
                stage TEXT DEFAULT '',
                started_at TEXT DEFAULT '',
                completed_at TEXT DEFAULT ''
            );
            ",
            )
            .map_err(|e| e.to_string())
    }
}

impl SnapshotStore for SqliteSnapshotStore {
    fn upsert(&self, snapshots: &[FileSnapshot]) -> Result<usize, String> {
        let mut count = 0;
        for snap in snapshots {
            let audio_json =
                serde_json::to_string(&snap.audio_tracks).unwrap_or_else(|_| "[]".into());
            let sub_json =
                serde_json::to_string(&snap.subtitle_tracks).unwrap_or_else(|_| "[]".into());
            let codec_str = match &snap.video_codec {
                VideoCodec::H264 => "h264",
                VideoCodec::Hevc => "hevc",
                VideoCodec::Av1 => "av1",
                VideoCodec::Mpeg2 => "mpeg2",
                VideoCodec::Vc1 => "vc1",
                VideoCodec::Unknown(s) => s.as_str(),
            };
            let hdr_str = match &snap.hdr_type {
                HdrType::Sdr => "SDR",
                HdrType::Hdr10 => "HDR10",
                HdrType::Hdr10Plus => "HDR10+",
                HdrType::DolbyVision { .. } => "DolbyVision",
            };

            self.conn.execute(
                "INSERT INTO file_snapshot (library_folder_id, relative_path, file_name, size_bytes, video_codec, video_width, video_height, hdr_type, audio_tracks, subtitle_tracks, duration_seconds, bitrate_bps, file_mtime, probe_ok, probe_error, scanned_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16)
                 ON CONFLICT(library_folder_id, relative_path) DO UPDATE SET
                 size_bytes=excluded.size_bytes, video_codec=excluded.video_codec,
                 video_width=excluded.video_width, video_height=excluded.video_height,
                 hdr_type=excluded.hdr_type, audio_tracks=excluded.audio_tracks,
                 subtitle_tracks=excluded.subtitle_tracks, duration_seconds=excluded.duration_seconds,
                 bitrate_bps=excluded.bitrate_bps, file_mtime=excluded.file_mtime,
                 probe_ok=excluded.probe_ok, probe_error=excluded.probe_error,
                 scanned_at=excluded.scanned_at",
                params![
                    snap.library_folder_id,
                    snap.relative_path,
                    snap.file_name,
                    snap.size_bytes,
                    codec_str,
                    snap.video_width,
                    snap.video_height,
                    hdr_str,
                    audio_json,
                    sub_json,
                    snap.duration_seconds,
                    snap.bitrate_bps,
                    snap.file_mtime,
                    snap.probe_ok as i32,
                    snap.probe_error,
                    snap.scanned_at,
                ],
            )
            .map_err(|e| e.to_string())?;
            count += 1;
        }
        Ok(count)
    }

    fn query(&self, filter: &FileFilter) -> Result<Vec<FileSnapshot>, String> {
        let mut sql = String::from(
            "SELECT id, library_folder_id, relative_path, file_name, size_bytes, video_codec, video_width, video_height, hdr_type, audio_tracks, subtitle_tracks, duration_seconds, bitrate_bps, file_mtime, probe_ok, probe_error, scanned_at FROM file_snapshot WHERE 1=1"
        );
        let mut param_values: Vec<Box<dyn rusqlite::types::ToSql>> = Vec::new();

        if let Some(folder_id) = filter.folder_id {
            sql.push_str(" AND library_folder_id = ?");
            param_values.push(Box::new(folder_id));
        }
        if filter.probe_ok_only.unwrap_or(false) {
            sql.push_str(" AND probe_ok = 1");
        }

        let mut stmt = self.conn.prepare(&sql).map_err(|e| e.to_string())?;
        let param_refs: Vec<&dyn rusqlite::types::ToSql> =
            param_values.iter().map(|p| p.as_ref()).collect();

        let rows = stmt
            .query_map(param_refs.as_slice(), |row| {
                let codec_str: String = row.get(5)?;
                let hdr_str: String = row.get(8)?;
                let audio_json: String = row.get(9)?;
                let sub_json: String = row.get(10)?;

                Ok(FileSnapshot {
                    id: Some(row.get(0)?),
                    library_folder_id: row.get(1)?,
                    relative_path: row.get(2)?,
                    file_name: row.get(3)?,
                    size_bytes: row.get(4)?,
                    video_codec: VideoCodec::from_str(&codec_str),
                    video_width: row.get(6)?,
                    video_height: row.get(7)?,
                    hdr_type: match hdr_str.as_str() {
                        "HDR10" => HdrType::Hdr10,
                        "HDR10+" => HdrType::Hdr10Plus,
                        "DolbyVision" => HdrType::DolbyVision {
                            profile: DvProfile::Profile8_1,
                        },
                        _ => HdrType::Sdr,
                    },
                    audio_tracks: serde_json::from_str(&audio_json).unwrap_or_default(),
                    subtitle_tracks: serde_json::from_str(&sub_json).unwrap_or_default(),
                    duration_seconds: row.get(11)?,
                    bitrate_bps: row.get(12)?,
                    file_mtime: row.get(13)?,
                    probe_ok: row.get::<_, i32>(14)? != 0,
                    probe_error: row.get(15)?,
                    scanned_at: row.get(16)?,
                })
            })
            .map_err(|e| e.to_string())?;

        let mut results = Vec::new();
        for row in rows {
            results.push(row.map_err(|e| e.to_string())?);
        }
        Ok(results)
    }

    fn mark_deleted(&self, path: &Path) -> Result<bool, String> {
        let relative = path.to_string_lossy().to_string();
        let affected = self
            .conn
            .execute(
                "DELETE FROM file_snapshot WHERE relative_path = ?1",
                params![relative],
            )
            .map_err(|e| e.to_string())?;
        Ok(affected > 0)
    }

    fn get_by_path(&self, path: &Path) -> Result<Option<FileSnapshot>, String> {
        let relative = path.to_string_lossy().to_string();
        let filter = FileFilter {
            library_id: None,
            folder_id: None,
            probe_ok_only: None,
        };
        let all = self.query(&filter)?;
        Ok(all.into_iter().find(|s| s.relative_path == relative))
    }

    fn random_snapshot(&self) -> Result<Option<FileSnapshot>, String> {
        let filter = FileFilter {
            library_id: None,
            folder_id: None,
            probe_ok_only: None,
        };
        let all = self.query(&filter)?;
        if all.is_empty() {
            return Ok(None);
        }
        let idx = fastrand::usize(0..all.len());
        Ok(Some(all[idx].clone()))
    }
}
```

- [ ] **Step 6: 运行测试确认通过**

```bash
cd leanreel-rs/src-tauri && cargo test --test infrastructure_db
```

Expected: 6 个测试全部 PASS。

- [ ] **Step 7: Commit**

```bash
git add leanreel-rs/src-tauri/src/infrastructure/ leanreel-rs/src-tauri/tests/infrastructure_db.rs leanreel-rs/src-tauri/src/main.rs leanreel-rs/src-tauri/Cargo.toml
git commit -m "feat: implement SqliteSnapshotStore with Python-compatible schema

SQLite schema matches Python version exactly (4 tables). Supports in-memory
for testing, file-based for production, and read-only mode for cross-version
verification. random_snapshot() enables behavioral comparison against Python.

Generated with Claude Code
via Happy

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Happy <yesreply@happy.engineering>"
```

---

## Task 5: 验证数据兼容性 — 读取 Python 数据库

**Files:**
- Test: `leanreel-rs/src-tauri/tests/data_compat.rs`

- [ ] **Step 1: 编写跨版本兼容性测试**

创建 `leanreel-rs/src-tauri/tests/data_compat.rs`：

```rust
use std::path::PathBuf;
use leanreel_rs::domain::traits::SnapshotStore;
use leanreel_rs::infrastructure::db::SqliteSnapshotStore;

/// 在 CI 中运行时需要设置 LEANREEL_PY_DB 环境变量
/// 指向 Python 版生成的 .db 文件
fn get_python_db_path() -> Option<PathBuf> {
    std::env::var("LEANREEL_PY_DB").ok().map(PathBuf::from)
}

#[test]
fn test_can_open_python_db_readonly() {
    let path = match get_python_db_path() {
        Some(p) => p,
        None => {
            eprintln!("Skipping: LEANREEL_PY_DB not set");
            return;
        }
    };
    let store = SqliteSnapshotStore::open_readonly(&path);
    assert!(store.is_ok(), "Should open Python DB in read-only mode");
}

#[test]
fn test_query_python_db_returns_data() {
    let path = match get_python_db_path() {
        Some(p) => p,
        None => return,
    };
    let store = SqliteSnapshotStore::open_readonly(&path).unwrap();
    let filter = leanreel_rs::domain::models::FileFilter {
        library_id: None,
        folder_id: None,
        probe_ok_only: None,
    };
    let results = store.query(&filter).unwrap();
    // Python DB 应该有数据（除非是空库）
    assert!(!results.is_empty(), "Python DB should have file_snapshot rows");
    // 验证字段被正确解析（不是空字段）
    let first = &results[0];
    assert!(!first.file_name.is_empty(), "file_name should not be empty");
    assert!(!first.relative_path.is_empty(), "relative_path should not be empty");
}

#[test]
fn test_random_snapshot_from_python_db() {
    let path = match get_python_db_path() {
        Some(p) => p,
        None => return,
    };
    let store = SqliteSnapshotStore::open_readonly(&path).unwrap();
    let snap = store.random_snapshot().unwrap();
    assert!(snap.is_some(), "Python DB should have at least one snapshot");
    let snap = snap.unwrap();
    // 验证关键字段可读
    assert!(snap.size_bytes > 0, "size should be positive");
}
```

- [ ] **Step 2: 用 Python 数据库运行测试（手动验证）**

开发者本地执行：

```bash
cd leanreel-rs/src-tauri
LEANREEL_PY_DB="C:\Users\groun\Desktop\Vide Coding\LeanReel\production.db" cargo test --test data_compat -- --nocapture
```

Expected: 3 个测试全部 PASS（如果 Python DB 路径正确且有数据）。

- [ ] **Step 3: Commit**

```bash
git add leanreel-rs/src-tauri/tests/data_compat.rs
git commit -m "test: add cross-version data compatibility tests

Validates that Rust can open Python-generated SQLite databases in read-only
mode, query rows, and extract random snapshots for behavioral comparison.

Generated with Claude Code
via Happy

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Happy <yesreply@happy.engineering>"
```

---

## Task 6: 最终验证 — 全量测试

- [ ] **Step 1: 运行所有测试**

```bash
cd leanreel-rs/src-tauri && cargo test
```

Expected: 所有 domain、traits、db 测试通过（data_compat 在 CI 中跳过）。

- [ ] **Step 2: 验证项目可编译**

```bash
cd leanreel-rs && cargo build --release
```

Expected: 编译成功，无警告。

- [ ] **Step 3: 验证 Svelte 前端可构建**

```bash
cd leanreel-rs && pnpm build
```

Expected: 前端构建成功。

- [ ] **Step 4: Commit (if any changes)**

---

## 完成状态

Batch 1 完成后，LeanReel-rs 具备：

- ✅ 完整的 domain 层类型系统（enum + struct）
- ✅ 可注入的 Trait 接口（SnapshotStore, MediaProber, Encoder）
- ✅ 与 Python 版 Schema 兼容的 SQLite 实现
- ✅ 只读模式读取 Python 数据库
- ✅ random_snapshot() 支持跨版本行为验证
- ✅ 策略 JSON 文件就位
- ✅ Svelte 前端壳可构建

**下一步**：Batch 2 实现 FFprobe 输出解析 + 文件扫描服务。
