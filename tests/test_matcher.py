"""策略匹配器测试"""
import pytest
from leanreel.core.strategy import Strategy, FilterRule
from leanreel.core.matcher import Matcher, estimate_savings
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
    matcher = Matcher([balanced, strip_only])
    snap = FileSnapshot(video_codec="hevc", size_bytes=50000000000)
    result = matcher.match(snap)
    # balanced has skip_x265=True, so it should not match. Only strip_only matches.
    assert result.name == "仅去冗余"

def test_match_x264_gets_balanced(balanced, strip_only):
    matcher = Matcher([balanced, strip_only])
    snap = FileSnapshot(video_codec="h264", size_bytes=50000000000)
    result = matcher.match(snap)
    assert result.name == "均衡压缩"

def test_match_remux(balanced):
    matcher = Matcher([balanced])
    snap = FileSnapshot(video_codec="h264", size_bytes=80000000000)
    result = matcher.match(snap)
    assert result.name == "均衡压缩"

def test_estimate_savings_bytes(balanced):
    snap = FileSnapshot(video_codec="h264", size_bytes=50000000000)
    savings = estimate_savings(snap, balanced)
    # 35-50% savings on 50GB = 17.5-25GB
    assert savings["estimated_min_bytes"] == int(50e9 * 0.35)
    assert savings["estimated_max_bytes"] == int(50e9 * 0.50)
    assert savings["percentage"] == "35-50%"


def test_match_only_remux_filter_matches_large_legacy_codec():
    """only_remux 策略匹配 >20GB 的 h264/mpeg2/vc1 文件"""
    remux_strategy = Strategy.from_dict({
        "name": "REMUX专用", "is_preset": True,
        "video": {"encoder": "copy"},
        "filters": {"only_remux": True},
        "audio": {"mode": "keep_original"},
        "subtitle": {"mode": "keep_all"},
    })
    fallback = Strategy.from_dict({
        "name": "兜底策略", "is_preset": True,
        "video": {"encoder": "libx265", "crf": 20},
        "filters": {},
        "audio": {"mode": "keep_original"},
        "subtitle": {"mode": "keep_chinese"},
    })
    matcher = Matcher([remux_strategy, fallback])

    # 大文件 + 旧编码 → 命中 remux
    large_h264 = FileSnapshot(video_codec="h264", size_bytes=30_000_000_000)
    assert matcher.match(large_h264).name == "REMUX专用"

    # 小文件 → 跳过 remux，命中兜底
    small_h264 = FileSnapshot(video_codec="h264", size_bytes=5_000_000_000)
    assert matcher.match(small_h264).name == "兜底策略"


def test_match_only_remux_skips_modern_codecs():
    """only_remux 跳过 hevc 文件，即使文件很大"""
    remux_strategy = Strategy.from_dict({
        "name": "REMUX专用", "is_preset": True,
        "video": {"encoder": "copy"},
        "filters": {"only_remux": True},
        "audio": {"mode": "keep_original"},
        "subtitle": {"mode": "keep_all"},
    })
    fallback = Strategy.from_dict({
        "name": "兜底策略", "is_preset": True,
        "video": {"encoder": "libx265", "crf": 20},
        "filters": {},
        "audio": {"mode": "keep_original"},
        "subtitle": {"mode": "keep_chinese"},
    })
    matcher = Matcher([remux_strategy, fallback])
    large_hevc = FileSnapshot(video_codec="hevc", size_bytes=50_000_000_000)
    assert matcher.match(large_hevc).name == "兜底策略"


def test_match_min_size_gb_filter():
    """min_size_gb 过滤小于阈值的文件"""
    big_only = Strategy.from_dict({
        "name": "大文件专用", "is_preset": True,
        "video": {"encoder": "libx265", "crf": 20},
        "filters": {"min_size_gb": 10},
        "audio": {"mode": "keep_original"},
        "subtitle": {"mode": "keep_chinese"},
    })
    fallback = Strategy.from_dict({
        "name": "兜底", "is_preset": True,
        "video": {"encoder": "copy"},
        "filters": {},
        "audio": {"mode": "keep_original"},
        "subtitle": {"mode": "keep_all"},
    })
    matcher = Matcher([big_only, fallback])

    big = FileSnapshot(video_codec="h264", size_bytes=15_000_000_000)  # 15GB > 10GB
    assert matcher.match(big).name == "大文件专用"

    small = FileSnapshot(video_codec="h264", size_bytes=5_000_000_000)  # 5GB < 10GB
    assert matcher.match(small).name == "兜底"


def test_match_returns_first_strategy_when_none_match():
    """所有策略都不匹配时返回第一条（兜底）"""
    only_big = Strategy.from_dict({
        "name": "仅大文件", "is_preset": True,
        "video": {"encoder": "libx265", "crf": 20},
        "filters": {"min_size_gb": 100},
        "audio": {"mode": "keep_original"},
        "subtitle": {"mode": "keep_chinese"},
    })
    matcher = Matcher([only_big])
    tiny = FileSnapshot(video_codec="h264", size_bytes=1_000_000)
    assert matcher.match(tiny).name == "仅大文件"
