"""Reproduce the Phase 8 real-preference cost-per-success benchmark."""
import json
from pathlib import Path

from replayguard.costing import PriceCatalog, analyze_costs, load_records, recommend

ROOT = Path(__file__).resolve().parents[1]


def main():
    records = load_records(ROOT / "tests/data/cost-preference-records.json")
    report = analyze_costs(records, PriceCatalog.load(ROOT / "examples/price-catalog-2025-06.json"))
    result = recommend(report, "candidate-1", min_quality=.45)
    before, after = result["baseline"]["cost_per_success_usd"], result["proposed"]["cost_per_success_usd"]
    print(json.dumps({"real_human_comparisons": len(records) // 2, "attribution_coverage": report["attribution_coverage"],
                      "baseline_human_preference": result["baseline"]["quality_score"],
                      "proposed_human_preference": result["proposed"]["quality_score"],
                      "baseline_cost_per_success_usd": before, "proposed_cost_per_success_usd": after,
                      "estimated_cost_per_success_reduction": (before - after) / before,
                      "catalog_version": report["catalog"]["version"], "token_measurement": "word-count approximation x1.3"}, indent=2))


if __name__ == "__main__": main()
