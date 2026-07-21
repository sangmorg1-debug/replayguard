from __future__ import annotations

import fnmatch
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse
from uuid import uuid4

from .redaction import Redactor
from .threat_mapping import mapping_for_gateway

OUTCOMES = {"allow", "deny", "require_confirmation", "rewrite", "sandbox", "rate_limit", "escalate"}
RISK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
SECRET = re.compile(r"(?i)(sk-[a-z0-9_-]{12,}|gh[pousr]_[a-z0-9]{16,}|bearer\s+[a-z0-9._~+/=-]{12,}|-----BEGIN .*PRIVATE KEY-----)")
UNSAFE_SHELL = re.compile(r"(?i)(rm\s+-rf|del\s+/[sq]|format\s+[a-z]:|shutdown|mkfs|dd\s+if=|curl.+\|\s*(?:sh|bash)|powershell.+-enc|invoke-expression)")
CONSEQUENTIAL = re.compile(r"(?i)(delete|remove|overwrite|write|send|transfer|pay|purchase|deploy|publish|execute|shell|admin|permission)")


@dataclass
class ActionRequest:
    user_id: str
    agent_id: str
    tool: str
    action: str
    arguments: dict[str, Any] = field(default_factory=dict)
    data_classification: str = "internal"
    environment: str = "production"
    task: str = ""
    user_intent: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    risk: str = "medium"
    location: str | None = None
    cost_usd: float = 0
    retry_count: int = 0
    recursion_depth: int = 0
    idempotency_key: str | None = None
    annotations: dict[str, Any] = field(default_factory=dict)

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass
class Decision:
    id: str
    outcome: str
    allowed: bool
    reason: str
    policy_version: str
    rule_id: str
    request_digest: str
    arguments: dict[str, Any]
    explanation: str
    latency_ms: float = 0
    approval_id: str | None = None
    atlas_techniques: list[dict[str, str]] = field(default_factory=list)
    owasp_risks: list[dict[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.atlas_techniques and not self.owasp_risks:
            mapped = mapping_for_gateway(self.reason)
            self.atlas_techniques = mapped["atlas_techniques"]
            self.owasp_risks = mapped["owasp_risks"]

    def to_dict(self) -> dict[str, Any]: return asdict(self)


MATCH_KEYS = {"max_risk", "user_id", "agent_id", "tool", "action", "environment", "data_classification", "location"}


class PolicySet:
    def __init__(self, value: dict[str, Any]) -> None:
        self.value = value
        self.version = str(value.get("version", "unversioned"))
        self.rules = sorted(value.get("rules", []), key=lambda item: int(item.get("priority", 0)), reverse=True)
        self.limits = value.get("limits", {})
        self.constraints = value.get("constraints", {})
        for rule in self.rules:
            if rule.get("effect") not in OUTCOMES: raise ValueError(f"invalid policy effect: {rule.get('effect')}")
            unknown = set(rule.get("match", {})) - MATCH_KEYS
            if unknown:
                # A typo'd condition key (e.g. "enviroment") must not silently widen a rule to
                # match regardless of that condition - fail to load instead of matching too much.
                raise ValueError(f"unknown match key(s) in rule {rule.get('id', 'unnamed')!r}: {sorted(unknown)}")

    @classmethod
    def load(cls, path: str | Path) -> "PolicySet": return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def save_versioned(self, directory: str | Path) -> Path:
        root = Path(directory); root.mkdir(parents=True, exist_ok=True)
        target = root / f"policy-{self.version}.json"
        target.write_text(json.dumps(self.value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (root / "active").write_text(target.name, encoding="utf-8")
        return target

    @classmethod
    def active(cls, directory: str | Path) -> "PolicySet":
        root = Path(directory); return cls.load(root / (root / "active").read_text(encoding="utf-8").strip())

    @staticmethod
    def rollback(directory: str | Path, version: str) -> None:
        root = Path(directory); target = root / f"policy-{version}.json"
        if not target.exists(): raise KeyError(version)
        (root / "active").write_text(target.name, encoding="utf-8")


class RuntimeGateway:
    def __init__(self, policy: PolicySet, database: str | Path = ".verify/gateway.sqlite3",
                 approval_secret: bytes | None = None) -> None:
        self.policy = policy
        self.database = Path(database); self.database.parent.mkdir(parents=True, exist_ok=True)
        configured = os.getenv("REPLAYGUARD_APPROVAL_SECRET")
        self.approval_secret = approval_secret or (configured.encode() if configured else secrets.token_bytes(32))
        self._init()

    @contextmanager
    def _connect(self, *, immediate: bool = False):
        db = sqlite3.connect(self.database, timeout=30); db.row_factory = sqlite3.Row
        try:
            with db:
                # BEGIN IMMEDIATE acquires the write lock before any statement runs, closing
                # the read-then-write window a deferred transaction would otherwise leave open
                # between a SELECT of "current state" and the INSERT/UPDATE that depends on it.
                if immediate:
                    db.execute("BEGIN IMMEDIATE")
                yield db
        finally:
            db.close()

    def _init(self) -> None:
        with self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY,created_at TEXT NOT NULL,user_id TEXT NOT NULL,
              agent_id TEXT NOT NULL,tool TEXT NOT NULL,action TEXT NOT NULL,outcome TEXT NOT NULL,allowed INTEGER NOT NULL,
              reason TEXT NOT NULL,policy_version TEXT NOT NULL,rule_id TEXT NOT NULL,request_digest TEXT NOT NULL,
              arguments_json TEXT NOT NULL,latency_ms REAL NOT NULL,prev_hash TEXT NOT NULL,entry_hash TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS decision_rate ON decisions(agent_id,tool,created_at);
            CREATE TABLE IF NOT EXISTS revocations(kind TEXT NOT NULL,value TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(kind,value));
            CREATE TABLE IF NOT EXISTS approvals(id TEXT PRIMARY KEY,decision_id TEXT NOT NULL,request_digest TEXT NOT NULL,
              token_hash TEXT NOT NULL,expires_at TEXT NOT NULL,used_at TEXT);
            """)

    def authorize(self, request: ActionRequest, approval_token: str | None = None) -> Decision:
        started = time.perf_counter()
        try:
            decision = self._evaluate(request, approval_token)
        except Exception as exc:
            decision = self._decision(request, "deny", "gateway_error", "fail-closed",
                                      f"Authorization failed safely: {type(exc).__name__}.")
        decision.latency_ms = (time.perf_counter() - started) * 1000
        try: self._log(request, decision)
        except Exception:
            decision.allowed = False; decision.outcome = "deny"; decision.reason = "audit_failure"
            decision.explanation = "Denied because the authorization decision could not be audited."
            self._remap(decision)
        return decision

    def _evaluate(self, request: ActionRequest, approval_token: str | None) -> Decision:
        if self._revoked("agent", request.agent_id) or self._revoked("tool", request.tool) or self._revoked("user", request.user_id):
            return self._decision(request, "deny", "emergency-revocation", "revoked", "Identity or tool is emergency-revoked.")
        if approval_token and self._consume_approval(request, approval_token):
            return self._decision(request, "allow", "human-approval", "approved", "A matching one-time human approval was consumed.")
        rendered = json.dumps(request.arguments, ensure_ascii=False, default=repr)
        external = bool(request.annotations.get("openWorldHint", True))
        if SECRET.search(rendered) and external:
            return self._decision(request, "deny", "secret-exfiltration", "built-in:secret", "Secrets cannot be sent to open-world tools.")
        if self._unsafe_shell(request):
            return self._decision(request, "deny", "unsafe-shell", "built-in:shell", "Unsafe shell operation denied.")
        constrained, violation = self._constrain_arguments(request)
        if violation:
            return self._decision(request, "deny", violation, f"built-in:{violation}", f"Arguments violate {violation} policy.")
        if self._over_rate(request):
            return self._decision(request, "rate_limit", "rate-limit", "built-in:rate", "Per-agent tool rate limit exceeded.")
        limits = self.policy.limits
        if request.retry_count > int(limits.get("max_retries", 3)):
            return self._decision(request, "rate_limit", "retry-limit", "built-in:retry", "Retry limit exceeded.")
        if request.recursion_depth > int(limits.get("max_recursion", 5)):
            return self._decision(request, "deny", "recursion-limit", "built-in:recursion", "Agent recursion limit exceeded.")
        if request.cost_usd > float(limits.get("max_cost_usd", float("inf"))):
            return self._decision(request, "deny", "cost-limit", "built-in:cost", "Configured cost limit exceeded.")
        consequential = self._consequential(request)
        if consequential and not request.idempotency_key:
            return self._decision(request, "deny", "missing-idempotency-key", "built-in:idempotency", "Consequential calls require an idempotency key.")
        for rule in self.policy.rules:
            if self._matches(rule.get("match", {}), request):
                effect = rule["effect"]
                args = self._rewrite(constrained, rule.get("rewrite", {}))
                if effect == "allow" and args != request.arguments: effect = "rewrite"
                allowed = effect in {"allow", "rewrite", "sandbox"}
                visible_args = args if allowed else Redactor().redact(args)
                return Decision(uuid4().hex, effect, allowed, str(rule.get("reason", effect)), self.policy.version,
                                str(rule.get("id", "unnamed")), request.digest(), visible_args,
                                f"Rule {rule.get('id', 'unnamed')} matched and produced {effect}.")
        if consequential or RISK.get(request.risk, 2) >= RISK["high"]:
            return self._decision(request, "require_confirmation", "unknown-high-risk", "default:high-risk",
                                  "Unknown consequential or high-risk actions require human confirmation.")
        return self._decision(request, "deny", "no-matching-allow", "default:deny", "No explicit allow rule matched.")

    def call(self, request: ActionRequest, adapter: Callable[..., Any], *, approval_token: str | None = None,
             sandbox_adapter: Callable[..., Any] | None = None) -> tuple[Decision, Any]:
        decision = self.authorize(request, approval_token)
        if not decision.allowed: return decision, None
        if decision.outcome == "sandbox":
            if not sandbox_adapter:
                decision.allowed = False; decision.outcome = "deny"; decision.reason = "sandbox-unavailable"
                self._remap(decision)
                return decision, None
            return decision, sandbox_adapter(**decision.arguments)
        return decision, adapter(**decision.arguments)

    def issue_approval(self, decision_id: str, ttl_seconds: int = 300) -> str:
        with self._connect() as db:
            row = db.execute("SELECT request_digest,outcome FROM decisions WHERE id=?", (decision_id,)).fetchone()
            if not row or row["outcome"] not in ("require_confirmation", "escalate"): raise KeyError(decision_id)
            raw = secrets.token_urlsafe(32); token_hash = hmac.new(self.approval_secret, raw.encode(), hashlib.sha256).hexdigest()
            approval_id = uuid4().hex
            expires = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()
            db.execute("INSERT INTO approvals VALUES(?,?,?,?,?,NULL)", (approval_id, decision_id, row["request_digest"], token_hash, expires))
        return raw

    def revoke(self, kind: str, value: str) -> None:
        if kind not in {"agent", "tool", "user"}: raise ValueError(kind)
        with self._connect() as db: db.execute("INSERT OR REPLACE INTO revocations VALUES(?,?,?)", (kind, value, _now()))

    def unrevoke(self, kind: str, value: str) -> None:
        with self._connect() as db: db.execute("DELETE FROM revocations WHERE kind=? AND value=?", (kind, value))

    def decisions(self, request_digest: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as db:
            query = "SELECT * FROM decisions" + (" WHERE request_digest=?" if request_digest else "") + " ORDER BY created_at,id"
            rows = db.execute(query, (request_digest,) if request_digest else ()).fetchall()
        results = []
        for row in rows:
            item = {key: row[key] for key in row.keys()}
            item.update(mapping_for_gateway(item["reason"]))
            results.append(item)
        return results

    def verify_audit_chain(self) -> bool:
        previous = "0" * 64
        for row in self.decisions():
            payload = self._log_payload(row["id"], row["request_digest"], row["outcome"], row["policy_version"], previous)
            if row["prev_hash"] != previous or row["entry_hash"] != hashlib.sha256(payload.encode()).hexdigest(): return False
            previous = row["entry_hash"]
        return True

    def _constrain_arguments(self, request: ActionRequest) -> tuple[dict[str, Any], str | None]:
        args = dict(request.arguments); constraints = self.policy.constraints
        roots = [Path(item).resolve() for item in constraints.get("approved_roots", [])]
        for key, value in args.items():
            if "path" in key.lower() and isinstance(value, str) and roots:
                resolved = Path(value).resolve()
                if not any(resolved == root or root in resolved.parents for root in roots): return args, "path-boundary"
                args[key] = str(resolved)
            if any(word in key.lower() for word in ("url", "uri", "endpoint")) and isinstance(value, str):
                host = (urlparse(value).hostname or "").lower()
                approved = constraints.get("approved_domains", [])
                if approved and not any(fnmatch.fnmatch(host, pattern) for pattern in approved): return args, "network-boundary"
                try:
                    address = ipaddress.ip_address(host)
                    if address.is_private or address.is_loopback or address.is_link_local: return args, "network-boundary"
                except ValueError: pass
            if key.lower() in {"recipient", "to", "email"}:
                named = request.user_intent.get("recipients", [])
                if named and value not in named: return args, "recipient-boundary"
            if key.lower() in {"amount", "amount_usd", "value"} and isinstance(value, (int, float)):
                if value > float(constraints.get("max_transaction_usd", float("inf"))): return args, "transaction-limit"
        return args, None

    def _unsafe_shell(self, request: ActionRequest) -> bool:
        if not re.search(r"(?i)(shell|exec|command|terminal)", request.tool + " " + request.action): return False
        return bool(UNSAFE_SHELL.search(json.dumps(request.arguments, default=repr)))

    def _consequential(self, request: ActionRequest) -> bool:
        annotations = request.annotations
        if annotations.get("readOnlyHint") is True and annotations.get("destructiveHint") is False: return False
        return annotations.get("destructiveHint", True) or bool(CONSEQUENTIAL.search(request.tool + " " + request.action))

    def _over_rate(self, request: ActionRequest) -> bool:
        limit = int(self.policy.limits.get("calls_per_minute", 0))
        if not limit: return False
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        with self._connect() as db:
            count = db.execute("SELECT COUNT(*) FROM decisions WHERE agent_id=? AND tool=? AND created_at>=?", (request.agent_id, request.tool, cutoff)).fetchone()[0]
        return count >= limit

    def _matches(self, match: dict[str, Any], request: ActionRequest) -> bool:
        simple = {"user_id": request.user_id, "agent_id": request.agent_id, "tool": request.tool,
                  "action": request.action, "environment": request.environment,
                  "data_classification": request.data_classification, "location": request.location or ""}
        for key, expected in match.items():
            if key == "max_risk" and RISK.get(request.risk, 3) > RISK.get(str(expected), 0): return False
            elif key in simple:
                patterns = expected if isinstance(expected, list) else [expected]
                if not any(fnmatch.fnmatch(str(simple[key]), str(pattern)) for pattern in patterns): return False
        return True

    @staticmethod
    def _rewrite(arguments: dict[str, Any], rewrite: dict[str, Any]) -> dict[str, Any]:
        value = dict(arguments); value.update(rewrite.get("set", {}))
        for key in rewrite.get("remove", []): value.pop(key, None)
        return value

    def _decision(self, request: ActionRequest, outcome: str, reason: str, rule: str, explanation: str) -> Decision:
        allowed = outcome in {"allow", "rewrite", "sandbox"}
        arguments = dict(request.arguments) if allowed else Redactor().redact(request.arguments)
        return Decision(uuid4().hex, outcome, allowed, reason, self.policy.version, rule, request.digest(), arguments, explanation)

    @staticmethod
    def _remap(decision: Decision) -> None:
        mapped = mapping_for_gateway(decision.reason)
        decision.atlas_techniques = mapped["atlas_techniques"]
        decision.owasp_risks = mapped["owasp_risks"]

    def _revoked(self, kind: str, value: str) -> bool:
        with self._connect() as db: return bool(db.execute("SELECT 1 FROM revocations WHERE kind=? AND value=?", (kind, value)).fetchone())

    def _consume_approval(self, request: ActionRequest, token: str) -> bool:
        digest = request.digest(); token_hash = hmac.new(self.approval_secret, token.encode(), hashlib.sha256).hexdigest()
        now = _now()
        with self._connect() as db:
            # A single UPDATE...WHERE used_at IS NULL is the atomic check-and-consume: SQLite
            # serializes writers, so at most one concurrent caller's UPDATE matches the row.
            # A separate SELECT-then-UPDATE would let multiple callers all pass the check
            # before any of them commits, double-spending a one-time approval.
            cursor = db.execute(
                "UPDATE approvals SET used_at=? WHERE request_digest=? AND token_hash=? AND used_at IS NULL AND expires_at>=?",
                (now, digest, token_hash, now))
        return cursor.rowcount == 1

    def _log(self, request: ActionRequest, decision: Decision) -> None:
        with self._connect(immediate=True) as db:
            row = db.execute("SELECT entry_hash FROM decisions ORDER BY created_at DESC,id DESC LIMIT 1").fetchone()
            previous = row[0] if row else "0" * 64
            payload = self._log_payload(decision.id, decision.request_digest, decision.outcome, decision.policy_version, previous)
            entry_hash = hashlib.sha256(payload.encode()).hexdigest()
            db.execute("INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (decision.id, _now(), request.user_id,
                       request.agent_id, request.tool, request.action, decision.outcome, int(decision.allowed), decision.reason,
                       decision.policy_version, decision.rule_id, decision.request_digest,
                       json.dumps(Redactor().redact(decision.arguments), sort_keys=True),
                       decision.latency_ms, previous, entry_hash))

    @staticmethod
    def _log_payload(decision_id: str, digest: str, outcome: str, version: str, previous: str) -> str:
        return "|".join((decision_id, digest, outcome, version, previous))


def _now() -> str: return datetime.now(timezone.utc).isoformat()
