"""Panel web (HTML) de estadísticas."""
from __future__ import annotations

import html
from pathlib import Path

from ..config import Config
from ..db import connection as db
from ..domain import elo
from ..errors import NotFound
from ..services import leaderboard, matches, users
from ..util import parse_iso
from .templating import render

STATIC = Path(__file__).parent / "static"


def _layout(config: Config, title: str, content: str) -> str:
    ov = leaderboard.overview()
    return render("base.html", title=title, content=content,
                  udp_host=f"{config.host_ip}:{config.udp_port}", protocol=config.protocol,
                  matches=ov["matches"], players=ov["players"])


def _fmt_duration(seconds: int | None) -> str:
    seconds = int(seconds or 0)
    return f"{seconds // 60}:{seconds % 60:02d}"


def _fmt_date(value: str | None) -> str:
    dt = parse_iso(value)
    return dt.strftime("%d/%m %H:%M") if dt else (value or "-")


def index(config: Config) -> str:
    ov = leaderboard.overview()
    rows = []
    for p in leaderboard.players(limit=50):
        rows.append(
            f"<tr><td>{p['position']}</td>"
            f"<td><a href='/player/{p['userId']}'>{html.escape(p['name'])}</a></td>"
            f"<td>{p['rating']:.0f}</td><td>{p['tier']}</td><td>{p['games']}</td>"
            f"<td>{p['wins']}</td><td>{p['winrate'] if p['winrate'] is not None else '-'}</td></tr>")
    recent = []
    for m in matches.recent(15):
        det = matches.get(m["id"])
        winners = {p["team"] for p in det["players"] if (p["result"] or "") == "win"}
        recent.append(
            f"<tr><td>{_fmt_date(m['created_at'])}</td>"
            f"<td><a href='/match/{html.escape(m['id'])}'>{html.escape(m['id'][:18])}</a></td>"
            f"<td>{html.escape(m['mode'] or 'normal')}</td><td>{_fmt_duration(m['duration_s'])}</td>"
            f"<td>{html.escape(', '.join(sorted(winners)) or '-')}</td></tr>")
    content = render("index.html",
                     players=ov["players"], match_count=ov["matches"],
                     hours=f"{ov['seconds'] / 3600:.1f}", lobbies=ov["lobbies"],
                     rows="".join(rows) or "<tr><td colspan=7>Aún no hay jugadores</td></tr>",
                     recent="".join(recent) or "<tr><td colspan=5>Sin partidas todavía</td></tr>")
    return _layout(config, "Clasificación", content)


def heroes_page(config: Config) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(h['hero'])}</td><td>{h['games']}</td><td>{h['wins'] or 0}</td>"
        f"<td>{h['winrate'] if h['winrate'] is not None else '-'}</td>"
        f"<td>{h['kills'] or 0}/{h['deaths'] or 0}/{h['assists'] or 0}</td></tr>"
        for h in leaderboard.heroes(40)) or "<tr><td colspan=5>Sin datos</td></tr>"
    return _layout(config, "Héroes", render("heroes.html", rows=rows))


def player_page(config: Config, user_id: int) -> str:
    try:
        prof = users.get(user_id)
    except NotFound:
        raise
    heroes = users.hero_stats(user_id)
    hrows = "".join(
        f"<tr><td>{html.escape(h['hero'])}</td><td>{h['games']}</td><td>{h['wins'] or 0}</td>"
        f"<td>{h['winrate'] if h['winrate'] is not None else '-'}</td>"
        f"<td>{h['kills'] or 0}/{h['deaths'] or 0}/{h['assists'] or 0}</td>"
        f"<td>{h['ratingDelta'] or 0:+.1f}</td></tr>" for h in heroes) or \
        "<tr><td colspan=6>Sin partidas</td></tr>"
    mrows = "".join(
        f"<tr><td>{_fmt_date(m['created_at'])}</td>"
        f"<td><a href='/match/{html.escape(m['id'])}'>{html.escape(m['id'][:18])}</a></td>"
        f"<td>{html.escape(m['hero'] or '-')}</td>"
        f"<td class='{(m['result'] or '').lower()}'>{html.escape(m['result'] or '-')}</td>"
        f"<td>{m['kills']}/{m['deaths']}/{m['assists']}</td>"
        f"<td>{(m['rating_delta'] or 0):+.1f}</td></tr>"
        for m in users.recent_matches(user_id, 25)) or "<tr><td colspan=6>Sin partidas</td></tr>"

    totals = db.query_one(
        "SELECT ROUND(AVG(kills),1) k, ROUND(AVG(deaths),1) d, ROUND(AVG(assists),1) a"
        "  FROM match_players WHERE user_id=?", (user_id,))
    kda = f"{totals['k'] or 0}/{totals['d'] or 0}/{totals['a'] or 0}"
    content = render("player.html", name=prof["name"], tier=prof["tier"],
                     rating=f"{prof['rating']:.0f}", games=prof["games"], wins=prof["wins"],
                     winrate=f"{prof['winrate']}%" if prof["winrate"] is not None else "-",
                     kda=kda, heroes=hrows, matches=mrows)
    return _layout(config, prof["name"], content)


def match_page(config: Config, match_id: str) -> str:
    m = matches.get(match_id)
    rows = "".join(
        f"<tr><td>{p['seat'] + 1}</td>"
        f"<td>{('<a href=/player/%d>%s</a>' % (p['user_id'], html.escape(p['display_name']))) if p['user_id'] else html.escape(p['display_name'])}</td>"
        f"<td>{html.escape(p['hero'] or '-')}</td><td>{html.escape(p['team'] or '-')}</td>"
        f"<td class='{(p['result'] or '').lower()}'>{html.escape(p['result'] or '-')}</td>"
        f"<td>{p['kills']}/{p['deaths']}/{p['assists']}</td>"
        f"<td>{(p['rating_delta'] or 0):+.1f}</td></tr>" for p in m["players"])
    content = render("match.html", id=m["id"], mode=m["mode"] or "normal",
                     duration=_fmt_duration(m["duration_s"]),
                     created_at=_fmt_date(m["created_at"]),
                     signature="válida" if m["signature_ok"] else "sin verificar",
                     rows=rows or "<tr><td colspan=7>Sin jugadores</td></tr>")
    return _layout(config, f"Partida {m['id'][:12]}", content)


def live_tiers() -> list[dict]:
    """Escalones de rango (para la leyenda del panel)."""
    return [{"name": name, "from": limit} for limit, name in
            ((1400, "Inmortal"), (1300, "Divino"), (1200, "Ancestral"), (1100, "Leyenda"),
             (1000, "Arconte"), (900, "Cruzado"), (0, "Heraldo"))]
