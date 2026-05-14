"""LeanReel 入口"""
import sys
import os
from pathlib import Path
from PySide6.QtWidgets import QApplication

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
from leanreel.executor.ffmpeg import FFmpegExecutor
from leanreel.executor.worker import EncodeTask, WorkerManager


def get_data_dir() -> Path:
    """获取数据目录（用户配置和数据库）"""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    d = base / "LeanReel"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_strategies_dir() -> Path:
    """获取策略目录"""
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
    """Build a non-destructive default output path."""
    return source.with_name(f"{source.stem}_SS{source.suffix}")


def build_encode_tasks(
    snapshots,
    folder_paths: dict[int, str],
    strategy,
    strategy_overrides: dict[str, object] | None = None,
) -> list[EncodeTask]:
    """Create encode tasks from displayed snapshots."""
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
    """Load a library by refreshing each folder through Scanner.

    Scanner skips valid cached metadata, but refreshes stale entries without codec
    data, so selecting a library can recover missing encoding information.
    """
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

    # 初始化数据层
    db_path = str(get_data_dir() / "leanreel.db")
    db = Database(db_path)

    # 初始化业务层
    lib_mgr = LibraryManager(db)
    strategies = load_strategies(str(get_strategies_dir()))
    matcher = Matcher(strategies)
    scanner = Scanner(db)
    current_snapshots = []
    current_folder_paths: dict[int, str] = {}
    strategy_overrides: dict[str, object] = {}
    active_custom_path: str | None = None

    # 初始化 GUI
    win = MainWindow()
    lib_panel = LibraryPanel()
    file_panel = FileListPanel()
    strategy_panel = StrategyPanel()
    queue_panel = QueuePanel()

    win.set_library_panel(lib_panel)
    win.set_file_list_panel(file_panel)
    win.set_strategy_panel(strategy_panel)
    win.set_queue_panel(queue_panel)

    # 填充策略列表
    strategy_panel.set_strategies(strategies)

    # 连接信号
    def on_library_added(name):
        try:
            lib = lib_mgr.create_library(name)
            refresh_libraries()
        except ValueError as e:
            win.status.showMessage(str(e))

    def on_folder_added(lib_id, path):
        nonlocal current_snapshots, current_folder_paths, strategy_overrides
        folder = lib_mgr.add_folder(lib_id, path)
        refresh_libraries()
        win.status.showMessage(f"正在扫描 {path}...")
        snapshots = scanner.scan_folder(folder.id, path)
        current_snapshots = snapshots
        current_folder_paths = {folder.id: path}
        strategy_overrides = {}
        matched = {}
        for s in snapshots:
            strategy = matcher.match(s)
            matched[s.relative_path] = {
                "strategy": strategy,
                "estimate": estimate_savings(s, strategy),
            }
        file_panel.populate(snapshots, matched, strategies)
        win.status.showMessage(f"扫描完成: {len(snapshots)} 个文件")

    def on_library_selected(lib_id):
        nonlocal current_snapshots, current_folder_paths, strategy_overrides
        snapshots, folder_paths = load_library_snapshots(db, scanner, lib_id)
        current_folder_paths = folder_paths
        strategy_overrides = {}
        current_snapshots = snapshots
        matched = {}
        for s in snapshots:
            strategy = matcher.match(s)
            matched[s.relative_path] = {
                "strategy": strategy,
                "estimate": estimate_savings(s, strategy),
            }
        file_panel.populate(snapshots, matched, strategies)

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
            win.status.showMessage("没有可用策略")
            return
        tasks = build_encode_tasks(
            current_snapshots,
            current_folder_paths,
            default_strategy,
            strategy_overrides,
        )
        if not tasks:
            win.status.showMessage("没有可压缩文件")
            return
        queue_panel.task_list.clear()
        for task in tasks:
            queue_panel.add_task_row(task)
        manager = WorkerManager(
            FFmpegExecutor(temp_dir=strategy_panel.temp_dir),
            strategy_panel.worker_count
        )
        manager.start(tasks)
        queue_panel.update_progress(manager.get_progress())
        win.status.showMessage(f"压缩任务完成: {manager.completed_count}/{manager.total_tasks}")

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
