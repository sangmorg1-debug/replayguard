from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class UsageRecord:
    id: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    success: bool
    latency_ms: float
    cached_input_tokens: int = 0
    retries: int = 0
    quality_score: float | None = None
    security_passed: bool = True
    repository: str | None = None
    feature: str | None = None
    customer: str | None = None
    agent: str | None = None
    task: str | None = None
    configuration: str = "default"
    billed_cost_usd: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class PriceCatalog:
    def __init__(self, value: dict[str, Any]) -> None:
        self.value = value
        self.version = str(value["version"])
        self.effective_at = str(value["effective_at"])
        self.currency = value.get("currency", "USD")
        self.models = {(item["provider"], item["model"]): item for item in value["models"]}

    @classmethod
    def load(cls, path: str | Path) -> "PriceCatalog": return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def price(self, usage: UsageRecord) -> dict[str, float]:
        if usage.input_tokens < 0 or usage.output_tokens < 0 or usage.cached_input_tokens < 0:
            raise ValueError("token counts cannot be negative")
        if usage.cached_input_tokens > usage.input_tokens: raise ValueError("cached input exceeds total input")
        try: rate = self.models[(usage.provider, usage.model)]
        except KeyError as exc: raise KeyError(f"no price for {usage.provider}/{usage.model} in catalog {self.version}") from exc
        unit = float(rate.get("token_unit", 1_000_000))
        uncached = usage.input_tokens - usage.cached_input_tokens
        input_cost = uncached / unit * float(rate["input_usd"])
        cached_cost = usage.cached_input_tokens / unit * float(rate.get("cached_input_usd", rate["input_usd"]))
        output_cost = usage.output_tokens / unit * float(rate["output_usd"])
        request_cost = float(rate.get("request_usd", 0))
        full_input_cost = usage.input_tokens / unit * float(rate["input_usd"])
        total = input_cost + cached_cost + output_cost + request_cost
        return {"input": input_cost, "cached_input": cached_cost, "output": output_cost, "request": request_cost,
                "total": total, "cache_savings": max(0.0, full_input_cost - input_cost - cached_cost)}


def _wilson(successes: int, total: int) -> list[float]:
    if not total: return [0.0, 1.0]
    z = 1.96; p = successes / total; denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [max(0, center - margin), min(1, center + margin)]


def analyze_costs(records: list[UsageRecord], catalog: PriceCatalog) -> dict[str, Any]:
    groups: dict[str, list[tuple[UsageRecord, dict[str, float]]]] = {}
    dimensions = {name: {} for name in ("repository", "feature", "customer", "agent", "task")}
    attributed = 0
    for record in records:
        priced = catalog.price(record); groups.setdefault(record.configuration, []).append((record, priced))
        if record.feature or record.task: attributed += 1
        for name in dimensions:
            value = getattr(record, name) or "unattributed"
            bucket = dimensions[name].setdefault(value, {"calls": 0, "cost_usd": 0.0, "successes": 0})
            bucket["calls"] += 1; bucket["cost_usd"] += priced["total"]; bucket["successes"] += int(record.success)
    configurations = []
    for name, values in sorted(groups.items()):
        runs = [item[0] for item in values]; prices = [item[1] for item in values]
        successes = sum(item.success for item in runs); cost = sum(item["total"] for item in prices)
        configurations.append({"configuration": name, "provider": runs[0].provider, "model": runs[0].model,
            "sample_size": len(runs), "successes": successes, "success_rate": successes / len(runs),
            "success_confidence_95": _wilson(successes, len(runs)),
            "quality_score": sum(item.quality_score if item.quality_score is not None else float(item.success) for item in runs) / len(runs),
            "security_pass_rate": sum(item.security_passed for item in runs) / len(runs),
            "total_cost_usd": cost, "cost_per_success_usd": cost / successes if successes else None,
            "mean_latency_ms": sum(item.latency_ms for item in runs) / len(runs),
            "cache_savings_usd": sum(item["cache_savings"] for item in prices),
            "retry_calls": sum(item.retries for item in runs),
            "retry_cost_usd": sum(price["total"] * run.retries / (run.retries + 1) for run, price in values if run.retries > 0)})
    return {"schema_version": "1.0", "catalog": {"version": catalog.version, "effective_at": catalog.effective_at,
            "currency": catalog.currency}, "records": len(records), "attribution_coverage": attributed / len(records) if records else 0,
            "configurations": configurations, "attribution": dimensions}


def recommend(report: dict[str, Any], baseline: str, *, min_quality: float, min_security: float = 1.0,
              max_latency_ms: float | None = None) -> dict[str, Any]:
    configs = {item["configuration"]: item for item in report["configurations"]}
    if baseline not in configs: raise KeyError(f"unknown baseline configuration: {baseline}")
    original = configs[baseline]
    eligible = [item for item in configs.values() if item["quality_score"] >= min_quality and
                item["security_pass_rate"] >= min_security and (max_latency_ms is None or item["mean_latency_ms"] <= max_latency_ms) and
                item["cost_per_success_usd"] is not None]
    chosen = min(eligible, key=lambda item: item["cost_per_success_usd"]) if eligible else None
    conditions = {"minimum_quality": min_quality, "minimum_security_pass_rate": min_security, "maximum_latency_ms": max_latency_ms,
                  "catalog_version": report["catalog"]["version"], "evaluation_records": report["records"]}
    if not chosen:
        return {"recommended": False, "baseline": original, "reason": "No configuration satisfies every quality, security, and latency constraint.", "conditions": conditions}
    return {"recommended": chosen["configuration"] != baseline, "baseline": original, "proposed": chosen,
            "measured_quality_difference": chosen["quality_score"] - original["quality_score"],
            "measured_cost_per_success_difference_usd": chosen["cost_per_success_usd"] - original["cost_per_success_usd"],
            "measured_latency_difference_ms": chosen["mean_latency_ms"] - original["mean_latency_ms"],
            "confidence": {"method": "Wilson 95% interval", "baseline": original["success_confidence_95"], "proposed": chosen["success_confidence_95"]},
            "conditions": conditions}


def check_budget(report: dict[str, Any], *, max_total_usd: float | None = None,
                 max_cost_per_success_usd: float | None = None) -> dict[str, Any]:
    failures = []
    total = sum(item["total_cost_usd"] for item in report["configurations"])
    if max_total_usd is not None and total > max_total_usd: failures.append({"kind": "total_cost", "actual": total, "limit": max_total_usd})
    if max_cost_per_success_usd is not None:
        for item in report["configurations"]:
            if item["cost_per_success_usd"] is None or item["cost_per_success_usd"] > max_cost_per_success_usd:
                failures.append({"kind": "cost_per_success", "configuration": item["configuration"], "actual": item["cost_per_success_usd"], "limit": max_cost_per_success_usd})
    return {"passed": not failures, "total_cost_usd": total, "failures": failures}


def reconcile_billing(records: list[UsageRecord], catalog: PriceCatalog, tolerance: float = .05) -> dict[str, Any]:
    checked = []
    for item in records:
        if item.billed_cost_usd is None: continue
        calculated = catalog.price(item)["total"]
        difference = abs(calculated - item.billed_cost_usd) / item.billed_cost_usd if item.billed_cost_usd else float(calculated != 0)
        checked.append({"id": item.id, "calculated_usd": calculated, "billed_usd": item.billed_cost_usd, "relative_difference": difference, "within_tolerance": difference <= tolerance})
    return {"tolerance": tolerance, "checked": len(checked), "passed": bool(checked) and all(item["within_tolerance"] for item in checked), "records": checked}


def load_records(path: str | Path) -> list[UsageRecord]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    return [UsageRecord(**item) for item in value.get("records", value)]
