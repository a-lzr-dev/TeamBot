import bcrypt


def get_password_hash(password: str) -> str:
    """Хеширование пароля с использованием bcrypt."""
    if password is None:
        password = ""
    if len(password.encode("utf-8")) > 72:
        password = password[:72]

    salt: bytes = bcrypt.gensalt()
    hashed: bytes = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверка пароля с использованием bcrypt."""
    if plain_password is None:
        return False
    if not hashed_password or not hashed_password.startswith("$2"):
        return False
    try:
        result: bool = bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
        return result
    except ValueError:
        return False
