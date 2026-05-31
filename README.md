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
