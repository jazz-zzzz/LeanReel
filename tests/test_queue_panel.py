"""QueuePanel 测试 — 覆盖 add_task_row、update_task_row、clear_tasks、update_progress、按钮信号"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton

from leanreel.executor.worker import EncodeTask
from leanreel.data.models import TaskStatus
from leanreel.gui.queue_panel import QueuePanel, _STATUS_ICONS


class TestQueuePanelAddTask:
    """add_task_row() 方法测试"""

    def test_add_task_row_creates_widget(self, qtbot):
        """添加任务后 widget 存在，包含文件名"""
        panel = QueuePanel()
        qtbot.addWidget(panel)

        task = EncodeTask(
            file_name="功夫熊猫.mkv",
            input_path="/movies/功夫熊猫.mkv",
            output_path="/movies/功夫熊猫_SS.mkv",
            status=TaskStatus.PENDING,
            original_size=8_500_000_000,
        )
        panel.add_task_row(task)

        assert panel.task_layout.count() == 2

        item = panel.task_layout.itemAt(0)
        assert item.widget() is not None

        name_label = item.widget().findChild(QLabel, "queue_name")
        assert name_label is not None
        assert name_label.text() == "功夫熊猫.mkv"

    def test_add_task_row_shows_file_size_for_pending(self, qtbot):
        """PENDING 任务显示文件大小并显示待处理图标"""
        panel = QueuePanel()
        qtbot.addWidget(panel)

        task = EncodeTask(
            file_name="阿凡达：水之道.mkv",
            input_path="/movies/阿凡达：水之道.mkv",
            output_path="/movies/阿凡达：水之道_SS.mkv",
            status=TaskStatus.PENDING,
            original_size=15_000_000_000,
        )
        panel.add_task_row(task)

        widget = panel.task_layout.itemAt(0).widget()
        info_label = widget.findChild(QLabel, "queue_info")
        assert info_label is not None
        assert "14.0 GB" in info_label.text()

        icon_label = widget.findChild(QLabel, "queue_icon")
        assert icon_label is not None
        assert icon_label.text() == _STATUS_ICONS[TaskStatus.PENDING]

    def test_add_task_row_shows_progress_for_running(self, qtbot):
        """RUNNING 任务显示压缩进度百分比"""
        panel = QueuePanel()
        qtbot.addWidget(panel)

        task = EncodeTask(
            file_name="星际穿越.mkv",
            input_path="/movies/星际穿越.mkv",
            output_path="/movies/星际穿越_SS.mkv",
            status=TaskStatus.RUNNING,
            original_size=22_000_000_000,
            progress=67.5,
        )
        panel.add_task_row(task)

        widget = panel.task_layout.itemAt(0).widget()
        info_label = widget.findChild(QLabel, "queue_info")
        assert info_label is not None
        assert "压缩中..." in info_label.text()

        icon_label = widget.findChild(QLabel, "queue_icon")
        assert icon_label is not None
        assert icon_label.text() == _STATUS_ICONS[TaskStatus.RUNNING]

    def test_add_task_row_shows_completed_info(self, qtbot):
        """COMPLETED 任务显示压缩前后大小及节省比例"""
        panel = QueuePanel()
        qtbot.addWidget(panel)

        task = EncodeTask(
            file_name="蝙蝠侠：黑暗骑士.mkv",
            input_path="/movies/蝙蝠侠：黑暗骑士.mkv",
            output_path="/movies/蝙蝠侠：黑暗骑士_SS.mkv",
            status=TaskStatus.COMPLETED,
            original_size=12_000_000_000,
            compressed_size=4_200_000_000,
        )
        panel.add_task_row(task)

        widget = panel.task_layout.itemAt(0).widget()
        info_label = widget.findChild(QLabel, "queue_info")
        assert info_label is not None
        assert "11.2 GB" in info_label.text()
        assert "3.9 GB" in info_label.text()

        icon_label = widget.findChild(QLabel, "queue_icon")
        assert icon_label.text() == _STATUS_ICONS[TaskStatus.COMPLETED]

    def test_add_task_row_shows_failed_info(self, qtbot):
        """FAILED 任务显示失败原因"""
        panel = QueuePanel()
        qtbot.addWidget(panel)

        task = EncodeTask(
            file_name="失败文件.mkv",
            input_path="/movies/失败文件.mkv",
            output_path="/movies/失败文件_SS.mkv",
            status=TaskStatus.FAILED,
            original_size=9_500_000_000,
            compressed_size=0,
            error_message="编码器崩溃",
        )
        panel.add_task_row(task)

        widget = panel.task_layout.itemAt(0).widget()
        icon_label = widget.findChild(QLabel, "queue_icon")
        assert icon_label.text() == _STATUS_ICONS[TaskStatus.FAILED]

        info_label = widget.findChild(QLabel, "queue_info")
        assert info_label.text() == "失败：编码器崩溃"
        assert info_label.toolTip() == "编码器崩溃"

        name_label = widget.findChild(QLabel, "queue_name")
        assert name_label.text() == "失败文件.mkv"

    def test_add_task_row_multiple_tasks_stacked(self, qtbot):
        """添加多个任务后按添加顺序排列"""
        panel = QueuePanel()
        qtbot.addWidget(panel)

        task1 = EncodeTask(
            file_name="movie_a.mkv",
            input_path="/movies/movie_a.mkv",
            output_path="/movies/movie_a_SS.mkv",
            status=TaskStatus.PENDING,
            original_size=1_000_000_000,
        )
        task2 = EncodeTask(
            file_name="movie_b.mkv",
            input_path="/movies/movie_b.mkv",
            output_path="/movies/movie_b_SS.mkv",
            status=TaskStatus.PENDING,
            original_size=2_000_000_000,
        )
        task3 = EncodeTask(
            file_name="movie_c.mkv",
            input_path="/movies/movie_c.mkv",
            output_path="/movies/movie_c_SS.mkv",
            status=TaskStatus.PENDING,
            original_size=3_000_000_000,
        )

        panel.add_task_row(task1)
        panel.add_task_row(task2)
        panel.add_task_row(task3)

        assert panel.task_layout.count() == 4

        names = []
        for i in range(panel.task_layout.count() - 1):
            widget = panel.task_layout.itemAt(i).widget()
            assert widget is not None
            name_label = widget.findChild(QLabel, "queue_name")
            assert name_label is not None
            names.append(name_label.text())

        assert names == ["movie_a.mkv", "movie_b.mkv", "movie_c.mkv"]


class TestQueuePanelUpdateTask:
    """update_task_row() 方法测试"""

    def test_update_task_row_changes_icon_and_info(self, qtbot):
        """更新任务从 PENDING → RUNNING → COMPLETED，图标和信息文本逐状态变化"""
        panel = QueuePanel()
        qtbot.addWidget(panel)

        task = EncodeTask(
            file_name="星球大战.mkv",
            input_path="/movies/星球大战.mkv",
            output_path="/movies/星球大战_SS.mkv",
            status=TaskStatus.PENDING,
            original_size=18_000_000_000,
        )
        panel.add_task_row(task)

        widget = panel.task_layout.itemAt(0).widget()
        icon_label = widget.findChild(QLabel, "queue_icon")
        info_label = widget.findChild(QLabel, "queue_info")
        assert icon_label.text() == _STATUS_ICONS[TaskStatus.PENDING]

        # PENDING → RUNNING
        task.status = TaskStatus.RUNNING
        task.progress = 42.0
        panel.update_task_row(task)

        assert icon_label.text() == _STATUS_ICONS[TaskStatus.RUNNING]
        assert "压缩中..." in info_label.text()

        # RUNNING → COMPLETED
        task.status = TaskStatus.COMPLETED
        task.compressed_size = 6_000_000_000
        panel.update_task_row(task)

        assert icon_label.text() == _STATUS_ICONS[TaskStatus.COMPLETED]
        assert " → " in info_label.text()

    def test_update_task_row_handles_nonexistent_file(self, qtbot):
        """更新不存在的任务不崩溃，原有任务保持不变"""
        panel = QueuePanel()
        qtbot.addWidget(panel)

        task = EncodeTask(
            file_name="真实任务.mkv",
            input_path="/movies/真实任务.mkv",
            output_path="/movies/真实任务_SS.mkv",
            status=TaskStatus.PENDING,
            original_size=5_000_000_000,
        )
        panel.add_task_row(task)

        nonexistent = EncodeTask(
            file_name="不存在的文件.mkv",
            input_path="/nonexistent",
            output_path="/nonexistent_out",
            status=TaskStatus.RUNNING,
            original_size=100,
        )
        # 不应崩溃
        panel.update_task_row(nonexistent)

        widget = panel.task_layout.itemAt(0).widget()
        name_label = widget.findChild(QLabel, "queue_name")
        assert name_label.text() == "真实任务.mkv"

        icon_label = widget.findChild(QLabel, "queue_icon")
        assert icon_label.text() == _STATUS_ICONS[TaskStatus.PENDING]

    def test_update_task_row_only_matches_correct_file(self, qtbot):
        """更新只影响同文件名的行，不影响其他行"""
        panel = QueuePanel()
        qtbot.addWidget(panel)

        task_a = EncodeTask(
            file_name="movie_a.mkv",
            input_path="/movies/movie_a.mkv",
            output_path="/movies/movie_a_SS.mkv",
            status=TaskStatus.PENDING,
            original_size=1_000_000_000,
        )
        task_b = EncodeTask(
            file_name="movie_b.mkv",
            input_path="/movies/movie_b.mkv",
            output_path="/movies/movie_b_SS.mkv",
            status=TaskStatus.PENDING,
            original_size=2_000_000_000,
        )
        panel.add_task_row(task_a)
        panel.add_task_row(task_b)

        task_b.status = TaskStatus.RUNNING
        task_b.progress = 30.0
        panel.update_task_row(task_b)

        # task_a 不变
        widget_a = panel.task_layout.itemAt(0).widget()
        assert widget_a is not None
        icon_a = widget_a.findChild(QLabel, "queue_icon")
        assert icon_a.text() == _STATUS_ICONS[TaskStatus.PENDING]

        # task_b 已更新
        widget_b = panel.task_layout.itemAt(1).widget()
        assert widget_b is not None
        icon_b = widget_b.findChild(QLabel, "queue_icon")
        assert icon_b.text() == _STATUS_ICONS[TaskStatus.RUNNING]

    def test_update_task_row_skipped_status(self, qtbot):
        """SKIPPED 状态更新后图标变为 →"""
        panel = QueuePanel()
        qtbot.addWidget(panel)

        task = EncodeTask(
            file_name="跳过测试.mkv",
            input_path="/movies/跳过测试.mkv",
            output_path="/movies/跳过测试_SS.mkv",
            status=TaskStatus.PENDING,
            original_size=3_000_000_000,
        )
        panel.add_task_row(task)

        task.status = TaskStatus.SKIPPED
        panel.update_task_row(task)

        widget = panel.task_layout.itemAt(0).widget()
        icon_label = widget.findChild(QLabel, "queue_icon")
        assert icon_label.text() == _STATUS_ICONS[TaskStatus.SKIPPED]

    def test_queue_updates_duplicate_basenames_by_input_path(self, qtbot):
        """同名文件在不同路径下应该各自更新正确的行"""
        panel = QueuePanel()
        qtbot.addWidget(panel)

        task_a = EncodeTask(
            file_name="movie.mkv",
            input_path="/path/A/movie.mkv",
            output_path="/path/A/movie_SS.mkv",
            strategy_name="均衡压缩",
            original_size=1024,
            status=TaskStatus.PENDING,
        )
        task_b = EncodeTask(
            file_name="movie.mkv",
            input_path="/path/B/movie.mkv",
            output_path="/path/B/movie_SS.mkv",
            strategy_name="极限压缩",
            original_size=2048,
            status=TaskStatus.PENDING,
        )

        panel.add_task_row(task_a)
        panel.add_task_row(task_b)

        # 验证两行的 task_key 属性不同
        row_a = panel.task_layout.itemAt(0).widget()
        row_b = panel.task_layout.itemAt(1).widget()
        assert row_a.property("task_key") == "/path/A/movie.mkv"
        assert row_b.property("task_key") == "/path/B/movie.mkv"

        # 验证两行都显示相同文件名
        name_a = row_a.findChild(QLabel, "queue_name")
        name_b = row_b.findChild(QLabel, "queue_name")
        assert name_a.text() == "movie.mkv"
        assert name_b.text() == "movie.mkv"

        # 更新 task B 的状态为 COMPLETED
        task_b.status = TaskStatus.COMPLETED
        task_b.compressed_size = 512
        panel.update_task_row(task_b)

        # 验证 task B 的行被更新（图标变为 COMPLETED）
        icon_b = row_b.findChild(QLabel, "queue_icon")
        assert icon_b.text() == _STATUS_ICONS[TaskStatus.COMPLETED]

        # 验证 task A 没有被误更新（图标仍为 PENDING）
        icon_a = row_a.findChild(QLabel, "queue_icon")
        assert icon_a.text() == _STATUS_ICONS[TaskStatus.PENDING]

    def test_add_task_row_sets_tooltip_to_input_path(self, qtbot):
        """文件名 label 的 tooltip 应该显示完整路径"""
        panel = QueuePanel()
        qtbot.addWidget(panel)

        task = EncodeTask(
            file_name="movie.mkv",
            input_path="/media/extdrive/movies/movie.mkv",
            output_path="/media/extdrive/movies/movie_SS.mkv",
            strategy_name="均衡压缩",
            original_size=5_000_000_000,
            status=TaskStatus.PENDING,
        )
        panel.add_task_row(task)

        widget = panel.task_layout.itemAt(0).widget()
        name_label = widget.findChild(QLabel, "queue_name")
        assert name_label.toolTip() == "/media/extdrive/movies/movie.mkv"


class TestQueuePanelClear:
    """clear_tasks() 方法测试"""

    def test_clear_tasks_removes_all_rows(self, qtbot):
        """清空后无任务行 widget 残留"""
        panel = QueuePanel()
        qtbot.addWidget(panel)

        for i in range(3):
            task = EncodeTask(
                file_name=f"movie_{i}.mkv",
                input_path=f"/movies/movie_{i}.mkv",
                output_path=f"/movies/movie_{i}_SS.mkv",
                status=TaskStatus.PENDING,
                original_size=1_000_000_000,
            )
            panel.add_task_row(task)

        assert panel.task_layout.count() == 4

        panel.clear_tasks()
        # 必须让事件循环运行才能处理 deleteLater 排队的 DeferredDelete
        qtbot.wait(50)

        # 只有 stretch 残留，无任务 widget
        assert panel.task_layout.count() == 1

    def test_clear_tasks_resets_progress(self, qtbot):
        """清空后进度条归零，标签重置为就绪"""
        panel = QueuePanel()
        qtbot.addWidget(panel)

        panel.update_progress({
            "total": 5, "completed": 3, "failed": 1,
            "skipped": 1, "percentage": 60.0,
        })
        assert panel.total_progress.value() == 60
        assert "完成 3/5" in panel.total_label.text()

        panel.clear_tasks()

        assert panel.total_progress.value() == 0
        assert panel.total_label.text() == "就绪"

    def test_clear_tasks_idempotent(self, qtbot):
        """对已清空的 panel 再次 clear 不崩溃"""
        panel = QueuePanel()
        qtbot.addWidget(panel)

        task = EncodeTask(
            file_name="test.mkv",
            input_path="/movies/test.mkv",
            output_path="/movies/test_SS.mkv",
            status=TaskStatus.PENDING,
            original_size=1_000_000,
        )
        panel.add_task_row(task)
        panel.clear_tasks()
        qtbot.wait(50)

        # 再次清空不应崩溃
        panel.clear_tasks()
        assert panel.total_progress.value() == 0
        assert panel.total_label.text() == "就绪"

    def test_clear_finished_keeps_running_and_pending_rows(self, qtbot):
        """清空已完成只移除终态任务，保留 RUNNING 和 PENDING。"""
        panel = QueuePanel()
        qtbot.addWidget(panel)

        tasks = [
            EncodeTask(
                file_name="running_task.mkv",
                input_path="/movies/running_task.mkv",
                output_path="/movies/running_task_SS.mkv",
                status=TaskStatus.RUNNING,
                original_size=5_000_000_000,
                progress=45.0,
            ),
            EncodeTask(
                file_name="completed_task.mkv",
                input_path="/movies/completed_task.mkv",
                output_path="/movies/completed_task_SS.mkv",
                status=TaskStatus.COMPLETED,
                original_size=8_000_000_000,
                compressed_size=3_000_000_000,
            ),
            EncodeTask(
                file_name="pending_task.mkv",
                input_path="/movies/pending_task.mkv",
                output_path="/movies/pending_task_SS.mkv",
                status=TaskStatus.PENDING,
                original_size=2_000_000_000,
            ),
            EncodeTask(
                file_name="failed_task.mkv",
                input_path="/movies/failed_task.mkv",
                output_path="/movies/failed_task_SS.mkv",
                status=TaskStatus.FAILED,
                original_size=6_000_000_000,
                compressed_size=0,
                error_message="编码错误",
            ),
        ]

        for t in tasks:
            panel.add_task_row(t)

        assert panel.task_layout.count() == 5  # 4 tasks + 1 stretch

        panel.clear_finished()
        qtbot.wait(50)

        visible_names = []
        for index in range(panel.task_layout.count() - 1):
            row = panel.task_layout.itemAt(index).widget()
            visible_names.append(row.findChild(QLabel, "queue_name").text())

        assert visible_names == ["running_task.mkv", "pending_task.mkv"]


class TestQueuePanelProgress:
    """update_progress() 方法测试"""

    def test_update_progress_sets_bar_and_label(self, qtbot):
        """更新进度后进度条值和标签文本正确"""
        panel = QueuePanel()
        qtbot.addWidget(panel)

        progress = {
            "total": 10,
            "completed": 7,
            "skipped": 2,
            "failed": 1,
            "percentage": 70.0,
        }
        panel.update_progress(progress)

        assert panel.total_progress.value() == 70
        assert "完成 7/10" in panel.total_label.text()
        assert "跳过 2" in panel.total_label.text()
        assert "失败 1" in panel.total_label.text()

    def test_update_progress_handles_zero_total(self, qtbot):
        """零总量的进度更新不崩溃"""
        panel = QueuePanel()
        qtbot.addWidget(panel)

        progress = {
            "total": 0,
            "completed": 0,
            "skipped": 0,
            "failed": 0,
            "percentage": 0,
        }
        panel.update_progress(progress)

        assert panel.total_progress.value() == 0

    def test_update_progress_with_nonzero_complex_values(self, qtbot):
        """非平凡非零值的进度更新"""
        panel = QueuePanel()
        qtbot.addWidget(panel)

        progress = {
            "total": 42,
            "completed": 15,
            "skipped": 3,
            "failed": 24,
            "percentage": 35,
        }
        panel.update_progress(progress)

        assert panel.total_progress.value() == 35
        assert "完成 15/42" in panel.total_label.text()
        assert "跳过 3" in panel.total_label.text()
        assert "失败 24" in panel.total_label.text()


class TestQueuePanelButtons:
    """按钮测试"""

    def test_pause_button_emits_pause_requested(self, qtbot):
        """点击暂停按钮发射 pause_requested 信号"""
        panel = QueuePanel()
        qtbot.addWidget(panel)

        received = []
        panel.pause_requested.connect(lambda: received.append(True))

        qtbot.mouseClick(panel.pause_btn, Qt.LeftButton)

        assert len(received) == 1

    def test_button_layout_includes_pause_cancel_clear(self, qtbot):
        """验证当前设计的按钮布局：暂停 | 取消全部 | 清空已完成"""
        panel = QueuePanel()
        qtbot.addWidget(panel)

        buttons = panel.findChildren(QPushButton)
        button_texts = [btn.text() for btn in buttons]

        assert "暂停" in button_texts
        assert "取消全部" in button_texts
        assert "清空已完成" in button_texts

    def test_clear_button_removes_rows(self, qtbot):
        """点击清空所有按钮移除所有任务行"""
        panel = QueuePanel()
        qtbot.addWidget(panel)

        task = EncodeTask(
            file_name="清空测试.mkv",
            input_path="/movies/清空测试.mkv",
            output_path="/movies/清空测试_SS.mkv",
            status=TaskStatus.COMPLETED,
            original_size=5_000_000_000,
            compressed_size=2_000_000_000,
        )
        panel.add_task_row(task)
        assert panel.task_layout.count() == 2

        qtbot.mouseClick(panel.clear_btn, Qt.LeftButton)
        qtbot.wait(50)

        assert panel.task_layout.count() == 1

    def test_pause_button_initial_text(self, qtbot):
        """暂停按钮初始文字为'暂停'"""
        panel = QueuePanel()
        qtbot.addWidget(panel)

        assert panel.pause_btn.text() == "暂停"


def test_queue_panel_cancel_all_button_emits_cancel_signal(qtbot):
    from leanreel.gui.queue_panel import QueuePanel

    panel = QueuePanel()
    qtbot.addWidget(panel)
    emitted = []
    panel.cancel_requested.connect(emitted.append)

    panel.cancel_btn.click()

    assert emitted == [-1]


def test_queue_panel_failed_task_shows_error_message(qtbot):
    panel = QueuePanel()
    qtbot.addWidget(panel)
    task = EncodeTask(
        file_name="failed.mkv",
        input_path="/movies/failed.mkv",
        output_path="/movies/failed_SS.mkv",
        status=TaskStatus.FAILED,
        original_size=1_000_000_000,
        compressed_size=0,
        error_message="编码器崩溃",
    )

    panel.add_task_row(task)

    row = panel.task_layout.itemAt(0).widget()
    info_label = row.findChild(QLabel, "queue_info")
    assert info_label.text() == "失败：编码器崩溃"
    assert info_label.toolTip() == "编码器崩溃"
