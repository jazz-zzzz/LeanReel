"""LeanReel 入口"""
import sys
import threading
from dataclasses import dataclass

from PySide6.QtWidgets import QApplication

from leanreel.controllers.scan_controller import ScanController, clear_current_state, remove_folder_from_current_state
from leanreel.controllers.signals import AppSignals
from leanreel.controllers.strategy_controller import StrategyController
from leanreel.controllers.encoding_controller import EncodingController
from leanreel.controllers.library_controller import LibraryController
from leanreel.state.app_state import AppState
from leanreel.utils.threading_contract import capture_main_thread, forbid_main_thread, require_main_thread
from leanreel.utils.paths import get_data_dir, get_strategies_dir
from leanreel.infrastructure.database import Database
from leanreel.infrastructure.file_discovery import find_video_files
from leanreel.infrastructure.repository import SnapshotRepository
from leanreel.executor.probe import FFprobeRunner
from leanreel.services.library import LibraryManager
from leanreel.services.strategy_utils import _prioritize_strategies
from leanreel.infrastructure.strategy_loader import load_strategies
from leanreel.services.matcher import Matcher
from leanreel.services.scanner import Scanner
from leanreel.gui.main_window import MainWindow
from leanreel.gui.library_panel import LibraryPanel
from leanreel.gui.file_list import FileListPanel
from leanreel.gui.strategy_panel import StrategyPanel
from leanreel.gui.queue_panel import QueuePanel
from leanreel.gui.theme import apply_theme
from leanreel.state.file_store import FileTableStore


@dataclass
class Services:
    """服务容器 — 持有所有核心服务实例，使其可注入、可测试"""
    db: Database
    lib_mgr: LibraryManager
    strategies: list
    matcher: Matcher
    scanner: Scanner


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
        self._init_strategy_controller()
        self._init_scan_controller()
        self._init_library_controller()
        self._wire_signals()
        self._start_strategy_prioritization()
        self._library_ctrl._refresh_libraries()

    # ── 初始化 ──

    def _init_qt(self):
        self.app = QApplication(sys.argv)
        self.app.setApplicationName("LeanReel")
        apply_theme(self.app)

    def _init_services(self):
        db_path = str(get_data_dir() / "leanreel.db")
        db = Database(db_path)
        lib_mgr = LibraryManager(db)
        strategies = load_strategies(str(get_strategies_dir()))
        self.services = Services(
            db=db,
            lib_mgr=lib_mgr,
            strategies=strategies,
            matcher=Matcher(strategies),
            scanner=Scanner(
                repo=SnapshotRepository(db),
                probe=FFprobeRunner(),
                max_workers=8,
            ),
        )

    def _init_state(self):
        capture_main_thread()
        self.app_state = AppState()
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

    def _init_strategy_controller(self):
        self.strategy_ctrl = StrategyController(
            state=self.app_state,
            services=self.services,
            strategy_panel=self.strategy_panel,
            file_panel=self.file_panel,
            win=self.win,
            store=self.store,
            encoding_ctrl=self.encoding_ctrl,
        )

    def _init_scan_controller(self):
        self.scan_ctrl = ScanController(
            state=self.app_state,
            services=self.services,
            file_panel=self.file_panel,
            win=self.win,
            store=self.store,
            notifier=self.notifier,
            file_discoverer=find_video_files,
        )

    def _init_library_controller(self):
        self._library_ctrl = LibraryController(
            state=self.app_state,
            services=self.services,
            lib_panel=self.lib_panel,
            file_panel=self.file_panel,
            win=self.win,
            notifier=self.notifier,
            on_folder_probe=self.scan_ctrl._probe_folder_streaming,
            on_file_list_refresh=self.scan_ctrl._populate_file_list,
        )

    # ── 信号连接 ──

    def _wire_signals(self):
        self.lib_panel.library_added.connect(self._library_ctrl._on_library_added)
        self.lib_panel.folder_added.connect(self._library_ctrl._on_folder_added)
        self.lib_panel.library_selected.connect(self._library_ctrl._on_library_selected)
        self.lib_panel.library_deleted.connect(self._library_ctrl._on_library_deleted)
        self.lib_panel.folder_removed.connect(self._library_ctrl._on_folder_removed)
        self.lib_panel.folder_refresh_requested.connect(self.scan_ctrl._on_single_folder_refresh)
        self.file_panel.tree_folder_refresh_requested.connect(self.scan_ctrl._on_single_folder_refresh)
        self.file_panel.strategy_override_changed.connect(self.strategy_ctrl._on_strategy_override_changed)
        self.file_panel.custom_strategy_requested.connect(self.strategy_ctrl._on_custom_strategy_requested)
        self.file_panel.refresh_requested.connect(self.scan_ctrl._on_refresh_requested)
        self.file_panel.row_selected.connect(self.strategy_ctrl._on_file_row_selected)
        self.strategy_panel.strategy_changed.connect(self.strategy_ctrl._on_preset_strategy_changed)
        self.strategy_panel.custom_strategy_changed.connect(self.strategy_ctrl._on_custom_strategy_changed)
        self.strategy_panel.start_requested.connect(self.strategy_ctrl._on_start_requested)
        self.win.set_toggle_queue_action(
            lambda: self.win.show_queue() if self.win.queue_dock.isHidden() else self.win.hide_queue()
        )
        self.queue_panel.pause_requested.connect(self.encoding_ctrl.toggle_pause)
        self.queue_panel.cancel_requested.connect(self.encoding_ctrl.cancel)

        self.notifier.scan_ready.connect(self.scan_ctrl._on_scan_ready)
        self.notifier.scan_resolved.connect(self.scan_ctrl._on_scan_resolved)
        self.notifier.library_cache_loaded.connect(self._on_library_cache_loaded)
        self.notifier.probe_result.connect(self.scan_ctrl._on_probe_result)
        self.notifier.strategies_ready.connect(self._on_strategies_ready)
        self.notifier.progress.connect(
            lambda done, total: (
                self.win.set_status(f"探测中：{done}/{total}..."),
                self.file_panel.set_progress(done, total)
            )
        )
        self.notifier.all_done.connect(
            lambda: (self.win.set_status("编码信息探测完成"),
                     self.file_panel.enable_sorting())
        )
        self.notifier.task_updated.connect(self.encoding_ctrl.on_task_updated)
        self.notifier.encoding_done.connect(self.encoding_ctrl.on_encoding_done)

        # 注入 Store 到 FileListPanel（新数据路径）
        self.file_panel.set_store(self.store)

    def _start_strategy_prioritization(self):
        strategies = list(self.services.strategies)

        def _detect_in_background():
            forbid_main_thread("strategy prioritization")
            prioritized = _prioritize_strategies(strategies)
            self.notifier.strategies_ready.emit(prioritized)

        threading.Thread(target=_detect_in_background, daemon=True).start()

    def _on_strategies_ready(self, strategies):
        require_main_thread("Application._on_strategies_ready")
        self.services.strategies = strategies
        self.services.matcher = Matcher(strategies)
        self.strategy_panel.set_strategies(strategies)
        self.file_panel.set_strategy_lookup(strategies)

    def _on_library_cache_loaded(self, snapshots, my_token):
        require_main_thread("Application._on_library_cache_loaded")
        if self.app_state.scan_token != my_token:
            return
        self.app_state.current_snapshots = snapshots
        self.scan_ctrl._populate_file_list(snapshots, )
        self.win.set_status(f"已加载 {len(snapshots)} 个文件")

    # ── 入口 ──

    def run(self):
        self.win.show()
        sys.exit(self.app.exec())


def main():
    Application().run()


if __name__ == "__main__":
    main()
