"""LeanReel 入口"""
import sys
import os
from pathlib import Path
from PySide6.QtWidgets import QApplication

from leanreel.data.database import Database
from leanreel.core.library import LibraryManager
from leanreel.core.strategy import load_strategies
from leanreel.core.matcher import Matcher
from leanreel.core.scanner import Scanner
from leanreel.gui.main_window import MainWindow
from leanreel.gui.library_panel import LibraryPanel
from leanreel.gui.file_list import FileListPanel
from leanreel.gui.strategy_panel import StrategyPanel
from leanreel.gui.queue_panel import QueuePanel


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
        folder = lib_mgr.add_folder(lib_id, path)
        refresh_libraries()
        win.status.showMessage(f"正在扫描 {path}...")
        snapshots = scanner.scan_folder(folder.id, path)
        matched = {}
        for s in snapshots:
            strategy = matcher.match(s)
            matched[s.relative_path] = strategy.name
        file_panel.populate(snapshots, matched)
        win.status.showMessage(f"扫描完成: {len(snapshots)} 个文件")

    def on_library_selected(lib_id):
        rows = db.execute(
            """SELECT fs.* FROM file_snapshot fs
               JOIN library_folder lf ON fs.library_folder_id = lf.id
               WHERE lf.library_id = ?""", [lib_id]
        )
        from leanreel.data.models import FileSnapshot
        snapshots = []
        for r in rows:
            snapshots.append(FileSnapshot(
                id=r["id"], library_folder_id=r["library_folder_id"],
                relative_path=r["relative_path"], file_name=r["file_name"],
                size_bytes=r["size_bytes"], video_codec=r["video_codec"],
                video_width=r["video_width"], video_height=r["video_height"],
                hdr_type=r["hdr_type"],
                duration_seconds=r["duration_seconds"], bitrate_bps=r["bitrate_bps"],
            ))
        matched = {}
        for s in snapshots:
            strategy = matcher.match(s)
            matched[s.relative_path] = strategy.name
        file_panel.populate(snapshots, matched)

    def refresh_libraries():
        libs = lib_mgr.get_all_libraries()
        folders_map = {}
        for lib in libs:
            folders_map[lib.id] = lib_mgr.get_folders(lib.id)
        lib_panel.populate(libs, folders_map)

    lib_panel.library_added.connect(on_library_added)
    lib_panel.folder_added.connect(on_folder_added)
    lib_panel.library_selected.connect(on_library_selected)

    refresh_libraries()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
