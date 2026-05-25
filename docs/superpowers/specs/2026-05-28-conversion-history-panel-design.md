# Conversion History Panel — 设计规格

**日期:** 2026-05-28
**状态:** 待批准

## 概述

全屏历史转换面板，从 `compression_history` 表读取数据，时间倒序展示所有转换记录。工具栏按钮一键切换。

## 入口与布局

- 状态栏或工具栏新增按钮 "转换历史"，始终可见
- 点击后**隐藏三面板**（库/文件/策略），全屏显示历史面板
- 再次点击或按返回按钮切回文件列表视图

## 数据源

```
compression_history
  JOIN file_snapshot ON file_snapshot_id = file_snapshot.id
  JOIN library_folder ON library_folder_id = library_folder.id
  JOIN library ON library_id = library.id
```

**纯 DB 查询，展示时不做任何文件系统访问。**

## 列表列

| 列 | 字段 | 说明 |
|------|------|------|
| 源文件名 | snapshot.file_name | |
| 库 | library.name | |
| 文件夹 | library_folder.path | |
| 源体积 | original_size | 格式化显示 |
| 输出体积 | output_size_bytes | 格式化显示 |
| 节省量 | original_size - output_size_bytes | 格式化显示 |
| 节省率 | savings_pct | 百分比 |
| 策略 | strategy_name | |
| 编码器 | encoder | libx265 / hevc_nvenc / av1_nvenc / copy |
| CQ/CRF | cq_value | |
| 耗时 | duration_seconds | 格式化显示 |
| 完成时间 | created_at | |
| 状态 | status | completed / failed / cancelled |
| 源已删 | source_deleted | 是 / 否 |

## 筛选

顶部筛选栏：
- 按库（下拉，可选全部）
- 按策略（下拉，可选全部）
- 按状态（下拉：全部 / 成功 / 失败 / 已取消）

## 交互

### 双击行
- 用系统文件浏览器定位**输出文件**（`output_path`）
- 输出文件不存在 → 弹提示："输出文件已不存在" + 可能原因（体积反超被丢弃 / 文件被手动删除）
- 不做任何文件存在性预检查（不用 `os.path.exists`）

### 源文件信息
- `source_deleted = 1` 时显示"是"，否则"否"
- 来源：DB 字段，不是文件系统检查

## 文件列表联动

`_decision_display` 中"已压缩"判断改为查询 `compression_history` 表：
- 源文件在 compression_history 中有 completed 记录 → 标记为"已压缩"
- 策略列显示："已被压缩为 XXX 片源"（XXX 从 encoder 字段映射）

Encoder 映射：
- libx265 → HEVC
- hevc_nvenc → HEVC
- av1_nvenc → AV1
- copy → 流复制

## 实现范围

### 包含
1. `gui/history_panel.py` — 全屏面板（QTableView + 筛选栏 + 返回按钮）
2. `gui/main_window.py` — 集成切换逻辑（QStackedWidget）
3. `infrastructure/database.py` — 新增 `get_all_history()` 查询方法
4. `gui/file_list.py` — `_decision_display` 接受 `compressed_info` 参数从 DB 判断
5. `controllers/scan_controller.py` — 扫描时查询 compression_history 标记已压缩文件

### 不包含
- 历史记录编辑/删除
- 导出报告
- 图表/统计
- Sidecar 文件内容查看

## 测试要点
- 历史面板从 DB 正确读取所有字段
- 筛选功能正确过滤
- 双击定位输出文件
- 输出文件不存在时正确弹提示
- 文件列表正确标记已压缩文件（从 DB 判断）
- 全屏切换不丢失状态
