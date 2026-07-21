"""Derive Phase 8 cost records from real OpenAI human-preference examples."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tests/data/public/openai_human_preferences.jsonl"
TARGET = ROOT / "tests/data/cost-preference-records.json"


def tokens(text):
    # Transparent approximation; production records should use provider usage fields.
    return max(1, round(len(text.split()) * 1.3))


def main():
    records = []
    for index, line in enumerate(SOURCE.open(encoding="utf-8")):
        item = json.loads(line)
        post = item["info"]["post"]
        for candidate, summary in enumerate(item["summaries"]):
            records.append({"id": f"{item['info']['id']}:{candidate}", "provider": "openai", "model": "gpt-4.1-mini",
                "input_tokens": tokens(post), "output_tokens": tokens(summary["text"]), "cached_input_tokens": 0,
                "success": candidate == item["choice"], "quality_score": float(candidate == item["choice"]),
                "latency_ms": 0, "configuration": f"candidate-{candidate}", "feature": "summarization",
                "task": f"{item['info']['id']}:comparison-{index}", "repository": "openai/summarize-from-feedback",
                "metadata": {"human_confidence": item.get("extra", {}).get("confidence"), "policy": summary.get("policy"), "token_measurement": "word-count approximation x1.3"}})
        if index == 99: break
    output = {"dataset": "openai/summarize-from-feedback human comparisons", "source": "https://github.com/openai/summarize-from-feedback",
              "license": "MIT", "records": records}
    TARGET.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(TARGET), "records": len(records), "tasks": len(records) // 2}, indent=2))


if __name__ == "__main__": main()
