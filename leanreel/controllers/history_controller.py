"""历史记录控制器"""
from leanreel.utils.threading_contract import require_main_thread


class HistoryController:
    def __init__(self, db, history_panel):
        self._db = db
        self._history_panel = history_panel

    @require_main_thread
    def load(self):
        rows = self._db.get_all_history()
        self._history_panel.populate(rows)
