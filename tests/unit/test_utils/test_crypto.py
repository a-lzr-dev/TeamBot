"""Расширенные тесты для модуля шифрования."""

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

    def test_encrypt_deterministic(self) -> None:
        """Проверка, что одинаковые данные шифруются по-разному (соль)."""
        data = "test"
        e1 = encrypt_data(data)
        e2 = encrypt_data(data)
        # Из-за соли результаты должны отличаться
        assert e1 != e2

    def test_decrypt_roundtrip_multiple(self) -> None:
        """Проверка множественного шифрования/дешифрования."""
        texts = ["short", "medium text with spaces", "long " * 50, "1234567890"]

        for text in texts:
            encrypted = encrypt_data(text)
            decrypted = decrypt_data(encrypted)
            assert decrypted == text

    def test_encrypt_with_none(self) -> None:
        """Проверка шифрования None — функция возвращает None."""
        # Функция encrypt_data возвращает None при передаче None
        result = encrypt_data(None)  # type: ignore
        assert result is None

    def test_decrypt_with_none(self) -> None:
        """Проверка дешифрования None — функция возвращает None."""
        # Функция decrypt_data возвращает None при передаче None
        result = decrypt_data(None)  # type: ignore
        assert result is None

    def test_encrypt_with_empty_string_returns_empty(self) -> None:
        """Проверка, что encrypt_data('') возвращает ''."""
        assert encrypt_data("") == ""

    def test_decrypt_with_empty_string_returns_empty(self) -> None:
        """Проверка, что decrypt_data('') возвращает ''."""
        assert decrypt_data("") == ""
