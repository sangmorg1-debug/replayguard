"""Reproducible Phase 6 latency and policy benchmark."""
import json
import tempfile
from pathlib import Path

from replayguard.gateway import ActionRequest, PolicySet, RuntimeGateway

ROOT = Path(__file__).resolve().parents[1]


def request(path="README.md"):
    return ActionRequest("benchmark-user", "benchmark-agent", "filesystem.read_file", "read", {"path": path},
                         risk="low", environment="development",
                         annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False})


def main():
    with tempfile.TemporaryDirectory(prefix="replayguard-gateway-") as temp:
        gateway = RuntimeGateway(PolicySet.load(ROOT / "examples/gateway-policy.json"), Path(temp) / "gateway.sqlite3")
        legitimate = [request() for _ in range(100)]
        malicious = [request("../../etc/passwd") for _ in range(100)]
        allowed_results = [gateway.authorize(item) for item in legitimate]
        blocked_results = [gateway.authorize(item) for item in malicious]
        latencies = sorted(item.latency_ms for item in allowed_results + blocked_results)
        print(json.dumps({"legitimate_allowed": sum(item.allowed for item in allowed_results),
                          "malicious_blocked": sum(not item.allowed for item in blocked_results),
                          "p95_latency_ms": latencies[int(len(latencies) * .95) - 1],
                          "audit_chain_valid": gateway.verify_audit_chain()}, indent=2))


if __name__ == "__main__": main()

