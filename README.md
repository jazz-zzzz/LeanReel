# LeanReel

视觉无损视频压缩工具 — 让你的媒体库瘦身而不损画质。

## 特性

- **视觉无损压缩** — x265 CRF 18-22，人眼无法区分
- **4 个内置预设** — 从极限压缩到仅去冗余，一键选择
- **HDR/Dolby Vision 完整支持** — 自动检测并保留/回注 DV RPU
- **多库管理** — 支持 Film / TV / Anime 等多库，每个库可设多个文件夹
- **并行编码** — 多文件同时处理，充分利用多核 CPU
- **可管理队列** — 暂停/恢复/取消，完成历史记录

## 安装

```bash
pip install -e ".[dev]"
```

## 运行

```bash
python -m leanreel.main
```

## 技术栈

Python 3.11+ · PySide6 · FFmpeg (bundled) · dovi_tool (bundled) · SQLite
