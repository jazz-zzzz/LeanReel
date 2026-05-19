"""Scan controller: file discovery, cache resolution, probing, and list updates."""
import os
import threading

from leanreel.domain.models import FileSnapshot, FileRow, MatchResult, get_skip_reason
from leanreel.services.matcher import estimate_savings
from leanreel.state.scan_state import ScanState
from leanreel.utils.threading_contract import require_main_thread, forbid_main_thread


def clear_current_state():
    """Return empty state triples used after deleting the active library."""
    return [], {}, {}


def remove_folder_from_current_state(snapshots, folder_paths, strategy_overrides, folder_id: int):
    """Remove all visible state that belongs to one folder."""
    remaining_snapshots = [s for s in snapshots if s.library_folder_id != folder_id]
    remaining_paths = {fid: path for fid, path in folder_paths.items() if fid != folder_id}
    remaining_relative_paths = {s.relative_path for s in remaining_snapshots}
    remaining_keys = {(s.library_folder_id, s.relative_path) for s in remaining_snapshots}
    remaining_overrides = {
        key: strategy
        for key, strategy in strategy_overrides.items()
        if (
            key in remaining_keys
            if isinstance(key, tuple)
            else key in remaining_relative_paths
        )
    }
    return remaining_snapshots, remaining_paths, remaining_overrides


class ScanController:
    """Owns scan batches while only updating UI for the current library."""

    def __init__(self, state, services, file_panel, win, store, notifier, file_discoverer=None):
        self._state = state
        self._services = services
        self._file_panel = file_panel
        self._win = win
        self._store = store
        self._notifier = notifier
        self._discover = file_discoverer

    def _current_library_id(self) -> int | None:
        return getattr(self._state, "current_library_id", None)

    def _current_folder_ids(self) -> set[int]:
        return set(getattr(self._state, "current_folder_paths", {}).keys())

    def _folder_ids_from_inputs(self, folder_inputs) -> set[int]:
        return {folder_id for folder_id, _path, _files in folder_inputs}

    def _scan_is_current(self, st: ScanState) -> bool:
        current_library_id = ScanController._current_library_id(self)
        if current_library_id is not None and st.library_id is not None:
            return st.library_id == current_library_id
        current_folder_ids = ScanController._current_folder_ids(self)
        if current_folder_ids:
            return st.owns_any_folder(current_folder_ids)
        return current_library_id is None

    def _state_for_token(self, token: int, folder_inputs=None) -> ScanState | None:
        st = self._state.scan_states.get(token)
        if st is not None:
            return st
        if getattr(self._state, "scan_token", None) != token:
            return None
        folder_ids = ScanController._folder_ids_from_inputs(self, folder_inputs or [])
        anchor = next(iter(folder_ids), 0)
        st = ScanState(
            running=True,
            token=token,
            library_id=ScanController._current_library_id(self),
            folder_ids=folder_ids,
            anchor_folder_id=anchor,
        )
        self._state.scan_states[token] = st
        if anchor:
            self._state.active_scan_folder_id = anchor
        return st

    def _start_scan(
        self,
        library_id: int | None,
        folder_ids: set[int],
        total_files: int,
        token: int,
        anchor_folder_id: int = 0,
    ) -> ScanState:
        anchor = anchor_folder_id or next(iter(folder_ids), 0)
        st = ScanState(
            running=True,
            token=token,
            library_id=library_id,
            folder_ids=set(folder_ids),
            total_files=total_files,
            anchor_folder_id=anchor,
        )
        self._state.active_scan_folder_id = anchor
        self._state.scan_states[token] = st
        return st

    def _is_scanning(self, folder_ids: set[int]) -> bool:
        """Return True only when an active scan owns any of these folders."""
        return any(
            st.running and st.owns_any_folder(folder_ids)
            for st in self._state.scan_states.values()
        )

    def _set_progress_indeterminate(self):
        if hasattr(self._file_panel, "set_progress_indeterminate"):
            self._file_panel.set_progress_indeterminate()
        elif hasattr(self._file_panel, "set_progress"):
            self._file_panel.set_progress(0, 0)

    def _populate_file_list(self, snapshots) -> dict[str, MatchResult]:
        matched: dict[str, MatchResult] = {}
        for s in snapshots:
            strategy = self._services.matcher.match(s)
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
        rows = []
        for s in snapshots:
            m = matched.get(s.relative_path)
            d = self._file_panel._decision_display(s, m)
            rows.append(FileRow(snap=s, match=m, decision=d))
        self._file_panel.set_strategy_lookup(self._services.strategies)
        self._store.rebuild(rows, strategies=self._services.strategies, keep_checked=False)
        self._file_panel._show_table()
        if self._services.strategies and self._file_panel._flat_adapter:
            self._file_panel._flat_adapter.create_combo_cells(self._file_panel._create_strategy_combo)
        return matched

    def _probe_folder_streaming(self, folder_id: int, path: str):
        """Probe one folder without blocking the UI thread."""
        if ScanController._is_scanning(self, {folder_id}):
            return
        self._state.scan_token += 1
        my_token = self._state.scan_token
        current_paths = getattr(self._state, "current_folder_paths", None)
        if current_paths is not None:
            current_paths[folder_id] = path
        ScanController._start_scan(
            self,
            ScanController._current_library_id(self),
            {folder_id},
            0,
            my_token,
            folder_id,
        )
        self._win.set_status(f"扫描 {path}...")
        self._file_panel.refresh_btn.setEnabled(False)
        self._file_panel.set_progress_visible(True)
        ScanController._set_progress_indeterminate(self)

        def _prepare_in_background():
            forbid_main_thread("single-folder file discovery")
            files = self._discover(path)
            placeholders = [
                FileSnapshot(
                    library_folder_id=folder_id,
                    relative_path=rel_path,
                    file_name=os.path.basename(abs_path),
                    size_bytes=0,
                    probe_ok=False,
                )
                for rel_path, abs_path in files
            ]
            self._notifier.scan_ready.emit(placeholders, [(folder_id, path, files)], my_token)

        threading.Thread(target=_prepare_in_background, daemon=True).start()

    def _on_refresh_requested(self):
        """Rebuild cache for the visible library."""
        current_paths = getattr(self._state, "current_folder_paths", {})
        if not current_paths:
            self._win.set_status("没有已添加的文件夹，请先添加文件夹")
            return

        folder_ids = set(current_paths.keys())
        if ScanController._is_scanning(self, folder_ids):
            self._win.set_status("当前库扫描已在进行中，请等待完成")
            return

        self._win.set_status("扫描中...")
        self._file_panel.refresh_btn.setEnabled(False)
        self._file_panel.set_progress_visible(True)
        ScanController._set_progress_indeterminate(self)
        self._state.scan_token += 1
        my_token = self._state.scan_token
        folders_at_call = list(current_paths.items())
        first_fid = folders_at_call[0][0] if folders_at_call else 0
        ScanController._start_scan(
            self,
            ScanController._current_library_id(self),
            folder_ids,
            0,
            my_token,
            first_fid,
        )

        def _scan_in_background():
            forbid_main_thread("file discovery")
            try:
                placeholders = []
                folder_inputs = []
                for folder_id, path in folders_at_call:
                    files = self._discover(path)
                    folder_inputs.append((folder_id, path, files))
                    for rel_path, abs_path in files:
                        placeholders.append(FileSnapshot(
                            library_folder_id=folder_id,
                            relative_path=rel_path,
                            file_name=os.path.basename(abs_path),
                            size_bytes=0,
                            probe_ok=False,
                        ))
                self._notifier.scan_ready.emit(placeholders, folder_inputs, my_token)
            except Exception:
                import traceback
                traceback.print_exc()
                self._notifier.scan_ready.emit([], [], my_token)

        threading.Thread(target=_scan_in_background, daemon=True).start()

    def _on_scan_ready(self, placeholders, folder_inputs, my_token):
        """Resolve cached rows in a worker, then commit visible rows on the main thread."""
        require_main_thread("ScanController._on_scan_ready")
        st = ScanController._state_for_token(self, my_token, folder_inputs)
        if st is None or not st.running:
            return
        total = len(placeholders)
        is_current = ScanController._scan_is_current(self, st)

        if total == 0:
            st.running = False
            if self._state.active_scan_folder_id == st.anchor_folder_id:
                self._state.active_scan_folder_id = 0
            if is_current:
                self._file_panel.refresh_btn.setEnabled(True)
                self._file_panel.set_progress_visible(False)
                self._win.set_status("未找到视频文件" if folder_inputs else "扫描失败，请检查后重试")
            return

        st.total_files = total
        st.done_files = 0
        if is_current:
            self._win.set_status("加载缓存中...")

        def _resolve_cache_in_background():
            forbid_main_thread("scan cache resolution")
            latest = self._state.scan_states.get(my_token)
            if latest is None or not latest.running:
                return
            cache_by_folder: dict[int, dict[str, FileSnapshot]] = {}
            try:
                for folder_id, path, _files in folder_inputs:
                    latest = self._state.scan_states.get(my_token)
                    if latest is None or not latest.running:
                        return
                    cache_by_folder[folder_id] = {
                        s.relative_path: s
                        for s in self._services.scanner.load_cached(folder_id, path)
                    }
                resolved = [
                    cache_by_folder.get(s.library_folder_id, {}).get(s.relative_path, s)
                    for s in placeholders
                ]
            except Exception:
                import traceback
                traceback.print_exc()
                resolved = placeholders
            self._notifier.scan_resolved.emit(resolved, folder_inputs, my_token)

        threading.Thread(target=_resolve_cache_in_background, daemon=True).start()

    def _on_scan_resolved(self, resolved, folder_inputs, my_token):
        require_main_thread("ScanController._on_scan_resolved")
        st = ScanController._state_for_token(self, my_token, folder_inputs)
        if st is None or not st.running:
            return
        total = len(resolved)
        st.total_files = total
        st.done_files = 0
        st.folder_ids = ScanController._folder_ids_from_inputs(self, folder_inputs) or st.folder_ids
        if not st.anchor_folder_id and st.folder_ids:
            st.anchor_folder_id = next(iter(st.folder_ids))

        if ScanController._scan_is_current(self, st):
            if len(folder_inputs) == 1:
                fid = folder_inputs[0][0]
                self._state.current_snapshots = [
                    s for s in self._state.current_snapshots
                    if s.library_folder_id != fid
                ]
                self._state.current_snapshots.extend(resolved)
            else:
                self._state.current_snapshots = list(resolved)
            self._populate_file_list(self._state.current_snapshots)
            self._file_panel.set_progress(0, total)
            self._win.set_status(f"探测中：0/{total}...")

        def _on_result(snap):
            self._notifier.probe_result.emit(snap, my_token)

        self._services.scanner.probe_multi(folder_inputs, _on_result, on_finished=None)

    def _on_probe_result(self, snap, my_token):
        require_main_thread("ScanController._on_probe_result")
        st = self._state.scan_states.get(my_token)
        if st is None or not st.running:
            return
        if not st.owns_any_folder({snap.library_folder_id}):
            return

        st.done_files += 1
        is_current = (
            ScanController._scan_is_current(self, st)
            and snap.library_folder_id in ScanController._current_folder_ids(self)
        )
        if is_current:
            for i, s in enumerate(self._state.current_snapshots):
                if s.relative_path == snap.relative_path and s.library_folder_id == snap.library_folder_id:
                    self._state.current_snapshots[i] = snap
                    break
            if snap.probe_ok:
                strategy = self._services.matcher.match(snap)
                match = (
                    MatchResult(
                        strategy=strategy,
                        estimate=estimate_savings(snap, strategy) if strategy else None,
                    )
                    if strategy else None
                )
            else:
                match = None
            self._notifier.probed.emit(snap, match)
            decision = self._file_panel._decision_display(snap, match)
            self._store.update_row((snap.library_folder_id, snap.relative_path), snap, match, decision=decision)
            self._notifier.progress.emit(st.done_files, st.total_files)

        if st.finished:
            st.running = False
            if is_current:
                self._file_panel.refresh_btn.setEnabled(True)
                self._file_panel.set_progress_visible(False)
                self._notifier.all_done.emit()

    def _on_single_folder_refresh(self, folder_id):
        """Refresh one visible folder."""
        current_paths = getattr(self._state, "current_folder_paths", {})
        if folder_id not in current_paths:
            return
        self._probe_folder_streaming(folder_id, current_paths[folder_id])
