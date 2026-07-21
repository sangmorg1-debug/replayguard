import pytest

from replayguard.redaction import REDACTED, Redactor

SECRETS = [
    "sk-abcdefghijklmnop", "ghp_abcdefghijklmnopqrstuvwxyz", "AKIAABCDEFGHIJKLMNOP",
    "Bearer abcdefghijklmnop", "password=hunter2",
]


@pytest.mark.parametrize("secret", SECRETS)
def test_seeded_secrets_are_removed(secret):
    redactor = Redactor()
    assert redactor.findings(secret)
    assert secret not in redactor.redact(secret)


@pytest.mark.parametrize("key", ["authorization", "api_key", "apikey", "password", "passwd", "secret", "token", "access_token", "refresh_token"])
def test_sensitive_keys_are_removed(key):
    assert Redactor().redact({key: "sensitive"})[key] == REDACTED

