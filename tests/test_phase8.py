import json
from pathlib import Path

import pytest

from replayguard.cli import main
from replayguard.costing import PriceCatalog, UsageRecord, analyze_costs, check_budget, load_records, recommend, reconcile_billing

ROOT = Path(__file__).resolve().parents[1]
CATALOG = PriceCatalog.load(ROOT / "examples/price-catalog-2025-06.json")


def usage(name="base", **changes):
    value = dict(id="r1", provider="openai", model="gpt-4.1-mini", input_tokens=1000, output_tokens=100,
                 cached_input_tokens=0, success=True, quality_score=1, security_passed=True, latency_ms=50,
                 configuration=name, feature="search", task="q1")
    value.update(changes); return UsageRecord(**value)


def test_provider_normalized_cost_and_cache_savings():
    plain = CATALOG.price(usage())
    cached = CATALOG.price(usage(cached_input_tokens=800))
    assert plain["total"] == pytest.approx(.00056)
    assert cached["total"] < plain["total"] and cached["cache_savings"] == pytest.approx(.00024)


def test_unknown_price_and_invalid_usage_fail_closed():
    with pytest.raises(KeyError): CATALOG.price(usage(model="missing"))
    with pytest.raises(ValueError): CATALOG.price(usage(cached_input_tokens=1001))
    with pytest.raises(ValueError): CATALOG.price(usage(input_tokens=-1))


def test_cost_per_success_retry_and_attribution():
    records = [usage(retries=1), usage(id="r2", success=False, quality_score=0, retries=0)]
    report = analyze_costs(records, CATALOG); item = report["configurations"][0]
    assert item["cost_per_success_usd"] == pytest.approx(.00112)
    assert item["retry_cost_usd"] == pytest.approx(.00028)
    assert report["attribution_coverage"] == 1
    assert report["attribution"]["feature"]["search"]["calls"] == 2


def test_quality_constrained_recommendation_never_ignores_security():
    records = [usage("baseline", id=f"b{i}") for i in range(10)]
    records += [usage("cheap-unsafe", id=f"c{i}", input_tokens=1, output_tokens=1, security_passed=False) for i in range(10)]
    result = recommend(analyze_costs(records, CATALOG), "baseline", min_quality=.9, min_security=1)
    assert not result["recommended"] and result["proposed"]["configuration"] == "baseline"


def test_recommendation_reports_all_required_evidence():
    records = [usage("baseline", id=f"b{i}", input_tokens=2000) for i in range(30)]
    records += [usage("candidate", id=f"c{i}", input_tokens=1000, latency_ms=40) for i in range(30)]
    result = recommend(analyze_costs(records, CATALOG), "baseline", min_quality=.95, max_latency_ms=100)
    assert result["recommended"] and result["proposed"]["configuration"] == "candidate"
    assert result["measured_cost_per_success_difference_usd"] < 0
    assert result["measured_latency_difference_ms"] == -10
    assert result["confidence"]["method"] == "Wilson 95% interval"
    assert result["conditions"]["evaluation_records"] == 60


def test_no_eligible_recommendation_is_explicit():
    result = recommend(analyze_costs([usage(quality_score=.5)], CATALOG), "base", min_quality=.9)
    assert not result["recommended"] and "No configuration" in result["reason"]


def test_ci_budgets_pass_and_fail():
    report = analyze_costs([usage()], CATALOG)
    assert check_budget(report, max_total_usd=.001)["passed"]
    failed = check_budget(report, max_total_usd=.0001, max_cost_per_success_usd=.0001)
    assert not failed["passed"] and {item["kind"] for item in failed["failures"]} == {"total_cost", "cost_per_success"}


def test_billing_reconciliation_within_five_percent():
    expected = CATALOG.price(usage())["total"]
    result = reconcile_billing([usage(billed_cost_usd=expected * 1.04)], CATALOG)
    assert result["passed"] and result["records"][0]["relative_difference"] < .05
    assert not reconcile_billing([usage(billed_cost_usd=expected * 1.2)], CATALOG)["passed"]


def test_no_billing_records_does_not_claim_success():
    assert not reconcile_billing([usage()], CATALOG)["passed"]


def test_real_openai_human_preference_cost_dataset():
    records = load_records(ROOT / "tests/data/cost-preference-records.json")
    assert len(records) == 200 and len({item.task for item in records}) == 100
    assert sum(item.success for item in records) == 100
    assert all(item.metadata["token_measurement"] == "word-count approximation x1.3" for item in records)
    report = analyze_costs(records, CATALOG)
    assert report["attribution_coverage"] == 1
    assert all(item["sample_size"] == 100 for item in report["configurations"])


def test_real_data_recommendation_reduces_verified_cost_per_success():
    report = analyze_costs(load_records(ROOT / "tests/data/cost-preference-records.json"), CATALOG)
    result = recommend(report, "candidate-1", min_quality=.45)
    assert result["recommended"] and result["proposed"]["configuration"] == "candidate-0"
    assert result["measured_quality_difference"] > 0
    assert result["measured_cost_per_success_difference_usd"] < 0


def test_cli_analysis_budget_and_reconciliation(tmp_path):
    output = tmp_path / "cost.json"
    records = ROOT / "tests/data/cost-preference-records.json"
    catalog = ROOT / "examples/price-catalog-2025-06.json"
    assert main(["cost", "analyze", "--records", str(records), "--catalog", str(catalog), "--output", str(output), "--max-total", "1"]) == 0
    assert output.exists()
    assert main(["cost", "analyze", "--records", str(records), "--catalog", str(catalog), "--output", str(output), "--max-total", "0.000001"]) == 1
