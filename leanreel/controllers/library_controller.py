"""Library controller: create, delete, select, and refresh libraries."""
import threading
from typing import Callable

from leanreel.state.app_state import AppState
from leanreel.ui_text import UI_TEXT


class LibraryController:
    """Keeps the active library UI context separate from background scans."""

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
        on_cancel_scans: Callable[[], None] | None = None,
    ):
        self._state = state
        self._services = services
        self._lib_panel = lib_panel
        self._file_panel = file_panel
        self._win = win
        self._notifier = notifier
        self._on_folder_probe = on_folder_probe or (lambda folder_id, path: None)
        self._on_file_list_refresh = on_file_list_refresh or (lambda snapshots: None)
        self._on_cancel_scans = on_cancel_scans or (lambda: None)

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

        folders = self._services.lib_mgr.get_folders(lib_id)
        folder_ids = {f.id for f in folders}
        self._state.current_library_id = lib_id
        self._state.current_folder_paths = {f.id: f.path for f in folders}
        self._state.current_snapshots = [
            s for s in self._state.current_snapshots
            if s.library_folder_id in folder_ids
        ]
        self._state.active_scan_folder_id = folder.id
        self._refresh_libraries()
        self._on_folder_probe(folder.id, path)

    def _on_library_selected(self, lib_id):
        self._on_cancel_scans()
        folders = self._services.db.get_folders_for_library(lib_id)
        folder_paths = {folder.id: folder.path for folder in folders}
        self._state.current_library_id = lib_id
        self._state.current_folder_paths = folder_paths
        self._state.active_scan_folder_id = next(iter(folder_paths), 0)
        self._state.library_token += 1
        my_token = self._state.library_token
        self._win.set_status(UI_TEXT.LOADING_CACHE)

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

        self._on_cancel_scans()
        self._services.lib_mgr.delete_library(lib_id)
        if getattr(self._state, "current_library_id", None) == lib_id:
            (
                self._state.current_snapshots,
                self._state.current_folder_paths,
                self._state.strategy_overrides,
            ) = clear_current_state()
            self._state.current_library_id = None
            self._file_panel.populate([], {}, self._services.strategies)
        self._refresh_libraries()
        self._win.set_status(UI_TEXT.LIBRARY_DELETED)

    def _on_folder_removed(self, folder_id):
        from leanreel.controllers.scan_controller import remove_folder_from_current_state

        self._on_cancel_scans()
        self._services.lib_mgr.remove_folder(folder_id)
        (
            self._state.current_snapshots,
            self._state.current_folder_paths,
            self._state.strategy_overrides,
        ) = remove_folder_from_current_state(
            self._state.current_snapshots,
            self._state.current_folder_paths,
            self._state.strategy_overrides,
            folder_id,
        )
        self._on_file_list_refresh(self._state.current_snapshots)
        self._refresh_libraries()
        self._win.set_status(UI_TEXT.FOLDER_REMOVED)

    def _refresh_libraries(self):
        libs = self._services.lib_mgr.get_all_libraries()
        folders_map = {}
        for lib in libs:
            folders_map[lib.id] = self._services.lib_mgr.get_folders(lib.id)
        self._lib_panel.populate(libs, folders_map)
