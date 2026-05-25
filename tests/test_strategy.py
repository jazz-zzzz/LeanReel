"""策略引擎测试"""
import json
from pathlib import Path
from leanreel.domain.models import Strategy
from leanreel.infrastructure.strategy_loader import load_strategies

SAMPLE_STRATEGY_JSON = """
{
  "name": "均衡压缩",
  "description": "视觉无损，适合大多数场景",
  "is_preset": true,
  "video": {"encoder": "libx265", "crf": 20, "preset": "slow", "pix_fmt": "yuv420p10le"},
  "hdr": {"mode": "preserve_hdr10", "dv_handling": "reinject_rpu"},
  "audio": {"mode": "keep_original", "remove_commentary": true},
  "subtitle": {"mode": "keep_chinese"},
  "filters": {"skip_x265": true, "min_size_gb": null},
  "estimated_savings": "35-50%",
  "quality_impact": "视觉无损，HDR/DV完整保留"
}
"""

def test_strategy_from_json():
    data = json.loads(SAMPLE_STRATEGY_JSON)
    s = Strategy.from_dict(data)
    assert s.name == "均衡压缩"
    assert s.video.encoder == "libx265"
    assert s.video.crf == 20
    assert s.hdr.mode == "preserve_hdr10"
    assert s.hdr.dv_handling == "reinject_rpu"
    assert s.audio.mode == "keep_original"
    assert s.audio.remove_commentary is True
    assert s.subtitle.mode == "keep_chinese"
    assert s.filters.skip_x265 is True
    assert s.filters.min_size_gb is None

def test_strategy_serializes_to_dict():
    data = json.loads(SAMPLE_STRATEGY_JSON)
    s = Strategy.from_dict(data)
    out = s.to_dict()
    assert out["name"] == "均衡压缩"
    assert out["video"]["crf"] == 20


def test_audio_rule_preserves_preferred_languages():
    data = json.loads(SAMPLE_STRATEGY_JSON)
    data["audio"]["preferred_languages"] = ["jpn", "eng"]

    strategy = Strategy.from_dict(data)
    out = strategy.to_dict()

    assert strategy.audio.preferred_languages == ["jpn", "eng"]
    assert out["audio"]["preferred_languages"] == ["jpn", "eng"]

def test_load_strategies_from_dir(tmp_path: Path):
    d = tmp_path / "strategies"
    d.mkdir()
    (d / "balanced.json").write_text(SAMPLE_STRATEGY_JSON, encoding="utf-8")
    (d / "extreme.json").write_text(
        SAMPLE_STRATEGY_JSON.replace("均衡压缩", "极限压缩"), encoding="utf-8"
    )
    strategies = load_strategies(str(d))
    assert len(strategies) == 2
    names = {s.name for s in strategies}
    assert "均衡压缩" in names
    assert "极限压缩" in names

def test_get_presets():
    from leanreel.infrastructure.strategy_loader import get_presets
    data = json.loads(SAMPLE_STRATEGY_JSON)
    s1 = Strategy.from_dict(data)
    data2 = json.loads(SAMPLE_STRATEGY_JSON)
    data2["name"] = "自定义"
    data2["is_preset"] = False
    s2 = Strategy.from_dict(data2)
    presets = get_presets([s1, s2])
    assert len(presets) == 1
    assert presets[0].name == "均衡压缩"


def test_load_strategies_skips_corrupted_json(tmp_path: Path):
    d = tmp_path / "strategies"
    d.mkdir()
    (d / "valid.json").write_text(SAMPLE_STRATEGY_JSON, encoding="utf-8")
    (d / "broken.json").write_text("{not valid json}", encoding="utf-8")
    (d / "empty.json").write_text("", encoding="utf-8")
    (d / "also_valid.json").write_text(
        SAMPLE_STRATEGY_JSON.replace("均衡压缩", "极限压缩"), encoding="utf-8"
    )

    strategies = load_strategies(str(d))
    names = {s.name for s in strategies}
    assert "均衡压缩" in names
    assert "极限压缩" in names
    assert len(strategies) == 2  # 损坏文件被跳过


def test_builtin_presets_are_three_av1_cpu_tiers():
    """内置主预设只保留两个 AV1 档和一个 CPU 保画质档。"""
    strategy_dir = Path(__file__).resolve().parents[1] / "leanreel" / "resources" / "strategies"

    strategies = load_strategies(str(strategy_dir))

    assert [s.name for s in strategies] == [
        "AV1 NVENC CQ34 均衡快速",
        "AV1 NVENC CQ32 保画质",
        "CPU x265 CRF18 慢速保画质",
    ]
    assert all(s.is_preset for s in strategies)

    av1_balanced, av1_quality, cpu_quality = strategies
    assert av1_balanced.video.encoder == "av1_nvenc"
    assert av1_balanced.video.gpu is True
    assert av1_balanced.video.rc == "vbr"
    assert av1_balanced.video.cq == 34
    assert av1_balanced.video.nv_preset == "p5"

    assert av1_quality.video.encoder == "av1_nvenc"
    assert av1_quality.video.gpu is True
    assert av1_quality.video.rc == "vbr"
    assert av1_quality.video.cq == 32
    assert av1_quality.video.nv_preset == "p6"

    assert cpu_quality.video.encoder == "libx265"
    assert cpu_quality.video.crf == 18
    assert cpu_quality.video.preset == "slow"
    assert cpu_quality.video.pix_fmt == "yuv420p10le"
    assert all("用户 PDF" not in s.description for s in strategies)
    assert all("PDF" not in s.description for s in strategies)


# ──────────────────────────────────────────
# VideoRule.is_gpu 测试
# ──────────────────────────────────────────

def test_video_rule_is_gpu_true_for_nvenc_encoder():
    """NVENC 编码器名自动标记 is_gpu=True"""
    from leanreel.domain.models import VideoRule

    rule = VideoRule(encoder="hevc_nvenc")
    assert rule.is_gpu is True


def test_video_rule_is_gpu_true_for_h264_nvenc_encoder():
    """h264_nvenc 编码器名自动标记 is_gpu=True"""
    from leanreel.domain.models import VideoRule

    rule = VideoRule(encoder="h264_nvenc")
    assert rule.is_gpu is True


def test_video_rule_is_gpu_true_for_av1_nvenc_encoder():
    """av1_nvenc 编码器名自动标记 is_gpu=True"""
    from leanreel.domain.models import VideoRule

    rule = VideoRule(encoder="av1_nvenc")
    assert rule.is_gpu is True


def test_video_rule_is_gpu_true_for_gpu_flag():
    """CPU 编码器 + gpu=True → is_gpu=True"""
    from leanreel.domain.models import VideoRule

    rule = VideoRule(encoder="libx265", gpu=True)
    assert rule.is_gpu is True


def test_video_rule_is_gpu_false_for_cpu_encoder():
    """CPU 编码器 + gpu=False → is_gpu=False"""
    from leanreel.domain.models import VideoRule

    rule = VideoRule(encoder="libx265", gpu=False)
    assert rule.is_gpu is False


def test_video_rule_is_gpu_false_for_default():
    """默认 VideoRule() 使用 libx265 + gpu=False → is_gpu=False"""
    from leanreel.domain.models import VideoRule

    rule = VideoRule()
    assert rule.is_gpu is False


def test_video_rule_is_gpu_false_for_h264_cpu():
    """libx264 CPU 编码器 → is_gpu=False"""
    from leanreel.domain.models import VideoRule

    rule = VideoRule(encoder="libx264")
    assert rule.is_gpu is False
