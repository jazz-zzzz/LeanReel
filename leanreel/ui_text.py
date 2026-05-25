"""Centralized user-facing copy for LeanReel."""
from __future__ import annotations


class UIText:
    READY = "就绪"
    PAUSE = "暂停"
    RESUME = "继续"
    CANCEL_ALL = "取消全部"
    CLEAR_FINISHED = "清空已完成"

    NO_FOLDERS = "没有已添加的文件夹，请先添加文件夹"
    SCAN_ALREADY_RUNNING = "当前库扫描已在进行中，请等待完成"
    SCANNING = "扫描中..."
    LOADING_CACHE = "加载缓存中..."
    NO_CHECKED_FILES = "没有勾选任何文件，请先在文件列表中勾选要处理的文件"
    CHECKED_FILES_MISSING = "勾选的文件未找到"
    LIBRARY_DELETED = "库已删除"
    FOLDER_REMOVED = "文件夹已移除"
    ENCODING_INFO_PROBED = "编码信息探测完成"

    ENCODE_IN_PROGRESS = "编码正在进行中，请等待完成"
    NO_STRATEGY = "没有可用策略"
    NO_ENCODABLE_FILES = "没有可压缩文件"
    ENCODE_RESUMED = "编码已恢复"
    ENCODE_PAUSED = "编码已暂停（等待当前任务完成）"
    ENCODE_CANCELING = "正在取消编码..."

    UNKNOWN_ERROR = "未知错误"
    SKIPPED = "已跳过"

    MAIN_MENU_FILE = "文件(&F)"
    MAIN_MENU_EXIT = "退出(&X)"
    MAIN_MENU_VIEW = "视图(&V)"
    MAIN_MENU_QUEUE_TOGGLE = "显示/隐藏队列"
    MAIN_MENU_HELP = "帮助(&H)"
    MAIN_MENU_ABOUT = "关于 LeanReel"
    MAIN_ABOUT_TITLE = "关于 LeanReel"
    MAIN_ABOUT_BODY = (
        "LeanReel — 视频压缩管理工具\n\n"
        "默认保护 HEVC/HDR/Dolby Vision 片源。\n"
        "为 SDR 旧编码片源提供可解释的本地转码策略。"
    )
    QUEUE_DOCK_TITLE = "任务队列"

    FILE_HEADERS = ["", "文件名", "体积", "编码信息", "HDR", "处理策略", "预计结果"]
    FILE_TREE_HEADERS = ["文件夹名", "体积", "文件数", "编码信息", "HDR", "处理策略", "预计结果"]
    FILE_UNSCANNED = "未扫描"
    FILE_REBUILD_CACHE = "重建缓存"
    FILE_REBUILD_CACHE_TOOLTIP = "重新扫描所有文件夹并重建编码信息缓存"
    FILE_PROGRESS_FORMAT = "探测中... %v/%m"
    FILE_VIEW_FLAT = "平铺"
    FILE_VIEW_TREE = "目录树"
    FILE_FILTER_ALL = "全部"
    FILE_FILTER_PROCESSABLE = "可处理"
    FILE_FILTER_PROTECTED = "已保护跳过"
    FILE_FILTER_PROBE_FAILED = "探测失败"
    FILE_FILTER_CHECKED = "已选择"
    FILE_EMPTY_HINT = "请先在左侧添加库和文件夹以扫描视频文件"
    FILE_SELECT_ALL = "全选"
    FILE_DESELECT_ALL = "取消全选"
    FILE_DISABLED_REASON = "该文件当前不可选择"
    FILE_REBUILD_FOLDER_CACHE = "重建此文件夹缓存"
    FILE_PROBE_FAILED = "探测失败"
    FILE_PROBING = "探测中..."
    FILE_UNRECOGNIZED = "未识别"
    FILE_UNMATCHED = "未匹配"
    FILE_CUSTOM_STRATEGY = "自定义"
    FILE_COMPRESSED = "已压缩"
    FILE_COMPLETED = "已完成"
    FILE_NOT_PROCESS = "不处理"
    FILE_CANNOT_ESTIMATE = "无法估算"
    FILE_PROBING_TOOLTIP = "正在探测编码信息"

    LIBRARY_NEW = "+ 新建"
    LIBRARY_NEW_TOOLTIP = "新建库"
    LIBRARY_SEARCH_PLACEHOLDER = "搜索库或文件夹..."
    LIBRARY_NO_MATCH = "没有匹配的库或文件夹"
    LIBRARY_DIALOG_NEW_TITLE = "新建库"
    LIBRARY_DIALOG_NAME_LABEL = "库名称："
    LIBRARY_CONTEXT_ADD_FOLDER = "添加文件夹..."
    LIBRARY_CONTEXT_DELETE = "从 LeanReel 删除库"
    LIBRARY_CONTEXT_REBUILD_CACHE = "重建缓存"
    LIBRARY_CONTEXT_REMOVE_FOLDER = "从片库移除文件夹"
    LIBRARY_CHOOSE_FOLDER_TITLE = "选择文件夹"
    LIBRARY_DELETE_TITLE = "删除库"
    LIBRARY_DELETE_PROMPT = "从 LeanReel 删除这个库？磁盘上的视频文件不会被删除。"
    LIBRARY_REMOVE_FOLDER_TITLE = "移除文件夹"
    LIBRARY_REMOVE_FOLDER_PROMPT = "从当前片库移除这个文件夹？磁盘上的视频文件不会被删除。"

    STRATEGY_PRESETS = "压缩策略"
    STRATEGY_CUSTOM_GROUP = "自定义参数"
    STRATEGY_CRF_TOOLTIP = "x265 质量参数，数字越小画质越高，体积越大"
    STRATEGY_NV_PRESET = "NV 预设"
    STRATEGY_ESTIMATED_SAVINGS_DEFAULT = "预计节省：35-50%"
    STRATEGY_ENCODER = "编码器"
    STRATEGY_AUDIO = "音轨"
    STRATEGY_SUBTITLE = "字幕"
    STRATEGY_ENCODING_SETTINGS = "编码设置"
    STRATEGY_WORKERS = "并行数"
    STRATEGY_WORKERS_SUFFIX = " 个"
    STRATEGY_TEMP_PLACEHOLDER = "编码临时目录（本地 SSD 路径）"
    STRATEGY_TEMP_DIR = "临时目录"
    STRATEGY_TEMP_DIALOG_TITLE = "选择编码临时目录"
    STRATEGY_SYNC_OUTPUT = "同步回源目录（输出移到源文件所在位置）"
    STRATEGY_KEEP_TEMP = "保留临时文件（调试用）"
    STRATEGY_DELETE_SOURCE = "删除源文件（压缩成功后永久删除）"
    STRATEGY_START = "开始压缩"
    STRATEGY_COPY_CUSTOM_NAME = "Copy Streams 自定义流复制"
    STRATEGY_COPY_QUALITY = "不重编码视频"
    STRATEGY_CPU_CUSTOM_NAME = "x265 HEVC CRF {crf} 自定义转码"
    STRATEGY_CPU_QUALITY = "CPU x265 编码"
    STRATEGY_GPU_CUSTOM_NAME = "NVENC HEVC CQ {cq} 自定义转码"
    STRATEGY_GPU_QUALITY = "GPU 硬件编码"
    STRATEGY_MANUAL_DESCRIPTION = "手动配置的压缩策略"

    def scan_path(self, path: str) -> str:
        return f"扫描 {path}..."

    def probe_progress(self, done: int, total: int) -> str:
        return f"探测中：{done}/{total}..."

    def loaded_files(self, count: int) -> str:
        return f"已加载 {count} 个文件"

    def scan_partial_failure(self, warning: str) -> str:
        return f"扫描部分失败：{warning}"

    def scan_empty(self, has_folder_inputs: bool) -> str:
        return "未找到视频文件" if has_folder_inputs else "扫描失败，请检查后重试"

    def error(self, error: object) -> str:
        return f"错误：{error}"

    def encoding_stage_status(self, stage_text: str, file_name: str, done: int, total: int, failed: int) -> str:
        suffix = f" ・ 失败 {failed}" if failed else ""
        return f"{stage_text} ｜ {file_name} ｜ 已处理 {done}/{total}{suffix}"

    def encoding_progress(self, done: int, total: int) -> str:
        return f"编码中：{done}/{total}"

    def encoding_summary(self, done: int, failed: int, cancelled: int) -> str:
        parts = [f"编码完成：成功 {done}"]
        if failed:
            parts.append(f"失败 {failed}")
        if cancelled:
            parts.append(f"取消 {cancelled}")
        return " ｜ ".join(parts)

    def queue_progress(self, progress: dict) -> str:
        return (
            f"完成 {progress['completed']}/{progress['total']}  "
            f"跳过 {progress['skipped']}  "
            f"失败 {progress['failed']}  "
            f"取消 {progress.get('cancelled', 0)}"
        )

    def failed_info(self, error_message: str) -> str:
        return f"失败：{error_message or self.UNKNOWN_ERROR}"

    def completed_info(self, original: str, compressed: str, ratio: str) -> str:
        return f"{original} → {compressed}{ratio}"

    def running_info(self, progress: float) -> str:
        return f"压缩中... {progress:.0f}%"

    def file_summary(self, count: int, pending: int, processable: int, total_tb: float) -> str:
        prefix = f"发现 {count} 个文件 · 正在探测 {pending}" if pending else f"已扫描 {count} 个文件"
        return f"{prefix} · 可处理 {processable} · 总计 {total_tb:.2f} TB"

    def file_selection_count(self, checked: int, processable_total: int) -> str:
        return f"已选中 {checked}/{processable_total} 个可处理文件"

    def compressed_strategy(self, strategy_name: str) -> str:
        return f"已压缩：{strategy_name}"

    def compressed_tooltip(self, sidecar_name: str) -> str:
        return f"该文件已压缩，审计记录：{sidecar_name}"

    def estimated_savings(self, savings: str) -> str:
        return f"预计节省：{savings}"


UI_TEXT = UIText()
