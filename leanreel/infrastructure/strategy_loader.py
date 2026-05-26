"""策略加载器 — 从 JSON 文件加载策略定义"""
import json
from pathlib import Path
from leanreel.domain.models import Strategy


def load_strategies(directory: str) -> list[Strategy]:
    """从目录加载所有 JSON 策略文件（损坏文件自动跳过）"""
    strategies = []
    seen_names = set()
    d = Path(directory)
    if not d.exists():
        return strategies
    for f in sorted(d.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            strategy = Strategy.from_dict(data)
            if strategy.name in seen_names:
                continue
            seen_names.add(strategy.name)
            strategies.append(strategy)
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            import sys
            print(f"警告：跳过损坏的策略文件 {f.name}: {e}", file=sys.stderr)
    return strategies


def get_presets(strategies: list[Strategy]) -> list[Strategy]:
    """筛选出预设策略"""
    return [s for s in strategies if s.is_preset]
