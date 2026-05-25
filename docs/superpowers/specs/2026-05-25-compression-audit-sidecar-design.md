# Compression Audit Sidecar — 设计规格

**日期:** 2026-05-25
**状态:** 已批准

## 概述

为每次编码生成一份完整的审计记录，同源双写：JSON sidecar 文件（磁盘）和 `compression_history` 表（SQL）。Sidecar 是权威源，DB 是可查询索引。

## 命名约定

| 项目 | 格式 | 示例 |
|------|------|------|
| 源文件 | `{filename}.{ext}` | `movie.mkv` |
| 输出文件 | `{filename}_zcompressed.{ext}` | `movie_zcompressed.mkv` |
| Sidecar | `{输出文件名}.leanreel.json` | `movie_zcompressed.mkv.leanreel.json` |

Sidecar 与输出文件同目录，自然成对排列。

## 领域模型：CompressionAudit

### 身份
- `library_folder_id: int` — 关联的文件夹 ID
- `relative_path: str` — 源文件相对路径

### source（源文件元数据）
- `path: str` — 绝对路径
- `size_bytes: int` — 原始体积
- `mtime: float` — 文件修改时间
- `video.codec, width, height, pix_fmt, bitrate_bps, duration_seconds, frame_rate, hdr_type` — 完整视频参数
- `video.color_primaries, color_transfer, color_space` — 色彩元数据
- `audio: list[{index, codec, channels, language, title, is_commentary}]` — 全部音轨
- `subtitle: list[{index, codec, language, title, is_forced}]` — 全部字幕轨

### output（输出文件）
- `path: str` — 输出文件绝对路径
- `size_bytes: int` — 压缩后体积
- `savings_bytes: int` — 节省字节数
- `savings_pct: float` — 节省百分比

### strategy（使用的策略）
- `name: str` — 策略名称
- `video: {encoder, crf/cq, preset, pix_fmt}` — 编码参数
- `audio: {mode, preferred_languages, remove_commentary}` — 音轨处理规则
- `subtitle: {mode}` — 字幕处理规则

### execution（执行详情）
- `command: list[str]` — 完整 FFmpeg 命令行
- `adaptive_cq: {original, adjusted, reason}` — 自适应 CQ 调整记录
- `started_at, completed_at: str` — ISO 时间戳
- `duration_seconds: float` — 实际耗时
- `status: str` — completed / failed / cancelled
- `stages: list[{slot_id, status, duration_seconds}]` — 各 stage 状态

### environment（环境）
- `ffmpeg_version: str`
- `dovi_tool_version: str`
- `leanreel_version: str`
- `platform: str`

### 数据库回链
- `db_record_id: int` — compression_history 行 ID（DB 写入后回填）

## 同源双写流程

```
FFmpegExecutor.encode() 完成
        │
        ▼
  build_audit(task, snap, strategy, cmd, env)
        │
        ▼
  CompressionAudit（单一数据对象）
        │
        ├──► write_sidecar(audit)       → {output}.leanreel.json
        │
        └──► insert_history(audit)      → compression_history 表
```

**写顺序：** sidecar 先，DB 后。Sidecar 是权威源。

**错误处理：**
- Sidecar 写入失败 → 不阻断流程，记录日志，DB 记录标记 `sidecar_path=""`
- DB 写入失败 → sidecar 已完成，不重试 DB，记录日志

## DB 扩展：compression_history

新增字段（通过 migration 添加）：

```sql
-- 输出
output_path TEXT DEFAULT ''
output_size_bytes INTEGER DEFAULT 0
savings_pct REAL DEFAULT 0

-- 策略详情
encoder TEXT DEFAULT ''
cq_value INTEGER DEFAULT 0
preset TEXT DEFAULT ''
pix_fmt TEXT DEFAULT ''
audio_mode TEXT DEFAULT ''
sub_mode TEXT DEFAULT ''

-- 执行
ffmpeg_command TEXT DEFAULT ''
sidecar_path TEXT DEFAULT ''
leanreel_version TEXT DEFAULT ''
```

源文件元数据不冗余存储——通过 `file_snapshot_id` JOIN `file_snapshot` 获取。

## Sidecar 与文件隔离

```
文件夹结构：
  /movies/
    ├── movie.mkv                           ← 源文件
    ├── movie_zcompressed.mkv               ← 输出文件
    ├── movie_zcompressed.mkv.leanreel.json ← sidecar
    ├── episode01.mkv
    ├── episode01_zcompressed.mkv
    └── episode01_zcompressed.mkv.leanreel.json
```

**隔离规则：**
- Sidecar 以输出文件为锚点，与源/输出文件同目录
- 多库引用同一物理文件夹 → 共享同一批 sidecar → 无冲突
- 删除库/文件夹 → sidecar 保留在磁盘，不随 DB 删除

## 扫描集成：已处理检测

扫描文件夹时检测 `*_zcompressed.mkv.leanreel.json`：

```
sidecar 存在 →
  源文件标记为 "已压缩"（status_key=compressed）
  文件列表策略列显示 "已压缩：{strategy_name}"
  复选框默认不勾选
  结果列显示上次节省率

DB 有记录但 sidecar 缺失 →
  仍标记 "已压缩"
  策略列显示 "已压缩（审计记录缺失）"

Sidecar 存在但 DB 无记录 →
  从 sidecar 补写 DB 记录
  然后正常标记
```

## 实现范围

### 本次实现
1. `CompressionAudit` 领域模型
2. `build_audit()` 构建函数（在 `FFmpegExecutor.encode()` 中调用）
3. `write_sidecar()` — JSON 序列化写入磁盘
4. `insert_history()` — DB 写入，包含新增字段
5. DB migration — compression_history 新增列
6. `_decision_display` 新增 `compressed` 状态（扫描时检测 sidecar）
7. 文件发现 `find_video_files` 同时收集 sidecar 信息

### 不包含
- 历史面板 UI（远期待做）
- 从 sidecar 批量重新导入 DB
- 压缩报告导出

## 测试要点

- sidecar JSON 结构与 schema 一致
- DB 写入包含所有新字段
- sidecar 和 DB 数据内容一致
- sidecar 写入失败不阻断编码
- 扫描时正确检测 `_zcompressed` 文件和 sidecar
- 已处理文件在文件列表正确标记为不可勾选
