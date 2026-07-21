"""Fetch checksum-pinned public benchmark subsets and create deterministic fixtures."""
from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "data" / "public"
SOURCES = {
    "bfcl_cases": {
        "project": "Berkeley Function Calling Leaderboard v4", "license": "Apache-2.0",
        "commit": "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8",
        "url": "https://raw.githubusercontent.com/ShishirPatil/gorilla/6ea57973c7a6097fd7c5915698c54c17c5b1b6c8/berkeley-function-call-leaderboard/bfcl_eval/data/BFCL_v4_live_simple.json",
        "sha256": "1af2ac87dca47556db7b7e37e51e28b459a38b594e3c7b3c792b4903598ca0c4", "format": "jsonl", "limit": 60,
    },
    "bfcl_answers": {
        "project": "Berkeley Function Calling Leaderboard v4", "license": "Apache-2.0",
        "commit": "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8",
        "url": "https://raw.githubusercontent.com/ShishirPatil/gorilla/6ea57973c7a6097fd7c5915698c54c17c5b1b6c8/berkeley-function-call-leaderboard/bfcl_eval/data/possible_answer/BFCL_v4_live_simple.json",
        "sha256": "fec9cfa9744a936f9126981e85a2023da1e63e273eafebc81923a1162fad70ce", "format": "jsonl", "limit": 60,
    },
    "tau_airline": {
        "project": "tau2-bench airline tasks", "license": "MIT",
        "commit": "cf71a8070269883e38a365ffa85f78f46844c1f4",
        "url": "https://raw.githubusercontent.com/sierra-research/tau2-bench/cf71a8070269883e38a365ffa85f78f46844c1f4/data/tau2/domains/airline/tasks.json",
        "sha256": "ccd8ba737b4cc371415af70151187788f728d6108d0916e73bb4317b40542052", "format": "json", "limit": 30,
    },
    "agentdojo_vectors": {
        "project": "AgentDojo workspace injection vectors", "license": "MIT",
        "commit": "089ed468cf3ed0322acc66b0211f26d9d90dbf60",
        "url": "https://raw.githubusercontent.com/ethz-spylab/agentdojo/089ed468cf3ed0322acc66b0211f26d9d90dbf60/src/agentdojo/data/suites/workspace/injection_vectors.yaml",
        "sha256": "3390ac3da090ea0fde5f50ef0a74bf260786b35ab6ff14d47a199ecb41a15489", "format": "yaml", "limit": None,
    },
    "openai_human_preferences": {
        "project": "OpenAI Learning to Summarize from Human Feedback", "license": "See upstream dataset terms",
        "commit": "public Azure dataset snapshot (2020-10-21)",
        "url": "https://openaipublic.blob.core.windows.net/summarize-from-feedback/dataset/comparisons/batch18.json",
        "sha256": "5008e223e287b4c38e434e270cf77301993adba70e1f87362f35fb928f83863a", "format": "jsonl", "limit": 100,
    },
    "tau_voice_trace_1": {
        "project": "tau2-bench recorded voice simulation", "license": "MIT",
        "commit": "cf71a8070269883e38a365ffa85f78f46844c1f4",
        "url": "https://raw.githubusercontent.com/sierra-research/tau2-bench/cf71a8070269883e38a365ffa85f78f46844c1f4/tests/test_voice/test_interaction_metrics/testdata/experiment/simulations/49b22f0c-4a56-41c5-922f-bc2a56e53a23.json",
        "sha256": "b93a43b9029c269219a08f2ff1de1afe7692998bf143c049a0adb4e56a5bfae0", "format": "json_object", "limit": None,
    },
    "tau_voice_trace_2": {
        "project": "tau2-bench recorded voice simulation", "license": "MIT",
        "commit": "cf71a8070269883e38a365ffa85f78f46844c1f4",
        "url": "https://raw.githubusercontent.com/sierra-research/tau2-bench/cf71a8070269883e38a365ffa85f78f46844c1f4/tests/test_voice/test_interaction_metrics/testdata/experiment/simulations/7c6a3e3e-ac3f-406f-aea9-8cacb0a2e680.json",
        "sha256": "110eb8d20658c59f3baabe8c6901e7fdbd66368fae17089437e4e94412e16ee4", "format": "json_object", "limit": None,
    },
    "tau_voice_trace_3": {
        "project": "tau2-bench recorded voice simulation", "license": "MIT",
        "commit": "cf71a8070269883e38a365ffa85f78f46844c1f4",
        "url": "https://raw.githubusercontent.com/sierra-research/tau2-bench/cf71a8070269883e38a365ffa85f78f46844c1f4/tests/test_voice/test_interaction_metrics/testdata/experiment/simulations/cd9c5ed2-9751-4c86-8dac-8a895a332e41.json",
        "sha256": "64ef7119d1b2191099d3c68d49edb446a4507cdc47b2553428577e0087cf26b8", "format": "json_object", "limit": None,
    },
}


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "ReplayGuard-real-data-tests/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def curate(raw: bytes, kind: str, limit: int | None) -> bytes:
    text = raw.decode("utf-8-sig")
    if kind == "jsonl":
        return ("\n".join(text.splitlines()[:limit]) + "\n").encode()
    if kind == "json":
        return (json.dumps(json.loads(text)[:limit], indent=2, ensure_ascii=False) + "\n").encode()
    return raw


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {"generated_by": "tools/fetch_real_data.py", "sources": {}}
    for name, metadata in SOURCES.items():
        raw = fetch(metadata["url"])
        digest = hashlib.sha256(raw).hexdigest()
        if metadata["sha256"] == "TO_BE_FILLED":
            raise RuntimeError(f"record verified checksum for {name}: {digest}")
        if digest != metadata["sha256"]:
            raise RuntimeError(f"checksum mismatch for {name}: {digest}")
        suffix = {"jsonl": ".jsonl", "json": ".json", "json_object": ".json", "yaml": ".yaml"}[metadata["format"]]
        content = curate(raw, metadata["format"], metadata["limit"])
        filename = f"{name}{suffix}"
        (OUT / filename).write_bytes(content)
        manifest["sources"][name] = {**metadata, "file": filename, "curated_sha256": hashlib.sha256(content).hexdigest()}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
