# LeanReel-rs 架构设计

## 1. 概述

LeanReel-rs 是对 Python 版 LeanReel 的完全重写。后端使用 Rust + Tauri，前端使用 Svelte。Python 代码库保留作为业务正确性的"黄金参照"。

**技术栈**：Rust, Tauri 2.x, Svelte, SQLite (rusqlite), FFmpeg/FFprobe 外部二进制。

**核心原则**：单向依赖，抽象在上，实现在下。层与层之间通过 Trait 契约通信，不泄露具体实现。

---

## 2. 分层架构

```
┌─────────────────────────────────┐
│  抽象层 (domain/)                │  纯类型 + Trait 契约，零外部依赖
├─────────────────────────────────┤    ↑ 只被依赖，不依赖任何人
│  实现层 (infrastructure/)        │  实现 domain Trait，含具体技术细节
├─────────────────────────────────┤
│  编排层 (services/)              │  持 Box<dyn Trait>，编排业务流程
├─────────────────────────────────┤
│  边界层 (commands/)              │  Tauri #[command]，唯一后端入口
├─────────────────────────────────┤
│  前端 (Svelte)                   │  纯 UI，通过 invoke/events 通信
└─────────────────────────────────┘
```

**单向依赖规则**：上层可以引用下层，下层绝不引用上层。domain 不引用任何人。

---

## 3. 项目结构

```
leanreel-rs/
├── src-tauri/
│   ├── Cargo.toml
│   ├── tauri.conf.json
│   └── src/
│       ├── main.rs              # 入口，注册 commands + 依赖注入
│       ├── commands/            # Tauri Commands（前端 API）
│       │   ├── library.rs
│       │   ├── scan.rs
│       │   ├── encode.rs
│       │   ├── strategy.rs
│       │   └── history.rs
│       ├── domain/              # 抽象层
│       │   ├── models.rs        # 数据结构 (enum, struct)
│       │   └── traits.rs        # Trait 接口定义
│       ├── infrastructure/      # 实现层
│       │   ├── db.rs            # rusqlite 封装
│       │   ├── ffprobe.rs       # FFprobe 调用 + 输出解析
│       │   ├── ffmpeg.rs        # FFmpeg 子进程管理
│       │   └── filesystem.rs    # 文件发现 (walkdir)
│       ├── services/            # 编排层
│       │   ├── scanner.rs       # 扫描编排
│       │   ├── matcher.rs       # 策略匹配
│       │   ├── pipeline.rs      # 编码管线状态机
│       │   └── worker.rs        # 并行任务调度
│       └── state/               # Tauri Managed State
│           └── app_state.rs     # 应用级状态 + 依赖注入容器
├── src/                         # Svelte 前端
│   ├── index.html
│   ├── app.css                  # 全局样式 + CSS 变量
│   ├── main.js
│   └── lib/
│       ├── components/          # Svelte 组件
│       ├── stores/              # Svelte stores
│       └── api.ts               # Tauri invoke 封装
├── strategies/                  # 策略 JSON（从 Python 版复制）
└── resources/                   # 内置二进制 (ffmpeg, dovi_tool)
```

---

## 4. 核心 Trait 契约

### 4.1 SnapshotStore — 文件快照持久化

```rust
trait SnapshotStore {
    fn upsert(&self, snapshots: &[FileSnapshot]) -> Result<usize>;
    fn query(&self, filter: &FileFilter) -> Result<Vec<FileSnapshot>>;
    fn mark_deleted(&self, path: &Path) -> Result<bool>;
    fn get_by_path(&self, path: &Path) -> Result<Option<FileSnapshot>>;
}
```

实现：`SqliteSnapshotStore` (infrastructure/db.rs)

### 4.2 MediaProber — 媒体元数据探测

```rust
trait MediaProber {
    fn probe(&self, path: &Path) -> Result<VideoMetadata>;
    fn probe_batch(&self, paths: &[PathBuf]) -> Result<Vec<ProbeResult>>;
}
```

实现：`FfprobeRunner` (infrastructure/ffprobe.rs)

### 4.3 Encoder — 编码执行器

```rust
trait Encoder {
    fn run(&self, job: &EncodingJob, on_progress: impl Fn(ProgressEvent)) -> Result<EncodeOutput>;
    fn cancel(&self, job_id: &JobId) -> Result<()>;
}
```

实现：`FfmpegEncoder` (infrastructure/ffmpeg.rs)

---

## 5. 前后端通信

### 5.1 双通道

| 通道 | 方向 | 用途 | 示例 |
|---|---|---|---|
| `invoke()` | 前端→后端→返回 | 请求/响应，用户操作 | 扫描目录、启动编码、查询历史 |
| `events` | 后端→前端推送 | 进度通知、状态变更 | 扫描进度、编码进度、文件状态变更 |

### 5.2 invoke 规范

所有 Tauri commands 返回 `Result<T, CommandError>`。前端统一处理：

```typescript
const report = await invoke<ScanReport>('scan_directory', { path });
// 成功：更新 store
// 失败：CommandError { kind, message, recoverable } → toast
```

### 5.3 events 规范

事件名遵循 `domain:action` 命名：

```
scan:progress     { current, total, current_path }
scan:complete     { report: ScanReport }
encode:progress   { job_id, stage, percent, fps }
encode:done       { job_id, output: EncodeOutput }
encode:failed     { job_id, error: String }
file:changed      { snapshot: FileSnapshot }
```

---

## 6. 错误处理

### 6.1 分层错误链

```
infrastructure/Error  →  services/Error  →  commands/CommandError
    (具体)                (业务)              (前端可读)
```

通过 `impl From<InfraError> for ServiceError` 和 `impl From<ServiceError> for CommandError` 自动转换。commands 层无需手动 mapping。

### 6.2 CommandError 结构

```rust
struct CommandError {
    kind: String,       // 错误类别标识
    message: String,    // 用户可读中文提示
    recoverable: bool,  // 是否可重试
}
```

---

## 7. 依赖注入

Tauri State 作为 DI 容器。main.rs 初始化所有服务并注入：

```rust
fn main() {
    tauri::Builder::default()
        .manage(AppState {
            store: Arc::new(SqliteSnapshotStore::open(db_path)?),
            prober: Arc::new(FfprobeRunner::new(ffprobe_path)),
            encoder: Arc::new(FfmpegEncoder::new(ffmpeg_path)),
            worker: Arc::new(Mutex::new(WorkerManager::new(2))),
            config: Arc::new(RwLock::new(Config::load()?)),
        })
        .invoke_handler(tauri::generate_handler![...])
        .run(tauri::generate_context!())
        .expect("launch failed");
}
```

Commands 通过 `State<AppState>` 获取依赖，不自行构造任何具体实现。

---

## 8. 动效策略

动效不作为架构决策预先确定，但架构保证后期可细化：

- Svelte 内置 `transition:`、`animate:`、`in:`/`out:` 指令覆盖所有动效需求
- CSS 变量 `--duration-fast/normal/slow`、`--ease-out/--ease-out-smooth` 全局统一定义
- 每个 Svelte 组件可独立添加动效，不影响其他组件
- 动效只用于状态反馈和展开收起，遵循 DESIGN.md 的克制原则

---

## 9. 打包与分发

- Tauri Bundler 生成 Windows .msi/.exe
- FFmpeg/FFprobe/dovi_tool 作为 sidecar 二进制捆绑
- 策略 JSON 通过 Tauri resource 机制嵌入
- 目标体积：不含 FFmpeg 约 5-15MB
