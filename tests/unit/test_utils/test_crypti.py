"""Тесты для модуля шифрования."""

import pytest

from app.utils.crypto import decrypt_data, encrypt_data


class TestCrypto:
    """Тесты для функций шифрования."""

    def test_encrypt_decrypt(self) -> None:
        """Проверка шифрования и дешифрования."""
        original = "Secret message"
        encrypted = encrypt_data(original)

        assert encrypted != original
        assert isinstance(encrypted, str)

        decrypted = decrypt_data(encrypted)
        assert decrypted == original

    def test_encrypt_empty_string(self) -> None:
        """Проверка шифрования пустой строки."""
        assert encrypt_data("") == ""
        assert decrypt_data("") == ""

    def test_encrypt_long_text(self) -> None:
        """Проверка шифрования длинного текста."""
        original = "A" * 1000
        encrypted = encrypt_data(original)
        decrypted = decrypt_data(encrypted)
        assert decrypted == original

    def test_decrypt_invalid_data(self) -> None:
        """Проверка дешифрования невалидных данных."""
        with pytest.raises(ValueError, match="Failed to decrypt data"):
            decrypt_data("invalid_data")

    def test_encrypt_decrypt_special_characters(self) -> None:
        """Проверка шифрования спецсимволов."""
        original = "!@#$%^&*()_+{}:<>?~`"
        encrypted = encrypt_data(original)
        decrypted = decrypt_data(encrypted)
        assert decrypted == original

    def test_encrypt_decrypt_unicode(self) -> None:
        """Проверка шифрования Unicode."""
        original = "Привет мир! 🌍"
        encrypted = encrypt_data(original)
        decrypted = decrypt_data(encrypted)
        assert decrypted == original
