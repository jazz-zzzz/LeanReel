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

    def fake_run(cmd, progress_callback=None):
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

    monkeypatch.setattr(ffmpeg, "run_ffmpeg", lambda cmd, progress_callback=None: (1, "mock_error"))
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


def test_build_filters_by_preferred_languages():
    from leanreel.data.models import AudioTrack
    strategy = Strategy.from_dict({
        "name": "test", "audio": {"mode": "keep_original", "preferred_languages": ["chi", "zho", "eng"]},
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


def test_ffmpeg_executor_dovi_flow(monkeypatch, tmp_path):
    from leanreel.executor import ffmpeg as ffmpeg_mod
    from leanreel.executor.worker import EncodeTask
    from leanreel.executor import dovi as dovi_mod

    ffmpeg_calls = []
    dovi_extract_calls = []
    dovi_inject_calls = []

    def fake_run_ffmpeg(cmd, progress_callback=None):
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

    def fake_run_ffmpeg(cmd, progress_callback=None):
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
