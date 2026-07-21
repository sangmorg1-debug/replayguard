"""Run transparent heuristic judges against real OpenAI human comparison labels."""
from pathlib import Path

from replayguard.datasets import load_openai_preferences
from replayguard.schema import EventKind

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data" / "public" / "openai_human_preferences.jsonl"


def main() -> None:
    runs = list(load_openai_preferences(DATA))
    heuristics = {
        "shorter_summary": lambda texts: min(range(2), key=lambda i: len(texts[i].split())),
        "longer_summary": lambda texts: max(range(2), key=lambda i: len(texts[i].split())),
        "candidate_zero": lambda texts: 0,
    }
    print(f"real_human_labels={len(runs)}")
    for name, judge in heuristics.items():
        agreements = 0
        for run in runs:
            texts = [event.response for event in run.events if event.kind == EventKind.ARTIFACT]
            agreements += judge(texts) == run.attributes["human_choice"]
        print(f"{name}_agreement={agreements / len(runs):.3f}")


if __name__ == "__main__":
    main()
