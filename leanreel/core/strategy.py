"""策略引擎 — JSON 驱动的压缩策略定义与加载"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import json
from pathlib import Path


@dataclass
class VideoRule:
    encoder: str = "libx265"
    crf: int = 20
    preset: str = "slow"
    pix_fmt: str = "yuv420p10le"

    def to_dict(self) -> dict:
        return {
            "encoder": self.encoder, "crf": self.crf,
            "preset": self.preset, "pix_fmt": self.pix_fmt
        }

    @classmethod
    def from_dict(cls, d: dict) -> "VideoRule":
        return cls(
            encoder=d.get("encoder", "libx265"),
            crf=d.get("crf", 20),
            preset=d.get("preset", "slow"),
            pix_fmt=d.get("pix_fmt", "yuv420p10le"),
        )


@dataclass
class HDRRule:
    mode: str = "preserve_hdr10"     # preserve_hdr10 | strip_hdr | pass_through
    dv_handling: str = "reinject_rpu" # reinject_rpu | degrade_to_hdr10 | pass_through

    def to_dict(self) -> dict:
        return {"mode": self.mode, "dv_handling": self.dv_handling}

    @classmethod
    def from_dict(cls, d: dict) -> "HDRRule":
        return cls(mode=d.get("mode", "preserve_hdr10"),
                   dv_handling=d.get("dv_handling", "reinject_rpu"))


@dataclass
class AudioRule:
    mode: str = "keep_original"       # keep_original | strip_commentary | strip_non_preferred
    preferred_languages: list[str] = field(default_factory=lambda: ["chi", "zho", "eng"])
    remove_commentary: bool = True

    def to_dict(self) -> dict:
        return {"mode": self.mode, "remove_commentary": self.remove_commentary}

    @classmethod
    def from_dict(cls, d: dict) -> "AudioRule":
        return cls(
            mode=d.get("mode", "keep_original"),
            remove_commentary=d.get("remove_commentary", True),
        )


@dataclass
class SubtitleRule:
    mode: str = "keep_chinese"        # keep_chinese | keep_chinese_english | keep_all | remove_all

    def to_dict(self) -> dict:
        return {"mode": self.mode}

    @classmethod
    def from_dict(cls, d: dict) -> "SubtitleRule":
        return cls(mode=d.get("mode", "keep_chinese"))


@dataclass
class FilterRule:
    skip_x265: bool = False
    min_size_gb: Optional[float] = None
    only_remux: bool = False

    def to_dict(self) -> dict:
        return {"skip_x265": self.skip_x265, "min_size_gb": self.min_size_gb,
                "only_remux": self.only_remux}

    @classmethod
    def from_dict(cls, d: dict) -> "FilterRule":
        return cls(
            skip_x265=d.get("skip_x265", False),
            min_size_gb=d.get("min_size_gb"),
            only_remux=d.get("only_remux", False),
        )


@dataclass
class Strategy:
    name: str = ""
    description: str = ""
    is_preset: bool = False
    video: VideoRule = field(default_factory=VideoRule)
    hdr: HDRRule = field(default_factory=HDRRule)
    audio: AudioRule = field(default_factory=AudioRule)
    subtitle: SubtitleRule = field(default_factory=SubtitleRule)
    filters: FilterRule = field(default_factory=FilterRule)
    estimated_savings: str = ""
    quality_impact: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name, "description": self.description,
            "is_preset": self.is_preset,
            "video": self.video.to_dict(), "hdr": self.hdr.to_dict(),
            "audio": self.audio.to_dict(), "subtitle": self.subtitle.to_dict(),
            "filters": self.filters.to_dict(),
            "estimated_savings": self.estimated_savings,
            "quality_impact": self.quality_impact,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Strategy":
        return cls(
            name=d.get("name", ""), description=d.get("description", ""),
            is_preset=d.get("is_preset", False),
            video=VideoRule.from_dict(d.get("video", {})),
            hdr=HDRRule.from_dict(d.get("hdr", {})),
            audio=AudioRule.from_dict(d.get("audio", {})),
            subtitle=SubtitleRule.from_dict(d.get("subtitle", {})),
            filters=FilterRule.from_dict(d.get("filters", {})),
            estimated_savings=d.get("estimated_savings", ""),
            quality_impact=d.get("quality_impact", ""),
        )


def load_strategies(directory: str) -> list[Strategy]:
    """从目录加载所有 JSON 策略文件"""
    strategies = []
    d = Path(directory)
    if not d.exists():
        return strategies
    for f in sorted(d.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        strategies.append(Strategy.from_dict(data))
    return strategies


def get_presets(strategies: list[Strategy]) -> list[Strategy]:
    """筛选出预设策略"""
    return [s for s in strategies if s.is_preset]
