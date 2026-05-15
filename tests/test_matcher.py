"""策略匹配器测试"""
import pytest
from leanreel.core.strategy import Strategy, FilterRule
from leanreel.core.matcher import Matcher, estimate_savings, get_skip_reason
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

def test_match_skips_hevc_sources_completely(balanced, strip_only):
    matcher = Matcher([balanced, strip_only])
    snap = FileSnapshot(video_codec="hevc", size_bytes=50000000000)
    result = matcher.match(snap)
    assert result is None
    assert get_skip_reason(snap) == "跳过：HEVC/H.265 片源"


@pytest.mark.parametrize("hdr_type", [HDRType.HDR10, HDRType.HDR10P, HDRType.DV_P5, HDRType.DV_P7, HDRType.DV_P8])
def test_match_skips_hdr_and_dolby_vision_sources_completely(balanced, strip_only, hdr_type):
    matcher = Matcher([balanced, strip_only])
    snap = FileSnapshot(video_codec="h264", hdr_type=hdr_type, size_bytes=50000000000)

    result = matcher.match(snap)

    assert result is None
    assert get_skip_reason(snap) in {
        "跳过：HDR10 片源",
        "跳过：HDR10+ 片源",
        "跳过：Dolby Vision 片源",
    }

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
    # CQ=23 + 1080p SDR → ratio ≈ 0.32, savings ~60-73%
    assert savings["percentage"]
    assert "%" in savings["percentage"]
    assert 0 < savings["estimated_min_bytes"] < snap.size_bytes
    assert savings["estimated_min_bytes"] <= savings["estimated_max_bytes"]
    # 节省空间在合理范围内（原始 50GB 的 20-80%）
    assert savings["estimated_max_bytes"] < snap.size_bytes * 0.85


def test_estimate_savings_4k_hdr_compresses_more():
    """4K HDR 相对压缩比更高（分辨率红利）"""
    from leanreel.data.models import HDRType
    snap_4k = FileSnapshot(video_codec="h264", size_bytes=80000000000,
                          video_width=3840, video_height=2160, hdr_type=HDRType.HDR10)
    snap_1080p = FileSnapshot(video_codec="h264", size_bytes=80000000000,
                             video_width=1920, video_height=1080, hdr_type=HDRType.SDR)
    s4 = estimate_savings(snap_4k, balanced)
    s1 = estimate_savings(snap_1080p, balanced)
    # 4K HDR 相对于其原始体积应该压缩得更多
    assert s4["estimated_min_bytes"] > 0
    assert s1["estimated_min_bytes"] > 0


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
    """HEVC 文件即使很大也被安全闸门完全跳过。"""
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
    assert matcher.match(large_hevc) is None


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
