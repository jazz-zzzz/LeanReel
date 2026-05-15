"""LeanReel 入口"""
import sys
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject, Signal

from leanreel.data.database import Database
from leanreel.core.library import LibraryManager
from leanreel.core.strategy import Strategy, load_strategies
from leanreel.core.matcher import Matcher, estimate_savings
from leanreel.core.scanner import Scanner
from leanreel.gui.main_window import MainWindow
from leanreel.gui.library_panel import LibraryPanel
from leanreel.gui.file_list import FileListPanel, MatchResult
from leanreel.gui.strategy_panel import StrategyPanel
from leanreel.gui.queue_panel import QueuePanel
from leanreel.gui.theme import apply_theme
from leanreel.executor.ffmpeg import FFmpegExecutor
from leanreel.executor.worker import EncodeTask, WorkerManager
from leanreel.data.models import TaskStatus


class ProbeNotifier(QObject):
    """线程安全的通知器"""
    probed = Signal(object)
    all_done = Signal()
    progress = Signal(int, int)  # done, total
    scan_finished = Signal(object, int, str, object)  # snapshots, folder_id, folder_path, pending_jobs
    task_updated = Signal(object)  # EncodeTask
    encoding_done = Signal()


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
            if not dest.exists():
                shutil.copy2(f, dest)
    return user_dir


def make_output_path(source: Path) -> Path:
    return source.with_name(f"{source.stem}_SS{source.suffix}")


def compute_encode_summary(results: list[EncodeTask]) -> tuple[int, int]:
    """从编码结果中统计完成数和失败数。返回 (done, failed)。"""
    done = sum(1 for t in results if t.status == TaskStatus.COMPLETED)
    failed = sum(1 for t in results if t.status == TaskStatus.FAILED)
    return done, failed


def _has_nvenc() -> bool:
    """检测系统是否支持 NVENC GPU 编码。"""
    import subprocess
    from leanreel.executor.ffmpeg_builder import get_ffmpeg_path
    try:
        result = subprocess.run(
            [get_ffmpeg_path(), "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=10
        )
        return "hevc_nvenc" in (result.stdout or "")
    except Exception:
        return False


def _prioritize_strategies(strategies: list) -> list:
    """GPU 可用时将 GPU 策略排到前面，CPU 策略排后面。"""
    if not _has_nvenc():
        return strategies
    gpu = [s for s in strategies if getattr(getattr(s, "video", None), "is_gpu", False)]
    cpu = [s for s in strategies if not getattr(getattr(s, "video", None), "is_gpu", False)]
    return gpu + cpu


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
        folder_path = folder_paths.get(snap.library_folder_id)
        if not folder_path:
            continue
        selected_strategy = strategy_overrides.get(snap.relative_path, strategy)
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
                f"完成 {progress['completed'] + progress['failed']}/{progress['total']}"
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
        done, failed = compute_encode_summary(results)
        self._win.set_status(
            f"编码完成：成功 {done}/{len(results)}"
            + (f"，失败 {failed}" if failed else "")
        )


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
            scanner=Scanner(db),
        )

    def _init_state(self):
        self.current_snapshots: list = []
        self.current_folder_paths: dict[int, str] = {}
        self.strategy_overrides: dict[str, Strategy] = {}
        self.active_custom_path: str | None = None

    def _init_notifier(self):
        self.notifier = ProbeNotifier()

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
        self.file_panel.strategy_override_changed.connect(self._on_strategy_override_changed)
        self.file_panel.custom_strategy_requested.connect(self._on_custom_strategy_requested)
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
            lambda: self.win.set_status("编码信息探测完成")
        )
        self.notifier.scan_finished.connect(self._on_scan_finished)
        self.notifier.task_updated.connect(self.encoding_ctrl.on_task_updated)
        self.notifier.encoding_done.connect(self.encoding_ctrl.on_encoding_done)

    # ── 文件列表填充 ──

    def _populate_file_list(self, snapshots) -> dict[str, MatchResult]:
        matched: dict[str, MatchResult] = {}
        for s in snapshots:
            strategy = self.services.matcher.match(s)
            matched[s.relative_path] = MatchResult(
                strategy=strategy,
                estimate=estimate_savings(s, strategy),
            )
        self.file_panel.populate(snapshots, matched, self.services.strategies)
        return matched

    # ── 库信号处理 ──

    def _on_library_added(self, name):
        try:
            self.services.lib_mgr.create_library(name)
            self._refresh_libraries()
        except ValueError as e:
            self.win.set_status(str(e))

    def _on_folder_added(self, lib_id, path):
        folder = self.services.lib_mgr.add_folder(lib_id, path)
        self._refresh_libraries()
        self.win.set_status(f"扫描 {path}...")

        def _scan_in_background():
            batch = self.services.scanner.scan_folder_fast_batch(folder.id, path)
            self.notifier.scan_finished.emit(batch.snapshots, folder.id, path, batch.pending_jobs)

        threading.Thread(target=_scan_in_background, daemon=True).start()

    def _on_scan_finished(self, snapshots, folder_id, folder_path, pending_jobs):
        """扫描后台线程完成后的回调（在主线程执行）"""
        self.current_folder_paths[folder_id] = folder_path
        self.current_snapshots = [
            s for s in self.current_snapshots
            if s.library_folder_id != folder_id
        ] + list(snapshots)
        self.strategy_overrides = {
            path: strategy for path, strategy in self.strategy_overrides.items()
            if any(s.relative_path == path for s in self.current_snapshots)
        }

        self._populate_file_list(self.current_snapshots)

        # 区分"无视频文件"和"有待探测文件"
        if len(snapshots) == 0:
            self.win.set_status(f"未找到视频文件：{folder_path}")
            return

        pending = len(pending_jobs)
        if pending > 0:
            self.win.set_status(f"扫描中：0/{pending} 个文件已探测...")

            done_count = [0]
            lock = threading.Lock()

            def on_probed(snap):
                self.notifier.probed.emit(snap)

            def on_progress():
                with lock:
                    done_count[0] += 1
                    self.notifier.progress.emit(done_count[0], pending)

            def on_finished():
                self.notifier.all_done.emit()

            self.services.scanner.start_background_probe_jobs(
                list(pending_jobs), on_probed, on_finished, on_progress
            )
        else:
            self.win.set_status(f"扫描完成：{len(snapshots)} 个文件")

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
        self._populate_file_list(snapshots)
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
