from __future__ import annotations

import math
import statistics
from collections import Counter
from dataclasses import asdict, dataclass

from .schema import EventKind, Run


@dataclass
class FlakinessReport:
    runs: int
    pass_rate: float
    response_variants: int
    tool_sequence_variants: int
    cost_mean: float
    cost_stdev: float
    latency_mean_ms: float
    latency_stdev_ms: float
    confidence_interval_95: tuple[float, float]
    minimum_runs_for_margin_10pct: int

    def to_dict(self):
        return asdict(self)


def analyze_flakiness(runs: list[Run]) -> FlakinessReport:
    if not runs:
        raise ValueError("at least one run is required")
    passed = [run.status == "ok" and not any(event.error for event in run.events) for run in runs]
    rate = sum(passed) / len(passed)
    z = 1.96
    denominator = 1 + z * z / len(runs)
    center = (rate + z * z / (2 * len(runs))) / denominator
    margin = z * math.sqrt(rate * (1 - rate) / len(runs) + z * z / (4 * len(runs) ** 2)) / denominator
    costs = [sum(event.cost_usd or 0 for event in run.events) for run in runs]
    latencies = [sum(event.latency_ms or 0 for event in run.events) for run in runs]
    responses = {tuple(event.response_hash for event in run.events) for run in runs}
    tools = {tuple(event.name for event in run.events if event.kind == EventKind.TOOL) for run in runs}
    required = math.ceil(z * z * max(rate * (1 - rate), 0.01) / 0.1**2)
    return FlakinessReport(len(runs), rate, len(responses), len(tools), statistics.mean(costs),
                           statistics.stdev(costs) if len(costs) > 1 else 0,
                           statistics.mean(latencies), statistics.stdev(latencies) if len(latencies) > 1 else 0,
                           (max(0, center - margin), min(1, center + margin)), required)

