"""C-15: MTProto security unit tests."""
from __future__ import annotations
import pytest
from cryptography.fernet import Fernet
from services.mtproto.session_crypto import SessionCryptoError, decrypt_string_session, encrypt_string_session
from services.mtproto.account_routing import assign_account_id, account_redis_prefix, route_redis_key
from services.mtproto.security_policy import assert_safe_log_message, check_production_session_policy, redact_sensitive

@pytest.fixture
def fernet_key():
    return Fernet.generate_key().decode()

def test_encrypt_decrypt_roundtrip(fernet_key):
    plain = "1BVtsOHwBu5X-example"
    ct = encrypt_string_session(plain, fernet_key)
    assert decrypt_string_session(ct, fernet_key) == plain

def test_decrypt_wrong_key(fernet_key):
    ct = encrypt_string_session("sess", fernet_key)
    with pytest.raises(SessionCryptoError):
        decrypt_string_session(ct, Fernet.generate_key().decode())

def test_assign_stable():
    pool = ["a1", "a2", "a3"]
    assert assign_account_id("u1", pool) == assign_account_id("u1", pool)

def test_redis_keys():
    assert route_redis_key(9) == "mtproto:route:9"
    assert account_redis_prefix("x") == "mtproto:acct:x:"

def test_redact():
    msg = "TELEGRAM_SESSION_STRINGS=1BVtsOHwBu5Xsecret"
    assert "[REDACTED]" in redact_sensitive(msg)
    with pytest.raises(ValueError):
        assert_safe_log_message(msg)

def test_prod_forbidden(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("TELEGRAM_SESSION_STRINGS", "x")
    assert check_production_session_policy()

def test_dev_ok(monkeypatch):
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("TELEGRAM_SESSION_STRINGS", "x")
    assert check_production_session_policy() == []
