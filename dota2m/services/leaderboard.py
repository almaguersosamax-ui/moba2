"""Clasificación y estadísticas agregadas para el panel."""
from __future__ import annotations

from ..db import connection as db
from ..domain import elo


def players(limit: int = 50, min_games: int = 0) -> list[dict]:
    rows = db.query(
        "SELECT id, name, rating, games, wins, avatar_hero FROM users"
        " WHERE games >= ? ORDER BY rating DESC, games DESC LIMIT ?",
        (min_games, limit),
    )
    out = []
    for i, r in enumerate(rows, start=1):
        out.append({
            "position": i,
            "userId": r["id"],
            "name": r["name"],
            "rating": round(r["rating"], 1),
            "tier": elo.tier(r["rating"]),
            "games": r["games"],
            "wins": r["wins"],
            "winrate": round(100.0 * r["wins"] / r["games"], 1) if r["games"] else None,
            "avatarHero": r["avatar_hero"],
        })
    return out


def heroes(limit: int = 25) -> list[dict]:
    rows = db.query(
        "SELECT hero, COUNT(*) AS games,"
        "       SUM(CASE WHEN lower(result)='win' THEN 1 ELSE 0 END) AS wins,"
        "       ROUND(AVG(kills),1) AS kills, ROUND(AVG(deaths),1) AS deaths,"
        "       ROUND(AVG(assists),1) AS assists"
        "  FROM match_players WHERE COALESCE(hero,'')<>''"
        " GROUP BY hero ORDER BY games DESC LIMIT ?",
        (limit,),
    )
    return [{**dict(r), "winrate": round(100.0 * (r["wins"] or 0) / r["games"], 1) if r["games"] else None}
            for r in rows]


def overview() -> dict:
    row = db.query_one(
        "SELECT (SELECT COUNT(*) FROM users) AS players,"
        "       (SELECT COUNT(*) FROM matches) AS matches,"
        "       (SELECT COALESCE(SUM(duration_s),0) FROM matches) AS seconds,"
        "       (SELECT COUNT(*) FROM lobbies WHERE closed_at IS NULL) AS lobbies")
    return dict(row)


def daily(limit: int = 14) -> list[dict]:
    rows = db.query(
        "SELECT substr(created_at,1,10) AS day, COUNT(*) AS matches"
        "  FROM matches GROUP BY day ORDER BY day DESC LIMIT ?", (limit,))
    return [dict(r) for r in reversed(rows)]
