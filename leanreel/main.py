"""LeanReel 入口"""
import sys
import os
import threading
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject, Signal

from leanreel.data.database import Database
from leanreel.core.library import LibraryManager
from leanreel.core.strategy import load_strategies
from leanreel.core.matcher import Matcher, estimate_savings
from leanreel.core.scanner import Scanner
from leanreel.gui.main_window import MainWindow
from leanreel.gui.library_panel import LibraryPanel
from leanreel.gui.file_list import FileListPanel
from leanreel.gui.strategy_panel import StrategyPanel
from leanreel.gui.queue_panel import QueuePanel
from leanreel.gui.theme import apply_theme
from leanreel.executor.ffmpeg import FFmpegExecutor
from leanreel.executor.worker import EncodeTask, WorkerManager


class ProbeNotifier(QObject):
    """线程安全的探测完成通知器"""
    probed = Signal(object)
    all_done = Signal()
    progress = Signal(int, int)  # done, total


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
    strategy,
    strategy_overrides: dict[str, object] | None = None,
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


def load_library_snapshots(db: Database, scanner: Scanner, lib_id: int):
    folders = db.get_folders_for_library(lib_id)
    snapshots = []
    folder_paths = {}
    for folder in folders:
        folder_paths[folder.id] = folder.path
        snapshots.extend(scanner.scan_folder(folder.id, folder.path))
    return snapshots, folder_paths


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("LeanReel")
    apply_theme(app)

    db_path = str(get_data_dir() / "leanreel.db")
    db = Database(db_path)

    lib_mgr = LibraryManager(db)
    strategies = load_strategies(str(get_strategies_dir()))
    matcher = Matcher(strategies)
    scanner = Scanner(db)
    current_snapshots = []
    current_folder_paths: dict[int, str] = {}
    strategy_overrides: dict[str, object] = {}
    active_custom_path: str | None = None

    notifier = ProbeNotifier()

    win = MainWindow()
    lib_panel = LibraryPanel()
    file_panel = FileListPanel()
    strategy_panel = StrategyPanel()
    queue_panel = QueuePanel()

    win.set_library_panel(lib_panel)
    win.set_file_list_panel(file_panel)
    win.set_strategy_widget(strategy_panel)
    win.set_queue_panel(queue_panel)

    strategy_panel.set_strategies(strategies)

    def _populate_file_list(snapshots):
        """用快照列表填充文件面板，返回匹配字典"""
        matched = {}
        for s in snapshots:
            strategy = matcher.match(s)
            matched[s.relative_path] = {
                "strategy": strategy,
                "estimate": estimate_savings(s, strategy),
            }
        file_panel.populate(snapshots, matched, strategies)
        return matched

    def on_library_added(name):
        try:
            lib = lib_mgr.create_library(name)
            refresh_libraries()
        except ValueError as e:
            win.set_status(str(e))

    def on_folder_added(lib_id, path):
        nonlocal current_snapshots, current_folder_paths, strategy_overrides
        folder = lib_mgr.add_folder(lib_id, path)
        refresh_libraries()
        win.set_status(f"扫描 {path}...")

        # 阶段1：快速扫描，立即显示文件列表
        snapshots = scanner.scan_folder_fast(folder.id, path)
        current_snapshots = snapshots
        current_folder_paths = {folder.id: path}
        strategy_overrides = {}

        _populate_file_list(snapshots)
        pending = scanner.pending_count
        if pending > 0:
            win.set_status(f"扫描中：0/{pending} 个文件已探测...")

            def on_probed(snap):
                notifier.probed.emit(snap)

            done_count = [0]
            lock = threading.Lock()

            def on_progress(snap):
                with lock:
                    done_count[0] += 1
                    notifier.progress.emit(done_count[0], pending)

            def on_finished():
                notifier.all_done.emit()

            def _probe_loop():
                import time
                while scanner.probe_next(on_probed):
                    on_progress(None)
                on_finished()

            t = threading.Thread(target=_probe_loop, daemon=True)
            t.start()
        else:
            win.set_status(f"扫描完成：{len(snapshots)} 个文件")

    notifier.probed.connect(file_panel.update_snapshot_row)
    notifier.progress.connect(
        lambda done, total: win.set_status(f"扫描中：{done}/{total} 个文件已探测...")
    )
    notifier.all_done.connect(
        lambda: win.set_status(f"扫描完成：{len(current_snapshots)} 个文件")
    )

    def on_library_selected(lib_id):
        nonlocal current_snapshots, current_folder_paths, strategy_overrides
        snapshots, folder_paths = load_library_snapshots(db, scanner, lib_id)
        current_folder_paths = folder_paths
        strategy_overrides = {}
        current_snapshots = snapshots
        _populate_file_list(snapshots)
        win.set_status(f"已加载 {len(snapshots)} 个文件")

    def on_strategy_override_changed(relative_path, strategy_name):
        nonlocal active_custom_path
        if strategy_name == "自定义":
            active_custom_path = relative_path
            return
        strategy_panel.show_preset_strategy()
        active_custom_path = None
        strategy = next((s for s in strategies if s.name == strategy_name), None)
        if strategy is None:
            strategy_overrides.pop(relative_path, None)
        else:
            strategy_overrides[relative_path] = strategy

    def on_custom_strategy_requested(relative_path):
        nonlocal active_custom_path
        active_custom_path = relative_path
        strategy_panel.show_custom_strategy()

    def on_custom_strategy_changed(strategy):
        if not active_custom_path:
            return
        strategy_overrides[active_custom_path] = strategy
        file_panel.apply_strategy_to_row(active_custom_path, strategy)

    def on_start_requested():
        default_strategy = strategy_panel.current_preset_strategy or strategy_panel.current_strategy
        if default_strategy is None:
            win.set_status("没有可用策略")
            return
        tasks = build_encode_tasks(
            current_snapshots,
            current_folder_paths,
            default_strategy,
            strategy_overrides,
        )
        if not tasks:
            win.set_status("没有可压缩文件")
            return
        queue_panel.task_list.clear()
        for task in tasks:
            queue_panel.add_task_row(task)

        progress_lock = threading.Lock()
        completed = [0]
        total = len(tasks)

        def _progress_callback(task):
            # 由 WorkerManager 在编码线程中调用
            pass

        def _encoding_progress(task):
            with progress_lock:
                if task.status.value in ("completed", "failed", "skipped"):
                    completed[0] += 1
            notifier.progress.emit(completed[0], total)

        manager = WorkerManager(
            FFmpegExecutor(temp_dir=strategy_panel.temp_dir, progress_callback=_progress_callback),
            strategy_panel.worker_count
        )
        win.show_queue()
        manager.start(tasks)
        queue_panel.update_progress(manager.get_progress())
        win.set_status(
            f"编码完成：成功 {manager.completed_count}/{manager.total_tasks}"
            + (f"，失败 {manager.failed_count}" if manager.failed_count else "")
        )

    def refresh_libraries():
        libs = lib_mgr.get_all_libraries()
        folders_map = {}
        for lib in libs:
            folders_map[lib.id] = lib_mgr.get_folders(lib.id)
        lib_panel.populate(libs, folders_map)

    lib_panel.library_added.connect(on_library_added)
    lib_panel.folder_added.connect(on_folder_added)
    lib_panel.library_selected.connect(on_library_selected)
    lib_panel.library_deleted.connect(lib_mgr.delete_library)
    lib_panel.folder_removed.connect(lib_mgr.remove_folder)
    file_panel.strategy_override_changed.connect(on_strategy_override_changed)
    file_panel.custom_strategy_requested.connect(on_custom_strategy_requested)
    strategy_panel.custom_strategy_changed.connect(on_custom_strategy_changed)
    strategy_panel.start_requested.connect(on_start_requested)

    refresh_libraries()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
