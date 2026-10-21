import pytest

from scripts.owner_password_generator import (
    DIGITS,
    LOWERCASE,
    PASSWORD_LENGTH,
    SYMBOLS,
    UPPERCASE,
    generate_password,
)


def test_generate_password_has_expected_length_and_character_groups():
    password = generate_password()

    assert len(password) == PASSWORD_LENGTH
    assert any(character in LOWERCASE for character in password)
    assert any(character in UPPERCASE for character in password)
    assert any(character in DIGITS for character in password)
    assert any(character in SYMBOLS for character in password)


def test_generate_password_rejects_length_shorter_than_required_groups():
    with pytest.raises(ValueError, match="minimal 4 karakter"):
        generate_password(3)
