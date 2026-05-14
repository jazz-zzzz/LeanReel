# SpaceSaver — 设计规格说明书

> 跨平台视觉无损视频压缩工具，面向个人媒体库管理。Python + PySide6 桌面应用。

**状态：** 已确认  
**日期：** 2026-05-14

---

## 1. 项目定位

SpaceSaver 是一个跨平台（Windows + macOS）桌面应用，帮助用户对视频媒体库进行**视觉无损压缩**，在画质不可感知的前提下显著减小文件体积。

### 1.1 核心原则

- **视觉无损优先** — 默认策略 CRF 20（x265），人眼无法区分
- **安全第一** — 默认输出到新位置，不直接覆盖原文件
- **透明可解释** — 每个策略附参数说明、画质影响、预期节省
- **本地运行** — 程序运行在本地，NAS 仅作为 SMB 挂载的普通目录

### 1.2 不在范围内

- 命名规范化、元数据刮削
- 图片/音频文件压缩
- 分布式集群编码
- 流媒体/浏览器播放

---

## 2. 技术栈

| 层 | 技术 | 理由 |
|---|------|------|
| GUI | PySide6 | 跨平台原生渲染，Qt 成熟稳定 |
| 业务逻辑 | Python 3.11+ | FFmpeg 生态最好，快速迭代 |
| 编码执行 | FFmpeg + dovi_tool（内置便携版） | 打包自带二进制，不依赖系统安装 |
| DV 处理 | dovi_tool | 提取/注入 Dolby Vision RPU，处理 Profile 7 双层结构 |
| 数据存储 | SQLite | 零配置，单文件，足够承载 |
| 策略定义 | JSON 文件 | 人类可读可编辑，新增策略不改代码 |
| 打包 | PyInstaller | 单目录/单文件输出，Win+Mac |

---

## 3. 架构总览

```
┌─────────────────────────────────────────────────────┐
│                    GUI 层 (PySide6)                   │
│  主窗口 · 库面板 · 文件列表 · 策略配置 · 队列面板       │
├─────────────────────────────────────────────────────┤
│                    业务层 (Python)                    │
│  库管理 · 文件扫描 · 策略引擎 · 规则匹配 · HDR/DV 检测  │
├─────────────────────────────────────────────────────┤
│                    执行层 (Python)                    │
│  FFmpeg 封装 · dovi_tool · 并行 Worker · 进度上报      │
├─────────────────────────────────────────────────────┤
│                    数据层                             │
│  SQLite (库/文件/历史) · JSON (策略) · Config (设置)   │
└─────────────────────────────────────────────────────┘
```

### 3.1 分层职责

**GUI 层** — 纯展示，不包含业务逻辑。通过信号/槽与业务层通信。

**业务层** — 所有决策逻辑所在。策略匹配、体积预估、任务生成均在业务层完成。

**执行层** — 封装 FFmpeg 和 dovi_tool 子进程调用。管理 Worker 池，上报进度，处理崩溃恢复。

**数据层** — SQLite 存储持久数据（库配置、文件快照、压缩历史），JSON 存储策略定义模板。

---

## 4. 功能模块

### 4.1 库管理

- 用户可创建多个「库」（如 Film、TV、Anime）
- 每个库可添加多个文件夹路径（本地或 SMB/NFS 挂载均可）
- 左侧面板：库列表 → 选中库后展开文件夹列表
- 支持增删改，库配置持久化到 SQLite

### 4.2 文件扫描

- 递归扫描库下所有文件夹
- 使用 FFprobe 提取元数据：编码格式、分辨率、码率、音轨信息（编码/声道/语言）、字幕轨信息
- 文件信息缓存到 SQLite，增量扫描仅更新变更
- 显示：文件名、体积、视频编码、音频编码、当前策略标签、预计节省

### 4.3 策略系统

#### 4.3.1 四个内置预设

| 预设 | 视频规则 | 音频规则 | HDR/DV处理 | 字幕/轨 | 预计节省 |
|------|---------|---------|-----------|---------|---------|
| **极限压缩** | x264/AVC→x265 CRF22 | 保持原音频 | HDR10保留,DV降为HDR10 | 去非中文轨 | 50-70% |
| **均衡压缩** ⭐ | x264/AVC/REMUX→x265 CRF20 | 保持原音频 | HDR10保留,DV注回RPU | 去评论轨 | 35-50% |
| **轻量压缩** | 仅 REMUX→x265 CRF18 | 保持原音频 | HDR10保留,DV注回RPU | 全部保留 | 20-35% |
| **仅去冗余** | 不重编码 | 保持原音频 | 不处理 | 去多余轨 | 5-15% |

#### 4.3.2 HDR / Dolby Vision 处理

HDR/DV 内容在重编码时需要特殊处理，否则会丢失动态元数据或色彩信息。

**HDR 类型检测（FFprobe 自动识别）：**

| 类型 | FFprobe 标识 | 来源 | 重编码风险 | 处理方案 |
|------|-------------|------|-----------|---------|
| **SDR** | 无 HDR 元数据 | 普通 BluRay/WEB | 无 | 正常编码 |
| **HDR10** | `color_transfer=smpte2084`, `color_primaries=bt2020` | UHD BluRay | 低 | x265 保留色彩空间+PQ+MD |
| **HDR10+** | 含 `mastering_display` + 动态元数据 SEI | UHD BluRay | 低 | x265 `--hdr10+` 参数 |
| **DV Profile 5** | `dolby_vision=5`, 单层 IPTPQc2 | 流媒体 WEB-DL | 中 | x265 `--dolby-vision-profile 5` |
| **DV Profile 7** | `dolby_vision=7`, 双层 BL+EL+RPU | UHD 原盘 REMUX | **高** | 需 dovi_tool 提取RPU→编码→回注 |
| **DV Profile 8** | `dolby_vision=8`, 单层 HDR10+RPU | WEB-DL / 重编码 | 中 | x265 `--dolby-vision-profile 8.1` |

**DV Profile 7 处理流程（最关键的路径）：**

```
1. FFprobe 识别 → DV Profile 7 → 弹出确认对话框
2. dovi_tool extract-rpu → 提取 RPU.bin
3. x265 编码 HDR10 基层（--hdr10 --colorprim bt2020 --transfer smpte2084 --colormatrix bt2020nc）
4. dovi_tool inject-rpu → 将 RPU 回注到编码后的 HEVC 流
5. MKV 封装，保留 DV 元数据
```

**用户交互：**
- 扫描时标注每个文件的 HDR 类型（图标 + 标签）
- DV Profile 7 文件在应用策略前弹出确认框，说明处理步骤和风险
- 提供"降级为 HDR10"选项（放弃 DV 增强层，节省处理复杂度）
- DV 处理失败时保留原 RPU 文件和日志，支持手动恢复

#### 4.3.3 高级模式（规则链）

用户可以自定义规则链，每项规则含：

- **视频规则**：x264/AVC→x265 / REMUX→x265 / 保持原编码 / 自定义编码器，指定 CRF 值
- **HDR/DV规则**：保留HDR10元数据 / 保留并回注DV RPU / 降级为HDR10（丢弃DV增强层）
- **音频规则**：保持原音频（默认，不重编码）/ 去除非指定语言音轨 / 去除评论轨 / 仅保留第一条音轨
- **字幕规则**：仅保留中文 / 保留中英 / 全部保留 / 全部删除 / 自定义语言列表
- **过滤器**：跳过已 x265 文件 / 仅处理 REMUX / 仅处理大于 N GB / 仅处理特定编码

参数附说明（tooltip），例如 CRF 滑块标注：
> **CRF 18**：极高画质，文件较大。适合 4K HDR 内容  
> **CRF 20**：视觉透明，推荐日常使用  
> **CRF 22**：轻微损失，适合 1080p 动画

#### 4.3.3 策略扩展

策略定义为 JSON 文件存储在 `strategies/` 目录。用户可复制修改创建自定义预设，程序启动时自动加载。格式：

```json
{
  "name": "均衡压缩",
  "description": "视觉无损，适合大多数场景。HDR保留，DV回注RPU。音频不重编码。",
  "is_preset": true,
  "video": {"encoder": "libx265", "crf": 20, "preset": "slow", "pix_fmt": "yuv420p10le"},
  "hdr": {"mode": "preserve_hdr10", "dv_handling": "reinject_rpu"},
  "audio": {"mode": "keep_original", "remove_commentary": true, "remove_non_preferred_langs": false},
  "subtitle": {"mode": "keep_chinese"},
  "filters": {"skip_x265": true, "min_size_gb": null},
  "estimated_savings": "35-50%",
  "quality_impact": "视觉无损，HDR/DV完整保留，音频原样保留"
}
```

#### 4.3.4 策略参数说明要求

每个参数在 GUI 中必须附带清晰的中文说明，包括：
- 该参数的含义（一句话）
- 对画质/音质的影响
- 对文件体积的影响
- 推荐值及适用场景

### 4.4 策略分配

- 扫描完成后，自动按规则匹配给出建议策略
- 用户可在文件列表中批量选中后手动覆盖策略
- 策略匹配逻辑：自上而下匹配过滤器规则，命中即应用

### 4.5 并行编码

- 可配置同时编码的 Worker 数量（1-16，默认 4）
- 每个 Worker 独立子进程，调用 FFmpeg
- CPU/内存使用率实时显示，提示用户合理设置
- 不支持单文件分段并行（破坏帧间参考）

### 4.6 输出处理

- 默认行为：压缩文件输出到原文件同目录（添加 `_SS` 后缀），原文件移至备份目录
- 可配置选项：
  - 输出目录（可指定不同于原文件的位置）
  - 压缩完成后自动删除原文件（默认关闭，需用户手动开启）
  - 备份目录路径

### 4.7 任务队列

- 队列面板显示所有待处理/进行中/已完成任务
- 支持：拖拽排序、暂停/恢复单个任务、取消任务
- 每个任务显示：文件名、压缩前体积、当前进度百分比、预估剩余时间、当前速率(fps)
- 完成的任务显示：压缩前后对比、节省百分比、耗时
- 出错任务显示错误信息，支持重试

### 4.8 历史记录

- 所有完成的压缩任务记录到 SQLite
- 可按库/日期/策略筛选查看
- 汇总统计：总处理文件数、总节省空间、平均压缩比

---

## 5. GUI 布局

```
┌──────────┬──────────────────────────┬──────────┐
│ 库面板    │     文件列表              │ 策略面板  │
│ (180px)  │     (flex)              │ (220px)  │
│          │                        │          │
│ Film 831 │ 文件名 | 体积 | 编码 | 策略│ 预设选择  │
│ TV   0   │ ...                    │ 并行设置  │
│ Anime 0  │ ...                    │ 输出设置  │
│          │                        │ [开始]   │
│ [+添加]  │                        │          │
├──────────┴──────────────────────────┴──────────┤
│           队列面板（可折叠，底部弹出）             │
│  ✓ done │ ⏳ running 42% ████░░ │ ⏳ waiting   │
└────────────────────────────────────────────────┘
```

### 5.1 顶部工具栏

- 扫描库按钮
- 高级模式切换开关
- 搜索/筛选文件

### 5.2 底部状态栏

- 总文件数 / 总大小 / 预计可节省空间
- 当前 Worker 状态

---

## 6. 数据模型（SQLite 核心表）

```sql
-- 库
CREATE TABLE library (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

-- 库文件夹
CREATE TABLE library_folder (
    id INTEGER PRIMARY KEY,
    library_id INTEGER REFERENCES library(id),
    path TEXT NOT NULL,
    UNIQUE(library_id, path)
);

-- 文件快照（扫描结果缓存）
CREATE TABLE file_snapshot (
    id INTEGER PRIMARY KEY,
    library_folder_id INTEGER REFERENCES library_folder(id),
    relative_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    size_bytes INTEGER,
    video_codec TEXT,
    video_width INTEGER,
    video_height INTEGER,
    hdr_type TEXT,            -- 'SDR', 'HDR10', 'HDR10+', 'DV_P5', 'DV_P7', 'DV_P8'
    audio_tracks TEXT,       -- JSON array
    subtitle_tracks TEXT,    -- JSON array
    duration_seconds REAL,
    bitrate_bps INTEGER,
    scanned_at TEXT DEFAULT (datetime('now')),
    UNIQUE(library_folder_id, relative_path)
);

-- 压缩历史
CREATE TABLE compression_history (
    id INTEGER PRIMARY KEY,
    file_snapshot_id INTEGER REFERENCES file_snapshot(id),
    strategy_name TEXT NOT NULL,
    original_size INTEGER,
    compressed_size INTEGER,
    status TEXT,             -- 'completed', 'failed', 'cancelled'
    duration_seconds INTEGER,
    error_message TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
```

---

## 7. 扩展预留

- **策略 JSON 加载** — 新增策略只需添加 JSON 文件，无需改代码
- **Worker 插件化** — 执行层 Worker 抽象为接口，未来可接入 GPU 编码 (NVENC/QSV/VideoToolbox)
- **前后端分离** — 业务层无 GUI 依赖，未来可移植到 Web 架构
- **i18n 预留** — 所有用户可见字符串集中管理

---

## 8. 非功能性需求

- 扫描 1000 个文件应在 30 秒内完成（依赖 FFprobe 并发数）
- 编码过程中 GUI 不卡顿（业务逻辑在后台线程）
- 程序异常退出后重启，未完成任务自动标记为失败
- 编码中途可安全取消（发送 SIGTERM 给 FFmpeg 子进程，不产生损坏文件）

---

## 9. 文件结构（规划）

```
SpaceSaver/
├── spacesaver/
│   ├── __init__.py
│   ├── main.py              # 入口
│   ├── gui/
│   │   ├── __init__.py
│   │   ├── main_window.py   # 主窗口
│   │   ├── library_panel.py # 库面板
│   │   ├── file_list.py     # 文件列表
│   │   ├── strategy_panel.py# 策略面板
│   │   └── queue_panel.py   # 队列面板
│   ├── core/
│   │   ├── __init__.py
│   │   ├── library.py       # 库管理
│   │   ├── scanner.py       # 文件扫描
│   │   ├── strategy.py      # 策略引擎
│   │   └── matcher.py       # 规则匹配
│   ├── executor/
│   │   ├── __init__.py
│   │   ├── worker.py        # Worker 管理
│   │   ├── ffmpeg.py        # FFmpeg 调用封装
│   │   ├── probe.py         # FFprobe 封装
│   │   └── dovi.py          # dovi_tool 调用封装 (RPU提取/注入)
│   ├── data/
│   │   ├── __init__.py
│   │   ├── database.py      # SQLite 操作
│   │   └── models.py        # 数据模型
│   └── resources/
│       ├── strategies/      # JSON 策略定义
│       │   ├── extreme.json
│       │   ├── balanced.json
│       │   ├── light.json
│       │   └── strip_only.json
│       ├── ffmpeg/          # 便携 FFmpeg 二进制
│       └── dovi_tool/       # 便携 dovi_tool 二进制
├── tests/
├── docs/superpowers/specs/
├── requirements.txt
└── README.md
```
