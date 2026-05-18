"""库管理控制器 — 库的增删改查和切换"""
import threading
from typing import Callable

from leanreel.state.app_state import AppState


class LibraryController:
    """管理库的添加、删除、选择和刷新。

    通过 AppState 共享可变状态，通过 Services 访问核心服务，
    通过回调与 Application 中尚未迁移的复杂方法（如 _probe_folder_streaming、
    _populate_file_list）通信。
    """

    def __init__(
        self,
        state: AppState,
        services,
        lib_panel,
        file_panel,
        win,
        notifier,
        on_folder_probe: Callable[[int, str], None] | None = None,
        on_file_list_refresh: Callable[[list], None] | None = None,
    ):
        self._state = state
        self._services = services
        self._lib_panel = lib_panel
        self._file_panel = file_panel
        self._win = win
        self._notifier = notifier
        self._on_folder_probe = on_folder_probe or (lambda folder_id, path: None)
        self._on_file_list_refresh = on_file_list_refresh or (lambda snapshots: None)

    # ── 库信号处理 ──

    def _on_library_added(self, name):
        try:
            self._services.lib_mgr.create_library(name)
            self._refresh_libraries()
        except ValueError as e:
            self._win.set_status(str(e))

    def _on_folder_added(self, lib_id, path):
        try:
            folder = self._services.lib_mgr.add_folder(lib_id, path)
        except ValueError as e:
            self._win.set_status(str(e))
            return
        # 同步更新状态
        self._state.current_folder_paths[folder.id] = folder.path
        self._refresh_libraries()
        self._on_folder_probe(folder.id, path)

    def _on_library_selected(self, lib_id):
        folders = self._services.db.get_folders_for_library(lib_id)
        folder_paths: dict[int, str] = {}
        for folder in folders:
            folder_paths[folder.id] = folder.path
        # 同步设置状态，避免选库后空窗期
        self._state.current_folder_paths = folder_paths
        # 切换活跃扫描锚点（切库时恢复该库的扫描状态）
        self._state.active_scan_folder_id = next(iter(folder_paths), 0)
        self._state.library_token += 1
        my_token = self._state.library_token
        self._win.set_status("加载缓存中...")

        def _load_cache_in_background():
            from leanreel.utils.threading_contract import forbid_main_thread
            forbid_main_thread("library cache loading")
            snapshots: list = []
            try:
                for folder in folders:
                    if self._state.library_token != my_token:
                        return
                    snapshots.extend(self._services.scanner.load_cached(folder.id, folder.path))
            except Exception:
                import traceback
                traceback.print_exc()
                snapshots = []
            self._notifier.library_cache_loaded.emit(snapshots, my_token)

        threading.Thread(target=_load_cache_in_background, daemon=True).start()

    def _on_library_deleted(self, lib_id):
        from leanreel.controllers.scan_controller import clear_current_state
        self._services.lib_mgr.delete_library(lib_id)
        self._state.current_snapshots, self._state.current_folder_paths, self._state.strategy_overrides = clear_current_state()
        self._file_panel.populate([], {}, self._services.strategies)
        self._refresh_libraries()
        self._win.set_status("库已删除")

    def _on_folder_removed(self, folder_id):
        from leanreel.controllers.scan_controller import remove_folder_from_current_state
        self._services.lib_mgr.remove_folder(folder_id)
        self._state.current_snapshots, self._state.current_folder_paths, self._state.strategy_overrides = remove_folder_from_current_state(
            self._state.current_snapshots,
            self._state.current_folder_paths,
            self._state.strategy_overrides,
            folder_id,
        )
        self._on_file_list_refresh(self._state.current_snapshots)
        self._refresh_libraries()
        self._win.set_status("文件夹已移除")

    # ── 库刷新 ──

    def _refresh_libraries(self):
        libs = self._services.lib_mgr.get_all_libraries()
        folders_map = {}
        for lib in libs:
            folders_map[lib.id] = self._services.lib_mgr.get_folders(lib.id)
        self._lib_panel.populate(libs, folders_map)
