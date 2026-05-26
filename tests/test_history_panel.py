"""历史面板测试"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor


def test_history_panel_creates_with_columns(qtbot):
    from leanreel.gui.history_panel import HistoryPanel

    panel = HistoryPanel()
    qtbot.addWidget(panel)
    model = panel.table.model()

    expected = [
        "源文件名", "进度", "库", "文件夹", "源体积", "输出体积",
        "节省量", "节省率", "策略", "编码器", "CQ/CRF",
        "耗时", "开始时间", "完成时间", "源已删", "备注",
    ]
    for i, col in enumerate(expected):
        assert model.headerData(i, Qt.Horizontal, Qt.DisplayRole) == col

    panel.close()


def test_history_panel_back_button_emits(qtbot):
    from leanreel.gui.history_panel import HistoryPanel

    panel = HistoryPanel()
    qtbot.addWidget(panel)
    signal_fired = []

    panel.back_requested.connect(lambda: signal_fired.append(True))
    panel.back_btn.click()

    assert len(signal_fired) == 1
    panel.close()


def test_history_panel_populate_renders_rows(qtbot):
    from leanreel.gui.history_panel import HistoryPanel

    panel = HistoryPanel()
    qtbot.addWidget(panel)
    rows = [
        {
            "id": 1, "file_name": "movie.mkv", "library_name": "电影",
            "folder_path": "/movies", "original_size": 10_000_000_000,
            "output_size_bytes": 3_500_000_000, "savings_pct": 65.0,
            "strategy_name": "AV1 NVENC CQ34 均衡快速",
            "encoder": "av1_nvenc", "cq_value": 34,
            "duration_seconds": 900, "created_at": "2026-05-28 12:00:00",
            "completed_at": "", "status": "completed", "source_deleted": 0,
            "output_path": "/out.mkv", "compressed_size": 0, "error_message": "",
            "progress": 100.0, "stage": "",
        },
    ]
    panel.populate(rows)

    model = panel.table.model()
    assert model.rowCount() == 1
    assert model.data(model.index(0, 0), Qt.DisplayRole) == "movie.mkv"
    # 进度列包含百分比和状态
    progress_text = str(model.data(model.index(0, 1), Qt.DisplayRole))
    assert "100%" in progress_text
    assert "成功" in progress_text
    # 输出体积列
    output_display = str(model.data(model.index(0, 5), Qt.DisplayRole))
    assert "GB" in output_display or "MB" in output_display
    assert model.data(model.index(0, 8), Qt.DisplayRole) == "AV1 NVENC CQ34 均衡快速"
    panel.close()


def test_history_panel_filter_by_status(qtbot):
    from leanreel.gui.history_panel import HistoryPanel

    panel = HistoryPanel()
    qtbot.addWidget(panel)
    rows = [
        {"status": "completed", "progress": 100.0, "stage": "", "file_name": "a.mkv", "library_name": "",
         "folder_path": "", "original_size": 1000, "output_size_bytes": 500,
         "savings_pct": 50.0, "strategy_name": "", "encoder": "",
         "cq_value": 0, "duration_seconds": 0, "created_at": "", "completed_at": "",
         "source_deleted": 0, "output_path": "", "compressed_size": 0, "error_message": ""},
        {"status": "failed", "progress": 25.0, "stage": "", "file_name": "b.mkv", "library_name": "",
         "folder_path": "", "original_size": 1000, "output_size_bytes": 0,
         "savings_pct": 0.0, "strategy_name": "", "encoder": "",
         "cq_value": 0, "duration_seconds": 0, "created_at": "", "completed_at": "",
         "source_deleted": 0, "output_path": "", "compressed_size": 0, "error_message": ""},
    ]
    panel.populate(rows)

    panel.status_filter.setCurrentText("成功")
    proxy = panel.table.model()
    assert proxy.rowCount() == 1

    panel.status_filter.setCurrentText("全部")
    assert proxy.rowCount() == 2

    panel.close()


def test_history_panel_does_not_use_alternating_row_backgrounds(qtbot):
    from leanreel.gui.history_panel import HistoryPanel

    panel = HistoryPanel()
    qtbot.addWidget(panel)

    assert panel.table.alternatingRowColors() is False
    panel.close()


def test_history_panel_empty_populate_does_not_crash(qtbot):
    from leanreel.gui.history_panel import HistoryPanel

    panel = HistoryPanel()
    qtbot.addWidget(panel)
    panel.populate([])

    model = panel.table.model()
    assert model.rowCount() == 0
    panel.close()


def test_history_panel_refresh_button_emits(qtbot):
    from leanreel.gui.history_panel import HistoryPanel

    panel = HistoryPanel()
    qtbot.addWidget(panel)
    signal_fired = []

    panel.refresh_requested.connect(lambda: signal_fired.append(True))
    panel.refresh_btn.click()

    assert len(signal_fired) == 1
    panel.close()


def test_history_panel_progress_column_has_label_and_color(qtbot):
    from leanreel.gui.history_panel import HistoryPanel

    panel = HistoryPanel()
    qtbot.addWidget(panel)
    rows = [
        {"status": "failed", "progress": 48.0, "stage": "转码", "file_name": "broken.mkv", "library_name": "",
         "folder_path": "", "original_size": 5000, "output_size_bytes": 0,
         "savings_pct": 0.0, "strategy_name": "", "encoder": "",
         "cq_value": 0, "duration_seconds": 0, "created_at": "", "completed_at": "",
         "source_deleted": 0, "output_path": "", "compressed_size": 0, "error_message": "encoder crashed"},
    ]
    panel.populate(rows)

    model = panel.table.model()
    progress_idx = model.index(0, 1)
    name_idx = model.index(0, 0)

    progress_text = str(model.data(progress_idx, Qt.DisplayRole))
    assert "48%" in progress_text
    assert "失败" in progress_text
    assert model.data(name_idx, Qt.ForegroundRole) is None
    assert model.data(progress_idx, Qt.ForegroundRole) == QColor("#c4554a")
    assert model.data(progress_idx, Qt.ToolTipRole) == "encoder crashed"
    panel.close()


def test_history_panel_colors_limited_to_progress_column(qtbot):
    from leanreel.gui.history_panel import HistoryPanel

    panel = HistoryPanel()
    qtbot.addWidget(panel)
    rows = [
        {"status": "completed", "progress": 100.0, "stage": "", "file_name": "done.mkv", "library_name": "",
         "folder_path": "", "original_size": 5000, "output_size_bytes": 3000,
         "savings_pct": 40.0, "strategy_name": "", "encoder": "",
         "cq_value": 0, "duration_seconds": 0, "created_at": "", "completed_at": "",
         "source_deleted": 1, "output_path": "", "compressed_size": 0, "error_message": ""},
        {"status": "cancelled", "progress": 22.0, "stage": "", "file_name": "cancel.mkv", "library_name": "",
         "folder_path": "", "original_size": 5000, "output_size_bytes": 0,
         "savings_pct": 0.0, "strategy_name": "", "encoder": "",
         "cq_value": 0, "duration_seconds": 0, "created_at": "", "completed_at": "",
         "source_deleted": 0, "output_path": "", "compressed_size": 0, "error_message": ""},
    ]
    panel.populate(rows)

    model = panel.table.model()
    # 进度列有颜色和状态文本
    assert "成功" in str(model.data(model.index(0, 1), Qt.DisplayRole))
    assert model.data(model.index(0, 1), Qt.ForegroundRole) == QColor("#6b9955")
    assert model.data(model.index(0, 0), Qt.ForegroundRole) is None
    assert "已取消" in str(model.data(model.index(1, 1), Qt.DisplayRole))
    assert model.data(model.index(1, 1), Qt.ForegroundRole) == QColor("#6b6560")
    assert model.data(model.index(1, 0), Qt.ForegroundRole) is None
    # 源已删列
    assert model.data(model.index(0, 14), Qt.DisplayRole) == "是"
    assert model.data(model.index(1, 14), Qt.DisplayRole) == "否"
    panel.close()


def test_history_panel_running_status_filter(qtbot):
    from leanreel.gui.history_panel import HistoryPanel

    panel = HistoryPanel()
    qtbot.addWidget(panel)
    rows = [
        {"status": "running", "progress": 37.0, "stage": "转码", "file_name": "run.mkv", "library_name": "",
         "folder_path": "", "original_size": 1000, "output_size_bytes": 0,
         "savings_pct": 0.0, "strategy_name": "", "encoder": "",
         "cq_value": 0, "duration_seconds": 0, "created_at": "", "completed_at": "",
         "source_deleted": 0, "output_path": "", "compressed_size": 0, "error_message": ""},
        {"status": "discarded", "progress": 100.0, "stage": "", "file_name": "discard.mkv", "library_name": "",
         "folder_path": "", "original_size": 1000, "output_size_bytes": 1000,
         "savings_pct": 0.0, "strategy_name": "", "encoder": "",
         "cq_value": 0, "duration_seconds": 0, "created_at": "", "completed_at": "",
         "source_deleted": 0, "output_path": "", "compressed_size": 0, "error_message": "输出体积不小于源文件"},
    ]
    panel.populate(rows)

    panel.status_filter.setCurrentText("进行中")
    assert panel.table.model().rowCount() == 1
    assert panel.table.model().data(panel.table.model().index(0, 0), Qt.DisplayRole) == "run.mkv"

    panel.status_filter.setCurrentText("已丢弃")
    assert panel.table.model().rowCount() == 1
    assert panel.table.model().data(panel.table.model().index(0, 0), Qt.DisplayRole) == "discard.mkv"

    panel.close()
