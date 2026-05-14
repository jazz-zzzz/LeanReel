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
    """估算压缩节省空间"""
    savings_str = strategy.estimated_savings
    try:
        parts = savings_str.replace("%", "").split("-")
        lo = float(parts[0]) / 100
        hi = float(parts[1]) / 100 if len(parts) > 1 else lo
    except (ValueError, IndexError):
        lo, hi = 0.1, 0.3

    return {
        "percentage": savings_str,
        "estimated_min_bytes": int(snapshot.size_bytes * lo),
        "estimated_max_bytes": int(snapshot.size_bytes * hi),
    }
