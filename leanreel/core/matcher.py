"""策略匹配器 — 根据文件元数据自动匹配最佳压缩策略"""
from leanreel.data.models import FileSnapshot, HDRType
from leanreel.core.strategy import Strategy


class Matcher:
    """策略匹配器"""

    def __init__(self, strategies: list[Strategy]):
        self.strategies = strategies

    def match(self, snapshot: FileSnapshot) -> Strategy:
        """为给定文件匹配最佳策略"""
        for strategy in self.strategies:
            if self._check_filters(snapshot, strategy):
                return strategy
        # 兜底：返回第一条策略（通常是最保守的）
        if self.strategies:
            return self.strategies[0]
        raise ValueError("没有可用策略")

    def _check_filters(self, snap: FileSnapshot, strategy: Strategy) -> bool:
        f = strategy.filters
        if f.skip_x265 and snap.video_codec in ("hevc", "h265"):
            return False
        if f.only_remux:
            # REMUX 判定：文件大 + 编码为 h264/mpeg2/vc1
            is_remux = (snap.video_codec in ("h264", "mpeg2video", "vc1")
                        and snap.size_bytes > 20_000_000_000)
            return is_remux
        if f.min_size_gb is not None:
            min_bytes = int(f.min_size_gb * 1e9)
            if snap.size_bytes < min_bytes:
                return False
        return True


def estimate_savings(snapshot: FileSnapshot, strategy: Strategy) -> dict:
    """基于 NVENC CQ 值、分辨率和位深科学估算压缩后体积。

    模型：
      base = 0.65 * exp(-0.08 * (CQ - 14))           ← CQ 指数衰减
      adj_res = 0.85 (4K) / 1.0 (1080p) / 1.15 (<1080p)
      adj_hdr = 1.08 (10-bit) / 1.0 (8-bit)
      ratio = clamp(base * adj_res * adj_hdr, 0.08, 0.70)
    """
    import math
    cq = getattr(getattr(strategy, "video", None), "cq", 23) or 23
    encoder = getattr(getattr(strategy, "video", None), "encoder", "") or ""

    # copy 模式几乎无节省
    if encoder == "copy":
        base = 0.95
    else:
        base = 0.65 * math.exp(-0.08 * (cq - 14))

    # 分辨率调整
    h = snapshot.video_height or 1080
    if h >= 2160:
        adj_res = 0.85
    elif h >= 1080:
        adj_res = 1.0
    else:
        adj_res = 1.15

    # HDR/10-bit 调整
    pix_fmt = getattr(strategy, "video", None)
    pix_fmt_str = getattr(pix_fmt, "pix_fmt", "") if pix_fmt else ""
    is_10bit = "10" in pix_fmt_str
    adj_hdr = 1.08 if is_10bit else 1.0

    ratio = max(0.08, min(0.70, base * adj_res * adj_hdr))
    savings_lo = ratio * 0.85
    savings_hi = ratio * 1.20
    lo_pct = int((1 - savings_hi) * 100)
    hi_pct = int((1 - savings_lo) * 100)

    return {
        "percentage": f"{lo_pct}-{hi_pct}%",
        "estimated_min_bytes": int(snapshot.size_bytes * savings_lo),
        "estimated_max_bytes": int(snapshot.size_bytes * savings_hi),
    }
