from app.core.security import hash_password, verify_password


def test_password_hash_roundtrip():
    hashed = hash_password("Rahasia123!")
    assert verify_password("Rahasia123!", hashed)
    assert not verify_password("salah", hashed)
