# Delete Source File After Encoding — 设计规格

**日期:** 2026-05-25
**状态:** 已批准

## 概述

编码成功后自动删除原始文件，permanent delete via `Path.unlink()`。

## UI

策略面板（`leanreel/gui/strategy_panel.py`）"保留临时文件（调试用）"下方新增：

```python
self.delete_source_cb = QCheckBox("删除源文件（压缩成功后永久删除）")
self.delete_source_cb.setChecked(False)
encode_layout.addRow(self.delete_source_cb)
```

## 数据流

```
StrategyPanel.delete_source_cb (QCheckBox, 默认 False)
        │
        ▼ 通过 property
EncodingController.start() → FFmpegExecutor(..., delete_source=panel.delete_source)
        │
        ▼ 通过 task._delete_source
FFmpegExecutor.encode() → move_out 成功后，sidecar 写入后
        │
        ▼
_delete_source_file(task.input_path)
```

## 删除逻辑

```python
def _delete_source_file(filepath: str):
    try:
        p = Path(filepath)
        if p.exists():
            p.chmod(0o777)
            p.unlink()
    except Exception:
        pass
```

- 仅当 `task._delete_source` 为 True 且 `task.status == COMPLETED` 时触发
- 删除失败不抛异常，不影响编码结果
- 失败/取消/跳过的任务不删除

## 涉及文件

| 文件 | 改动 |
|------|------|
| `leanreel/gui/strategy_panel.py` | 新增 `delete_source_cb` + `delete_source` property |
| `leanreel/controllers/encoding_controller.py` | 传递 `delete_source` 到 FFmpegExecutor |
| `leanreel/executor/ffmpeg.py` | 接收 `delete_source` 参数 + 编码成功后调用 `_delete_source_file` |

## 安全设计

- 默认关闭（`setChecked(False)`）
- 删除失败静默处理，不阻断编码流程
- 删除前 `chmod(0o777)` 解除只读属性

## 与 Sidecar 的关系

Sidecar 写入在源文件删除之前完成，确保审计记录不丢失。
