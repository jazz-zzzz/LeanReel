"""FFmpeg 命令构建测试"""
import pytest
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
    assert "-c:v" in cmd and "libx265" in cmd
    assert "-crf" in cmd and "20" in cmd
    assert "-preset" in cmd and "slow" in cmd
    assert "input.mkv" in cmd
    assert "output.mkv" in cmd


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
        calls.append(cmd)
        return 0

    monkeypatch.setattr(ffmpeg, "run_ffmpeg", fake_run)
    task = EncodeTask(
        file_name="sample.mkv",
        input_path=str(tmp_path / "sample.mkv"),
        output_path=str(tmp_path / "sample.out.mkv"),
        strategy=balanced_strategy,
        snapshot=FileSnapshot(video_codec="h264"),
    )

    FFmpegExecutor().encode(task)

    assert calls
    assert calls[0][-1] == str(tmp_path / "sample.out.mkv")


def test_ffmpeg_executor_raises_when_command_fails(monkeypatch, balanced_strategy, tmp_path):
    from leanreel.executor import ffmpeg
    from leanreel.executor.worker import EncodeTask

    monkeypatch.setattr(ffmpeg, "run_ffmpeg", lambda cmd, progress_callback=None: 1)
    task = EncodeTask(
        file_name="sample.mkv",
        input_path=str(tmp_path / "sample.mkv"),
        output_path=str(tmp_path / "sample.out.mkv"),
        strategy=balanced_strategy,
        snapshot=FileSnapshot(video_codec="h264"),
    )

    with pytest.raises(RuntimeError):
        FFmpegExecutor().encode(task)
