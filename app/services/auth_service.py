import bcrypt


def get_password_hash(password: str) -> str:
    """Хеширование пароля с использованием bcrypt"""
    salt: bytes = bcrypt.gensalt()
    hashed: bytes = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверка пароля с использованием bcrypt"""
    result: bool = bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    return result
