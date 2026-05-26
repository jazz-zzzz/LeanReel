"""历史面板测试"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor


def test_history_panel_creates_with_columns(qtbot):
    from leanreel.gui.history_panel import HistoryPanel

    panel = HistoryPanel()
    qtbot.addWidget(panel)
    model = panel.table.model()

    expected = [
        "源文件名", "库", "文件夹", "源体积", "输出体积",
        "节省量", "节省率", "策略", "编码器", "CQ/CRF",
        "耗时", "完成时间", "状态", "源已删",
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
            "status": "completed", "source_deleted": 0, "output_path": "/out.mkv",
            "compressed_size": 0, "error_message": "",
        },
    ]
    panel.populate(rows)

    model = panel.table.model()
    assert model.rowCount() == 1
    assert model.data(model.index(0, 0), Qt.DisplayRole) == "movie.mkv"
    # 避免精确匹配 — 验证业务不变性：包含大小单位
    output_display = str(model.data(model.index(0, 4), Qt.DisplayRole))
    assert output_display != "—"
    assert "GB" in output_display or "MB" in output_display
    assert model.data(model.index(0, 7), Qt.DisplayRole) == "AV1 NVENC CQ34 均衡快速"
    panel.close()


def test_history_panel_filter_by_status(qtbot):
    from leanreel.gui.history_panel import HistoryPanel

    panel = HistoryPanel()
    qtbot.addWidget(panel)
    rows = [
        {"status": "completed", "file_name": "a.mkv", "library_name": "",
         "folder_path": "", "original_size": 1000, "output_size_bytes": 500,
         "savings_pct": 50.0, "strategy_name": "", "encoder": "",
         "cq_value": 0, "duration_seconds": 0, "created_at": "",
         "source_deleted": 0, "output_path": "", "compressed_size": 0, "error_message": ""},
        {"status": "failed", "file_name": "b.mkv", "library_name": "",
         "folder_path": "", "original_size": 1000, "output_size_bytes": 0,
         "savings_pct": 0.0, "strategy_name": "", "encoder": "",
         "cq_value": 0, "duration_seconds": 0, "created_at": "",
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
    """空数据 populate 不应崩溃，rowCount 为 0"""
    from leanreel.gui.history_panel import HistoryPanel

    panel = HistoryPanel()
    qtbot.addWidget(panel)
    panel.populate([])

    model = panel.table.model()
    assert model.rowCount() == 0
    panel.close()


def test_history_panel_refresh_button_emits(qtbot):
    """刷新按钮点击应发射 refresh_requested 信号"""
    from leanreel.gui.history_panel import HistoryPanel

    panel = HistoryPanel()
    qtbot.addWidget(panel)
    signal_fired = []

    panel.refresh_requested.connect(lambda: signal_fired.append(True))
    panel.refresh_btn.click()

    assert len(signal_fired) == 1
    panel.close()


def test_history_panel_status_column_has_explicit_label_and_color(qtbot):
    """状态颜色只属于状态列，不污染整行文本。"""
    from leanreel.gui.history_panel import HistoryPanel

    panel = HistoryPanel()
    qtbot.addWidget(panel)
    rows = [
        {"status": "failed", "file_name": "broken.mkv", "library_name": "",
         "folder_path": "", "original_size": 5000, "output_size_bytes": 0,
         "savings_pct": 0.0, "strategy_name": "", "encoder": "",
         "cq_value": 0, "duration_seconds": 0, "created_at": "",
         "source_deleted": 0, "output_path": "", "compressed_size": 0, "error_message": "encoder crashed"},
    ]
    panel.populate(rows)

    model = panel.table.model()
    name_idx = model.index(0, 0)
    status_idx = model.index(0, 12)

    assert model.data(status_idx, Qt.DisplayRole) == "失败"
    assert model.data(name_idx, Qt.ForegroundRole) is None
    assert model.data(status_idx, Qt.ForegroundRole) == QColor("#c4554a")
    assert model.data(status_idx, Qt.ToolTipRole) == "encoder crashed"
    panel.close()


def test_history_panel_status_colors_are_limited_to_status_column(qtbot):
    from leanreel.gui.history_panel import HistoryPanel

    panel = HistoryPanel()
    qtbot.addWidget(panel)
    rows = [
        {"status": "completed", "file_name": "done.mkv", "library_name": "",
         "folder_path": "", "original_size": 5000, "output_size_bytes": 3000,
         "savings_pct": 40.0, "strategy_name": "", "encoder": "",
         "cq_value": 0, "duration_seconds": 0, "created_at": "",
         "source_deleted": 1, "output_path": "", "compressed_size": 0, "error_message": ""},
        {"status": "cancelled", "file_name": "cancel.mkv", "library_name": "",
         "folder_path": "", "original_size": 5000, "output_size_bytes": 0,
         "savings_pct": 0.0, "strategy_name": "", "encoder": "",
         "cq_value": 0, "duration_seconds": 0, "created_at": "",
         "source_deleted": 0, "output_path": "", "compressed_size": 0, "error_message": ""},
    ]
    panel.populate(rows)

    model = panel.table.model()
    assert model.data(model.index(0, 12), Qt.DisplayRole) == "成功"
    assert model.data(model.index(0, 12), Qt.ForegroundRole) == QColor("#6b9955")
    assert model.data(model.index(0, 0), Qt.ForegroundRole) is None
    assert model.data(model.index(1, 12), Qt.DisplayRole) == "已取消"
    assert model.data(model.index(1, 12), Qt.ForegroundRole) == QColor("#6b6560")
    assert model.data(model.index(1, 0), Qt.ForegroundRole) is None
    panel.close()
