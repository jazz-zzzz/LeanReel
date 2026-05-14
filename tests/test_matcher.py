"""策略匹配器测试"""
import pytest
from leanreel.core.strategy import Strategy, FilterRule
from leanreel.core.matcher import Matcher, match_strategy, estimate_savings
from leanreel.data.models import FileSnapshot, HDRType

@pytest.fixture
def balanced():
    data = {
        "name": "均衡压缩", "is_preset": True,
        "video": {"encoder": "libx265", "crf": 20},
        "hdr": {"mode": "preserve_hdr10", "dv_handling": "reinject_rpu"},
        "audio": {"mode": "keep_original"},
        "subtitle": {"mode": "keep_chinese"},
        "filters": {"skip_x265": True},
        "estimated_savings": "35-50%",
    }
    return Strategy.from_dict(data)

@pytest.fixture
def strip_only():
    data = {
        "name": "仅去冗余", "is_preset": True,
        "video": {"encoder": "copy", "crf": 0},
        "hdr": {"mode": "pass_through", "dv_handling": "pass_through"},
        "audio": {"mode": "keep_original"},
        "subtitle": {"mode": "remove_all"},
        "filters": {},
        "estimated_savings": "5-15%",
    }
    return Strategy.from_dict(data)

def test_match_skips_x265(balanced, strip_only):
    snap = FileSnapshot(video_codec="hevc", size_bytes=50000000000)
    result = match_strategy(snap, [balanced, strip_only])
    # balanced has skip_x265=True, so it should not match. Only strip_only matches.
    assert result.name == "仅去冗余"

def test_match_x264_gets_balanced(balanced, strip_only):
    snap = FileSnapshot(video_codec="h264", size_bytes=50000000000)
    result = match_strategy(snap, [balanced, strip_only])
    assert result.name == "均衡压缩"

def test_match_remux(balanced):
    snap = FileSnapshot(video_codec="h264", size_bytes=80000000000)
    result = match_strategy(snap, [balanced])
    assert result.name == "均衡压缩"

def test_estimate_savings_bytes(balanced):
    snap = FileSnapshot(video_codec="h264", size_bytes=50000000000)
    savings = estimate_savings(snap, balanced)
    # 35-50% savings on 50GB = 17.5-25GB
    assert savings["estimated_min_bytes"] == int(50e9 * 0.35)
    assert savings["estimated_max_bytes"] == int(50e9 * 0.50)
    assert savings["percentage"] == "35-50%"
