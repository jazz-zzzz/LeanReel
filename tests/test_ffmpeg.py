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
        return 0

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

    assert calls
    # I/O 分离：命令输出到临时目录
    assert str(temp_dir) in str(calls[0][-1])
    # 最终文件在目标路径
    assert (tmp_path / "sample.out.mkv").exists()


def test_ffmpeg_executor_raises_when_command_fails(monkeypatch, balanced_strategy, tmp_path):
    from leanreel.executor import ffmpeg
    from leanreel.executor.worker import EncodeTask

    monkeypatch.setattr(ffmpeg, "run_ffmpeg", lambda cmd, progress_callback=None: 1)
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
