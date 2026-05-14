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
