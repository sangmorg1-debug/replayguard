from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

REDACTED = "[REDACTED]"
DEFAULT_PATTERNS = {
    "openai_key": r"\bsk-[A-Za-z0-9_-]{16,}\b",
    "github_token": r"\bgh[pousr]_[A-Za-z0-9]{20,}\b",
    "aws_access_key": r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
    "bearer_token": r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}",
    "private_key": r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    "password_assignment": r"(?i)(password|passwd|pwd)\s*[:=]\s*([^\s,;]+)",
}
SENSITIVE_KEYS = {"authorization", "api_key", "apikey", "password", "passwd", "secret", "token", "access_token", "refresh_token"}


@dataclass
class Redactor:
    patterns: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_PATTERNS))

    def redact(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: REDACTED if isinstance(key, str) and key.lower() in SENSITIVE_KEYS else self.redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.redact(item) for item in value)
        if not isinstance(value, str):
            return value
        result = value
        for name, pattern in self.patterns.items():
            if name == "password_assignment":
                result = re.sub(pattern, lambda m: f"{m.group(1)}={REDACTED}", result)
            else:
                result = re.sub(pattern, REDACTED, result)
        return result

    def findings(self, value: Any) -> list[str]:
        text = repr(value)
        found = [name for name, pattern in self.patterns.items() if re.search(pattern, text)]
        if isinstance(value, dict):
            found.extend(f"sensitive_key:{key}" for key in value if key.lower() in SENSITIVE_KEYS)
        return sorted(set(found))
