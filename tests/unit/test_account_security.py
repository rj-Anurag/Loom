"""Security primitives used by public account authentication."""

from loom.security import (
    generate_session_token,
    hash_password,
    hash_session_token,
    password_hash_needs_upgrade,
    verify_password,
)


def test_password_hash_is_salted_and_verifiable() -> None:
    first = hash_password("correct horse battery staple")
    second = hash_password("correct horse battery staple")

    assert first.startswith("scrypt$")
    assert first != second
    assert verify_password("correct horse battery staple", first) is True
    assert verify_password("wrong password", first) is False
    assert password_hash_needs_upgrade(first) is False


def test_malformed_password_hash_is_rejected() -> None:
    assert verify_password("anything", "not-a-password-hash") is False


def test_session_tokens_are_opaque_and_only_digests_are_stable() -> None:
    token = generate_session_token()

    assert token.startswith("loom_session_")
    assert len(token) >= 50
    assert hash_session_token(token) == hash_session_token(token)
    assert token not in hash_session_token(token)
