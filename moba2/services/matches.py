"""Ingesta de reportes de partida, deduplicación y actualización de ratings."""
from __future__ import annotations

import hashlib
import hmac
import json

from ..config import Config
from ..db import connection as db
from ..domain import elo
from ..protocol import SIGNATURE_HEADER, TIMESTAMP_HEADER
from ..domain.validation import clean_text
from ..errors import ApiError
from ..util import iso, new_token

MAX_PLAYERS = 16
RESULT_WIN = {"win", "w", "victory"}


def verify_signature(config: Config, headers: dict, body: dict) -> bool:
    """Comprueba la firma del reporte (v1 = HMAC-SHA256 sobre 'ts.' + json compacto)."""
    if not config.report_hmac_key:
        return False
    signature = (headers.get(SIGNATURE_HEADER.lower()) or "").strip()
    timestamp = (headers.get(TIMESTAMP_HEADER.lower()) or "").strip()
    if not signature.startswith("v1=") or not timestamp:
        return False
    payload = f"{timestamp}.".encode() + json.dumps(body, separators=(",", ":")).encode()
    expected = hmac.new(config.report_hmac_key.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature[3:])


def _match_id(body: dict) -> str:
    raw = clean_text(body.get("matchId") or body.get("id"), 64)
    if raw:
        return raw
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return f"auto-{digest[:12]}"


def _players(body: dict) -> list[dict]:
    raw = body.get("players")
    if isinstance(raw, list) and raw:
        return [p for p in raw if isinstance(p, dict)][:MAX_PLAYERS]
    return [body]


def ingest(config: Config, body: dict, signature_ok: bool) -> dict:
    if not isinstance(body, dict) or not body:
        raise ApiError("payload vacío", code="invalid_payload")
    match_id = _match_id(body)
    players = _players(body)
    mode = clean_text(body.get("mode"), 32)
    duration = int(body.get("duration") or body.get("durationS") or 0)
    version = clean_text(body.get("version"), 16)
    lobby = clean_text(body.get("lobby"), 8).upper() or None

    if db.query_one("SELECT 1 FROM matches WHERE id=?", (match_id,)):
        return {"ok": True, "matchId": match_id, "stored": 0, "duplicate": True,
                "signatureOk": signature_ok}

    # 1) resolver identidades y ratings previos
    resolved: list[dict] = []
    for seat, p in enumerate(players):
        name = clean_text(p.get("name") or p.get("player"), 24)
        user = db.query_one("SELECT * FROM users WHERE name=? COLLATE NOCASE", (name,)) if name else None
        resolved.append({
            "seat": seat,
            "user_id": user["id"] if user else None,
            "name": name or f"Player {seat + 1}",
            "hero": clean_text(p.get("hero"), 64).lower() or None,
            "team": (clean_text(p.get("team"), 16) or "").lower() or None,
            "result": (clean_text(p.get("result"), 16) or "").lower() or None,
            "kills": int(p.get("kills") or 0),
            "deaths": int(p.get("deaths") or 0),
            "assists": int(p.get("assists") or 0),
            "rating": float(user["rating"]) if user else elo.BASE_RATING,
            "games": int(user["games"]) if user else 0,
        })

    # 2) ELO por equipos
    rated = [elo.PlayerRating(user_id=r["user_id"], rating=r["rating"], games=r["games"],
                              team=r["team"] or "", result=r["result"] or "")
             for r in resolved if r["user_id"] is not None]
    deltas = elo.compute(rated)

    with db.transaction() as con:
        con.execute(
            "INSERT INTO matches(id, mode, duration_s, version, lobby_code, signature_ok, raw,"
            " reported_at, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (match_id, mode, duration, version, lobby, 1 if signature_ok else 0,
             json.dumps(body, ensure_ascii=False)[:20000], iso(), iso()),
        )
        for r in resolved:
            delta = deltas.get(r["user_id"], 0.0) if r["user_id"] else None
            after = elo.apply(r["rating"], delta) if (r["user_id"] and delta is not None) else None
            con.execute(
                "INSERT INTO match_players(match_id, seat, user_id, display_name, hero, team, result,"
                " kills, deaths, assists, rating_before, rating_after, rating_delta)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (match_id, r["seat"], r["user_id"], r["name"], r["hero"], r["team"], r["result"],
                 r["kills"], r["deaths"], r["assists"],
                 r["rating"] if r["user_id"] else None, after, delta),
            )
            if r["user_id"] and delta is not None:
                won = 1 if (r["result"] or "") in RESULT_WIN else 0
                con.execute("UPDATE users SET rating=?, games=games+1, wins=wins+?,"
                            " last_seen_at=? WHERE id=?",
                            (after, won, iso(), r["user_id"]))
                con.execute("INSERT INTO rating_events(user_id, match_id, rating_before,"
                            " rating_after, delta, created_at) VALUES(?,?,?,?,?,?)",
                            (r["user_id"], match_id, r["rating"], after, delta, iso()))
        con.execute("INSERT INTO audit_log(at, actor_id, action, detail) VALUES(?,?,?,?)",
                    (iso(), None, "match_ingest", match_id))
    return {"ok": True, "matchId": match_id, "stored": len(resolved), "duplicate": False,
            "signatureOk": signature_ok}


def get(match_id: str) -> dict:
    match = db.query_one("SELECT * FROM matches WHERE id=?", (match_id,))
    if not match:
        from ..errors import NotFound
        raise NotFound("partida no encontrada")
    players = db.query("SELECT * FROM match_players WHERE match_id=? ORDER BY seat", (match_id,))
    return {**dict(match), "players": [dict(p) for p in players]}


def recent(limit: int = 20, user_id: int | None = None) -> list[dict]:
    if user_id:
        rows = db.query(
            "SELECT m.* FROM matches m JOIN match_players p ON p.match_id = m.id"
            " WHERE p.user_id=? ORDER BY m.created_at DESC LIMIT ?", (user_id, limit))
    else:
        rows = db.query("SELECT * FROM matches ORDER BY created_at DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]


def create_test(config: Config, body: dict) -> dict:
    """Utilidad de administración: genera un reporte sintético (para probar el panel)."""
    payload = dict(body)
    payload.setdefault("matchId", f"test-{new_token()[:10]}")
    return ingest(config, payload, signature_ok=False)
