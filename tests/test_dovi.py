"""dovi_tool 封装测试"""
import pytest
from pathlib import Path
import tempfile
from leanreel.executor.dovi import DoviTool, needs_dovi_processing
from leanreel.data.models import FileSnapshot, HDRType
from leanreel.core.strategy import Strategy

@pytest.fixture
def strategy_dv_reinject():
    data = {
        "name": "均衡压缩",
        "video": {"encoder": "libx265", "crf": 20},
        "hdr": {"mode": "preserve_hdr10", "dv_handling": "reinject_rpu"},
        "audio": {"mode": "keep_original"},
        "subtitle": {"mode": "keep_chinese"},
        "filters": {},
    }
    return Strategy.from_dict(data)

@pytest.fixture
def strategy_dv_degrade():
    data = {
        "name": "极限压缩",
        "video": {"encoder": "libx265", "crf": 22},
        "hdr": {"mode": "preserve_hdr10", "dv_handling": "degrade_to_hdr10"},
        "audio": {"mode": "keep_original"},
        "subtitle": {"mode": "keep_chinese"},
        "filters": {},
    }
    return Strategy.from_dict(data)

def test_needs_dovi_p7_reinject(strategy_dv_reinject):
    snap = FileSnapshot(video_codec="hevc", hdr_type=HDRType.DV_P7)
    assert needs_dovi_processing(snap, strategy_dv_reinject)

def test_needs_dovi_p7_degrade_skips_extract(strategy_dv_degrade):
    snap = FileSnapshot(video_codec="hevc", hdr_type=HDRType.DV_P7)
    # 降级模式不需要 dovi_tool
    assert not needs_dovi_processing(snap, strategy_dv_degrade)

def test_needs_dovi_p8(strategy_dv_reinject):
    snap = FileSnapshot(video_codec="hevc", hdr_type=HDRType.DV_P8)
    assert not needs_dovi_processing(snap, strategy_dv_reinject)

def test_needs_dovi_sdr(strategy_dv_reinject):
    snap = FileSnapshot(video_codec="h264", hdr_type=HDRType.SDR)
    assert not needs_dovi_processing(snap, strategy_dv_reinject)

def test_dovi_tool_build_extract_cmd():
    cmd = DoviTool.build_extract_command("input.mkv", "/tmp/rpu.bin")
    assert "extract-rpu" in cmd
    assert "input.mkv" in cmd
    assert "/tmp/rpu.bin" in cmd

def test_dovi_tool_build_inject_cmd():
    cmd = DoviTool.build_inject_command("encoded.hevc", "/tmp/rpu.bin", "output.hevc")
    assert "inject-rpu" in cmd
    assert "encoded.hevc" in cmd
    assert "output.hevc" in cmd


def test_extract_rpu_calls_subprocess_with_correct_args(monkeypatch):
    import subprocess
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    ok, stderr = DoviTool.extract_rpu("source.mkv", "/tmp/rpu.bin")
    assert ok is True
    assert stderr == ""
    assert len(calls) == 1
    assert "extract-rpu" in calls[0]
    assert "source.mkv" in calls[0]
    assert "/tmp/rpu.bin" in calls[0]
    assert calls[0][calls[0].index("-o") + 1] == "/tmp/rpu.bin"


def test_inject_rpu_calls_subprocess_with_correct_args(monkeypatch):
    import subprocess
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    ok, stderr = DoviTool.inject_rpu("encoded.hevc", "/tmp/rpu.bin", "output.mkv")
    assert ok is True
    assert stderr == ""
    assert len(calls) == 1
    assert "inject-rpu" in calls[0]
    assert "encoded.hevc" in calls[0]
    assert "--rpu-in" in calls[0]
    assert "/tmp/rpu.bin" in calls[0]
    assert calls[0][-1] == "output.mkv"


def test_extract_rpu_returns_false_on_nonzero_exit(monkeypatch):
    import subprocess

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stderr="extraction error")

    monkeypatch.setattr("subprocess.run", fake_run)
    ok, stderr = DoviTool.extract_rpu("source.mkv", "/tmp/rpu.bin")
    assert not ok
    assert "extraction error" in stderr


def test_inject_rpu_returns_false_on_nonzero_exit(monkeypatch):
    import subprocess

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stderr="injection error")

    monkeypatch.setattr("subprocess.run", fake_run)
    ok, stderr = DoviTool.inject_rpu("bad.hevc", "/tmp/rpu.bin", "out.mkv")
    assert not ok
    assert "injection error" in stderr


def test_extract_rpu_propagates_timeout(monkeypatch):
    import subprocess

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 120)

    monkeypatch.setattr("subprocess.run", fake_run)
    with pytest.raises(subprocess.TimeoutExpired):
        DoviTool.extract_rpu("source.mkv", "/tmp/rpu.bin")
