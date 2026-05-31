# LeanReel

桌面视频压缩工具。批量将视频转码为 HEVC/AV1，大幅缩减存储体积的同时保留画质。

## 技术栈

| 层 | 技术 |
|---|------|
| 桌面壳 | Tauri 2.x |
| 后端 | Rust |
| 前端 | Svelte 5 |
| 数据库 | SQLite |
| 编码 | FFmpeg |

## 目录结构

```
src/          Svelte 前端
src-tauri/    Rust 后端
  ├── src/domain/        领域模型与接口
  ├── src/infrastructure/ FFmpeg/FFprobe/SQLite 实现
  ├── src/services/       扫描/匹配/流水线/队列
  └── src/commands/       Tauri 命令层
strategies/   策略 JSON 配置文件
```

## 架构

单向四层依赖：`命令层 → 服务层 → 基础设施层 → 领域层`

编码流水线固定 3 阶段：**Prepare → Transcode → MoveOut**，采用原子提交策略。

### GPU 并发控制

NVIDIA 消费级 GPU 驱动硬限制 **3 个并发 NVENC 编码会话**。若 16 线程池同时启动超过 3 个 GPU 编码任务，额外的 `av1_nvenc`/`hevc_nvenc`/`h264_nvenc` 会话会收到 `NV_ENC_ERR_INVALID_PARAM (-22)` 并立即失败。

**方案：Channel 令牌信号量**

```
Worker 线程池 (16 线程)
     │
     ├─ CPU 任务 (libx265): 直接执行，不受限制
     │
     └─ GPU 任务 (NVENC):
          │
          └─ 获取令牌 ──→ 有令牌? ──是──→ 启动 ffmpeg
                  ↑                │
                  │               否 (阻塞等待)
                  │                │
                  └── 归还令牌 ←──┘ 编码完成
     令牌总数: 3 (与驱动限制一致)
```

实现细节：
- 用 `mpsc::channel` 预填 3 个 `()` 令牌，天然 FIFO 保证公平排队
- `GpuToken` RAII 守卫在 `Drop` 时自动归还令牌，异常安全
- `recv()` 阻塞不消耗 CPU，令牌不足时线程挂起而非忙等
- CPU 编码（`libx265`）不经过信号量，16 线程可全速并行
- 准备/搬运（Prepare/MoveOut）阶段不占用 GPU，线程不会空闲

### 错误诊断

FFmpeg 失败时，完整命令行会同时输出到：
1. 控制台日志 (`eprintln!`)
2. 前端错误提示
3. 数据库 `compression_history.ffmpeg_command` 字段

便于从参数层面精准定位编码失败原因。

## 开发

```powershell
# 安装依赖
pnpm install

# 启动 (前端 + 后端编译)
.\dev.ps1
```

需要 Rust 工具链和 ffprobe/ffmpeg 可执行文件。首次运行可在设置面板配置路径。

## 许可

MIT
