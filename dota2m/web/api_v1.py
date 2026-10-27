"""API compatible con el cliente: /v1/*."""
from __future__ import annotations

from ..config import Config
from ..errors import NotFound, Unauthorized
from ..domain.validation import clean_text
from ..services import auth, leaderboard, lobbies, matches, users
from .router import Request, Router


def build_router(config: Config) -> Router:
    r = Router()

    # ---------------------------------------------------------------- auth
    def device_login(req: Request):
        return 200, auth.login(config, req.json()), "application/json"

    def me(req: Request):
        return 200, users.me(_user(req)), "application/json"

    def profiles(req: Request):
        return 200, users.get(_user(req)["id"]), "application/json"

    def profile_by_id(req: Request):
        return 200, users.get(int(req.params["user_id"])), "application/json"

    def my_heroes(req: Request):
        return 200, users.hero_stats(_user(req)["id"]), "application/json"

    def heroes_by_id(req: Request):
        return 200, users.hero_stats(int(req.params["user_id"])), "application/json"

    def set_name(req: Request):
        return 200, users.rename(_user(req), (req.json() or {}).get("name")), "application/json"

    def check_name(req: Request):
        return 200, users.check_name(req.q("n")), "application/json"

    def set_profile(req: Request):
        body = req.json()
        hero = body.get("avatarHero", body.get("avatar_hero"))
        return 200, users.set_avatar(_user(req), hero), "application/json"

    # --------------------------------------------------------------- salas
    def play(req: Request):
        return 200, lobbies.create(config, _user(req), req.json(), req.client), "application/json"

    def join(req: Request):
        return 200, lobbies.join(config, _user(req), req.json()), "application/json"

    def lobby_state(req: Request):
        return 200, lobbies.state(req.params["code"]), "application/json"

    def lobby_close(req: Request):
        return 200, lobbies.close(_user(req), req.params["code"]), "application/json"

    # -------------------------------------------------------------- partidas
    def list_matches(req: Request):
        limit = req.q_int("limit", 20, maximum=200)
        scope = req.q("user", "all")
        uid = _user(req)["id"] if scope == "me" else (
            int(scope) if scope.isdigit() else None)
        return 200, [dict(m) for m in matches.recent(limit, uid)], "application/json"

    def get_match(req: Request):
        return 200, matches.get(req.params["match_id"]), "application/json"

    def post_match(req: Request):
        body = req.json()
        ok = matches.verify_signature(config, req.headers, body)
        return 200, matches.ingest(config, body, ok), "application/json"

    # ---------------------------------------------------------- clasificación
    def board(req: Request):
        return 200, {"players": leaderboard.players(req.q_int("limit", 50, maximum=200),
                                                    req.q_int("minGames", 0, maximum=1000)),
                     "heroes": leaderboard.heroes(25),
                     "overview": leaderboard.overview()}, "application/json"

    def health(req: Request):
        return 200, {"ok": True, "protocol": config.protocol, "version": config.server_version,
                     "udp": f"{config.host_ip}:{config.udp_port}"}, "application/json"

    # ----------------------------------------------------------------- rutas
    r.add("POST", "/v1/auth/device", device_login)
    r.add("GET", "/v1/me", me)
    r.add("GET", "/v1/users/me/profile", profiles)
    r.add("GET", "/v1/users/{user_id}/profile", profile_by_id)
    r.add("GET", "/v1/me/profile", profiles)
    r.add("PUT", "/v1/me/profile", set_profile)
    r.add("POST", "/v1/me/profile", set_profile)
    r.add("POST", "/v1/me/name", set_name)
    r.add("PUT", "/v1/me/name", set_name)
    r.add("GET", "/v1/names/check", check_name)
    r.add("GET", "/v1/users/me/heroes", my_heroes)
    r.add("GET", "/v1/users/{user_id}/heroes", heroes_by_id)
    r.add("POST", "/v1/play", play)
    r.add("POST", "/v1/lobbies", play)
    r.add("POST", "/v1/lobbies/join", join)
    r.add("GET", "/v1/lobbies/{code}", lobby_state)
    r.add("DELETE", "/v1/lobbies/{code}", lobby_close)
    r.add("GET", "/v1/matches", list_matches)
    r.add("GET", "/v1/matches/{match_id}", get_match)
    r.add("POST", "/v1/matches", post_match)
    r.add("POST", "/v1/report", post_match)
    r.add("GET", "/v1/leaderboard", board)
    r.add("GET", "/healthz", health)
    r.add("GET", "/v1/health", health)
    return r


def _user(req: Request) -> dict:
    token = req.bearer()
    if not token:
        raise Unauthorized("falta el token")
    return auth.resolve(token)
