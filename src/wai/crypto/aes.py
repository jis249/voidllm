"""AES-256-GCM encrypt/decrypt matching pkg/crypto."""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CiphertextTooShortError(ValueError):
    pass


def parse_key(raw: str) -> bytes:
    """Return a 32-byte AES-256 key from raw (base64 or SHA-256 fallback)."""
    if not raw:
        raise ValueError("ParseKey: key must be at least 16 characters")
    try:
        decoded = base64.b64decode(raw, validate=True)
        if len(decoded) == 32:
            return decoded
    except Exception:
        pass
    if len(raw) < 16:
        raise ValueError("ParseKey: key must be at least 16 characters")
    return hashlib.sha256(raw.encode()).digest()


def encrypt(plaintext: bytes, key: bytes, aad: bytes | None = None) -> bytes:
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, plaintext, aad)
    return nonce + ct


def decrypt(ciphertext: bytes, key: bytes, aad: bytes | None = None) -> bytes:
    if len(ciphertext) < 12 + 16:
        raise CiphertextTooShortError("ciphertext too short")
    nonce, ct = ciphertext[:12], ciphertext[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct, aad)


def encrypt_string(plaintext: str, key: bytes, aad: bytes | None = None) -> str:
    return base64.b64encode(encrypt(plaintext.encode(), key, aad)).decode()


def decrypt_string(ciphertext: str, key: bytes, aad: bytes | None = None) -> str:
    decoded = base64.b64decode(ciphertext)
    return decrypt(decoded, key, aad).decode()
