"""Perfiles, nombres, avatares y estadísticas por jugador."""
from __future__ import annotations

from ..db import connection as db
from ..domain import elo
from ..domain.validation import ValidationError, clean_text, validate_hero, validate_name
from ..errors import Conflict, NotFound
from ..util import iso


def _row_to_profile(row) -> dict:
    return {
        "userId": row["id"],
        "name": row["name"],
        "avatarHero": row["avatar_hero"],
        "rating": round(row["rating"], 1),
        "tier": elo.tier(row["rating"]),
        "games": row["games"],
        "wins": row["wins"],
        "losses": max(0, row["games"] - row["wins"]),
        "winrate": round(100.0 * row["wins"] / row["games"], 1) if row["games"] else None,
        "createdAt": row["created_at"],
    }


def get(user_id: int) -> dict:
    row = db.query_one("SELECT * FROM users WHERE id=?", (user_id,))
    if not row:
        raise NotFound("jugador no encontrado")
    return _row_to_profile(row)


def me(user: dict) -> dict:
    prof = get(user["id"])
    prof["nextRename"] = None
    prof["nameSet"] = bool(user["name_set"])
    return prof


def rename(user: dict, name: object) -> dict:
    try:
        new_name = validate_name(name)
    except ValidationError as exc:
        return {"name": clean_text(name, 24), "problem": exc.code, "ok": False}
    other = db.query_one("SELECT id FROM users WHERE name=? COLLATE NOCASE AND id<>?",
                         (new_name, user["id"]))
    if other:
        return {"name": new_name, "problem": "taken", "ok": False}
    db.execute("UPDATE users SET name=?, name_set=1 WHERE id=?", (new_name, user["id"]))
    db.execute("INSERT INTO audit_log(at, actor_id, action, detail) VALUES(?,?,?,?)",
               (iso(), user["id"], "rename", new_name))
    return {"name": new_name, "problem": None, "ok": True}


def check_name(name: object) -> dict:
    try:
        candidate = validate_name(name)
    except ValidationError as exc:
        return {"name": clean_text(name, 24), "problem": exc.code, "ok": False}
    if db.query_one("SELECT 1 FROM users WHERE name=? COLLATE NOCASE", (candidate,)):
        return {"name": candidate, "problem": "taken", "ok": False}
    return {"name": candidate, "problem": None, "ok": True}


def set_avatar(user: dict, hero: object) -> dict:
    try:
        hero_key = validate_hero(hero)
    except ValidationError as exc:
        raise Conflict(exc.code) from exc
    db.execute("UPDATE users SET avatar_hero=? WHERE id=?", (hero_key or None, user["id"]))
    return get(user["id"])


def hero_stats(user_id: int) -> list[dict]:
    rows = db.query(
        "SELECT COALESCE(hero,'') AS hero, COUNT(*) AS games,"
        "       SUM(CASE WHEN lower(result)='win' THEN 1 ELSE 0 END) AS wins,"
        "       ROUND(AVG(kills),1) AS kills, ROUND(AVG(deaths),1) AS deaths,"
        "       ROUND(AVG(assists),1) AS assists, ROUND(AVG(rating_delta),1) AS ratingDelta"
        "  FROM match_players WHERE user_id=? AND COALESCE(hero,'')<>''"
        " GROUP BY hero ORDER BY games DESC, wins DESC",
        (user_id,),
    )
    return [{**dict(r),
             "winrate": round(100.0 * (r["wins"] or 0) / r["games"], 1) if r["games"] else None}
            for r in rows]


def recent_matches(user_id: int, limit: int = 20) -> list[dict]:
    rows = db.query(
        "SELECT m.id, m.mode, m.duration_s, m.created_at, p.hero, p.team, p.result,"
        "       p.kills, p.deaths, p.assists, p.rating_delta"
        "  FROM match_players p JOIN matches m ON m.id = p.match_id"
        " WHERE p.user_id=? ORDER BY m.created_at DESC LIMIT ?",
        (user_id, limit),
    )
    return [dict(r) for r in rows]
