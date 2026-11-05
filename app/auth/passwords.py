"""Хеширование паролей без внешних зависимостей."""

from __future__ import annotations

import hashlib
import hmac
import os

_ITERATIONS = 120_000
_SALT_LEN = 16


def hash_password(password: str) -> str:
    salt = os.urandom(_SALT_LEN)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"{_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        iterations_s, salt_hex, digest_hex = stored.split("$", 2)
        iterations = int(iterations_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)
