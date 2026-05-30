# LeanReel Python → Rust 迁移映射

本文档提供 LeanReel Python 代码库与 LeanReel-rs 之间的一对一模块映射，标注每个模块的关键设计差异。

---

## 1. 总体映射

| Python 模块 | Rust 模块 | 差异说明 |
|---|---|---|
| `leanreel/main.py` | `src-tauri/src/main.rs` | 入口从 QApplication 改为 Tauri Builder，服务初始化改为依赖注入 |
| `leanreel/ui_text.py` | 分散到各 Svelte 组件 | 中文文案直接写在 Svelte 模板中，不再集中管理 |

---

## 2. domain 层映射

### 2.1 领域模型

| Python 文件 | Rust 文件 | 关键差异 |
|---|---|---|
| `leanreel/domain/models.py` | `domain/models.rs` | `dataclass` → `struct`；字符串常量 → `enum`；`Optional` → `Option` |
| `leanreel/domain/interfaces.py` | `domain/traits.rs` | ABC 抽象类 → Trait；方法签名从 `def fn(x: T) -> Y` 变为 `fn fn(x: &T) -> Result<Y>` |

### 2.2 类型迁移细节

| Python | Rust | 说明 |
|---|---|---|
| `HDRType = Literal["SDR", "HDR10", "HDR10+", "DolbyVision"]` | `enum HdrType { Sdr, Hdr10, Hdr10Plus, DolbyVision { profile: DvProfile } }` | 穷举 enum + 携带数据 |
| `strategy: Optional[str]` (魔法字符串 "SKIP") | `enum StrategyResult { Encode { ... }, SkipProtected { reason }, SkipNoMatch { reason } }` | 类型安全的结果 |
| `codec: Optional[str]` | `enum VideoCodec { H264, Hevc, Av1, Mpeg2, Vc1, Unknown(String) }` | 枚举 + 兜底变体 |
| `current_stage: str` + `progress: float` | `enum PipelineState { Running { stage: Stage, progress: f32 }, ... }` | 状态机携带数据 |

---

## 3. infrastructure 层映射

### 3.1 数据库

| Python 文件 | Rust 文件 | 关键差异 |
|---|---|---|
| `leanreel/infrastructure/database.py` | `infrastructure/db.rs` | `sqlite3` → `rusqlite`；行映射从 `dict` → `serde` 反序列化到 struct |
| `leanreel/infrastructure/repository.py` | `infrastructure/db.rs` (合并) | `SnapshotRepository` 类 → `SqliteSnapshotStore` 实现 `SnapshotStore` Trait |

### 3.2 FFprobe

| Python 文件 | Rust 文件 | 关键差异 |
|---|---|---|
| `leanreel/executor/probe.py` | `infrastructure/ffprobe.rs` | `subprocess.run()` → `std::process::Command`；正则解析 → `nom` 组合子零拷贝解析 |

### 3.3 FFmpeg

| Python 文件 | Rust 文件 | 关键差异 |
|---|---|---|
| `leanreel/executor/ffmpeg.py` | `infrastructure/ffmpeg.rs` | `subprocess.Popen` → `Command::spawn()`；进度解析 → `nom`；线程管理 → `std::thread` 或 `tokio::task` |
| `leanreel/executor/ffmpeg_builder.py` | `infrastructure/ffmpeg.rs` (合并) | 命令行字符串拼接 → 类型安全的 builder 模式 |

### 3.4 文件发现

| Python 文件 | Rust 文件 | 关键差异 |
|---|---|---|
| `leanreel/infrastructure/file_discovery.py` | `infrastructure/filesystem.rs` | `os.walk` → `walkdir` crate |

---

## 4. services 层映射

### 4.1 扫描

| Python 文件 | Rust 文件 | 关键差异 |
|---|---|---|
| `leanreel/services/scanner.py` | `services/scanner.rs` | 编排逻辑不变，底层依赖从具体类 → `Box<dyn MediaProber + SnapshotStore>` |
| `leanreel/services/_probe_batch.py` | 合并到 `services/scanner.rs` | 批量探测逻辑内联 |

### 4.2 策略匹配

| Python 文件 | Rust 文件 | 关键差异 |
|---|---|---|
| `leanreel/services/matcher.py` | `services/matcher.rs` | `if/elif` 链 → `match` 穷举；返回字符串 → 返回 `StrategyResult` enum |
| `leanreel/services/strategy_utils.py` | 合并到 `services/matcher.rs` | CQ 估算逻辑 |

### 4.3 编码管线

| Python 文件 | Rust 文件 | 关键差异 |
|---|---|---|
| `leanreel/services/pipeline.py` | `services/pipeline.rs` | 阶段字符串 → `enum Stage` 状态机；阶段转移 → `match` 穷举所有合法转移 |
| `leanreel/services/cancellation.py` | 合并到 `services/pipeline.rs` | 取消标志位 → `CancellationToken` |

### 4.4 调度

| Python 文件 | Rust 文件 | 关键差异 |
|---|---|---|
| `leanreel/executor/worker.py` | `services/worker.rs` | `ThreadPoolExecutor` → `rayon` 线程池；GIL 限制 → 真正并行 |

### 4.5 审计

| Python 文件 | Rust 文件 | 关键差异 |
|---|---|---|
| `leanreel/services/audit.py` | 合并到 `services/pipeline.rs` | 编码完成后同步写入 SQLite + JSON |

### 4.6 库管理

| Python 文件 | Rust 文件 | 关键差异 |
|---|---|---|
| `leanreel/services/library.py` | 合并到 `infrastructure/db.rs` | 本质是 CRUD，不需要独立 service |

---

## 5. 移除的模块（Rust 版不需要）

| Python 文件 | 移除原因 |
|---|---|
| `leanreel/gui/*` | 全部由 Svelte 组件替代 |
| `leanreel/gui/adapters/*` | Svelte stores + serde 序列化替代 |
| `leanreel/controllers/*` | Tauri Commands 替代 |
| `leanreel/controllers/signals.py` | Tauri events 替代 |
| `leanreel/state/*` | Tauri Managed State + Svelte stores 替代 |
| `leanreel/executor/output_commit.py` | 逻辑并入 `services/pipeline.rs` |
| `leanreel/executor/resources.py` | Tauri resource 机制替代 |
| `leanreel/executor/_config.py` | Tauri Config 或 serde 直接读文件 |
| `leanreel/utils/*` | `paths.py` → 合并到配置；`gpu.py` → 移除（不需要自动探测）；`threading_contract.py` → Rust Send+Sync 编译器保证 |

---

## 6. 新增模块（Rust 版独有）

| Rust 模块 | 说明 |
|---|---|
| `src-tauri/tauri.conf.json` | Tauri 窗口配置、资源声明、安全策略 |
| `src-tauri/build.rs` | Tauri 构建脚本 |
| `src/app.css` | 全局 CSS 变量 (token-agnostic 的 DESIGN.md 映射) |
| `src/lib/stores/` | Svelte stores，替代 Python 的 Qt signals + QObject |
| `src/lib/api.ts` | Tauri invoke 封装，类型安全的前端 API 层 |

---

## 7. 迁移顺序

按风险递增，分五批：

| 批次 | 模块 | 理由 |
|---|---|---|
| 1 | domain/ (models + traits) | 纯数据，零依赖，为后续提供类型基础 |
| 1 | infrastructure/db.rs | SQLite 操作，可独立测试 |
| 1 | strategies/ (JSON 复制) | 数据文件，零代码 |
| 2 | infrastructure/ffprobe.rs | 最复杂的解析逻辑，优先验证 |
| 2 | services/scanner.rs | 依赖 ffprobe + db，第一批业务流 |
| 3 | services/matcher.rs | 纯业务逻辑，依赖 domain only |
| 3 | infrastructure/ffmpeg.rs | 子进程管理 + 并发 |
| 3 | services/pipeline.rs | 管线状态机，依赖 ffmpeg |
| 4 | Svelte 组件 + stores | 每完成一个 service 就接上对应 command 和 UI |
| 5 | commands/* | 串联所有 services |
| 5 | 打包配置 + CI | 最后胶水层 |

---

## 8. Golden Test 策略

### 8.1 选取 Golden 用例

从 Python 版测试中选取非平凡输入/输出对：

```
tests/golden/
├── scan/                    # 扫描输入输出
├── match/                   # 策略匹配输入输出
├── probe/                   # FFprobe 输出解析用例
├── pipeline/                # 管线状态转移用例
└── fixtures/                # 共享测试数据
```

### 8.2 验证方式

Rust 测试加载与 Python 相同的输入 fixtures，断言输出在结构上等价（允许内部表示不同）。验证的不是代码，而是行为。
