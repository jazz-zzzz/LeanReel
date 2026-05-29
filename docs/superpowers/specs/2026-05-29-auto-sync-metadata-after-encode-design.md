# 编码完成后自动同步文件元数据

**日期**: 2026-05-29  
**状态**: 已确认

## 动机

当前编码完成后，输出文件（`_zcompressed`）存在于磁盘上，但其元数据（编码格式、分辨率、HDR、音轨等）不在 `file_snapshot` 表中。若源文件被 `delete_source` 策略删除，旧元数据仍残留于数据库中。

用户必须在每次编码结束后手动点击"刷新扫描"来同步数据库。本功能在编码完成后自动完成这一操作。

## 行为

| 场景 | 操作 |
|------|------|
| 编码成功，输出已提交 | 用 ffprobe 探测新文件 → `file_snapshot` upsert |
| 编码成功 + 源文件被删除 | 追加：从 `file_snapshot` 删除源文件记录 |
| 编码失败 | 不操作（输出不存在） |
| 输出因体积反超被丢弃 | 不操作（输出不存在） |
| 探测失败 | 静默吞掉，不影响编码主流程 |

## 实现位置

`leanreel/executor/ffmpeg.py` — `FFmpegExecutor`

### 选择理由

- `FFmpegExecutor` 已有 `self._db`，且已在同位置执行审计双写（sidecar）和 `finish_compression`
- `SnapshotRepository` 和 `FFprobeRunner` 可从现有依赖直接构造，无需改动构造函数签名
- 操作在 worker 线程池中同步执行，不阻塞 UI
- 符合代码库的"尽力而为"模式（silent failure for non-critical operations）

### 具体插入点

`encode()` 方法中，`# ── 审计双写 ──` 块内，源删除逻辑之后。

## 新增方法

```python
FFmpegExecutor._sync_file_snapshot(task, output_path, source_was_deleted)
```

1. 从 `task.snapshot` 获取 `library_folder_id`、源文件 `relative_path`
2. 创建 `SnapshotRepository(self._db)` 和 `FFprobeRunner()`
3. 计算输出文件的 `relative_path`（源文件目录 + 新文件名）
4. 调用 `FFprobeRunner.probe(output_path, library_folder_id)` → `FileSnapshot`
5. 设置 `relative_path` 和 `file_mtime`
6. 调用 `SnapshotRepository.save()`（已有 ON CONFLICT upsert）
7. 若 `source_was_deleted`，执行 `DELETE FROM file_snapshot WHERE library_folder_id=? AND relative_path=?`
8. 所有异常 `except Exception: pass`

## 测试要点

- 源文件删除后，`file_snapshot` 中不再存在该条目
- 新文件探测成功后，`file_snapshot` 中存在正确元数据
- 源文件未删除时，新旧两条记录均存在于 `file_snapshot`
- 探测失败时，不抛异常，不影响编码成功状态
- 空输入边界：library_folder_id 为 0 时跳过

## 不涉及

- 不做外部媒体服务器 API 调用（Plex、Jellyfin 等）
- 不改变 `file_snapshot` 表结构
- 不改变 `FFmpegExecutor.__init__()` 签名
