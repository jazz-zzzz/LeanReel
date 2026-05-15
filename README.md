# LeanReel

LeanReel 是一个面向个人媒体库的桌面视频压缩工具。它用 PySide6 提供图形界面，内置 FFmpeg / FFprobe / dovi_tool，帮助你扫描影片目录、识别编码信息、选择压缩策略，并以更安全的方式生成压缩任务。

目标很简单：让媒体库变轻，同时尽量保留你真正关心的画质、音轨和 HDR 信息。

## Highlights

- **媒体库扫描**：递归扫描电影、剧集、动画等目录，缓存文件大小、编码、HDR、音轨、字幕等元数据。
- **真实编码识别**：通过 FFprobe 识别视频编码；旧缓存缺失编码时会自动重新探测。
- **策略预设与自定义**：内置均衡、极限、轻量、仅去冗余等策略，也支持按文件选择自定义参数。
- **预计节省空间**：根据策略实时估算节省空间，切换策略或调整自定义 CRF 后即时刷新。
- **列表与目录树视图**：支持平铺列表和目录树两种浏览方式，表格列可手动调整宽度并支持排序。
- **并发扫描与队列基础**：扫描阶段并发探测文件元数据，编码任务通过队列执行并显示状态。
- **安全默认输出**：默认生成 `_SS` 后缀文件，避免直接覆盖原始媒体。

## Interface

LeanReel 的主界面分为四个区域：

| 区域 | 用途 |
| --- | --- |
| Library | 管理媒体库和库下文件夹 |
| File List | 查看文件、编码、HDR、匹配策略、预计节省空间 |
| Strategy Panel | 选择预设策略或编辑自定义参数 |
| Queue | 查看编码任务状态与结果 |

文件列表支持两种模式：

- **平铺**：适合快速排序、筛选和批量检查。
- **目录树**：适合按剧集、季度、子目录浏览媒体结构。

## Quick Start

### 1. 准备环境

```bash
py -m pip install -e ".[dev]"
```

如果你的环境中 `python` 可用，也可以使用：

```bash
python -m pip install -e ".[dev]"
```

### 2. 启动应用

```bash
py -m leanreel.main
```

或：

```bash
python -m leanreel.main
```

### 3. 使用流程

1. 在左侧创建一个媒体库，例如 `Film`、`TV` 或 `Anime`。
2. 为媒体库添加一个或多个文件夹。
3. 等待扫描完成，确认列表中的编码、HDR 和预计节省空间。
4. 在每个文件行中选择预设策略，或选择“自定义”并在右侧调整参数。
5. 点击“开始压缩”，LeanReel 会使用安全的 `_SS` 输出路径生成任务。

## Built-in Strategies

| 策略 | 适合场景 | 默认方向 |
| --- | --- | --- |
| 均衡压缩 | 大多数电影和剧集 | x265 CRF 20，兼顾画质与体积 |
| 极限压缩 | 体积优先 | 更高压缩率，更激进的节省估算 |
| 轻量压缩 | 画质优先 | 较保守参数，适合高质量源 |
| 仅去冗余 | 不想重编码视频 | 尽量保留视频，仅整理冗余轨道 |

自定义策略当前支持：

- 编码器：`libx265`、`libx264`、`copy`
- CRF：`0` 到 `35`
- 编码预设：`medium`、`slow`、`slower`、`fast`
- 音轨处理：保留原始音轨或移除评论轨
- 字幕处理：保留中文、中英、全部或移除

## Project Status

LeanReel 仍处于早期版本。当前重点是把本地媒体扫描、策略选择、任务生成和基础编码链路跑通。

已经具备：

- SQLite 持久化
- FFprobe 元数据扫描
- 并发元数据探测
- 策略预设加载
- 文件级策略覆盖
- 自定义策略面板
- PyInstaller 打包配置

仍在演进：

- 更完整的后台编码进度
- 更细的取消、暂停、恢复控制
- Dolby Vision Profile 7 的完整端到端工作流
- 旧缓存迁移和更丰富的错误恢复
- 跨平台发布包验证

## Development

运行测试：

```bash
py -m pytest -q
```

编译检查：

```bash
py -m compileall -q leanreel tests
```

构建 Windows 可执行文件：

```bash
py -m PyInstaller build.spec --noconfirm
```

## Tech Stack

- Python 3.11+
- PySide6
- SQLite
- FFmpeg / FFprobe
- dovi_tool
- pytest
- PyInstaller

## Safety Notes

LeanReel 默认不会直接覆盖原始视频文件。压缩输出会使用 `_SS` 后缀，例如：

```text
Movie.mkv -> Movie_SS.mkv
```

在大规模处理媒体库前，建议先用一个小文件夹验证策略、画质和输出路径。对于 HDR / Dolby Vision 内容，也建议先抽样测试，确认播放器和设备链路符合预期。
