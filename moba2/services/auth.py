"""Autenticación por dispositivo: el cliente envía deviceId + secret y recibe un token."""
from __future__ import annotations

from ..config import Config
from ..db import connection as db
from ..errors import Unauthorized
from ..util import hash_token, iso, iso_after, new_token, parse_iso, now
from ..domain.validation import clean_text, validate_name


def _device_key(device_id: str, secret: str) -> str:
    """Identidad estable del dispositivo (no se guarda el secret)."""
    return hash_token(f"{device_id}|{secret}")


def login(config: Config, body: dict) -> dict:
    device_id = clean_text(body.get("deviceId"), 128)
    secret = clean_text(body.get("secret"), 256)
    if not device_id:
        raise Unauthorized("deviceId requerido", code="device_required")

    key = _device_key(device_id, secret)
    row = db.query_one("SELECT * FROM users WHERE device_id = ?", (key,))
    requested_name = clean_text(body.get("name"), 24)

    with db.transaction() as con:
        if row is None:
            name = _unique_name(requested_name or f"Player{key[:4].upper()}")
            uid = db.execute(
                "INSERT INTO users(device_id, name, name_set, created_at, last_seen_at)"
                " VALUES(?,?,?,?,?)",
                (key, name, 1 if requested_name else 0, iso(), iso()),
            )
        else:
            uid = row["id"]
            name = row["name"]
            if requested_name and not row["name_set"] and requested_name.casefold() != name.casefold():
                try:
                    name = validate_name(requested_name)
                    db.execute("UPDATE users SET name=?, name_set=1 WHERE id=?", (name, uid))
                except Exception:
                    pass
            db.execute("UPDATE users SET last_seen_at=? WHERE id=?", (iso(), uid))

        token = new_token()
        con.execute(
            "INSERT INTO tokens(token_hash, user_id, device_id, created_at, expires_at)"
            " VALUES(?,?,?,?,?)",
            (hash_token(token), uid, key, iso(), iso_after(days=config.token_ttl_days)),
        )
        con.execute("INSERT INTO audit_log(at, actor_id, action, detail) VALUES(?,?,?,?)",
                    (iso(), uid, "login", device_id[:48]))

    return {"userId": uid, "name": name, "token": token,
            "expiresAt": iso_after(days=config.token_ttl_days)}


def _unique_name(base: str) -> str:
    candidate = base[:24] or "Player"
    suffix = 1
    while db.query_one("SELECT 1 FROM users WHERE name = ? COLLATE NOCASE", (candidate,)):
        suffix += 1
        tail = f"#{suffix}"
        candidate = base[: 24 - len(tail)] + tail
    return candidate


def resolve(token: str | None) -> dict:
    """Devuelve el usuario dueño del token o lanza Unauthorized."""
    if not token:
        raise Unauthorized("falta el token")
    row = db.query_one(
        "SELECT u.*, t.expires_at AS token_expires_at, t.revoked AS token_revoked,"
        "       t.token_hash AS token_hash"
        "  FROM tokens t JOIN users u ON u.id = t.user_id WHERE t.token_hash = ?",
        (hash_token(token),),
    )
    if row is None:
        raise Unauthorized("token desconocido")
    if row["token_revoked"]:
        raise Unauthorized("token revocado")
    expires = parse_iso(row["token_expires_at"])
    if expires and expires < now():
        raise Unauthorized("token expirado")
    db.execute("UPDATE tokens SET last_used_at=? WHERE token_hash=?", (iso(), row["token_hash"]))
    return dict(row)


def revoke(token: str) -> None:
    db.execute("UPDATE tokens SET revoked=1 WHERE token_hash=?", (hash_token(token),))
