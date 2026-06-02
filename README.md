# LeanReel

桌面视频批量压缩工具。将 H.264/HEVC 视频转码为 AV1 或 HEVC，大幅缩减存储体积——**1,747 个文件从 2.4 TB 压缩到 974 GB，平均节省 59%。**

<p align="center">
  <img src="docs/screenshot.png" alt="LeanReel 主界面" width="800">
</p>

## 安装

从 [Releases](https://github.com/jazz-zzzz/LeanReel/releases) 下载最新 `.msi` 或 `.exe` 安装包，双击安装。

**系统要求：**
- Windows 10/11 x64
- 自备 [FFmpeg](https://www.gyan.dev/ffmpeg/builds/)（首次启动在设置中配置路径）
- GPU 编码需 NVIDIA RTX 显卡（CPU 编码无此要求）

## 功能

- **批量编码** — 选中目录一次性处理成百上千个文件，16 线程并行
- **GPU 加速** — 支持 AV1/HEVC/H.264 NVENC 硬件编码，RTX 40 系列 AV1 编码速度 8-15× 实时
- **智能限流** — 自动控制 GPU 并发会话数，避免驱动层报错
- **多种策略** — 内置 AV1 CQ28 保画质 / CQ32 均衡快速 / CPU x265 慢速高质量，支持自定义
- **实时进度** — 多任务轮播展示进度、FPS、码率、SMB 网络吞吐
- **性能采样** — 每任务自动采集编码 FPS/码率，NAS 场景采集 SMB 读写速率和 I/O 队列
- **原子写入** — 临时文件编码完成后 `rename` 到目标路径，崩溃不丢源文件
- **超大保护** — 输出大于源文件自动丢弃，避免反向压缩
- **历史追溯** — 全部编码记录可查，含完整 FFmpeg 命令行和性能数据

## 使用

1. **添加库** — 左侧面板创建库，添加视频目录
2. **扫描** — 点击"扫描"，自动用 ffprobe 探测所有文件的编码/HDR/音轨信息
3. **选择文件** — 表格中勾选要处理的文件（支持 Ctrl/Shift 批量选）
4. **选择策略** — 右侧面板选择编码策略，或自定义参数
5. **开始编码** — 底部"开始编码"按钮，支持删除源文件选项
6. **查看结果** — 顶部"查看任务"面板查看历史、性能数据和累计节省空间

## 策略

| 策略 | 编码器 | 参数 | 适用场景 |
|------|--------|------|----------|
| AV1 CQ28 保画质 | `av1_nvenc` | CQ28, preset p6 | 高画质需求，适合电影/动画蓝光源 |
| AV1 CQ32 均衡快速 | `av1_nvenc` | CQ32, preset p5 | 日常批量压缩，体积优先 |
| x265 CRF18 慢速 | `libx265` | CRF18, preset slow | CPU 高质量，兼容无 NVIDIA 环境 |

> **提示**：AV1 对高码率蓝光源（>5 Mbps）压缩效果极佳，但对已高度压缩的低码率文件（<2 Mbps）可能反而膨胀。遇到膨胀会自动丢弃输出。

## 架构

```
策略 JSON 配置
      │
  ┌───▼──────────────┐
  │ 命令层 (commands) │  Tauri IPC 入口
  └───┬──────────────┘
  ┌───▼──────────────┐
  │ 服务层 (services) │  扫描/匹配/流水线/Worker 线程池
  └───┬──────────────┘
  ┌───▼───────────────┐
  │ 基础设施 (infra)   │  FFmpeg/FFprobe/SQLite/SMB 采样
  └───┬───────────────┘
  ┌───▼──────┐
  │ 领域模型  │  类型定义与接口
  └──────────┘
```

**编码流水线**：Prepare → Transcode → MoveOut，原子提交，失败自动清理。

**GPU 并发控制**：NVIDIA 消费级显卡驱动限制 3 个并发 NVENC 会话。超过此数会触发 `NV_ENC_ERR_INVALID_PARAM`。本工具用 Channel 令牌信号量自动排队——GPU 任务获取令牌后执行、完成后归还，CPU 任务不受影响。

```
16 线程池
  ├─ CPU (libx265) ────────────→ 直接执行
  └─ GPU (NVENC) ──→ 取令牌 ──→ 编码 ──→ 还令牌
                      ↑ 最多 3 个并发
```

**I/O 优化**：NAS 编码场景通过 `-pkt_size 8MB` 扩大 FFmpeg 文件协议缓冲、关闭 Windows SMB 带宽节流（`EnableBandwidthThrottling=false`），确保网络吞吐最大化。

## 从源码构建

```powershell
# 需要 Rust 工具链 + pnpm
pnpm install
pnpm tauri build
```

输出在 `src-tauri/target/release/bundle/`。

## FAQ

**Q: 为什么 AV1 编码有些文件反而变大？**  
A: AV1 在 CQ28 下对低码率源（<2 Mbps）可能膨胀。这类文件的 H.264 压缩已接近极限，AV1 试图保留那些"细节"（本质是编码噪声）反而产生反向压缩。工具会自动丢弃输出大于源的结果。

**Q: 支持 Mac/Linux 吗？**  
A: 目前仅 Windows。Tauri 框架本身跨平台，但 GPU 编码路径和 SMB 采样依赖 Windows 特定 API。

**Q: 为什么限制 3 个并发 GPU 编码？**  
A: NVIDIA 消费级驱动硬限制，无法绕过。CPU 编码（libx265）无此限制。

## 许可

MIT
