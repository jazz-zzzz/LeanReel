"""扫描控制器 — 管理文件遍历、缓存解析、探测调度和文件列表填充"""
import os
import threading
from pathlib import Path

from leanreel.domain.models import FileSnapshot, FileRow, MatchResult, get_skip_reason
from leanreel.services.matcher import estimate_savings
from leanreel.utils.threading_contract import require_main_thread, forbid_main_thread


def clear_current_state():
    """返回空状态三元组，用于库删除后完全重置。"""
    return [], {}, {}


def remove_folder_from_current_state(snapshots, folder_paths, strategy_overrides, folder_id: int):
    """从当前状态中移除指定文件夹的所有数据，返回新的三元组。"""
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
    """扫描控制器 — 管理文件遍历、缓存解析、探测调度和文件列表填充"""

    def __init__(self, state, services, file_panel, win, store, notifier, file_discoverer=None):
        self._state = state
        self._services = services
        self._file_panel = file_panel
        self._win = win
        self._store = store
        self._notifier = notifier
        self._discover = file_discoverer  # 注入：避免 controller import infrastructure
        self._probe_total = 0
        self._probe_done = 0
        self._probe_token = 0

    # ── 文件列表填充 ──

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
        # D QComboBox 立即开始创建（视口内懒加载，不会阻塞）
        if self._services.strategies and self._file_panel._flat_adapter:
            self._file_panel._flat_adapter.create_combo_cells(self._file_panel._create_strategy_combo)
        return matched

    # ── 单文件夹流式探测 ──

    def _probe_folder_streaming(self, folder_id: int, path: str):
        """流式探测单个文件夹 — I/O 在后台，UI 在主线程。"""
        if self._state.refresh_running:
            return
        self._state.refresh_running = True
        self._state.scan_token += 1
        my_token = self._state.scan_token
        self._state.current_folder_paths[folder_id] = path
        self._win.set_status(f"扫描 {path}...")
        self._file_panel.refresh_btn.setEnabled(False)
        self._file_panel.set_progress_visible(True)

        def _prepare_in_background():
            forbid_main_thread("single-folder file discovery")
            files = self._discover(path)
            if not files:
                self._notifier.scan_ready.emit([], [(folder_id, path, [])], my_token)
                return
            placeholders = []
            for rel_path, abs_path in files:
                placeholders.append(FileSnapshot(
                    library_folder_id=folder_id, relative_path=rel_path,
                    file_name=os.path.basename(abs_path), size_bytes=0, probe_ok=False))
            self._notifier.scan_ready.emit(placeholders,
                [(folder_id, path, files)], my_token)

        threading.Thread(target=_prepare_in_background, daemon=True).start()

    # ── 全量刷新 ──

    def _on_refresh_requested(self):
        """重建缓存：后台遍历文件 + 主线程即时展示占位 + 共享线程池探测。"""
        if not self._state.current_folder_paths:
            self._win.set_status("没有已添加的文件夹，请先添加文件夹")
            return

        if self._state.refresh_running:
            self._win.set_status("扫描已在进行中，请等待完成")
            return

        self._state.refresh_running = True
        self._win.set_status("扫描中...")
        # A 懒切换：不清空旧列表，只置灰按钮
        self._file_panel.refresh_btn.setEnabled(False)
        self._file_panel.set_progress_visible(True)
        self._state.scan_token += 1
        my_token = self._state.scan_token
        folders_at_call = list(self._state.current_folder_paths.items())

        def _scan_in_background():
            """后台线程：遍历目录（I/O 不阻塞主线程）"""
            forbid_main_thread("file discovery")
            try:
                placeholders = []
                folder_inputs = []
                for folder_id, path in folders_at_call:
                    files = self._discover(path)
                    folder_inputs.append((folder_id, path, files))
                    for rel_path, abs_path in files:
                        placeholders.append(FileSnapshot(
                            library_folder_id=folder_id, relative_path=rel_path,
                            file_name=os.path.basename(abs_path), size_bytes=0, probe_ok=False))
                self._notifier.scan_ready.emit(placeholders, folder_inputs, my_token)
            except Exception:
                import traceback
                traceback.print_exc()
                self._notifier.scan_ready.emit([], [], my_token)

        threading.Thread(target=_scan_in_background, daemon=True).start()

    def _on_scan_ready(self, placeholders, folder_inputs, my_token):
        """主线程：缓存解析（同步，毫秒级）→ 填充列表 → 启动探测。"""
        require_main_thread("ScanController._on_scan_ready")
        if self._state.scan_token != my_token:
            return
        total = len(placeholders)

        if total == 0:
            self._state.refresh_running = False
            self._file_panel.refresh_btn.setEnabled(True)
            self._file_panel.set_progress_visible(False)
            if not folder_inputs:
                self._win.set_status("扫描失败，请检查网络连接后重试")
            else:
                self._win.set_status("未找到视频文件")
            return

        # Cache resolution may touch slow storage, so keep it off the UI thread.
        self._win.set_status("加载缓存中...")

        def _resolve_cache_in_background():
            forbid_main_thread("scan cache resolution")
            cache_by_folder: dict[int, dict[str, FileSnapshot]] = {}
            try:
                for folder_id, path, _files in folder_inputs:
                    if self._state.scan_token != my_token:
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
        if self._state.scan_token != my_token:
            return
        total = len(resolved)

        if len(folder_inputs) == 1:
            fid = folder_inputs[0][0]
            self._state.current_snapshots = [s for s in self._state.current_snapshots if s.library_folder_id != fid]
            self._state.current_snapshots.extend(resolved)
        else:
            self._state.current_snapshots = resolved

        self._populate_file_list(self._state.current_snapshots, )

        # D 缓存加载后策略下拉立即可用；排序通过手动表头点击支持，不启原生（防自动重排）
        self._file_panel.set_progress(0, total)
        self._win.set_status(f"探测中：0/{total}...")

        self._probe_total = total
        self._probe_done = 0
        self._probe_token = my_token

        def _on_result(snap):
            self._notifier.probe_result.emit(snap, my_token)

        self._services.scanner.probe_multi(folder_inputs, _on_result, on_finished=None)

    def _on_probe_result(self, snap, my_token):
        require_main_thread("ScanController._on_probe_result")
        if self._state.scan_token != my_token or self._probe_token != my_token:
            return
        for i, s in enumerate(self._state.current_snapshots):
            if s.relative_path == snap.relative_path and s.library_folder_id == snap.library_folder_id:
                self._state.current_snapshots[i] = snap
                break
        if snap.probe_ok:
            strategy = self._services.matcher.match(snap)
            match = MatchResult(strategy=strategy, estimate=estimate_savings(snap, strategy) if strategy else None) if strategy else None
        else:
            match = None
        self._notifier.probed.emit(snap, match)
        d = self._file_panel._decision_display(snap, match)
        self._store.update_row((snap.library_folder_id, snap.relative_path), snap, match, decision=d)
        self._probe_done += 1
        self._notifier.progress.emit(self._probe_done, self._probe_total)
        if self._probe_done == self._probe_total:
            self._state.refresh_running = False
            self._file_panel.refresh_btn.setEnabled(True)
            self._file_panel.set_progress_visible(False)
            self._notifier.all_done.emit()

    def _on_single_folder_refresh(self, folder_id):
        """流式刷新单个文件夹（库面板或树视图右键触发）。"""
        if folder_id not in self._state.current_folder_paths:
            return
        # A 懒切换：保留旧数据，等新数据就绪后 _on_scan_ready 替换
        self._probe_folder_streaming(folder_id, self._state.current_folder_paths[folder_id])
