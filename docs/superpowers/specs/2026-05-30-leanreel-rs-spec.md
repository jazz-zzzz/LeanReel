# LeanReel-rs 业务正确性规范

本文档从 Python 版 LeanReel 提取核心业务规则，作为 Rust 版实现的正确性标准。每条规则标注对应 Python 源代码位置。

---

## 数据契约：数据库 Schema

Python 版 SQLite 数据库是两版本间的"数据接口规范"。Rust 版的表结构必须完全兼容以下 Schema，能直接读取 Python 版生成的数据库文件并产生相同查询结果。

### library 表

```sql
CREATE TABLE library (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
```

### library_folder 表

```sql
CREATE TABLE library_folder (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    library_id INTEGER NOT NULL REFERENCES library(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    UNIQUE(library_id, path)
);
```

### file_snapshot 表

```sql
CREATE TABLE file_snapshot (
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
```

### compression_history 表

```sql
CREATE TABLE compression_history (
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
```

### 兼容规则

- 表名、列名、列类型、DEFAULT 值、NOT NULL 约束必须与 Python 版一致
- Rust 版读取 Python 数据库时以只读模式打开，不执行任何写入
- 新增列（Rust 版扩展）必须有 DEFAULT 值，保证旧库可读
- Rust 版自带独立的写入数据库，不与 Python 版共享

**参照**：`leanreel/infrastructure/database.py`

---

## 1. 受保护片源规则（最高优先级）

### 1.1 HEVC/H.265 片源

**规则**：编码格式为 HEVC 或 H.265 的视频文件**默认不处理**。状态显示为"跳过：HEVC/H.265 片源"，复选框禁用。

**参照**：`leanreel/services/matcher.py` match_strategy()

**输入**：
- 文件编码格式为 `hevc` 或 `h265`（大小写不敏感）

**输出**：
- 策略结果：SkipProtected，原因：HevcSource
- UI：禁用复选框，跳过原因列显示中文说明
- 不计入可压缩文件统计

### 1.2 HDR 片源

**规则**：HDR 类型为 HDR10、HDR10+、Dolby Vision 的视频文件**默认不处理**。

**HDR 子类型**：
| HDR 类型 | 跳过原因显示 |
|---|---|
| HDR10 | 跳过：HDR10 片源 |
| HDR10+ | 跳过：HDR10+ 片源 |
| Dolby Vision (Profile 5) | 跳过：Dolby Vision 片源 |
| Dolby Vision (Profile 7) | 跳过：Dolby Vision 片源 |
| Dolby Vision (Profile 8.1) | 跳过：Dolby Vision 片源 |
| Dolby Vision (Profile 8.4) | 跳过：Dolby Vision 片源 |

**输入**：
- 文件的 HDR 类型字段

**输出**：
- 策略结果：SkipProtected，原因：对应 HDR 类型
- SDR 文件不受此限制，继续匹配

**参照**：`leanreel/services/matcher.py`

### 1.3 受保护检查顺序

**规则**：先检查 HEVC，再检查 HDR。HEVC 优先于 HDR 报告（一个文件同时是 HEVC + HDR10 时，显示"跳过：HEVC/H.265 片源"）。

---

## 2. 策略匹配规则

### 2.1 匹配优先级

**规则**：遍历策略列表（按 JSON 文件加载顺序），返回第一个匹配的策略。没有匹配项时返回 SkipNoMatch。

**策略 JSON 字段**：
```json
{
  "name": "x265 HEVC CRF 20 标准转码",
  "type": "CPU",
  "encoder": "libx265",
  "target_codec": "hevc",
  "params": { "crf": 20, "preset": "medium" },
  "rules": {
    "max_bitrate": null,
    "source_codecs": ["h264", "mpeg2", "vc1"],
    "exclude_hdr": ["HDR10", "HDR10+", "DolbyVision"]
  }
}
```

**参照**：`leanreel/services/matcher.py`、`leanreel/services/strategy_utils.py`

### 2.2 匹配条件

- 文件编码格式在策略的 `source_codecs` 白名单内（大小写不敏感）
- 文件比特率 ≤ 策略 `max_bitrate`（如果设置了上限）
- 文件的 HDR 类型不在策略的 `exclude_hdr` 列表中
- 策略 `enabled` 为 true

### 2.3 自适应 CQ/CRF 估算

**规则**：如果策略 JSON 中 `params.cq` 或 `params.crf` 包含 `"auto"`，根据源文件分辨率动态计算：

- ≤ 1080p → 基础值保持不变
- 1440p → 基础值 + 2
- 2160p (4K) → 基础值 + 4

**参照**：`leanreel/services/strategy_utils.py` estimate_cq()

---

## 3. 文件扫描规则

### 3.1 支持格式

**规则**：递归扫描时只收集扩展名为以下格式的文件（大小写不敏感）：
`.mkv` `.mp4` `.avi` `.ts` `.mov` `.wmv` `.m2ts` `.mts` `.webm`

**参照**：`leanreel/infrastructure/file_discovery.py`

### 3.2 去重规则

**规则**：以**文件绝对路径**为唯一标识。同一路径的多个扫描结果以最新探测信息覆盖。

**参照**：`leanreel/infrastructure/repository.py`

### 3.3 删除处理

**规则**：扫描时发现数据库中有记录但磁盘上文件已不存在，标记为"已删除"状态，不自动删除数据库记录。

**参照**：`leanreel/services/scanner.py`

### 3.4 元数据自动同步

**规则**：编码完成后自动对输出文件执行 FFprobe 探测，将元数据写入快照缓存。同时检查源文件是否仍存在于磁盘，已删除则标记。

**参照**：`leanreel/services/scanner.py` sync_file_snapshot()

---

## 4. 编码管线规则

### 4.1 管线阶段

**规则**：编码分为以下阶段，按序执行：

1. **Prepare** — 构建 FFmpeg 命令行，创建临时目录
2. **Extract RPU** — 仅 Dolby Vision 文件，提取 RPU 数据（dovi_tool）
3. **Transcode** — 执行 FFmpeg 编码
4. **Inject RPU** — 仅 Dolby Vision 文件，注入 RPU（dovi_tool）
5. **Move Out** — 将临时输出移到目标位置

非 Dolby Vision 文件跳过阶段 2 和 4。

**参照**：`leanreel/services/pipeline.py`

### 4.2 取消机制

**规则**：
- 取消请求发送 `SIGTERM`/`CTRL_BREAK_EVENT` 给 FFmpeg 进程
- 设置取消标志，阻止后续任务自动启动
- 已完成的阶段不可撤销
- 临时文件在取消后清理

**参照**：`leanreel/services/cancellation.py`、`leanreel/executor/worker.py`

### 4.3 输出文件命名

**规则**：输出文件命名格式为 `{原文件名}_leanreel_{编码器名}.{扩展名}`。如果目标路径已存在文件，追加数字后缀避免覆盖。

---

## 5. 审计记录

### 5.1 双写审计

**规则**：每次编码完成后：
1. SQLite `encoding_history` 表写入一行完整记录
2. 输出目录下生成 `{输出文件名}.leanreel.json` 侧挂文件

### 5.2 审计字段

| 字段 | 说明 |
|---|---|
| timestamp | 编码开始时间 (ISO 8601) |
| source_path | 源文件绝对路径 |
| output_path | 输出文件绝对路径 |
| source_size_bytes | 源文件大小 |
| output_size_bytes | 输出文件大小 |
| source_codec | 源编码格式 |
| output_codec | 目标编码格式 |
| strategy_name | 使用的策略名称 |
| duration_seconds | 编码耗时 |
| success | 是否成功 |
| error_message | 失败时错误信息 |

**参照**：`leanreel/services/audit.py`

---

## 6. 并行编码

### 6.1 并行度

**规则**：默认 2 路并行（匹配 NVENC 物理编码芯片数量）。可配置为 1-16。

**参照**：`leanreel/executor/worker.py` WorkerManager

### 6.2 任务调度

**规则**：用户勾选文件后点击"开始编码"，所有选中文件进入任务队列。WorkerManager 按 FIFO 顺序从队列取任务，有空闲线程时自动启动下一个。

---

## 7. 库管理

### 7.1 库与文件夹

**规则**：
- 一个库可以挂载多个文件夹
- 文件夹是文件扫描的根目录
- 删除库时，关联的文件夹和文件快照一并清理
- 文件夹可以单独添加/移除

**参照**：`leanreel/services/library.py`

### 7.2 新建库

**规则**：库名称不能为空，不能与已有库重名。每个库独立存储其扫描文件列表。

---

## 8. 历史面板

### 8.1 展示规则

**规则**：`encoding_history` 表全部记录以表格展示，15 列（对应审计字段全集）。默认按时间倒序排列。

### 8.2 筛选

**规则**：支持按编码状态（成功/失败/取消）和策略名称筛选。双击行可打开输出文件所在文件夹。

### 8.3 存储

**规则**：所有库的编码记录汇总在同一张 `encoding_history` 表中。删除库时不删除其历史记录。清理历史由用户手动触发。

**参照**：`leanreel/gui/history_panel.py`、`leanreel/controllers/history_controller.py`
