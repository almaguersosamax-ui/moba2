"""Salas: creación, unión por código, estado y caducidad."""
from __future__ import annotations

from ..config import Config
from ..db import connection as db
from ..domain.validation import ValidationError, clean_text, validate_lobby_code
from ..errors import Conflict, NotFound
from ..util import b64, iso, iso_after, new_lobby_code, new_session_key, parse_iso, now


def _expire_old(config: Config) -> None:
    db.execute("UPDATE lobbies SET closed_at=? WHERE closed_at IS NULL AND expires_at < ?",
               (iso(), iso()))


def _play_payload(config: Config, lobby: dict, *, rejoin: bool) -> dict:
    return {
        "host": lobby["host"],
        "port": lobby["port"],
        "ticket": lobby["session_key"],
        "sessionKey": lobby["session_key"],
        "expiresAt": lobby["expires_at"],
        "lobby": lobby["code"],
        "rejoin": rejoin,
    }


def _host_for(config: Config, client_ip: str) -> str:
    """El anfitrión real es el teléfono que crea la sala: usamos su IP de origen.

    Si viene de la propia máquina (127.x, pruebas locales) se usa `--host-ip`.
    """
    ip = (client_ip or "").strip()
    private = (ip.startswith("10.") or ip.startswith("192.168.")
               or (ip.startswith("172.") and 16 <= int(ip.split(".")[1] or 0) <= 31))
    if ip and private and not ip.startswith("127."):
        return ip
    return config.host_ip


def create(config: Config, user: dict, body: dict, client_ip: str = "") -> dict:
    _expire_old(config)
    code = clean_text(body.get("lobby"), 8).upper() or new_lobby_code()
    try:
        code = validate_lobby_code(code)
    except ValidationError as exc:
        raise Conflict(exc.code) from exc
    if db.query_one("SELECT 1 FROM lobbies WHERE code=? AND closed_at IS NULL", (code,)):
        raise Conflict("ya existe una sala activa con ese código")

    session_key = b64(new_session_key())   # Base64: el cliente lo convierte a byte[]
    expires = iso_after(hours=config.lobby_ttl_hours)
    with db.transaction() as con:
        con.execute(
            "INSERT OR REPLACE INTO lobbies(code, owner_id, host, port, session_key, is_private,"
            " max_members, created_at, expires_at, closed_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,NULL)",
            (code, user["id"], _host_for(config, client_ip), config.udp_port, session_key,
             1 if body.get("private") else 0, 16, iso(), expires),
        )
        con.execute("INSERT OR REPLACE INTO lobby_members(lobby_code, user_id, slot, ready, joined_at)"
                    " VALUES(?,?,?,?,?)", (code, user["id"], 0, 1, iso()))
        con.execute("INSERT INTO audit_log(at, actor_id, action, detail) VALUES(?,?,?,?)",
                    (iso(), user["id"], "lobby_create", code))
    lobby = db.query_one("SELECT * FROM lobbies WHERE code=?", (code,))
    return _play_payload(config, dict(lobby), rejoin=False)


def join(config: Config, user: dict, body: dict) -> dict:
    _expire_old(config)
    try:
        code = validate_lobby_code(body.get("code"))
    except ValidationError as exc:
        raise NotFound("código de sala inválido o inexistente") from exc
    lobby = db.query_one("SELECT * FROM lobbies WHERE code=?", (code,))
    if not lobby or lobby["closed_at"]:
        raise NotFound("sala no encontrada o cerrada")
    expires = parse_iso(lobby["expires_at"])
    if expires and expires < now():
        raise NotFound("sala caducada")
    members = db.query("SELECT 1 FROM lobby_members WHERE lobby_code=?", (code,))
    if len(members) >= lobby["max_members"]:
        raise Conflict("sala completa")
    db.execute("INSERT OR REPLACE INTO lobby_members(lobby_code, user_id, slot, ready, joined_at)"
               " VALUES(?,?,?,?,?)", (code, user["id"], None, 0, iso()))
    db.execute("INSERT INTO audit_log(at, actor_id, action, detail) VALUES(?,?,?,?)",
               (iso(), user["id"], "lobby_join", code))
    return _play_payload(config, dict(lobby), rejoin=True)


def state(code: str) -> dict:
    lobby = db.query_one("SELECT * FROM lobbies WHERE code=?", (code.upper(),))
    if not lobby:
        raise NotFound("sala no encontrada")
    members = db.query(
        "SELECT lm.user_id, u.name, lm.slot, lm.ready, lm.joined_at"
        "  FROM lobby_members lm JOIN users u ON u.id = lm.user_id"
        " WHERE lm.lobby_code=? ORDER BY lm.slot IS NULL, lm.slot, lm.joined_at",
        (lobby["code"],),
    )
    return {
        "code": lobby["code"],
        "ownerId": lobby["owner_id"],
        "host": lobby["host"],
        "port": lobby["port"],
        "private": bool(lobby["is_private"]),
        "expiresAt": lobby["expires_at"],
        "closed": bool(lobby["closed_at"]),
        "members": [dict(m) for m in members],
    }


def close(user: dict, code: str) -> dict:
    lobby = db.query_one("SELECT * FROM lobbies WHERE code=?", (code.upper(),))
    if not lobby:
        raise NotFound("sala no encontrada")
    if lobby["owner_id"] != user["id"]:
        raise Conflict("solo el anfitrión puede cerrar la sala")
    db.execute("UPDATE lobbies SET closed_at=? WHERE code=?", (iso(), lobby["code"]))
    return {"code": lobby["code"], "closed": True}


def active_for_user(user_id: int) -> dict | None:
    row = db.query_one(
        "SELECT l.* FROM lobbies l JOIN lobby_members m ON m.lobby_code = l.code"
        " WHERE m.user_id=? AND l.closed_at IS NULL AND l.expires_at > ?"
        " ORDER BY l.created_at DESC LIMIT 1", (user_id, iso()))
    return dict(row) if row else None
