import base64

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from ..config import settings


def get_encryption_key() -> bytes:
    """Получение ключа шифрования"""
    secret = getattr(settings, "ENCRYPTION_SECRET", "change_me_in_production_use_strong_key_here")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"fixed_salt_change_me_in_production",
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(secret.encode()))
    return key


def encrypt_data(data: str) -> str:
    """Шифрование данных"""
    if not data:
        return data

    try:
        key = get_encryption_key()
        f = Fernet(key)
        encrypted = f.encrypt(data.encode())
        return base64.urlsafe_b64encode(encrypted).decode()
    except Exception as e:
        raise ValueError(f"Failed to encrypt data: {e}") from e


def decrypt_data(encrypted_data: str) -> str:
    """Дешифрование данных"""
    if not encrypted_data:
        return encrypted_data

    try:
        key = get_encryption_key()
        f = Fernet(key)
        encrypted = base64.urlsafe_b64decode(encrypted_data.encode())
        decrypted = f.decrypt(encrypted)
        return decrypted.decode("utf-8")  # type: ignore[no-any-return]
    except Exception as e:
        raise ValueError(f"Failed to decrypt data: {e}") from e


__all__ = [
    "encrypt_data",
    "decrypt_data",
]
