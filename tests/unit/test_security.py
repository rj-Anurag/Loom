from loom.security import API_KEY_PREFIX, generate_api_key, hash_api_key


def test_generated_api_keys_are_opaque_and_high_entropy() -> None:
    first = generate_api_key()
    second = generate_api_key()

    assert first.startswith(API_KEY_PREFIX)
    assert second.startswith(API_KEY_PREFIX)
    assert first != second
    assert len(first) >= 40
    assert hash_api_key(first) != first
    assert hash_api_key(first) == hash_api_key(first)
