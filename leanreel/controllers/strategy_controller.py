"""策略控制器 — 管理策略选择、覆盖和编码启动"""
from __future__ import annotations
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt

from leanreel.state.app_state import AppState

if TYPE_CHECKING:
    from leanreel.main import Services


class StrategyController:
    """策略控制器 — 处理策略下拉变更、自定义策略选择、文件选中策略同步和编码启动"""

    def __init__(
        self,
        state: AppState,
        services: Services,
        strategy_panel,
        file_panel,
        win,
        store,
        encoding_ctrl,
    ):
        self._state = state
        self._services = services
        self._strategy_panel = strategy_panel
        self._file_panel = file_panel
        self._win = win
        self._store = store
        self._encoding_ctrl = encoding_ctrl

    # ── 策略信号处理 ──

    def _on_strategy_override_changed(self, relative_path, strategy_name):
        if strategy_name == "自定义":
            self._state.active_custom_path = relative_path
            return
        self._strategy_panel.show_preset_strategy()
        self._state.active_custom_path = None
        strategy = next((s for s in self._services.strategies if s.name == strategy_name), None)
        if strategy is None:
            self._state.strategy_overrides.pop(relative_path, None)
        else:
            self._state.strategy_overrides[relative_path] = strategy

    def _on_file_row_selected(self, relative_path):
        """单个文件行被选中时，右侧策略面板同步显示该文件的策略。"""
        if not relative_path:
            return
        # 优先用用户手动选择的覆盖策略，其次用自动匹配的策略
        override = self._state.strategy_overrides.get(relative_path)
        if override:
            self._strategy_panel.show_preset_strategy()
            self._strategy_panel.preset_panel.select_by_strategy(override.name)
            return
        # 从 Store 中查找该文件的匹配策略
        for row_obj in self._store.rows():
            if row_obj.snap.relative_path == relative_path:
                match = row_obj.match
                strategy = getattr(match, "strategy", None) if match else None
                if strategy:
                    name = strategy if isinstance(strategy, str) else getattr(strategy, "name", "")
                    if name:
                        self._strategy_panel.show_preset_strategy()
                        self._strategy_panel.preset_panel.select_by_strategy(name)
                break

    def _on_preset_strategy_changed(self, index):
        """策略面板预设策略变更时，应用到所有选中/勾选的文件。"""
        strategy = self._strategy_panel.current_preset_strategy
        if strategy is None:
            return
        # 收集需要覆盖的 relative_path
        targets = set(self._file_panel.get_checked_file_keys())
        model = self._file_panel.table.model()
        selection = self._file_panel.table.selectionModel()
        if model is not None and selection is not None:
            for idx in selection.selectedRows(1):
                key = model.data(idx, Qt.UserRole)
                if isinstance(key, tuple) and len(key) == 2:
                    targets.add(key)
        if not targets:
            return
        for key in targets:
            self._state.strategy_overrides[key] = strategy
            self._file_panel.apply_strategy_to_row(key, strategy)

    def _on_custom_strategy_requested(self, relative_path):
        self._state.active_custom_path = relative_path
        self._strategy_panel.show_custom_strategy()

    def _on_custom_strategy_changed(self, strategy):
        if not self._state.active_custom_path:
            return
        self._state.strategy_overrides[self._state.active_custom_path] = strategy
        self._file_panel.apply_strategy_to_row(self._state.active_custom_path, strategy)

    # ── 编码控制 ──

    def _on_start_requested(self):
        checked_keys = set(self._file_panel.get_checked_file_keys())
        if not checked_keys:
            self._win.set_status("没有勾选任何文件，请先在文件列表中勾选要处理的文件")
            return
        snapshots = [s for s in self._state.current_snapshots if (s.library_folder_id, s.relative_path) in checked_keys]
        if not snapshots:
            self._win.set_status("勾选的文件未找到")
            return
        self._encoding_ctrl.start(
            snapshots,
            self._state.current_folder_paths,
            self._state.strategy_overrides,
        )
