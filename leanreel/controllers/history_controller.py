"""历史记录控制器 — 后台加载，不阻塞 UI"""
import threading
from PySide6.QtCore import QObject, Signal

from leanreel.utils.threading_contract import require_main_thread, forbid_main_thread


class HistoryController(QObject):
    data_ready = Signal(list)  # rows list

    def __init__(self, db, history_panel):
        super().__init__()
        self._db = db
        self._history_panel = history_panel
        self._loading = False
        self.data_ready.connect(self._on_data_ready)

    def refresh(self):
        """从后台线程加载数据，不阻塞 UI。"""
        if self._loading:
            return
        self._loading = True

        def _load():
            forbid_main_thread("HistoryController._load")
            try:
                rows = self._db.get_all_history()
            except Exception:
                rows = []
            self.data_ready.emit(rows)

        threading.Thread(target=_load, daemon=True).start()

    def _on_data_ready(self, rows):
        self._history_panel.populate(rows)
        self._loading = False
