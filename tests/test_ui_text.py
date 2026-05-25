from leanreel.ui_text import UI_TEXT


def test_scan_status_copy_is_centralized():
    assert UI_TEXT.scan_path("D:/Media") == "扫描 D:/Media..."
    assert UI_TEXT.probe_progress(3, 8) == "探测中：3/8..."
    assert UI_TEXT.scan_empty(has_folder_inputs=True) == "未找到视频文件"
    assert UI_TEXT.scan_empty(has_folder_inputs=False) == "扫描失败，请检查后重试"


def test_queue_copy_is_centralized():
    progress = {
        "completed": 2,
        "total": 5,
        "skipped": 1,
        "failed": 1,
        "cancelled": 1,
    }

    assert UI_TEXT.queue_progress(progress) == "完成 2/5  跳过 1  失败 1  取消 1"
    assert UI_TEXT.failed_info("编码器崩溃") == "失败：编码器崩溃"
    assert UI_TEXT.running_info(42) == "压缩中... 42%"
