"""FFmpeg 命令构建测试"""
import pytest
from pathlib import Path
from leanreel.executor.ffmpeg import FFmpegBuilder, FFmpegExecutor
from leanreel.core.strategy import Strategy
from leanreel.data.models import FileSnapshot, HDRType


@pytest.fixture
def balanced_strategy():
    data = {
        "name": "均衡压缩", "is_preset": True,
        "video": {"encoder": "libx265", "crf": 20, "preset": "slow", "pix_fmt": "yuv420p10le"},
        "hdr": {"mode": "preserve_hdr10", "dv_handling": "reinject_rpu"},
        "audio": {"mode": "keep_original"},
        "subtitle": {"mode": "keep_chinese"},
        "filters": {"skip_x265": True},
        "estimated_savings": "35-50%",
    }
    return Strategy.from_dict(data)


def test_build_basic_x265_command(balanced_strategy):
    snap = FileSnapshot(video_codec="h264", video_width=1920, video_height=1080)
    cmd = FFmpegBuilder.build(snap, balanced_strategy, "input.mkv", "output.mkv")
    assert "-c:V" in cmd and "libx265" in cmd
    assert "-crf" in cmd and "20" in cmd
    assert "-preset" in cmd and "slow" in cmd
    assert "input.mkv" in cmd
    assert "output.mkv" in cmd


def test_build_nvenc_command():
    from leanreel.core.strategy import Strategy
    data = {
        "name": "NVENC 测试", "is_preset": False,
        "video": {"encoder": "hevc_nvenc", "gpu": True, "nv_preset": "p1", "rc": "vbr", "cq": 23},
        "hdr": {}, "audio": {"mode": "keep_original"}, "subtitle": {"mode": "keep_chinese"},
        "filters": {},
    }
    strategy = Strategy.from_dict(data)
    snap = FileSnapshot(video_codec="h264", video_width=1920, video_height=1080)
    cmd = FFmpegBuilder.build(snap, strategy, "in.mkv", "out.mkv")
    assert "-c:V" in cmd and "hevc_nvenc" in cmd
    assert "-preset" in cmd and "p1" in cmd
    assert "-rc" in cmd and "vbr" in cmd
    assert "-cq" in cmd and "23" in cmd
    assert "-crf" not in cmd


def test_build_preserves_chapters_and_attachments(balanced_strategy):
    snap = FileSnapshot(video_codec="h264")
    cmd = FFmpegBuilder.build(snap, balanced_strategy, "in.mkv", "out.mkv")
    joined = " ".join(cmd)
    assert "-map_chapters 0" in joined
    assert "-map_metadata 0" in joined
    assert "-copy_unknown" in joined
    assert "-map 0:t?" in joined
    assert "-c:t copy" in joined
    assert "-map 0:d?" in joined
    assert "-c:d copy" in joined


def test_build_command_preserves_audio(balanced_strategy):
    snap = FileSnapshot(video_codec="h264")
    cmd = FFmpegBuilder.build(snap, balanced_strategy, "in.mkv", "out.mkv")
    joined = " ".join(cmd)
    assert "-c:a copy" in joined


def test_build_hdr10_preservation(balanced_strategy):
    snap = FileSnapshot(video_codec="h264", hdr_type=HDRType.HDR10,
                        video_width=3840, video_height=2160)
    cmd = FFmpegBuilder.build(snap, balanced_strategy, "in.mkv", "out.mkv")
    joined = " ".join(cmd)
    assert "-color_primaries bt2020" in joined
    assert "-color_trc smpte2084" in joined
    assert "-colorspace bt2020nc" in joined


def test_build_sdr_no_hdr_flags(balanced_strategy):
    snap = FileSnapshot(video_codec="h264", hdr_type=HDRType.SDR)
    cmd = FFmpegBuilder.build(snap, balanced_strategy, "in.mkv", "out.mkv")
    joined = " ".join(cmd)
    assert "-color_primaries" not in joined


def test_build_command_does_not_overwrite_existing_output_by_default(balanced_strategy):
    snap = FileSnapshot(video_codec="h264")
    cmd = FFmpegBuilder.build(snap, balanced_strategy, "in.mkv", "out.mkv")
    assert "-y" not in cmd
    assert "-n" in cmd


def test_ffmpeg_executor_runs_built_command(monkeypatch, balanced_strategy, tmp_path):
    from leanreel.executor import ffmpeg
    from leanreel.executor.worker import EncodeTask

    calls = []

    def fake_run(cmd, progress_callback=None, cancel_event=None):
        # 模拟 ffmpeg 在临时路径创建输出文件
        temp_out = cmd[-1]
        Path(temp_out).parent.mkdir(parents=True, exist_ok=True)
        Path(temp_out).write_text("")
        calls.append(cmd)
        return 0, ""

    monkeypatch.setattr(ffmpeg, "run_ffmpeg", fake_run)
    temp_dir = tmp_path / "temp"
    task = EncodeTask(
        file_name="sample.mkv",
        input_path=str(tmp_path / "sample.mkv"),
        output_path=str(tmp_path / "sample.out.mkv"),
        strategy=balanced_strategy,
        snapshot=FileSnapshot(video_codec="h264"),
    )

    FFmpegExecutor(temp_dir=str(temp_dir)).encode(task)

    assert len(calls) == 1
    cmd = calls[0]
    cmd_joined = " ".join(cmd)

    # 验证关键参数
    assert "-n" in cmd           # 不覆盖已存在文件
    assert "-i" in cmd
    assert task.input_path in cmd
    assert "-map 0:V" in cmd_joined  # 视频映射
    assert "-c:V" in cmd_joined
    assert "libx265" in cmd_joined
    assert "-crf" in cmd_joined and "20" in cmd_joined
    assert "-map 0:a" in cmd_joined   # 音频保留（无探测数据时回退）
    assert "-c:a copy" in cmd_joined
    assert "-map_metadata 0" in cmd_joined
    assert "-map_chapters 0" in cmd_joined

    # I/O 分离：命令输出到临时目录
    assert str(temp_dir) in str(cmd[-1])
    # 最终文件在目标路径
    assert (tmp_path / "sample.out.mkv").exists()


def test_ffmpeg_executor_raises_when_command_fails(monkeypatch, balanced_strategy, tmp_path):
    from leanreel.executor import ffmpeg
    from leanreel.executor.worker import EncodeTask

    monkeypatch.setattr(ffmpeg, "run_ffmpeg", lambda cmd, progress_callback=None, cancel_event=None: (1, "mock_error"))
    temp_dir = tmp_path / "temp"
    task = EncodeTask(
        file_name="sample.mkv",
        input_path=str(tmp_path / "sample.mkv"),
        output_path=str(tmp_path / "sample.out.mkv"),
        strategy=balanced_strategy,
        snapshot=FileSnapshot(video_codec="h264"),
    )

    with pytest.raises(RuntimeError):
        FFmpegExecutor(temp_dir=str(temp_dir)).encode(task)

    # 失败时临时文件应被清理
    temps = list(temp_dir.glob("sample.out.mkv"))
    assert not temps


def test_build_uses_uppercase_v_for_video_map(balanced_strategy):
    """确保使用大写 V 排除内嵌封面 mjpeg 流"""
    snap = FileSnapshot(video_codec="h264")
    cmd = FFmpegBuilder.build(snap, balanced_strategy, "in.mkv", "out.mkv")
    joined = " ".join(cmd)
    assert "-map 0:V" in joined
    assert "-map 0:v" not in joined


def test_build_filters_commentary_audio():
    from leanreel.data.models import AudioTrack
    strategy = Strategy.from_dict({
        "name": "test", "audio": {"mode": "keep_original", "remove_commentary": True,
                                  "preferred_languages": []},
        "subtitle": {"mode": "keep_all"},
        "video": {}, "filters": {},
    })
    snap = FileSnapshot(video_codec="h264", audio_tracks=[
        AudioTrack(codec="aac", channels=2, language="eng", title="Main"),
        AudioTrack(codec="aac", channels=2, language="eng", title="Commentary", is_commentary=True),
        AudioTrack(codec="aac", channels=2, language="jpn", title="Japanese"),
    ])
    cmd = FFmpegBuilder.build(snap, strategy, "in.mkv", "out.mkv")
    joined = " ".join(cmd)
    assert "-map 0:a:0" in joined
    assert "-map 0:a:2" in joined
    assert "-map 0:a:1" not in joined


def test_build_strip_commentary_mode():
    from leanreel.data.models import AudioTrack
    strategy = Strategy.from_dict({
        "name": "test", "audio": {"mode": "strip_commentary", "remove_commentary": False},
        "subtitle": {"mode": "keep_all"},
        "video": {}, "filters": {},
    })
    snap = FileSnapshot(video_codec="h264", audio_tracks=[
        AudioTrack(codec="truehd", channels=8, language="eng", title="Atmos"),
        AudioTrack(codec="aac", channels=2, language="eng", title="Commentary", is_commentary=True),
    ])
    cmd = FFmpegBuilder.build(snap, strategy, "in.mkv", "out.mkv")
    joined = " ".join(cmd)
    assert "-map 0:a:0" in joined
    assert "-map 0:a:1" not in joined


def test_build_keep_original_keeps_unknown_language_audio():
    from leanreel.data.models import AudioTrack

    strategy = Strategy.from_dict({
        "name": "keep-original",
        "audio": {
            "mode": "keep_original",
            "remove_commentary": True,
            "preferred_languages": ["chi", "zho", "eng"],
        },
        "subtitle": {"mode": "keep_all"},
        "video": {},
        "filters": {},
    })
    snap = FileSnapshot(video_codec="h264", audio_tracks=[
        AudioTrack(codec="truehd", channels=8, language="und", title="Main Atmos"),
        AudioTrack(codec="aac", channels=2, language="eng", title="Commentary", is_commentary=True),
    ])

    cmd = FFmpegBuilder.build(snap, strategy, "in.mkv", "out.mkv")
    joined = " ".join(cmd)

    assert "-map 0:a:0" in joined
    assert "-map 0:a:1" not in joined
    assert "-c:a copy" in joined


def test_build_filters_by_preferred_languages():
    from leanreel.data.models import AudioTrack
    strategy = Strategy.from_dict({
        "name": "test", "audio": {"mode": "strip_non_preferred", "preferred_languages": ["chi", "zho", "eng"]},
        "subtitle": {"mode": "keep_all"},
        "video": {}, "filters": {},
    })
    snap = FileSnapshot(video_codec="h264", audio_tracks=[
        AudioTrack(codec="aac", channels=2, language="eng"),
        AudioTrack(codec="aac", channels=2, language="jpn"),
        AudioTrack(codec="aac", channels=2, language="chi"),
    ])
    cmd = FFmpegBuilder.build(snap, strategy, "in.mkv", "out.mkv")
    joined = " ".join(cmd)
    assert "-map 0:a:0" in joined
    assert "-map 0:a:2" in joined
    assert "-map 0:a:1" not in joined


def test_build_filters_subtitles_by_language():
    from leanreel.data.models import SubtitleTrack
    strategy = Strategy.from_dict({
        "name": "test", "audio": {"mode": "keep_original"},
        "subtitle": {"mode": "keep_chinese"},
        "video": {}, "filters": {},
    })
    snap = FileSnapshot(video_codec="h264", subtitle_tracks=[
        SubtitleTrack(codec="hdmv_pgs", language="chi", title="Chinese"),
        SubtitleTrack(codec="hdmv_pgs", language="eng", title="English"),
        SubtitleTrack(codec="hdmv_pgs", language="jpn", title="Japanese"),
    ])
    cmd = FFmpegBuilder.build(snap, strategy, "in.mkv", "out.mkv")
    joined = " ".join(cmd)
    assert "-map 0:s:0" in joined
    assert "-map 0:s:1" not in joined
    assert "-map 0:s:2" not in joined


def test_build_keep_chinese_english_subtitles():
    from leanreel.data.models import SubtitleTrack
    strategy = Strategy.from_dict({
        "name": "test", "audio": {"mode": "keep_original"},
        "subtitle": {"mode": "keep_chinese_english"},
        "video": {}, "filters": {},
    })
    snap = FileSnapshot(video_codec="h264", subtitle_tracks=[
        SubtitleTrack(codec="hdmv_pgs", language="chi"),
        SubtitleTrack(codec="hdmv_pgs", language="eng"),
        SubtitleTrack(codec="hdmv_pgs", language="fre"),
    ])
    cmd = FFmpegBuilder.build(snap, strategy, "in.mkv", "out.mkv")
    joined = " ".join(cmd)
    assert "-map 0:s:0" in joined
    assert "-map 0:s:1" in joined
    assert "-map 0:s:2" not in joined


def test_build_remove_all_subtitles():
    from leanreel.data.models import SubtitleTrack
    strategy = Strategy.from_dict({
        "name": "test", "audio": {"mode": "keep_original"},
        "subtitle": {"mode": "remove_all"},
        "video": {}, "filters": {},
    })
    snap = FileSnapshot(video_codec="h264", subtitle_tracks=[
        SubtitleTrack(codec="hdmv_pgs", language="chi"),
    ])
    cmd = FFmpegBuilder.build(snap, strategy, "in.mkv", "out.mkv")
    joined = " ".join(cmd)
    assert "-map 0:s" not in joined


def test_build_audio_fallback_when_no_probe_data(balanced_strategy):
    snap = FileSnapshot(video_codec="h264", audio_tracks=[])
    cmd = FFmpegBuilder.build(snap, balanced_strategy, "in.mkv", "out.mkv")
    joined = " ".join(cmd)
    assert "-map 0:a" in joined
    assert "-c:a copy" in joined


def test_ffmpeg_executor_uses_unique_temp_paths_for_same_output_names(monkeypatch, balanced_strategy, tmp_path):
    from leanreel.executor import ffmpeg
    from leanreel.executor.worker import EncodeTask

    commands = []

    def fake_run(cmd, progress_callback=None, cancel_event=None):
        commands.append(cmd)
        Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
        Path(cmd[-1]).write_text("encoded")
        return 0, ""

    monkeypatch.setattr(ffmpeg, "run_ffmpeg", fake_run)
    temp_dir = tmp_path / "temp"

    first_output = tmp_path / "Film A" / "movie_SS.mkv"
    second_output = tmp_path / "Film B" / "movie_SS.mkv"

    for output in (first_output, second_output):
        task = EncodeTask(
            file_name="movie.mkv",
            input_path=str(tmp_path / "source.mkv"),
            output_path=str(output),
            strategy=balanced_strategy,
            snapshot=FileSnapshot(video_codec="h264", size_bytes=1000),
        )
        FFmpegExecutor(temp_dir=str(temp_dir)).encode(task)
        assert task.compressed_size == len("encoded")

    assert len(commands) == 2
    assert commands[0][-1] != commands[1][-1]
    assert first_output.exists()
    assert second_output.exists()


def test_ffmpeg_executor_dovi_flow(monkeypatch, tmp_path):
    from leanreel.executor import ffmpeg as ffmpeg_mod
    from leanreel.executor.worker import EncodeTask
    from leanreel.executor import dovi as dovi_mod

    ffmpeg_calls = []
    dovi_extract_calls = []
    dovi_inject_calls = []

    def fake_run_ffmpeg(cmd, progress_callback=None, cancel_event=None):
        ffmpeg_calls.append(cmd)
        Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
        Path(cmd[-1]).write_text("")
        return 0, ""

    def fake_extract(input_file, rpu_output):
        dovi_extract_calls.append((input_file, rpu_output))
        Path(rpu_output).write_text("rpu_data")
        return True

    def fake_inject(encoded, rpu, output):
        dovi_inject_calls.append((encoded, rpu, output))
        Path(output).write_text("dv_data")
        return True

    monkeypatch.setattr(ffmpeg_mod, "run_ffmpeg", fake_run_ffmpeg)
    monkeypatch.setattr(dovi_mod.DoviTool, "extract_rpu", staticmethod(fake_extract))
    monkeypatch.setattr(dovi_mod.DoviTool, "inject_rpu", staticmethod(fake_inject))

    strategy = Strategy.from_dict({
        "name": "DV测试", "is_preset": False,
        "video": {"encoder": "libx265", "crf": 20, "preset": "slow", "pix_fmt": "yuv420p10le"},
        "hdr": {"dv_handling": "reinject_rpu"},
        "audio": {"mode": "keep_original"},
        "subtitle": {"mode": "keep_chinese"},
        "filters": {},
    })
    snap = FileSnapshot(video_codec="h264", hdr_type=HDRType.DV_P7,
                        video_width=3840, video_height=2160)

    temp_dir = tmp_path / "temp"
    task = EncodeTask(
        file_name="dv_movie.mkv",
        input_path=str(tmp_path / "dv_movie.mkv"),
        output_path=str(tmp_path / "dv_movie_SS.mkv"),
        strategy=strategy,
        snapshot=snap,
    )

    FFmpegExecutor(temp_dir=str(temp_dir)).encode(task)

    assert len(dovi_extract_calls) == 1
    assert len(dovi_inject_calls) == 1
    assert len(ffmpeg_calls) == 1
    assert (tmp_path / "dv_movie_SS.mkv").exists()


def test_ffmpeg_executor_dovi_cleanup_rpu_on_failure(monkeypatch, tmp_path):
    from leanreel.executor import ffmpeg as ffmpeg_mod
    from leanreel.executor.worker import EncodeTask
    from leanreel.executor import dovi as dovi_mod

    def fake_run_ffmpeg(cmd, progress_callback=None, cancel_event=None):
        Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
        return 1, "mock_error"  # 模拟失败

    def fake_extract(input_file, rpu_output):
        Path(rpu_output).write_text("rpu_data")
        return True

    monkeypatch.setattr(ffmpeg_mod, "run_ffmpeg", fake_run_ffmpeg)
    monkeypatch.setattr(dovi_mod.DoviTool, "extract_rpu", staticmethod(fake_extract))

    strategy = Strategy.from_dict({
        "name": "DV测试", "video": {"encoder": "libx265", "crf": 20, "preset": "slow"},
        "hdr": {"dv_handling": "reinject_rpu"},
        "audio": {"mode": "keep_original"},
        "subtitle": {"mode": "keep_chinese"},
        "filters": {},
    })
    snap = FileSnapshot(video_codec="h264", hdr_type=HDRType.DV_P7)

    temp_dir = tmp_path / "temp"
    task = EncodeTask(
        file_name="dv_movie.mkv",
        input_path=str(tmp_path / "dv_movie.mkv"),
        output_path=str(tmp_path / "dv_movie_SS.mkv"),
        strategy=strategy,
        snapshot=snap,
    )

    with pytest.raises(RuntimeError):
        FFmpegExecutor(temp_dir=str(temp_dir)).encode(task)

    # RPU 临时文件应该被清理
    rpu_files = list(temp_dir.glob("*.rpu"))
    assert len(rpu_files) == 0


# ============================================================
# A. run_ffmpeg() 单元测试（mock subprocess.Popen）
# ============================================================

def test_run_ffmpeg_returns_exit_code_and_stderr_tail():
    """Mock Popen 返回 exit_code=0, stderr="" — 验证返回 (0, "") 且 Popen 参数正确"""
    from unittest.mock import patch, MagicMock
    import subprocess
    from leanreel.executor.ffmpeg_builder import run_ffmpeg

    mock_proc = MagicMock()
    mock_proc.stderr = []
    mock_proc.wait.return_value = 0

    cmd = ["ffmpeg", "-i", "input.mkv", "-c:v", "libx265", "output.mkv"]
    with patch("leanreel.executor.ffmpeg_builder.subprocess.Popen", return_value=mock_proc) as mock_popen:
        exit_code, stderr_tail = run_ffmpeg(cmd)

    assert exit_code == 0
    assert stderr_tail == ""

    # TDD 规则: mock 必须验证调用参数
    mock_popen.assert_called_once_with(
        cmd,
        stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
    )
    mock_proc.wait.assert_called_once()


def test_run_ffmpeg_captures_stderr_tail():
    """Mock Popen 返回 30 行 stderr — 验证只返回最后 20 行"""
    from unittest.mock import patch, MagicMock
    import subprocess
    from leanreel.executor.ffmpeg_builder import run_ffmpeg

    # 30 行 stderr（非平凡数据，非空值）
    stderr_30_lines = [f"ffmpeg log line #{i}\n" for i in range(1, 31)]
    mock_proc = MagicMock()
    mock_proc.stderr = stderr_30_lines
    mock_proc.wait.return_value = 1

    cmd = ["ffmpeg", "-i", "input.mkv", "output.mkv"]
    with patch("leanreel.executor.ffmpeg_builder.subprocess.Popen", return_value=mock_proc) as mock_popen:
        exit_code, stderr_tail = run_ffmpeg(cmd)

    assert exit_code == 1
    # 只有最后 20 行
    expected_tail = "".join(stderr_30_lines[-20:])
    assert stderr_tail == expected_tail
    # 前 10 行（索引 0-9）不应出现在尾部
    # 使用换行符锚定精确行，避免 "line #1" 误匹配 "line #11"
    for i in range(1, 11):
        assert f"ffmpeg log line #{i}\n" not in stderr_tail, f"line #{i} should not be in tail"
    # 最后一行应在尾部
    assert "ffmpeg log line #30\n" in stderr_tail

    mock_popen.assert_called_once_with(
        cmd,
        stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
    )


def test_run_ffmpeg_passes_timeout_to_communicate():
    """验证 Popen 参数和 progress_callback 被触发（仅 time= 行）"""
    from unittest.mock import patch, MagicMock
    import subprocess
    from leanreel.executor.ffmpeg_builder import run_ffmpeg

    # 混合 stderr：有些行含 time=，有些不含
    stderr_lines = [
        "ffmpeg version n7.0.2\n",
        "frame=   50 fps= 25 time=00:00:02.00 bitrate=5000kbits/s\n",
        "[libx265] starting encode\n",
        "frame=  100 fps= 25 time=00:00:04.00 bitrate=4800kbits/s\n",
    ]
    mock_proc = MagicMock()
    mock_proc.stderr = stderr_lines
    mock_proc.wait.return_value = 0

    progress_records = []
    def progress_cb(line):
        progress_records.append(line)

    cmd = ["ffmpeg", "-i", "input.mkv", "-c:v", "libx265", "output.mkv"]
    with patch("leanreel.executor.ffmpeg_builder.subprocess.Popen", return_value=mock_proc) as mock_popen:
        run_ffmpeg(cmd, progress_callback=progress_cb)

    # 验证 Popen 调用参数
    mock_popen.assert_called_once_with(
        cmd,
        stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
    )
    mock_proc.wait.assert_called_once()

    # 只有含 "time=" 的行触发回调
    assert len(progress_records) == 2
    assert "time=00:00:02.00" in progress_records[0]
    assert "time=00:00:04.00" in progress_records[1]
    # 不含 "time=" 的行不应出现在回调中
    assert not any("ffmpeg version" in rec for rec in progress_records)
    assert not any("[libx265]" in rec for rec in progress_records)


def test_run_ffmpeg_handles_missing_executable():
    """mock subprocess.Popen 抛出 FileNotFoundError — 验证转为 RuntimeError"""
    from unittest.mock import patch
    from leanreel.executor.ffmpeg_builder import run_ffmpeg

    with patch("leanreel.executor.ffmpeg_builder.subprocess.Popen",
               side_effect=FileNotFoundError("ffmpeg not found")):
        with pytest.raises(RuntimeError, match="ffmpeg"):
            run_ffmpeg(["nonexistent_ffmpeg", "-i", "in.mkv", "out.mkv"])


# ============================================================
# B. get_ffmpeg_path / set_ffmpeg_path 测试
# ============================================================

def test_get_ffmpeg_path_returns_default():
    """重置全局状态后 get_ffmpeg_path 返回非空字符串（默认或内置路径）"""
    import leanreel.executor.ffmpeg_builder as fb

    # 重置为初始状态
    fb._FFMPEG_PATH = None
    result = fb.get_ffmpeg_path()
    # 应返回内置 ffmpeg.exe 路径或 "ffmpeg" 回退
    assert isinstance(result, str) and len(result) > 0


def test_set_ffmpeg_path_overrides_and_get_returns_it():
    """set_ffmpeg_path 后 get_ffmpeg_path 返回设置值"""
    import leanreel.executor.ffmpeg_builder as fb

    custom = "C:\\tools\\ffmpeg.exe"
    try:
        fb.set_ffmpeg_path(custom)
        assert fb.get_ffmpeg_path() == custom
    finally:
        # 恢复初始状态，避免影响其他测试
        fb._FFMPEG_PATH = None


# ============================================================
# C. HDR10+ 动态元数据参数测试
# ============================================================

def test_build_hdr10plus_preserves_dynamic_metadata():
    """HDR10+ snapshot 的 hdr_type=HDR10P — 验证命令包含 -hdr10+ 且包含色彩元数据"""
    from leanreel.core.strategy import Strategy

    strategy = Strategy.from_dict({
        "name": "HDR10+测试", "is_preset": False,
        "video": {"encoder": "libx265", "crf": 18, "preset": "slow", "pix_fmt": "yuv420p10le"},
        "hdr": {"mode": "preserve_hdr10"},
        "audio": {"mode": "keep_original"},
        "subtitle": {"mode": "keep_all"},
        "filters": {},
    })
    snap = FileSnapshot(
        video_codec="hevc", hdr_type=HDRType.HDR10P,
        video_width=3840, video_height=2160,
    )
    cmd = FFmpegBuilder.build(snap, strategy, "hdr10p_sample.mkv", "output.mkv")
    joined = " ".join(cmd)

    # HDR10+ 动态元数据标志
    assert "-hdr10+" in cmd
    assert "-color_primaries bt2020" in joined
    assert "-color_trc smpte2084" in joined
    assert "-colorspace bt2020nc" in joined


def test_build_hdr10plus_with_copy_encoder():
    """验证 copy 编码器 + HDR10P 不会产生 -hdr10+ 标志（copy 模式不触发 HDR 逻辑）"""
    from leanreel.core.strategy import Strategy

    strategy = Strategy.from_dict({
        "name": "copy模式", "is_preset": False,
        "video": {"encoder": "copy"},
        "hdr": {"mode": "preserve_hdr10"},
        "audio": {"mode": "keep_original"},
        "subtitle": {"mode": "keep_all"},
        "filters": {},
    })
    snap = FileSnapshot(
        video_codec="hevc", hdr_type=HDRType.HDR10P,
        video_width=3840, video_height=2160,
    )
    cmd = FFmpegBuilder.build(snap, strategy, "hdr10p_copy.mkv", "output.mkv")
    joined = " ".join(cmd)

    # copy 模式不加 -hdr10+ 或色彩元数据
    assert "-hdr10+" not in cmd
    assert "-color_primaries" not in joined


# ============================================================
# D. GPU (NVENC) + HDR10 组合测试
# ============================================================

def test_build_nvenc_with_hdr10_preserves_color_info():
    """NVENC 编码器 + HDR10 snapshot — 验证色彩元数据完整且无 -crf"""
    from leanreel.core.strategy import Strategy

    strategy = Strategy.from_dict({
        "name": "NVENC HDR10", "is_preset": False,
        "video": {"encoder": "hevc_nvenc", "gpu": True, "nv_preset": "p1",
                   "rc": "vbr", "cq": 26},
        "hdr": {"mode": "preserve_hdr10"},
        "audio": {"mode": "keep_original"},
        "subtitle": {"mode": "keep_all"},
        "filters": {},
    })
    snap = FileSnapshot(
        video_codec="hevc", hdr_type=HDRType.HDR10,
        video_width=3840, video_height=2160,
    )
    cmd = FFmpegBuilder.build(snap, strategy, "hdr10_sample.mkv", "output.mkv")
    joined = " ".join(cmd)

    # NVENC 编码器参数
    assert "-c:V" in cmd and "hevc_nvenc" in cmd
    assert "-preset" in cmd and "p1" in cmd
    assert "-rc" in cmd and "vbr" in cmd
    assert "-cq" in cmd and "26" in cmd
    # NVENC 不应有 -crf
    assert "-crf" not in cmd
    # HDR10 色彩元数据
    assert "-color_primaries bt2020" in joined
    assert "-color_trc smpte2084" in joined
    assert "-colorspace bt2020nc" in joined
    # HDR10（非 HDR10+）不应有 -hdr10+
    assert "-hdr10+" not in cmd


def test_build_nvenc_with_hdr10plus_preserves_color_and_dynamic_metadata():
    """NVENC 编码器 + HDR10+ snapshot — 验证同时有色彩元数据和 -hdr10+"""
    from leanreel.core.strategy import Strategy

    strategy = Strategy.from_dict({
        "name": "NVENC HDR10+", "is_preset": False,
        "video": {"encoder": "hevc_nvenc", "gpu": True, "nv_preset": "p1",
                   "rc": "vbr", "cq": 26},
        "hdr": {"mode": "preserve_hdr10"},
        "audio": {"mode": "keep_original"},
        "subtitle": {"mode": "keep_all"},
        "filters": {},
    })
    snap = FileSnapshot(
        video_codec="hevc", hdr_type=HDRType.HDR10P,
        video_width=3840, video_height=2160,
    )
    cmd = FFmpegBuilder.build(snap, strategy, "hdr10plus_gpu.mkv", "output.mkv")
    joined = " ".join(cmd)

    # NVENC 参数
    assert "-c:V" in cmd and "hevc_nvenc" in cmd
    # HDR10+ 特有: -hdr10+
    assert "-hdr10+" in cmd
    # HDR 色彩元数据
    assert "-color_primaries bt2020" in joined
    assert "-color_trc smpte2084" in joined
    assert "-colorspace bt2020nc" in joined


def test_build_nvenc_with_sdr_no_hdr_flags():
    """NVENC 编码器 + SDR snapshot — 验证不产生任何 HDR 标志"""
    from leanreel.core.strategy import Strategy

    strategy = Strategy.from_dict({
        "name": "NVENC SDR", "is_preset": False,
        "video": {"encoder": "hevc_nvenc", "gpu": True, "nv_preset": "p1",
                   "rc": "vbr", "cq": 23},
        "hdr": {"mode": "preserve_hdr10"},
        "audio": {"mode": "keep_original"},
        "subtitle": {"mode": "keep_all"},
        "filters": {},
    })
    snap = FileSnapshot(
        video_codec="h264", hdr_type=HDRType.SDR,
        video_width=1920, video_height=1080,
    )
    cmd = FFmpegBuilder.build(snap, strategy, "sdr_sample.mkv", "output.mkv")
    joined = " ".join(cmd)

    assert "-c:V" in cmd and "hevc_nvenc" in cmd
    assert "-color_primaries" not in joined
    assert "-color_trc" not in joined
    assert "-colorspace" not in joined
    assert "-hdr10+" not in cmd


# ============================================================
# E. DV_P5 和 DV_P8 的 HDRType 枚举测试
# ============================================================

def test_dv_p5_enum_value():
    """确认 HDRType.DV_P5.value == "DV_P5" """
    assert HDRType.DV_P5.value == "DV_P5"
    assert isinstance(HDRType.DV_P5, HDRType)
    assert HDRType.DV_P5 != HDRType.DV_P7


def test_dv_p8_enum_value():
    """确认 HDRType.DV_P8.value == "DV_P8" """
    assert HDRType.DV_P8.value == "DV_P8"
    assert isinstance(HDRType.DV_P8, HDRType)
    assert HDRType.DV_P8 != HDRType.DV_P7


# ============================================================
# F. Issue 1 修复验证：DV_P5 色彩元数据测试
# ============================================================

def test_build_dv_p5_includes_color_metadata():
    """DV_P5 snapshot 的命令包含完整色彩空间元数据（bt2020/smpte2084/bt2020nc）"""
    snap = FileSnapshot(video_codec="hevc", hdr_type=HDRType.DV_P5,
                        video_width=3840, video_height=2160)
    strategy = Strategy.from_dict({
        "name": "DV_P5测试", "is_preset": False,
        "video": {"encoder": "libx265", "crf": 20, "preset": "slow", "pix_fmt": "yuv420p10le"},
        "hdr": {"mode": "preserve_hdr10"},
        "audio": {"mode": "keep_original"},
        "subtitle": {"mode": "keep_all"},
        "filters": {},
    })
    cmd = FFmpegBuilder.build(snap, strategy, "dv_p5_sample.mkv", "output.mkv")
    joined = " ".join(cmd)

    # DV_P5 必须有完整色彩元数据（否则播放器无法正确渲染）
    assert "-color_primaries bt2020" in joined
    assert "-color_trc smpte2084" in joined
    assert "-colorspace bt2020nc" in joined
    # DV_P5 不是 HDR10+，不应有 -hdr10+
    assert "-hdr10+" not in cmd


def test_build_dv_p5_nvenc_includes_color_metadata():
    """DV_P5 + NVENC GPU 编码器也包含色彩元数据"""
    snap = FileSnapshot(video_codec="hevc", hdr_type=HDRType.DV_P5,
                        video_width=3840, video_height=2160)
    strategy = Strategy.from_dict({
        "name": "NVENC DV_P5", "is_preset": False,
        "video": {"encoder": "hevc_nvenc", "gpu": True, "nv_preset": "p1",
                   "rc": "vbr", "cq": 26},
        "hdr": {"mode": "preserve_hdr10"},
        "audio": {"mode": "keep_original"},
        "subtitle": {"mode": "keep_all"},
        "filters": {},
    })
    cmd = FFmpegBuilder.build(snap, strategy, "dv_p5_gpu.mkv", "output.mkv")
    joined = " ".join(cmd)

    assert "-c:V" in cmd and "hevc_nvenc" in cmd
    assert "-color_primaries bt2020" in joined
    assert "-color_trc smpte2084" in joined
    assert "-colorspace bt2020nc" in joined


# ============================================================
# G. Issue 2 修复验证：进度回调测试
# ============================================================

def test_ffmpeg_executor_progress_callback_is_called(monkeypatch, tmp_path):
    """验证 FFmpegExecutor.encode 通过管线阶段和 run_ffmpeg 进度回调更新 task.progress"""
    from leanreel.executor import ffmpeg as ffmpeg_mod
    from leanreel.executor.worker import EncodeTask

    progress_tasks = []

    def fake_run(cmd, progress_callback=None, cancel_event=None):
        # 模拟 ffmpeg stderr 含 time= 行
        Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
        Path(cmd[-1]).write_text("encoded")
        if progress_callback:
            progress_callback("frame=  150 fps= 25 time=00:00:06.00 bitrate=5000kbits/s")
            progress_callback("frame=  300 fps= 25 time=00:00:12.00 bitrate=4800kbits/s")
        return 0, ""

    def fake_progress_cb(task):
        progress_tasks.append((task.file_name, task.progress))

    monkeypatch.setattr(ffmpeg_mod, "run_ffmpeg", fake_run)

    strategy = Strategy.from_dict({
        "name": "test", "video": {"encoder": "libx265", "crf": 20, "preset": "slow"},
        "audio": {"mode": "keep_original"}, "subtitle": {"mode": "keep_all"},
        "filters": {},
    })
    snap = FileSnapshot(video_codec="h264", duration_seconds=30.0)

    temp_dir = tmp_path / "temp"
    task = EncodeTask(
        file_name="progress.mkv",
        input_path=str(tmp_path / "progress.mkv"),
        output_path=str(tmp_path / "progress_SS.mkv"),
        strategy=strategy,
        snapshot=snap,
    )
    task.progress = 0.0

    executor = FFmpegExecutor(temp_dir=str(temp_dir), progress_callback=fake_progress_cb)
    executor.encode(task)

    # 所有阶段完成后，总进度应为 1.0
    assert task.progress == pytest.approx(1.0)
    # 管线各阶段 + transcode 子进度均触发回调，应 >= 4 次
    assert len(progress_tasks) >= 4, f"expected >=4 progress callbacks, got {len(progress_tasks)}"
    # 进度值应单调递增
    progress_values = [p for _, p in progress_tasks]
    for j in range(1, len(progress_values)):
        assert progress_values[j] >= progress_values[j - 1], f"progress decreased at index {j}"
    # 所有进度值在 [0, 1] 范围内
    for p in progress_values:
        assert 0.0 <= p <= 1.0, f"progress out of range: {p}"


def test_ffmpeg_executor_progress_callback_clamped_to_one(monkeypatch, tmp_path):
    """验证管线总进度值和阶段进度值都不会超过 1.0"""
    from leanreel.executor import ffmpeg as ffmpeg_mod
    from leanreel.executor.worker import EncodeTask

    def fake_run(cmd, progress_callback=None, cancel_event=None):
        Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
        Path(cmd[-1]).write_text("encoded")
        if progress_callback:
            # 时间超过总时长（ffmpeg 可能报出轻微超过 duration 的时间）
            progress_callback("frame=99999 fps=25 time=01:00:00.00 bitrate=5000kbits/s")
        return 0, ""

    monkeypatch.setattr(ffmpeg_mod, "run_ffmpeg", fake_run)

    strategy = Strategy.from_dict({
        "name": "test", "video": {"encoder": "libx265", "crf": 20, "preset": "slow"},
        "audio": {"mode": "keep_original"}, "subtitle": {"mode": "keep_all"},
        "filters": {},
    })
    snap = FileSnapshot(video_codec="h264", duration_seconds=10.0)

    task = EncodeTask(
        file_name="overflow.mkv",
        input_path=str(tmp_path / "overflow.mkv"),
        output_path=str(tmp_path / "overflow_SS.mkv"),
        strategy=strategy,
        snapshot=snap,
    )

    # 不设置 progress_callback — 仅验证内部 task.progress
    FFmpegExecutor(temp_dir=str(tmp_path / "temp")).encode(task)

    # 所有阶段完成后，总进度应为 1.0
    assert task.progress == pytest.approx(1.0)
    # 管线计划存在
    assert task.pipeline_plan is not None
    # transcode 阶段内部进度也应被 clamp 在 1.0
    for stage in task.pipeline_plan.stages:
        if stage.slot.slot_id == "transcode":
            assert stage.internal_progress <= 1.0
            break


# ============================================================
# H. Issue 3 修复验证：取消终止 ffmpeg 进程测试
# ============================================================

def test_cancel_terminates_running_process():
    """验证 run_ffmpeg 在 cancel_event 被设置时调用 proc.terminate()"""
    from unittest.mock import patch, MagicMock
    import threading
    from leanreel.executor.ffmpeg_builder import run_ffmpeg

    cancel_event = threading.Event()

    class StderrWithCancel:
        """可迭代 stderr 模拟：持续产出行，取消逻辑由 run_ffmpeg 循环体内的 cancel_event 检查处理"""
        def __init__(self):
            self._count = 0
        def __iter__(self):
            return self
        def __next__(self):
            import time
            time.sleep(0.01)
            self._count += 1
            return f"frame={self._count} time=00:00:04.00 bitrate=5000kbits/s\n"

    mock_proc = MagicMock()
    mock_proc.stderr = StderrWithCancel()
    mock_proc.wait.return_value = 0

    cmd = ["ffmpeg", "-i", "in.mkv", "-c:v", "libx265", "out.mkv"]

    with patch("leanreel.executor.ffmpeg_builder.subprocess.Popen",
               return_value=mock_proc) as mock_popen:
        def trigger_cancel():
            import time
            time.sleep(0.1)
            cancel_event.set()

        t = threading.Thread(target=trigger_cancel, daemon=True)
        t.start()
        run_ffmpeg(cmd, cancel_event=cancel_event)

    # Popen 参数验证
    mock_popen.assert_called_once()
    # terminate 必须被调用（因为 cancel_event 被设置）
    mock_proc.terminate.assert_called_once()


def test_ffmpeg_executor_cancel_sets_event():
    """验证 FFmpegExecutor.cancel() 设置内部 cancel_event"""
    executor = FFmpegExecutor()
    assert not executor._cancel_event.is_set()
    executor.cancel()
    assert executor._cancel_event.is_set()


# ============================================================
# I. Issue 4 修复验证：inject_rpu 失败时 dv_output 清理测试
# ============================================================

def test_encode_cleans_up_dv_output_on_inject_failure(monkeypatch, tmp_path):
    """验证 inject_rpu 失败时 dv_output 临时文件被清理，不泄漏在磁盘上"""
    from leanreel.executor import ffmpeg as ffmpeg_mod
    from leanreel.executor import dovi as dovi_mod
    from leanreel.executor.worker import EncodeTask

    def fake_run_ffmpeg(cmd, progress_callback=None, cancel_event=None):
        Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
        Path(cmd[-1]).write_text("encoded_data")
        return 0, ""

    def fake_extract(input_file, rpu_output):
        Path(rpu_output).write_text("rpu_data")
        return True

    def fake_inject(encoded, rpu, output):
        # 模拟 dovi_tool 部分写入输出文件后失败
        Path(output).write_text("partial_dv_data")
        return False

    monkeypatch.setattr(ffmpeg_mod, "run_ffmpeg", fake_run_ffmpeg)
    monkeypatch.setattr(dovi_mod.DoviTool, "extract_rpu", staticmethod(fake_extract))
    monkeypatch.setattr(dovi_mod.DoviTool, "inject_rpu", staticmethod(fake_inject))

    strategy = Strategy.from_dict({
        "name": "DV测试", "video": {"encoder": "libx265", "crf": 20, "preset": "slow"},
        "hdr": {"dv_handling": "reinject_rpu"},
        "audio": {"mode": "keep_original"},
        "subtitle": {"mode": "keep_chinese"},
        "filters": {},
    })
    snap = FileSnapshot(video_codec="h264", hdr_type=HDRType.DV_P7)

    temp_dir = tmp_path / "temp"
    task = EncodeTask(
        file_name="dv_fail.mkv",
        input_path=str(tmp_path / "dv_fail.mkv"),
        output_path=str(tmp_path / "dv_fail_SS.mkv"),
        strategy=strategy,
        snapshot=snap,
    )

    with pytest.raises(RuntimeError) as exc_info:
        FFmpegExecutor(temp_dir=str(temp_dir)).encode(task)

    assert "inject" in str(exc_info.value).lower()

    # dv_output 临时文件必须被清理
    dv_files = list(temp_dir.glob("*_dv.mkv"))
    assert len(dv_files) == 0, f"dv_output files leaked: {dv_files}"

    # RPU 临时文件也必须被清理（finally 块）
    rpu_files = list(temp_dir.glob("*.rpu"))
    assert len(rpu_files) == 0, f"rpu files leaked: {rpu_files}"

    # 编码输出临时文件也应被清理
    temp_outputs = list(temp_dir.glob("dv_fail_SS.mkv"))
    assert len(temp_outputs) == 0, f"temp output files leaked: {temp_outputs}"
