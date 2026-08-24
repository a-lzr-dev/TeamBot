"""
Утилиты для шифрования и дешифрования данных.

Назначение:
    Предоставляет функции для безопасного шифрования/дешифрования данных
    с использованием библиотеки cryptography (Fernet).

Основные функции:
    1. Шифрование данных с использованием Fernet
    2. Дешифрование данных с использованием Fernet
    3. Генерация ключа шифрования на основе секрета

Технические особенности:
    - Использует PBKDF2HMAC для генерации ключа из парольной фразы
    - Алгоритм SHA256, 100000 итераций, длина ключа 32 байта
    - URL-safe Base64 кодирование для безопасной передачи
    - Обработка ошибок с информативными сообщениями

Безопасность:
    - Ключ генерируется из ENCRYPTION_SECRET из настроек
    - Соль должна быть изменена в production
    - Использует надёжный алгоритм Fernet (симметричное шифрование)

Архитектура:
    - Простой модуль с утилитами
    - Интегрируется с конфигурацией через settings
"""

import base64

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from ..config import settings

# ============================================================
# 1. ГЕНЕРАЦИЯ КЛЮЧА ШИФРОВАНИЯ
# ============================================================


def get_encryption_key() -> bytes:
    """
    Получение ключа шифрования на основе секрета из настроек.

    Использует PBKDF2HMAC для преобразования парольной фразы в криптографический ключ.
    Это позволяет использовать человекочитаемый секрет вместо бинарного ключа.

    Returns:
        bytes: Ключ шифрования в формате URL-safe Base64

    Warning:
        В production необходимо изменить соль на уникальную!
        Использование фиксированной соли в примере только для демонстрации.
    """
    secret = getattr(settings, "ENCRYPTION_SECRET", "change_me_in_production_use_strong_key_here")

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"fixed_salt_change_me_in_production",  # В production заменить на уникальную соль!
        iterations=100000,
    )

    key = base64.urlsafe_b64encode(kdf.derive(secret.encode()))
    return key


# ============================================================
# 2. ШИФРОВАНИЕ ДАННЫХ
# ============================================================


def encrypt_data(data: str) -> str:
    """
    Шифрование данных с использованием Fernet.

    Args:
        data: Данные для шифрования в виде строки

    Returns:
        str: Зашифрованные данные в формате URL-safe Base64

    Raises:
        ValueError: Если шифрование не удалось
    """
    if not data:
        return data

    try:
        key = get_encryption_key()
        f = Fernet(key)
        encrypted = f.encrypt(data.encode())
        return base64.urlsafe_b64encode(encrypted).decode()
    except Exception as e:
        raise ValueError(f"Failed to encrypt data: {e}") from e


# ============================================================
# 3. ДЕШИФРОВАНИЕ ДАННЫХ
# ============================================================


def decrypt_data(encrypted_data: str) -> str:
    """
    Дешифрование данных с использованием Fernet.

    Args:
        encrypted_data: Зашифрованные данные в формате URL-safe Base64

    Returns:
        str: Расшифрованные данные

    Raises:
        ValueError: Если дешифрование не удалось (неверный ключ, повреждённые данные)
    """
    if not encrypted_data:
        return encrypted_data

    try:
        key = get_encryption_key()
        f = Fernet(key)
        encrypted = base64.urlsafe_b64decode(encrypted_data.encode())
        decrypted = f.decrypt(encrypted)
        result: str = decrypted.decode("utf-8")
        return result
    except Exception as e:
        raise ValueError(f"Failed to decrypt data: {e}") from e


__all__ = [
    "encrypt_data",
    "decrypt_data",
    "get_encryption_key",
]
