# LeanReel 功能/行为硬实现规范

> 每一个条目都是强制约束。实现必须逐条满足。改动必须更新本文档。

## 1. 列表页（平铺视图）

### 1.1 列定义

| 序号 | 表头 | 宽度 | 缩放 | 数据源 | 排序 |
|------|------|------|------|--------|------|
| 0 | `""` | 30px | Fixed | `store.is_checked(key)` → `Qt.Checked`/`Unchecked` | — |
| 1 | `文件名` | 260px | Interactive | `snap.file_name` | 文本 |
| 2 | `体积` | 70px | Interactive | `snap.size_bytes` → 格式化文本，`Qt.UserRole`=原始数值 | 数值 |
| 3 | `编码信息` | 175px | Interactive | `snap.video_codec` + 分辨率 | — |
| 4 | `HDR` | 60px | Interactive | `snap.hdr_type.value` | — |
| 5 | `处理策略` | 260px | Interactive | `decision.strategy_text` | — |
| 6 | `预计结果` | 190px | Interactive | `decision.result_text`, `Qt.UserRole`=`decision.result_sort` | 数值 |

### 1.2 QComboBox 策略下拉

- **必须一直可见**（不是双击才出现）。使用 `QTableView.openPersistentEditor(index)` 对列 5 的每一行 `processable=True` 开启。
- 过滤后重建时，需要先 `closePersistentEditor` 再 `openPersistentEditor`。
- 滚轮事件必须被忽略（`combo.wheelEvent = lambda e: e.ignore()`）。
- 选择"自定义"时发射 `custom_strategy_requested` 信号。
- 选择任何其他策略时发射 `strategy_override_changed` 信号。
- 策略变更后，列 6 的预计结果必须同步刷新。

### 1.3 复选框

- `processable=True` 的行可勾选（`Qt.ItemIsUserCheckable | Qt.ItemIsEnabled`）。
- `processable=False` 的行不可勾选（`Qt.ItemIsUserCheckable`，disable）。
- 勾选变更 → `store.set_checked(key, state)` → `checked_changed` 信号。
- "全选"只作用于 `processable=True` 的行。

### 1.4 过滤

- 过滤器选项：全部/可处理/已保护跳过/探测失败/已选择。
- 切换过滤 → `model.set_filter(key)` → `_visible_rows` 重建 → `layoutChanged`。
- 统计数字（"已选中 N/M 个可处理文件"）基于 `store` 的实际计数，不受过滤影响。

### 1.5 颜色规则

| 列 | 条件 | 颜色 |
|----|------|------|
| 3(编码) | `probe_ok=True` 且有编码 | `#8db87c` 绿 |
| 3(编码) | 探测失败 | `#c8675e` 红 |
| 3(编码) | 其他 | `#6b6560` 灰 |
| 4(HDR) | DV | `#6ba8d6` 蓝 |
| 4(HDR) | HDR10/HDR10+ | `#d4a853` 金 |
| 4(HDR) | SDR | `#6b6560` 灰 |
| 5(策略) | protected | `#6ba8d6` 蓝 |
| 5(策略) | probe_failed | `#c8675e` 红 |

---

## 2. 树视图

### 2.1 结构

- 顶层节点 = 文件夹（加粗）。
- 子节点 = 文件。
- 文件夹名称从 `snap.relative_path` 提取（`rsplit("/", 1)[0]` 或 `"."`）。

### 2.2 列

| 0 | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| 文件名 | 体积 | 编码 | HDR | 策略 | 预计结果 |

- 文件夹行：列 0 = 目录名，列 1 = 文件夹总大小（`_format_bytes`），其余列空白。
- 文件夹行的列 1 存储 `Qt.UserRole`=总字节数，用于排序。

### 2.3 勾选

- 叶子节点可勾选当 `processable=True`。
- 勾选变更 → `store.set_checked(key, state)`。
- 切换平铺↔树时，勾选状态必须保持一致（读同一 `store._checked`）。

### 2.4 颜色

- 与平铺视图完全一致。

### 2.5 右键菜单

- 文件夹节点右键 → "重建此文件夹缓存" → 发射 `tree_folder_refresh_requested(folder_id)`。

---

## 3. 数据流

### 3.1 单数据源

- `FileTableStore` 是所有文件数据的**唯一**存储。
- 不存在任何 `_snapshots_by_path`、`_last_matches`、`_row_by_path` 等备份 dict。
- 控制器中 `current_snapshots` 仅用于编码启动时的路径解析——不用于 UI 渲染。

### 3.2 写入路径

```
控制器 _populate_file_list
  → store.rebuild(rows)           # 全量替换
  → rows_rebuilt 信号
  → Model._on_rebuilt
  → layoutChanged 信号
  → QTableView 重绘全部可见行
```

```
控制器 _on_result (探测完成)
  → store.update_row(key, snap, match)
  → row_updated 信号
  → Model._on_row_updated
  → dataChanged 信号 (单行范围)
  → QTableView 只重绘这一行
```

### 3.3 探测定时更新

- 频率：8 线程并行，每个探测 ~0.1s → ~80 次/秒。
- 每次更新：仅 `dataChanged(row, row)` 一行范围。
- 禁止：全表重绘 (`layoutChanged`)、QTableWidget.setItem。

### 3.4 信号契约

| 信号 | 发射者 | 接收者 | 用途 |
|------|--------|--------|------|
| `rows_rebuilt` | Store | Model | 全量数据替换 |
| `row_updated(int, FileRow)` | Store | Model | 单行更新 |
| `checked_changed` | Store | Model, TreeAdapter | 勾选同步 |
| `probed(Snapshot, MatchResult)` | Controller | (历史，无连接) | — |
| `progress(int, int)` | Controller | 状态栏 | 探测进度 |
| `all_done` | Controller | 状态栏+sorting | 探测完成 |
| `scan_ready` | 后台线程 | Controller | 目录遍历完毕 |

---

## 4. 刷新/重建行为

### 4.1 全量重建（"重建缓存"按钮）

1. 后台线程：`find_video_files` × 所有文件夹 → 创建占位快照 → `scan_ready` 信号。
2. 主线程：新旧合并——`is_probe_complete(old)` 的保留，其余用占位符。
3. `_populate_file_list` → `store.rebuild` → 表格刷新。
4. `probe_multi` 启动：共享一个线程池，每个文件 `os.stat` + 缓存校验 + (命中?跳过:ffprobe)。
5. 每个探测完成 → `store.update_row` → UI 流式刷新。

### 4.2 单文件夹重建（右键）

- 仅针对一个 `folder_id` 执行上述流程。

### 4.3 添加文件夹

- 同单文件夹重建流程。

### 4.4 缓存校验规则

```
缓存命中条件（全部满足才跳过 ffprobe）：
  existing.size_bytes == os.stat().st_size      # 体积未变
  AND existing.file_mtime == os.stat().st_mtime  # 修改时间未变
  AND is_probe_complete(existing)                # 数据完整

is_probe_complete:
  probe_ok == True
  AND video_codec != ""
  AND size_bytes > 0
  AND video_width > 0
  AND video_height > 0
```

---

## 5. 性能约束

| 指标 | 约束值 | 验证方法 |
|------|--------|---------|
| 重建缓存：点击到首条反馈 | <500ms | 人工计时 |
| 主线程单次阻塞 | <50ms | 主观不卡 |
| 探测定时更新渲染 | 仅 `dataChanged(row,row)` | 代码审查 |
| 树视图构建 | <200ms（异步） | `blockSignals(True)` 包裹 |
| QComboBox 创建 | `openPersistentEditor`，行级按需 | 代码审查 |

---

## 6. 测试覆盖

### 6.1 必须通过的测试

```bash
pytest tests/ -q  # 必须 333+ passed
```

### 6.2 测试不可逃逸规约

- 每个公开方法至少 1 个测试。
- 每类边界条件至少 1 个测试（空列表、单元素、0 值、NaN）。
- 测试必须用真实 FileTableStore 数据，不得 mock 核心路径。
