"""Cálculo de rating (ELO por equipos, con K adaptativo por experiencia)."""
from __future__ import annotations

from dataclasses import dataclass

BASE_RATING = 1000.0
FLOOR = 100.0
MIN_K = 16.0
MAX_K = 40.0


@dataclass(slots=True)
class PlayerRating:
    user_id: int
    rating: float
    games: int
    team: str
    result: str          # win | loss | draw


def k_factor(games: int) -> float:
    """Cuanto menos jugado, más se mueve el rating (convergencia más rápida)."""
    if games < 10:
        return MAX_K
    if games < 30:
        return 32.0
    if games < 80:
        return 24.0
    return MIN_K


def expected_score(rating: float, opponent_rating: float) -> float:
    return 1.0 / (1.0 + 10 ** ((opponent_rating - rating) / 400.0))


def _score(result: str) -> float:
    r = (result or "").strip().lower()
    if r in ("win", "w", "victory", "radiant_win", "dire_win"):
        return 1.0
    if r in ("draw", "tie"):
        return 0.5
    return 0.0


def compute(players: list[PlayerRating]) -> dict[int, float]:
    """Devuelve {user_id: delta}. Si falta un equipo o los resultados, devuelve 0."""
    if not players:
        return {}
    teams: dict[str, list[PlayerRating]] = {}
    for p in players:
        teams.setdefault((p.team or "").strip().lower(), []).append(p)
    if len(teams) != 2:
        # sin dos equipos identificables no se puede emparejar: no se toca el rating
        return {p.user_id: 0.0 for p in players}

    (team_a, members_a), (team_b, members_b) = list(teams.items())
    avg_a = sum(m.rating for m in members_a) / len(members_a)
    avg_b = sum(m.rating for m in members_b) / len(members_b)
    exp_a = expected_score(avg_a, avg_b)
    exp_b = 1.0 - exp_a

    score_a = sum(_score(m.result) for m in members_a) / len(members_a)
    score_b = 1.0 - score_a

    deltas: dict[int, float] = {}
    for m in members_a:
        deltas[m.user_id] = round(k_factor(m.games) * (score_a - exp_a), 2)
    for m in members_b:
        deltas[m.user_id] = round(k_factor(m.games) * (score_b - exp_b), 2)
    return deltas


def apply(rating: float, delta: float) -> float:
    return max(FLOOR, round(rating + delta, 2))


def tier(rating: float) -> str:
    """Etiqueta cualitativa para el panel."""
    for limit, name in ((1400, "Inmortal"), (1300, "Divino"), (1200, "Ancestral"),
                        (1100, "Leyenda"), (1000, "Arconte"), (900, "Cruzado")):
        if rating >= limit:
            return name
    return "Heraldo"
