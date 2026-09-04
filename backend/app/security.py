"""Password hashing (PBKDF2-SHA256, 240k iterations) and JWT utilities."""
import datetime as dt
import hashlib
import hmac
import os
import secrets

import jwt

from .config import settings

_ITERATIONS = 240_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(dk.hex(), digest)
    except Exception:
        return False


def _make_token(user, token_type: str, ttl: int) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": user.id,
        "role": user.role,
        "type": token_type,
        "iat": now,
        "exp": now + dt.timedelta(seconds=ttl),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALG)


def create_access_token(user) -> str:
    return _make_token(user, "access", settings.ACCESS_TTL)


def create_refresh_token(user) -> str:
    return _make_token(user, "refresh", settings.REFRESH_TTL)


def decode_token(token: str, expected_type: str = "access") -> dict:
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALG])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("wrong token type")
    return payload
