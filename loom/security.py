"""Credential helpers for agent API keys.

Agent identifiers remain accepted as a legacy credential so existing local
installations can migrate without downtime. Newly issued credentials are
opaque bearer tokens and only their SHA-256 digest is persisted.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

API_KEY_PREFIX = "loom_"
SESSION_TOKEN_PREFIX = "loom_session_"

_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_SALT_BYTES = 16
_SCRYPT_KEY_BYTES = 32
_SCRYPT_MAX_MEMORY = 160 * 1024 * 1024


def generate_api_key() -> str:
    """Create a high-entropy opaque API key."""

    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def hash_api_key(api_key: str) -> str:
    """Return the stable digest stored in ``agents.credentials_ref``."""

    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def generate_session_token() -> str:
    """Create a high-entropy opaque user-session token."""

    return f"{SESSION_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def hash_session_token(token: str) -> str:
    """Return the one-way digest persisted for a user session."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    """Hash a password with the memory-hard scrypt KDF and a random salt."""

    salt = secrets.token_bytes(_SCRYPT_SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_KEY_BYTES,
        maxmem=_SCRYPT_MAX_MEMORY,
    )
    return "$".join(
        (
            "scrypt",
            str(_SCRYPT_N),
            str(_SCRYPT_R),
            str(_SCRYPT_P),
            salt.hex(),
            derived.hex(),
        )
    )


def verify_password(password: str, encoded_hash: str) -> bool:
    """Verify a password without raising for malformed persisted values."""

    try:
        algorithm, raw_n, raw_r, raw_p, raw_salt, raw_expected = encoded_hash.split("$")
        if algorithm != "scrypt":
            return False
        n, r, p = int(raw_n), int(raw_r), int(raw_p)
        if n < 2**14 or n > 2**17 or n & (n - 1) or (r, p) != (_SCRYPT_R, _SCRYPT_P):
            return False
        salt = bytes.fromhex(raw_salt)
        expected = bytes.fromhex(raw_expected)
        if len(salt) != _SCRYPT_SALT_BYTES or len(expected) != _SCRYPT_KEY_BYTES:
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=len(expected),
            maxmem=_SCRYPT_MAX_MEMORY,
        )
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(actual, expected)


def password_hash_needs_upgrade(encoded_hash: str) -> bool:
    """Return true when a valid historical hash uses weaker KDF parameters."""

    try:
        algorithm, raw_n, raw_r, raw_p, _, _ = encoded_hash.split("$")
        return algorithm != "scrypt" or (
            int(raw_n), int(raw_r), int(raw_p)
        ) != (_SCRYPT_N, _SCRYPT_R, _SCRYPT_P)
    except (TypeError, ValueError):
        return True
