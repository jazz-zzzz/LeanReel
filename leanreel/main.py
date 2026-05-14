"""LeanReel 入口"""
import sys
import os
import threading
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
from leanreel.gui.file_list import FileListPanel
from leanreel.gui.strategy_panel import StrategyPanel
from leanreel.gui.queue_panel import QueuePanel
from leanreel.gui.theme import apply_theme
from leanreel.executor.ffmpeg import FFmpegExecutor
from leanreel.executor.worker import EncodeTask, WorkerManager, TaskStatus


class ProbeNotifier(QObject):
    """线程安全的通知器"""
    probed = Signal(object)
    all_done = Signal()
    progress = Signal(int, int)  # done, total
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
        ))
    return tasks


class Application:
    """LeanReel 应用控制器 — 管理生命周期、服务初始化和信号路由"""

    def __init__(self):
        self._init_qt()
        self._init_services()
        self._init_state()
        self._init_notifier()
        self._init_ui()
        self._setup_ui()
        self._wire_signals()
        self._refresh_libraries()

    # ── 初始化 ──

    def _init_qt(self):
        self.app = QApplication(sys.argv)
        self.app.setApplicationName("LeanReel")
        apply_theme(self.app)

    def _init_services(self):
        db_path = str(get_data_dir() / "leanreel.db")
        self.db = Database(db_path)
        self.lib_mgr = LibraryManager(self.db)
        self.strategies = load_strategies(str(get_strategies_dir()))
        self.matcher = Matcher(self.strategies)
        self.scanner = Scanner(self.db)

    def _init_state(self):
        self.current_snapshots: list = []
        self.current_folder_paths: dict[int, str] = {}
        self.strategy_overrides: dict[str, Strategy] = {}
        self.active_custom_path: str | None = None
        self.active_manager: WorkerManager | None = None
        self.encoding_in_progress = False

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
        self.strategy_panel.set_strategies(self.strategies)

    # ── 信号连接 ──

    def _wire_signals(self):
        self.lib_panel.library_added.connect(self._on_library_added)
        self.lib_panel.folder_added.connect(self._on_folder_added)
        self.lib_panel.library_selected.connect(self._on_library_selected)
        self.lib_panel.library_deleted.connect(self.lib_mgr.delete_library)
        self.lib_panel.folder_removed.connect(self.lib_mgr.remove_folder)
        self.file_panel.strategy_override_changed.connect(self._on_strategy_override_changed)
        self.file_panel.custom_strategy_requested.connect(self._on_custom_strategy_requested)
        self.strategy_panel.custom_strategy_changed.connect(self._on_custom_strategy_changed)
        self.strategy_panel.start_requested.connect(self._on_start_requested)
        self.win.set_toggle_queue_action(
            lambda: self.win.show_queue() if self.win.queue_dock.isHidden() else self.win.hide_queue()
        )
        self.queue_panel.pause_requested.connect(self._on_pause_requested)
        self.queue_panel.cancel_requested.connect(self._on_cancel_requested)

        self.notifier.probed.connect(self.file_panel.update_snapshot_row)
        self.notifier.progress.connect(
            lambda done, total: self.win.set_status(f"探测中：{done}/{total} ...")
        )
        self.notifier.all_done.connect(
            lambda: self.win.set_status("编码信息探测完成")
        )
        self.notifier.task_updated.connect(self._on_task_updated)
        self.notifier.encoding_done.connect(self._on_encoding_done)

    # ── 文件列表填充 ──

    def _populate_file_list(self, snapshots) -> dict:
        matched = {}
        for s in snapshots:
            strategy = self.matcher.match(s)
            matched[s.relative_path] = {
                "strategy": strategy,
                "estimate": estimate_savings(s, strategy),
            }
        self.file_panel.populate(snapshots, matched, self.strategies)
        return matched

    # ── 库信号处理 ──

    def _on_library_added(self, name):
        try:
            self.lib_mgr.create_library(name)
            self._refresh_libraries()
        except ValueError as e:
            self.win.set_status(str(e))

    def _on_folder_added(self, lib_id, path):
        folder = self.lib_mgr.add_folder(lib_id, path)
        self._refresh_libraries()
        self.win.set_status(f"扫描 {path}...")

        snapshots = self.scanner.scan_folder_fast(folder.id, path)
        self.current_snapshots = snapshots
        self.current_folder_paths[folder.id] = path
        self.strategy_overrides = {}

        self._populate_file_list(snapshots)
        pending = self.scanner.pending_count
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

            self.scanner.start_background_probe(on_probed, on_finished, on_progress)
        else:
            self.win.set_status(f"扫描完成：{len(snapshots)} 个文件")

    def _on_library_selected(self, lib_id):
        folders = self.db.get_folders_for_library(lib_id)
        snapshots: list = []
        folder_paths: dict[int, str] = {}
        for folder in folders:
            folder_paths[folder.id] = folder.path
            snapshots.extend(self.scanner.load_cached(folder.id, folder.path))
        self.current_folder_paths = folder_paths
        self.strategy_overrides = {}
        self.current_snapshots = snapshots
        self._populate_file_list(snapshots)
        self.win.set_status(f"已加载 {len(snapshots)} 个文件")

    # ── 策略信号处理 ──

    def _on_strategy_override_changed(self, relative_path, strategy_name):
        if strategy_name == "自定义":
            self.active_custom_path = relative_path
            return
        self.strategy_panel.show_preset_strategy()
        self.active_custom_path = None
        strategy = next((s for s in self.strategies if s.name == strategy_name), None)
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
        if self.encoding_in_progress:
            self.win.set_status("编码正在进行中，请等待完成")
            return
        try:
            default_strategy = self.strategy_panel.current_preset_strategy or self.strategy_panel.current_strategy
            if default_strategy is None:
                self.win.set_status("没有可用策略")
                return
            tasks = build_encode_tasks(
                self.current_snapshots,
                self.current_folder_paths,
                default_strategy,
                self.strategy_overrides,
            )
            if not tasks:
                self.win.set_status("没有可压缩文件")
                return
            self.queue_panel.clear_tasks()
            for task in tasks:
                self.queue_panel.add_task_row(task)

            self.win.show_queue()
            self.encoding_in_progress = True
            self.active_manager = WorkerManager(
                FFmpegExecutor(temp_dir=self.strategy_panel.temp_dir),
                self.strategy_panel.worker_count,
                progress_callback=lambda t: self.notifier.task_updated.emit(t),
            )

            def _run_encode():
                try:
                    self.active_manager.start(tasks)
                finally:
                    self.notifier.encoding_done.emit()

            t = threading.Thread(target=_run_encode, daemon=True)
            t.start()
        except Exception as e:
            self.encoding_in_progress = False
            self.win.set_status(f"错误：{e}")

    def _on_pause_requested(self):
        if self.active_manager is None:
            return
        if self.active_manager.is_paused:
            self.active_manager.resume()
            self.win.set_status("编码已恢复")
            self.queue_panel.pause_btn.setText("暂停")
        else:
            self.active_manager.pause()
            self.win.set_status("编码已暂停（等待当前任务完成）")
            self.queue_panel.pause_btn.setText("继续")

    def _on_cancel_requested(self, _idx):
        if self.active_manager is None:
            return
        self.active_manager.cancel()
        self.win.set_status("正在取消编码...")

    def _on_task_updated(self, task):
        self.queue_panel.update_task_row(task)
        if self.active_manager is None:
            return
        progress = self.active_manager.get_progress()
        self.queue_panel.update_progress(progress)
        self.win.set_status(
            f"编码中：{progress['completed'] + progress['failed']}/{progress['total']}"
        )

    def _on_encoding_done(self):
        self.encoding_in_progress = False
        if self.active_manager is None:
            return
        results = self.active_manager.get_results()
        done = sum(1 for t in results if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in results if t.status == TaskStatus.FAILED)
        self.win.set_status(
            f"编码完成：成功 {done}/{len(results)}"
            + (f"，失败 {failed}" if failed else "")
        )

    # ── 库刷新 ──

    def _refresh_libraries(self):
        libs = self.lib_mgr.get_all_libraries()
        folders_map = {}
        for lib in libs:
            folders_map[lib.id] = self.lib_mgr.get_folders(lib.id)
        self.lib_panel.populate(libs, folders_map)

    # ── 入口 ──

    def run(self):
        self.win.show()
        sys.exit(self.app.exec())


def main():
    Application().run()


if __name__ == "__main__":
    main()
