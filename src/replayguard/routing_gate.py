"""Conservative policy selection for diagnostic candidate routers."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    policy: str
    reason: str
    calibration_f1_delta: float
    calibration_precision_delta: float


def select_routing_policy(
    fallback: dict,
    challenger: dict,
    *,
    minimum_f1_gain: float = 0.01,
) -> RoutingDecision:
    """Admit a challenger only for a material F1 gain without precision loss."""
    f1_delta = float(challenger["f1"]) - float(fallback["f1"])
    precision_delta = float(challenger["precision"]) - float(fallback["precision"])
    if f1_delta >= minimum_f1_gain and precision_delta >= 0:
        return RoutingDecision("meta_ranker", "calibration gate passed", f1_delta, precision_delta)
    failures = []
    if f1_delta < minimum_f1_gain:
        failures.append(f"F1 gain {f1_delta:.4f} is below required {minimum_f1_gain:.4f}")
    if precision_delta < 0:
        failures.append(f"precision regressed by {-precision_delta:.4f}")
    return RoutingDecision("claim_graph", "; ".join(failures), f1_delta, precision_delta)
