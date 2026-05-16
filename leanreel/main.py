"""LeanReel 入口"""
import sys
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from leanreel.controllers.signals import AppSignals
from leanreel.data.database import Database
from leanreel.core.library import LibraryManager
from leanreel.core.strategy import Strategy, load_strategies
from leanreel.core.matcher import Matcher, estimate_savings, get_skip_reason, is_protected_source
from leanreel.core.scanner import Scanner
from leanreel.gui.main_window import MainWindow
from leanreel.gui.library_panel import LibraryPanel
from leanreel.gui.file_list import FileListPanel, MatchResult
from leanreel.gui.strategy_panel import StrategyPanel
from leanreel.gui.queue_panel import QueuePanel
from leanreel.gui.theme import apply_theme
from leanreel.executor.ffmpeg import FFmpegExecutor
from leanreel.executor.worker import EncodeTask, WorkerManager
from leanreel.data.file_store import FileTableStore, FileRow
from leanreel.data.models import TaskStatus, FileSnapshot


def get_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    d = base / "LeanReel"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_strategies_dir() -> Path:
    user_dir = get_data_dir() / "strategies"
    user_dir.mkdir(parents=True, exist_ok=True)
    builtin = Path(__file__).parent / "resources" / "strategies"
    if builtin.exists():
        import shutil
        for f in builtin.glob("*.json"):
            dest = user_dir / f.name
            shutil.copy2(f, dest)
    return user_dir


def make_output_path(source: Path) -> Path:
    return source.with_name(f"{source.stem}_SS{source.suffix}")


def compute_encode_summary(results: list[EncodeTask]) -> tuple[int, int, int]:
    """从编码结果中统计完成数、失败数、取消数。返回 (done, failed, cancelled)。"""
    done = sum(1 for t in results if t.status == TaskStatus.COMPLETED)
    failed = sum(1 for t in results if t.status == TaskStatus.FAILED)
    cancelled = sum(1 for t in results if t.status == TaskStatus.CANCELLED)
    return done, failed, cancelled


def _has_nvenc() -> bool:
    """检测系统是否支持 NVENC GPU 编码。"""
    import subprocess
    from leanreel.executor.ffmpeg_builder import get_ffmpeg_path
    try:
        result = subprocess.run(
            [get_ffmpeg_path(), "-hide_banner", "-encoders"],
            capture_output=True, text=True, encoding="utf-8", timeout=10
        )
        return "hevc_nvenc" in (result.stdout or "")
    except Exception:
        return False


def _prioritize_strategies(strategies: list) -> list:
    """仅保留 GPU 策略；如果 NVENC 不可用则保留全部（回退到 CPU）。"""
    if not _has_nvenc():
        return strategies
    gpu = [s for s in strategies if getattr(getattr(s, "video", None), "is_gpu", False)]
    # 始终保留 copy 模式（仅去冗余，不需要编码器）
    copy = [s for s in strategies if getattr(getattr(s, "video", None), "encoder", "") == "copy"]
    return gpu + copy


def clear_current_state():
    """返回空状态三元组，用于库删除后完全重置。"""
    return [], {}, {}


def remove_folder_from_current_state(snapshots, folder_paths, strategy_overrides, folder_id: int):
    """从当前状态中移除指定文件夹的所有数据，返回新的三元组。"""
    remaining_snapshots = [s for s in snapshots if s.library_folder_id != folder_id]
    remaining_paths = {fid: path for fid, path in folder_paths.items() if fid != folder_id}
    remaining_relative_paths = {s.relative_path for s in remaining_snapshots}
    remaining_overrides = {
        path: strategy
        for path, strategy in strategy_overrides.items()
        if path in remaining_relative_paths
    }
    return remaining_snapshots, remaining_paths, remaining_overrides


def build_encode_tasks(
    snapshots,
    folder_paths: dict[int, str],
    strategy: Strategy,
    strategy_overrides: dict[str, Strategy] | None = None,
) -> list[EncodeTask]:
    tasks: list[EncodeTask] = []
    strategy_overrides = strategy_overrides or {}
    for snap in snapshots:
        if is_protected_source(snap):
            continue
        folder_path = folder_paths.get(snap.library_folder_id)
        if not folder_path:
            continue
        file_key = (int(snap.library_folder_id or 0), str(snap.relative_path))
        selected_strategy = strategy_overrides.get(file_key, strategy_overrides.get(snap.relative_path, strategy))
        input_path = Path(folder_path) / snap.relative_path
        tasks.append(EncodeTask(
            file_name=snap.file_name,
            input_path=str(input_path),
            output_path=str(make_output_path(input_path)),
            strategy_name=selected_strategy.name,
            strategy=selected_strategy,
            snapshot=snap,
            original_size=snap.size_bytes,
        ))
    return tasks


@dataclass
class Services:
    """服务容器 — 持有所有核心服务实例，使其可注入、可测试"""
    db: Database
    lib_mgr: LibraryManager
    strategies: list
    matcher: Matcher
    scanner: Scanner


class EncodingController:
    """编码控制器 — 管理编码生命周期（开始/暂停/取消/完成）"""

    def __init__(self, strategy_panel, win, queue_panel, notifier):
        self._strategy_panel = strategy_panel
        self._win = win
        self._queue_panel = queue_panel
        self._notifier = notifier
        self.active_manager: WorkerManager | None = None
        self.encoding_in_progress = False
        self._encode_lock = threading.Lock()

    def start(self, snapshots, folder_paths, strategy_overrides):
        """启动编码。返回 True 表示编码已成功启动。"""
        with self._encode_lock:
            if self.encoding_in_progress:
                self._win.set_status("编码正在进行中，请等待完成")
                return False
            self.encoding_in_progress = True

        try:
            default_strategy = self._strategy_panel.current_preset_strategy or self._strategy_panel.current_strategy
            if default_strategy is None:
                self._win.set_status("没有可用策略")
                with self._encode_lock:
                    self.encoding_in_progress = False
                return False

            tasks = build_encode_tasks(
                snapshots,
                folder_paths,
                default_strategy,
                strategy_overrides,
            )
            if not tasks:
                self._win.set_status("没有可压缩文件")
                with self._encode_lock:
                    self.encoding_in_progress = False
                return False

            self._queue_panel.clear_tasks()
            for task in tasks:
                self._queue_panel.add_task_row(task)

            self._win.show_queue()
            self.active_manager = WorkerManager(
                FFmpegExecutor(
                    temp_dir=self._strategy_panel.temp_dir,
                    progress_callback=lambda t: self._notifier.task_updated.emit(t),
                    sync_output=self._strategy_panel.sync_output,
                    keep_temp=self._strategy_panel.keep_temp,
                ),
                self._strategy_panel.worker_count,
                progress_callback=lambda t: self._notifier.task_updated.emit(t),
            )

            def _run_encode():
                try:
                    self.active_manager.start(tasks)
                finally:
                    self._notifier.encoding_done.emit()

            t = threading.Thread(target=_run_encode, daemon=True)
            t.start()
            return True
        except Exception as e:
            with self._encode_lock:
                self.encoding_in_progress = False
            self._win.set_status(f"错误：{e}")
            return False

    def toggle_pause(self):
        """切换暂停/继续状态。"""
        if self.active_manager is None:
            return
        if self.active_manager.is_paused:
            self.active_manager.resume()
            self._win.set_status("编码已恢复")
            self._queue_panel.pause_btn.setText("暂停")
        else:
            self.active_manager.pause()
            self._win.set_status("编码已暂停（等待当前任务完成）")
            self._queue_panel.pause_btn.setText("继续")

    def cancel(self, _idx=None):
        """取消当前编码。"""
        if self.active_manager is None:
            return
        self.active_manager.cancel()
        self._win.set_status("正在取消编码...")

    def on_task_updated(self, task):
        """单个任务状态更新时由 WorkerManager 回调触发。"""
        self._queue_panel.update_task_row(task)
        if self.active_manager is None:
            return
        progress = self.active_manager.get_progress()
        self._queue_panel.update_progress(progress)

        # 构建包含阶段信息的状态栏消息
        stage = getattr(task, 'current_stage', None)
        if stage and task.status == TaskStatus.RUNNING:
            stage_text = stage.slot.display_name
            if stage.progress_type.value == "estimated":
                stage_text += f" {stage.internal_progress:.0%}"
            self._win.set_status(
                f"{stage_text} ｜ {task.file_name} ｜ "
                f"已处理 {progress['completed'] + progress['failed']}/{progress['total']}"
                + (f" ・ 失败 {progress['failed']}" if progress['failed'] else "")
            )
        else:
            self._win.set_status(
                f"编码中：{progress['completed'] + progress['failed']}/{progress['total']}"
            )

    def on_encoding_done(self):
        """所有编码任务完成后由后台线程触发。"""
        with self._encode_lock:
            self.encoding_in_progress = False
        if self.active_manager is None:
            return
        results = self.active_manager.get_results()
        done, failed, cancelled = compute_encode_summary(results)
        parts = [f"编码完成：成功 {done}"]
        if failed:
            parts.append(f"失败 {failed}")
        if cancelled:
            parts.append(f"取消 {cancelled}")
        self._win.set_status(" ｜ ".join(parts))


class Application:
    """LeanReel 应用控制器 — 管理生命周期、服务初始化和信号路由"""

    def __init__(self):
        self._init_qt()
        self._init_services()
        self._init_state()
        self._init_notifier()
        self._init_ui()
        self._setup_ui()
        self._init_encoding_controller()
        self._wire_signals()
        self._refresh_libraries()

    # ── 初始化 ──

    def _init_qt(self):
        self.app = QApplication(sys.argv)
        self.app.setApplicationName("LeanReel")
        apply_theme(self.app)

    def _init_services(self):
        db_path = str(get_data_dir() / "leanreel.db")
        db = Database(db_path)
        lib_mgr = LibraryManager(db)
        strategies = _prioritize_strategies(load_strategies(str(get_strategies_dir())))
        self.services = Services(
            db=db,
            lib_mgr=lib_mgr,
            strategies=strategies,
            matcher=Matcher(strategies),
            scanner=Scanner(db, max_workers=8),
        )

    def _init_state(self):
        self.current_snapshots: list = []
        self.current_folder_paths: dict[int, str] = {}
        self.strategy_overrides: dict[str, Strategy] = {}
        self.active_custom_path: str | None = None
        self._refresh_running = False
        self._scan_token = 0
        self.store = FileTableStore()

    def _init_notifier(self):
        self.notifier = AppSignals()

    def _init_ui(self):
        self.win = MainWindow()
        self.lib_panel = LibraryPanel()
        self.file_panel = FileListPanel()
        self.strategy_panel = StrategyPanel()
        self.queue_panel = QueuePanel()

    def _setup_ui(self):
        self.win.set_library_panel(self.lib_panel)
        self.win.set_file_list_panel(self.file_panel)
        self.win.set_strategy_widget(self.strategy_panel)
        self.win.set_queue_panel(self.queue_panel)
        self.strategy_panel.set_strategies(self.services.strategies)

    def _init_encoding_controller(self):
        self.encoding_ctrl = EncodingController(
            strategy_panel=self.strategy_panel,
            win=self.win,
            queue_panel=self.queue_panel,
            notifier=self.notifier,
        )

    # ── 信号连接 ──

    def _wire_signals(self):
        self.lib_panel.library_added.connect(self._on_library_added)
        self.lib_panel.folder_added.connect(self._on_folder_added)
        self.lib_panel.library_selected.connect(self._on_library_selected)
        self.lib_panel.library_deleted.connect(self._on_library_deleted)
        self.lib_panel.folder_removed.connect(self._on_folder_removed)
        self.lib_panel.folder_refresh_requested.connect(self._on_single_folder_refresh)
        self.file_panel.tree_folder_refresh_requested.connect(self._on_single_folder_refresh)
        self.file_panel.strategy_override_changed.connect(self._on_strategy_override_changed)
        self.file_panel.custom_strategy_requested.connect(self._on_custom_strategy_requested)
        self.file_panel.refresh_requested.connect(self._on_refresh_requested)
        self.file_panel.row_selected.connect(self._on_file_row_selected)
        self.strategy_panel.strategy_changed.connect(self._on_preset_strategy_changed)
        self.strategy_panel.custom_strategy_changed.connect(self._on_custom_strategy_changed)
        self.strategy_panel.start_requested.connect(self._on_start_requested)
        self.win.set_toggle_queue_action(
            lambda: self.win.show_queue() if self.win.queue_dock.isHidden() else self.win.hide_queue()
        )
        self.queue_panel.pause_requested.connect(self.encoding_ctrl.toggle_pause)
        self.queue_panel.cancel_requested.connect(self.encoding_ctrl.cancel)

        self.notifier.probed.connect(self.file_panel.update_snapshot_row)
        self.notifier.progress.connect(
            lambda done, total: self.win.set_status(f"探测中：{done}/{total} ...")
        )
        self.notifier.all_done.connect(
            lambda: (self.win.set_status("编码信息探测完成"), self.file_panel.enable_sorting())
        )
        self.notifier.task_updated.connect(self.encoding_ctrl.on_task_updated)
        self.notifier.encoding_done.connect(self.encoding_ctrl.on_encoding_done)

        # 注入 Store 到 FileListPanel（新数据路径）
        self.file_panel.set_store(self.store)

    # ── 文件列表填充 ──

    def _populate_file_list(self, snapshots, fast: bool = False) -> dict[str, MatchResult]:
        matched: dict[str, MatchResult] = {}
        for s in snapshots:
            strategy = self.services.matcher.match(s)
            if strategy is None:
                matched[s.relative_path] = MatchResult(
                    strategy=get_skip_reason(s) or "跳过",
                    estimate={},
                )
                continue
            matched[s.relative_path] = MatchResult(
                strategy=strategy,
                estimate=estimate_savings(s, strategy),
            )
        # Store 是唯一数据路径
        rows = []
        for s in snapshots:
            m = matched.get(s.relative_path)
            d = self.file_panel._decision_display(s, m)
            rows.append(FileRow(snap=s, match=m, decision=d))
        keep_checked = not fast  # fast=True 表示切库，应清空勾选
        self.store.rebuild(rows, strategies=self.services.strategies, keep_checked=keep_checked)
        # 确保策略查找表已更新（供 ComboBox 工厂使用）
        self.file_panel._strategy_lookup = self.file_panel._build_strategy_lookup(self.services.strategies)
        # Store.rebuild 通过信号驱动 Adapter 自动更新 UI，显式调用确保即时刷新
        if self.file_panel._flat_adapter:
            self.file_panel._flat_adapter._on_rebuild()
        if self.file_panel._tree_adapter:
            self.file_panel._tree_adapter._on_rebuild()
        return matched

    # ── 库信号处理 ──

    def _on_library_added(self, name):
        try:
            self.services.lib_mgr.create_library(name)
            self._refresh_libraries()
        except ValueError as e:
            self.win.set_status(str(e))

    def _on_folder_added(self, lib_id, path):
        try:
            folder = self.services.lib_mgr.add_folder(lib_id, path)
        except ValueError as e:
            self.win.set_status(str(e))
            return
        self._refresh_libraries()
        self._probe_folder_streaming(folder.id, path)

    def _probe_folder_streaming(self, folder_id: int, path: str):
        """流式探测单个文件夹 — stat+ffprobe 合并，即时渲染。"""
        self._scan_token += 1
        my_token = self._scan_token
        self.win.set_status(f"扫描 {path}...")

        # 先获取文件总数预填充表格
        from leanreel.core.file_discovery import find_video_files
        files = find_video_files(path)
        total = len(files)
        if total == 0:
            self.win.set_status(f"未找到视频文件：{path}")
            return

        self.current_folder_paths[folder_id] = path

        # 创建占位快照（探测完逐个刷新）
        placeholders = []
        for rel_path, abs_path in files:
            placeholders.append(FileSnapshot(
                library_folder_id=folder_id,
                relative_path=rel_path,
                file_name=os.path.basename(abs_path),
                size_bytes=0,
                probe_ok=False,
            ))
        self.current_snapshots = [s for s in self.current_snapshots if s.library_folder_id != folder_id]
        self.current_snapshots.extend(placeholders)
        self._populate_file_list(self.current_snapshots)

        done = [0]
        lock = threading.Lock()

        def _on_result(snap):
            if self._scan_token != my_token:
                return
            # 替换占位快照
            for i, s in enumerate(self.current_snapshots):
                if s.relative_path == snap.relative_path and s.library_folder_id == folder_id:
                    self.current_snapshots[i] = snap
                    break
            if snap.probe_ok:
                strategy = self.services.matcher.match(snap)
                match = MatchResult(strategy=strategy, estimate=estimate_savings(snap, strategy) if strategy else None) if strategy else None
            else:
                match = None
            self.notifier.probed.emit(snap, match)
            d = self.file_panel._decision_display(snap, match)
            self.store.update_row((snap.library_folder_id, snap.relative_path), snap, match, decision=d)
            with lock:
                done[0] += 1
                self.notifier.progress.emit(done[0], total)

        def _on_finished():
            if self._scan_token != my_token:
                return
            self._populate_file_list(self.current_snapshots)
            self.notifier.all_done.emit()

        self.services.scanner.probe_stream(folder_id, path, _on_result, _on_finished, files=files)
        self.win.set_status(f"探测中：0/{total} ...")

    def _on_library_selected(self, lib_id):
        folders = self.services.db.get_folders_for_library(lib_id)
        snapshots: list = []
        folder_paths: dict[int, str] = {}
        for folder in folders:
            folder_paths[folder.id] = folder.path
            snapshots.extend(self.services.scanner.load_cached(folder.id, folder.path))
        self.current_folder_paths = folder_paths
        self.strategy_overrides = {}
        self.current_snapshots = snapshots
        self._populate_file_list(snapshots, fast=True)
        self.win.set_status(f"已加载 {len(snapshots)} 个文件")

    def _on_library_deleted(self, lib_id):
        self.services.lib_mgr.delete_library(lib_id)
        self.current_snapshots, self.current_folder_paths, self.strategy_overrides = clear_current_state()
        self.file_panel.populate([], {}, self.services.strategies)
        self._refresh_libraries()
        self.win.set_status("库已删除")

    def _on_folder_removed(self, folder_id):
        self.services.lib_mgr.remove_folder(folder_id)
        self.current_snapshots, self.current_folder_paths, self.strategy_overrides = remove_folder_from_current_state(
            self.current_snapshots,
            self.current_folder_paths,
            self.strategy_overrides,
            folder_id,
        )
        self._populate_file_list(self.current_snapshots)
        self._refresh_libraries()
        self.win.set_status("文件夹已移除")

    def _on_refresh_requested(self):
        """重建缓存：重新扫描所有文件夹（合并 stat+ffprobe 为一次 I/O）。"""
        if not self.current_folder_paths:
            self.win.set_status("没有已添加的文件夹，请先添加文件夹")
            return

        if self._refresh_running:
            self.win.set_status("扫描已在进行中，请等待完成")
            return

        from leanreel.core.file_discovery import find_video_files

        self._refresh_running = True
        self._scan_token += 1
        my_token = self._scan_token
        folders_at_call = list(self.current_folder_paths.items())

        # 第一步：预先收集所有文件，创建占位快照（主线程，很快 <1s）
        self.current_snapshots = []
        for folder_id, path in folders_at_call:
            self.current_folder_paths[folder_id] = path
            for rel_path, abs_path in find_video_files(path):
                self.current_snapshots.append(FileSnapshot(
                    library_folder_id=folder_id,
                    relative_path=rel_path,
                    file_name=os.path.basename(abs_path),
                    size_bytes=0,
                    probe_ok=False,
                ))

        total = len(self.current_snapshots)
        if total == 0:
            self._refresh_running = False
            self.win.set_status("未找到视频文件")
            return

        # 第二步：一次性展示所有占位行
        self._populate_file_list(self.current_snapshots)
        self.win.set_status(f"探测中：0/{total} ...")

        # 第三步：合并所有文件夹到一个共享线程池探测
        done = [0]
        lock = threading.Lock()

        def _on_result(snap):
            if self._scan_token != my_token:
                return
            for i, s in enumerate(self.current_snapshots):
                if s.relative_path == snap.relative_path and s.library_folder_id == snap.library_folder_id:
                    self.current_snapshots[i] = snap
                    break
            if snap.probe_ok:
                strategy = self.services.matcher.match(snap)
                match = MatchResult(strategy=strategy, estimate=estimate_savings(snap, strategy) if strategy else None) if strategy else None
            else:
                match = None
            self.notifier.probed.emit(snap, match)
            d = self.file_panel._decision_display(snap, match)
            self.store.update_row((snap.library_folder_id, snap.relative_path), snap, match, decision=d)
            with lock:
                done[0] += 1
                self.notifier.progress.emit(done[0], total)
                if done[0] == total:
                    self._refresh_running = False
                    self.notifier.all_done.emit()

        folders_input = []
        for folder_id, path in folders_at_call:
            folders_input.append((folder_id, path, find_video_files(path)))

        self.services.scanner.probe_multi(folders_input, _on_result, on_finished=None)

    def _on_single_folder_refresh(self, folder_id):
        """流式刷新单个文件夹（库面板或树视图右键触发）。"""
        if folder_id not in self.current_folder_paths:
            return
        path = self.current_folder_paths[folder_id]
        self.current_snapshots = [s for s in self.current_snapshots if s.library_folder_id != folder_id]
        self._populate_file_list(self.current_snapshots)
        self._probe_folder_streaming(folder_id, path)

    # ── 策略信号处理 ──

    def _on_strategy_override_changed(self, relative_path, strategy_name):
        if strategy_name == "自定义":
            self.active_custom_path = relative_path
            return
        self.strategy_panel.show_preset_strategy()
        self.active_custom_path = None
        strategy = next((s for s in self.services.strategies if s.name == strategy_name), None)
        if strategy is None:
            self.strategy_overrides.pop(relative_path, None)
        else:
            self.strategy_overrides[relative_path] = strategy

    def _on_file_row_selected(self, relative_path):
        """单个文件行被选中时，右侧策略面板同步显示该文件的策略。"""
        if not relative_path:
            return
        # 优先用用户手动选择的覆盖策略，其次用自动匹配的策略
        override = self.strategy_overrides.get(relative_path)
        if override:
            self.strategy_panel.show_preset_strategy()
            self.strategy_panel.preset_panel.select_by_strategy(override.name)
            return
        # 从 Store 中查找该文件的匹配策略
        for row_obj in self.store._rows:
            if row_obj.snap.relative_path == relative_path:
                match = row_obj.match
                strategy = getattr(match, "strategy", None) if match else None
                if strategy:
                    name = strategy if isinstance(strategy, str) else getattr(strategy, "name", "")
                    if name:
                        self.strategy_panel.show_preset_strategy()
                        self.strategy_panel.preset_panel.select_by_strategy(name)
                break

    def _on_preset_strategy_changed(self, index):
        """策略面板预设策略变更时，应用到所有选中/勾选的文件。"""
        strategy = self.strategy_panel.current_preset_strategy
        if strategy is None:
            return
        # 收集需要覆盖的 relative_path
        targets = set(self.file_panel.get_checked_relative_paths())
        for idx in self.file_panel.table.selectedIndexes():
            if idx.column() == 0:
                continue
            item = self.file_panel.table.item(idx.row(), 1)
            if item:
                rel = item.data(Qt.UserRole)
                if rel:
                    targets.add(rel)
        if not targets:
            return
        for rel in targets:
            self.strategy_overrides[rel] = strategy
            self.file_panel.apply_strategy_to_row(rel, strategy)

    def _on_custom_strategy_requested(self, relative_path):
        self.active_custom_path = relative_path
        self.strategy_panel.show_custom_strategy()

    def _on_custom_strategy_changed(self, strategy):
        if not self.active_custom_path:
            return
        self.strategy_overrides[self.active_custom_path] = strategy
        self.file_panel.apply_strategy_to_row(self.active_custom_path, strategy)

    # ── 编码控制 ──

    def _on_start_requested(self):
        checked_paths = set(self.file_panel.get_checked_relative_paths())
        if not checked_paths:
            self.win.set_status("没有勾选任何文件，请先在文件列表中勾选要处理的文件")
            return
        snapshots = [s for s in self.current_snapshots if s.relative_path in checked_paths]
        if not snapshots:
            self.win.set_status("勾选的文件未找到")
            return
        self.encoding_ctrl.start(
            snapshots,
            self.current_folder_paths,
            self.strategy_overrides,
        )

    # ── 库刷新 ──

    def _refresh_libraries(self):
        libs = self.services.lib_mgr.get_all_libraries()
        folders_map = {}
        for lib in libs:
            folders_map[lib.id] = self.services.lib_mgr.get_folders(lib.id)
        self.lib_panel.populate(libs, folders_map)

    # ── 入口 ──

    def run(self):
        self.win.show()
        sys.exit(self.app.exec())


def main():
    Application().run()


if __name__ == "__main__":
    main()
