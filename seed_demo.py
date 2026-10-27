#!/usr/bin/env python3
"""Genera partidas de ejemplo para ver el panel con datos (útil para probar sin jugar).

    python3 seed_demo.py --url http://127.0.0.1:8080 --players 8 --matches 20
"""
from __future__ import annotations

import argparse
import json
import random
import urllib.request

HEROES = ["antimage", "axe", "crystal_maiden", "juggernaut", "invoker", "lion", "pudge",
          "storm_spirit", "sniper", "templar_assassin", "faceless_void", "lina"]
NAMES = ["Carlos", "Yanet", "Ernesto", "Lázaro", "Mabel", "Randy", "Yusimi", "Alejandro",
         "Dayana", "Osmany"]


def call(url: str, method: str, path: str, body: dict | None = None, token: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--players", type=int, default=8)
    ap.add_argument("--matches", type=int, default=20)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    rnd = random.Random(a.seed)

    players = []
    for i in range(a.players):
        name = NAMES[i % len(NAMES)] + ("" if i < len(NAMES) else str(i))
        players.append(call(a.url, "POST", "/v1/auth/device",
                            {"deviceId": f"seed-{i}", "secret": "seed", "name": name}))

    for m in range(a.matches):
        team_a = rnd.sample(players, min(2, len(players)))
        team_b = rnd.sample([p for p in players if p not in team_a], min(2, len(players)))
        winner = rnd.random()
        rows = []
        for team, members in (("radiant", team_a), ("dire", team_b)):
            for p in members:
                win = (team == "radiant") == (winner > 0.5)
                rows.append({
                    "name": p["name"], "hero": rnd.choice(HEROES), "team": team,
                    "result": "win" if win else "loss",
                    "kills": rnd.randint(0, 18), "deaths": rnd.randint(0, 14),
                    "assists": rnd.randint(0, 20),
                })
        call(a.url, "POST", "/v1/matches",
             {"matchId": f"demo-{m:03d}", "mode": rnd.choice(["normal", "ranked"]),
              "duration": rnd.randint(1200, 3600), "version": "1.1", "players": rows})
    print(f"listo: {a.matches} partidas para {len(players)} jugadores · abre {a.url}/")


if __name__ == "__main__":
    main()
