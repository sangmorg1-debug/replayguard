from __future__ import annotations

import json
import sqlite3
import statistics
import time
from pathlib import Path

from replayguard.cli import main
from replayguard.gateway import ActionRequest, PolicySet, RuntimeGateway

ROOT = Path(__file__).parents[1]


def policy(tmp_path, **overrides):
    value = json.loads((ROOT / "examples/gateway-policy.json").read_text())
    value.update(overrides)
    return PolicySet(value)


def gateway(tmp_path, **overrides): return RuntimeGateway(policy(tmp_path, **overrides), tmp_path / "gateway.sqlite3", b"approval-test-secret")


def read_request(**changes):
    value = dict(user_id="user", agent_id="agent", tool="filesystem.read_file", action="read",
                 arguments={"path": "README.md"}, risk="low", environment="development",
                 annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False})
    value.update(changes); return ActionRequest(**value)


def test_known_read_is_allowed_and_path_is_constrained(tmp_path):
    decision = gateway(tmp_path).authorize(read_request())
    assert decision.allowed and decision.outcome == "rewrite"
    assert Path(decision.arguments["path"]).is_absolute()
    assert "project-read" in decision.explanation


def test_secrets_shell_paths_network_recipient_and_amount_are_denied(tmp_path):
    engine = gateway(tmp_path)
    requests = [
        read_request(tool="http.fetch", action="get", arguments={"url":"https://api.example.com", "token":"sk-abcdefghijklmnop"}, annotations={"readOnlyHint":True,"destructiveHint":False,"openWorldHint":True}),
        read_request(tool="shell", action="execute", arguments={"command":"rm -rf /"}, idempotency_key="x"),
        read_request(arguments={"path":"../outside/secret.txt"}),
        read_request(tool="http.fetch", action="get", arguments={"url":"http://127.0.0.1/private"}),
        read_request(tool="email.send", action="send", arguments={"recipient":"attacker@example.com"}, user_intent={"recipients":["friend@example.com"]}, idempotency_key="x"),
        read_request(tool="payment", action="pay", arguments={"amount_usd":101}, idempotency_key="x"),
    ]
    decisions = [engine.authorize(item) for item in requests]
    assert all(not item.allowed for item in decisions)
    assert {item.reason for item in decisions} >= {"secret-exfiltration","unsafe-shell","path-boundary","network-boundary","recipient-boundary","transaction-limit"}
    assert "sk-abcdefghijklmnop" not in json.dumps(decisions[0].to_dict())
    assert b"sk-abcdefghijklmnop" not in (tmp_path / "gateway.sqlite3").read_bytes()


def test_confirmation_one_time_approval_and_replay_prevention(tmp_path):
    engine = gateway(tmp_path)
    request = read_request(tool="custom.delete", action="delete", arguments={}, risk="high", idempotency_key="once",
                           annotations={"destructiveHint":True,"openWorldHint":False})
    first = engine.authorize(request)
    assert first.outcome == "require_confirmation" and not first.allowed
    token = engine.issue_approval(first.id)
    approved = engine.authorize(request, token)
    assert approved.allowed and approved.rule_id == "approved"
    replayed = engine.authorize(request, token)
    assert not replayed.allowed and replayed.outcome == "require_confirmation"


def test_limits_revocation_and_fail_closed(tmp_path, monkeypatch):
    engine = gateway(tmp_path, limits={"max_retries":1,"max_recursion":1,"max_cost_usd":.1,"calls_per_minute":0})
    assert engine.authorize(read_request(retry_count=2)).outcome == "rate_limit"
    assert engine.authorize(read_request(recursion_depth=2)).reason == "recursion-limit"
    assert engine.authorize(read_request(cost_usd=.2)).reason == "cost-limit"
    engine.revoke("agent", "agent")
    assert engine.authorize(read_request()).reason == "emergency-revocation"
    engine.unrevoke("agent", "agent")
    monkeypatch.setattr(engine, "_evaluate", lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))
    assert engine.authorize(read_request()).reason == "gateway_error"


def test_rate_limit_and_complete_human_readable_audit(tmp_path):
    engine = gateway(tmp_path, limits={"calls_per_minute":2,"max_retries":3,"max_recursion":5,"max_cost_usd":1})
    assert engine.authorize(read_request()).allowed
    assert engine.authorize(read_request()).allowed
    third = engine.authorize(read_request())
    assert third.outcome == "rate_limit" and "rate limit" in third.explanation.lower()
    assert len(engine.decisions()) == 3 and engine.verify_audit_chain()
    with sqlite3.connect(tmp_path / "gateway.sqlite3") as db:
        db.execute("UPDATE decisions SET outcome='allow' WHERE id=?", (third.id,))
    assert not engine.verify_audit_chain()


def test_call_never_executes_denied_and_routes_sandbox(tmp_path):
    engine = gateway(tmp_path)
    calls = []
    denied, value = engine.call(read_request(tool="database", action="write", arguments={}, idempotency_key="x"), lambda **kw: calls.append(kw))
    assert not denied.allowed and value is None and calls == []
    request = read_request(tool="code.execute", action="run", arguments={"source":"print(1)"}, idempotency_key="x",
                           annotations={"destructiveHint":True,"openWorldHint":False})
    decision, value = engine.call(request, lambda **kw: "HOST", sandbox_adapter=lambda **kw: "SANDBOX")
    assert decision.outcome == "sandbox" and value == "SANDBOX"


def test_unrecognized_match_key_is_rejected_not_silently_ignored():
    """A typo'd condition key (e.g. "enviroment") must not silently widen a rule to match
    regardless of that condition - it must fail to load instead."""
    try:
        PolicySet({"version": "1", "rules": [
            {"id": "typo", "match": {"enviroment": "development"}, "effect": "allow"}]})
        assert False, "expected PolicySet to reject an unrecognized match key"
    except ValueError as exc:
        assert "enviroment" in str(exc)


def test_policy_version_save_activate_and_rollback(tmp_path):
    root = tmp_path / "policies"
    first = PolicySet({"version":"1","rules":[]}); first.save_versioned(root)
    second = PolicySet({"version":"2","rules":[]}); second.save_versioned(root)
    assert PolicySet.active(root).version == "2"
    PolicySet.rollback(root, "1")
    assert PolicySet.active(root).version == "1"


def test_controlled_benchmark_blocks_malicious_and_allows_legitimate(tmp_path):
    engine = gateway(tmp_path)
    malicious = []
    for index in range(100):
        kind = index % 5
        if kind == 0: malicious.append(read_request(tool="shell", action="execute", arguments={"command":"rm -rf /"}, idempotency_key=str(index)))
        elif kind == 1: malicious.append(read_request(arguments={"path":"../../etc/passwd"}))
        elif kind == 2: malicious.append(read_request(tool="http.fetch", action="get", arguments={"url":"http://169.254.169.254/latest"}))
        elif kind == 3: malicious.append(read_request(tool="email.send", action="send", arguments={"recipient":"evil@example.com"}, user_intent={"recipients":["ok@example.com"]}, idempotency_key=str(index)))
        else: malicious.append(read_request(tool="http.fetch", action="get", arguments={"url":"https://api.example.com","token":"sk-abcdefghijklmnop"}, annotations={"readOnlyHint":True,"destructiveHint":False,"openWorldHint":True}))
    legitimate = [read_request(arguments={"path": "README.md"}) for _ in range(100)]
    blocked = sum(not engine.authorize(item).allowed for item in malicious)
    allowed = sum(engine.authorize(item).allowed for item in legitimate)
    assert blocked >= 95 and allowed >= 95


def test_policy_latency_p95_below_100ms(tmp_path):
    engine = gateway(tmp_path)
    latencies = [engine.authorize(read_request()).latency_ms for _ in range(200)]
    p95 = sorted(latencies)[int(len(latencies) * .95) - 1]
    assert p95 < 100


def test_concurrent_approval_consumption_only_succeeds_once(tmp_path):
    """A one-time approval token must be consumable by exactly one concurrent caller - a
    check-then-act race in _consume_approval would let multiple threads all read
    'used_at IS NULL' before any of them commits the UPDATE, granting the same approval
    to several concurrent destructive calls."""
    import concurrent.futures
    engine = gateway(tmp_path)
    request = read_request(tool="custom.delete", action="delete", arguments={}, risk="high",
                           idempotency_key="race", annotations={"destructiveHint": True, "openWorldHint": False})
    first = engine.authorize(request)
    token = engine.issue_approval(first.id)
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: engine.authorize(request, token), range(16)))
    assert sum(item.allowed for item in results) == 1


def test_concurrent_decisions_keep_the_audit_chain_valid(tmp_path):
    """Concurrent _log calls must not both read the same 'latest entry_hash' before either
    commits - that produces two decisions claiming the same prev_hash and breaks the
    hash-chain invariant that verify_audit_chain checks."""
    import concurrent.futures
    engine = gateway(tmp_path)
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(lambda i: engine.authorize(read_request(idempotency_key=str(i))), range(40)))
    assert len(engine.decisions()) == 40
    assert engine.verify_audit_chain()


def test_gateway_cli_check_and_audit(tmp_path, capsys):
    database = tmp_path / "cli.sqlite3"
    assert main(["gateway","check","--policy",str(ROOT / "examples/gateway-policy.json"),
                 "--request",str(ROOT / "examples/gateway-request.json"),"--database",str(database)]) == 0
    assert main(["gateway","audit","--policy",str(ROOT / "examples/gateway-policy.json"),"--database",str(database)]) == 0
    assert '"valid_hash_chain": true' in capsys.readouterr().out.lower()
