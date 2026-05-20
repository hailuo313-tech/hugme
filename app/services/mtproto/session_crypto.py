"""Fernet encrypt/decrypt for Telethon StringSession (C-15 / P1-18)."""
from __future__ import annotations
from cryptography.fernet import Fernet, InvalidToken

class SessionCryptoError(ValueError):
    pass

def _fernet(key: str | bytes) -> Fernet:
    if isinstance(key, str):
        key = key.encode("ascii")
    try:
        return Fernet(key)
    except Exception as exc:
        raise SessionCryptoError(f"invalid Fernet key: {exc}") from exc

def encrypt_string_session(plaintext: str, fernet_key: str | bytes) -> bytes:
    if not plaintext or not plaintext.strip():
        raise SessionCryptoError("empty session string")
    return _fernet(fernet_key).encrypt(plaintext.strip().encode("utf-8"))

def decrypt_string_session(ciphertext: bytes, fernet_key: str | bytes) -> str:
    try:
        raw = _fernet(fernet_key).decrypt(ciphertext)
    except InvalidToken as exc:
        raise SessionCryptoError("decrypt failed") from exc
    return raw.decode("utf-8")
