"""策略引擎测试"""
import json
from pathlib import Path
from leanreel.core.strategy import Strategy, load_strategies

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
    from leanreel.core.strategy import get_presets
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
