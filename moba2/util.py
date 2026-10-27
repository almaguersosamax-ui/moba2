"""Utilidades transversales."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import string
from datetime import datetime, timedelta, timezone

ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    return (dt or now()).strftime(ISO_FMT)


def iso_after(**delta) -> str:
    return iso(now() + timedelta(**delta))


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, ISO_FMT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def new_token() -> str:
    return secrets.token_urlsafe(32)





def hash_token(token: str) -> str:
    """Los tokens no se guardan en claro: solo su SHA-256."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# Alfabeto del cliente: OnlineService.CodeAlphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ" (sin I ni O)
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ"
CODE_LENGTH = 4          # OnlineService.CodeLength = 4


def new_lobby_code(size: int = CODE_LENGTH) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(size))


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def new_session_key() -> bytes:
    return secrets.token_bytes(32)
