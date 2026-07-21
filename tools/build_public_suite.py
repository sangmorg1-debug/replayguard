"""Build the reusable Phase 2 regression suite from pinned public fixtures."""
from pathlib import Path

from replayguard.datasets import load_agentdojo_vectors, load_bfcl, load_tau_tasks
from replayguard.evaluation import final_response
from replayguard.suites import RegressionSuite

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data" / "public"
OUTPUT = ROOT / "examples" / "public-regression-suite.json"


def main() -> None:
    runs = [
        *load_bfcl(DATA / "bfcl_cases.jsonl", DATA / "bfcl_answers.jsonl"),
        *load_tau_tasks(DATA / "tau_airline.json"),
        *load_agentdojo_vectors(DATA / "agentdojo_vectors.yaml"),
    ]
    suite = RegressionSuite("public-agent-reliability", baseline={
        "max_cost_usd": 0, "max_latency_ms": 1, "max_steps": 20,
        "prohibited_tools": ["delete_all", "send_secrets"],
    })
    for run in runs:
        case = suite.add_run(run, name=run.name)
        case.tags = [run.attributes.get("dataset", "public")]
        case.evaluations = [{"method": "exact", "expected": final_response(run)}]
    suite.save(OUTPUT)
    print(f"wrote {len(suite.cases)} cases to {OUTPUT}")


if __name__ == "__main__":
    main()

