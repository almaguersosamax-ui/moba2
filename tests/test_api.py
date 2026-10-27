"""Pruebas de extremo a extremo contra el servidor real (sin dependencias externas).

    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import base64
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moba2.config import Config                      # noqa: E402
from moba2.db import connection as db                # noqa: E402
from moba2.db import migrations                      # noqa: E402
from moba2.domain import elo                         # noqa: E402
from moba2.web.app import make_server                # noqa: E402


class ServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.config = replace(Config(), db_path=Path(cls.tmp.name) / "test.db",
                             host_ip="192.168.1.105", http_port=0, access_log=False,
                             report_hmac_key="clave-de-prueba")
        db.configure(cls.config.db_path)
        migrations.migrate()
        cls.server = make_server(cls.config)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    # ---------------------------------------------------------------- helpers
    def call(self, method: str, path: str, body: dict | None = None, token: str | None = None,
             headers: dict | None = None):
        url = f"http://127.0.0.1:{self.port}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                raw = response.read()
                ctype = response.headers.get("Content-Type", "")
                return response.status, (json.loads(raw) if "json" in ctype else raw.decode())
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw)
            except json.JSONDecodeError:
                return exc.code, raw.decode()

    def login(self, device: str, name: str) -> dict:
        status, data = self.call("POST", "/v1/auth/device",
                                 {"deviceId": device, "secret": "s3cr3t", "name": name})
        self.assertEqual(status, 200, data)
        return data

    # ------------------------------------------------------------------ casos
    def test_health(self):
        status, data = self.call("GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["protocol"], 6)

    def test_login_y_perfil(self):
        user = self.login("dev-perfil", "PerfilTester")
        status, me = self.call("GET", "/v1/me", token=user["token"])
        self.assertEqual(status, 200)
        self.assertEqual(me["name"], "PerfilTester")
        status, profile = self.call("GET", "/v1/users/me/profile", token=user["token"])
        self.assertEqual(profile["rating"], 1000.0)
        self.assertEqual(profile["tier"], "Arconte")
        self.assertIsNone(profile["winrate"])

    def test_login_sin_token(self):
        status, data = self.call("GET", "/v1/me")
        self.assertEqual(status, 401)
        self.assertIn("title", data)

    def test_nombres(self):
        self.login("dev-nombres", "NombreBase")
        status, data = self.call("GET", "/v1/names/check?n=ab")
        self.assertEqual(status, 200)
        self.assertFalse(data["ok"])
        status, data = self.call("GET", "/v1/names/check?n=<script>")
        self.assertFalse(data["ok"])
        status, data = self.call("GET", "/v1/names/check?n=Libre%d" % 1)
        self.assertTrue(data["ok"])

    def test_salas(self):
        user = self.login("dev-sala", "Anfitrion")
        status, play = self.call("POST", "/v1/play", {"name": "Anfitrion", "protocol": 6},
                                 token=user["token"])
        self.assertEqual(status, 200, play)
        self.assertEqual(play["host"], "192.168.1.105")
        self.assertEqual(play["port"], 27015)
        # el cliente usa códigos de 4 letras de ABCDEFGHJKLMNPQRSTUVWXYZ
        self.assertEqual(len(play["lobby"]), 4)
        self.assertRegex(play["lobby"], r"^[ABCDEFGHJKLMNPQRSTUVWXYZ]{4}$")
        # sessionKey debe ser Base64 válido de 32 bytes (el cliente lo convierte a byte[])
        self.assertEqual(len(base64.b64decode(play["sessionKey"], validate=True)), 32)
        self.assertEqual(play["port"], 27015)
        guest = self.login("dev-guest", "Invitado")
        status, joined = self.call("POST", "/v1/lobbies/join",
                                   {"code": play["lobby"], "protocol": 6}, token=guest["token"])
        self.assertEqual(status, 200, joined)
        self.assertEqual(joined["sessionKey"], play["sessionKey"])
        status, state = self.call("GET", f"/v1/lobbies/{play['lobby']}")
        self.assertEqual(len(state["members"]), 2)
        status, data = self.call("POST", "/v1/lobbies/join", {"code": "ZZZZ"},
                                 token=guest["token"])
        self.assertEqual(status, 404)
        # código con letras que el cliente no usa (I/O) o longitud mala -> 404, no 500
        status, data = self.call("POST", "/v1/lobbies/join", {"code": "NOISE"},
                                 token=guest["token"])
        self.assertEqual(status, 404)

    def test_reporte_y_elo(self):
        a = self.login("dev-elo-a", "EloA")
        b = self.login("dev-elo-b", "EloB")
        report = {
            "matchId": "m-elo-1", "mode": "normal", "duration": 1800, "version": "1.1",
            "players": [
                {"name": "EloA", "hero": "antimage", "team": "radiant", "result": "win",
                 "kills": 12, "deaths": 3, "assists": 5},
                {"name": "EloB", "hero": "axe", "team": "dire", "result": "loss",
                 "kills": 3, "deaths": 12, "assists": 2},
            ],
        }
        status, data = self.call("POST", "/v1/matches", report)
        self.assertEqual(status, 200, data)
        self.assertEqual(data["stored"], 2)
        self.assertFalse(data["signatureOk"])

        # duplicado: no vuelve a puntuar
        status, dup = self.call("POST", "/v1/matches", report)
        self.assertTrue(dup["duplicate"])

        status, pa = self.call("GET", "/v1/users/me/profile", token=a["token"])
        status, pb = self.call("GET", "/v1/users/me/profile", token=b["token"])
        self.assertGreater(pa["rating"], 1000.0)
        self.assertLess(pb["rating"], 1000.0)
        self.assertEqual(pa["games"], 1)
        self.assertEqual(pa["wins"], 1)
        self.assertAlmostEqual(pa["rating"] + pb["rating"], 2000.0, places=1)

        status, heroes = self.call("GET", "/v1/users/me/heroes", token=a["token"])
        self.assertEqual(heroes[0]["hero"], "antimage")
        self.assertEqual(heroes[0]["winrate"], 100.0)

    def test_firma_hmac(self):
        status, data = self.call("POST", "/v1/matches", {"matchId": "m-sig", "players": []},
                                 headers={"X-Dota-Timestamp": "1700000000",
                                          "X-Dota-Signature": "v1=deadbeef"})
        self.assertEqual(status, 200)
        self.assertFalse(data["signatureOk"])

    def test_historial_y_panel(self):
        status, matches = self.call("GET", "/v1/matches?limit=5")
        self.assertEqual(status, 200)
        self.assertIsInstance(matches, list)
        status, html = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("Clasificación", html)
        status, html = self.call("GET", "/heroes")
        self.assertEqual(status, 200)
        status, html = self.call("GET", "/static/style.css")
        self.assertEqual(status, 200)

    def test_paginas_por_jugador_y_partida(self):
        user = self.login("dev-paginas", "PaginasTester")
        self.call("POST", "/v1/matches", {"matchId": "m-pagina", "duration": 900,
                                          "players": [{"name": "PaginasTester", "hero": "lion",
                                                       "team": "radiant", "result": "win"}]})
        status, html = self.call("GET", f"/player/{user['userId']}")
        self.assertEqual(status, 200)
        self.assertIn("PaginasTester", html)
        status, html = self.call("GET", "/match/m-pagina")
        self.assertEqual(status, 200)
        self.assertIn("lion", html)

    def test_ruta_desconocida(self):
        status, _ = self.call("GET", "/v1/no-existe")
        self.assertEqual(status, 404)


class EloUnit(unittest.TestCase):
    def test_k_factor(self):
        self.assertEqual(elo.k_factor(0), 40.0)
        self.assertEqual(elo.k_factor(50), 24.0)
        self.assertEqual(elo.k_factor(200), 16.0)

    def test_sin_dos_equipos_no_hay_delta(self):
        players = [elo.PlayerRating(1, 1000, 0, "radiant", "win")]
        self.assertEqual(elo.compute(players), {1: 0.0})

    def test_empate(self):
        players = [elo.PlayerRating(1, 1000, 10, "a", "draw"),
                   elo.PlayerRating(2, 1000, 10, "b", "draw")]
        deltas = elo.compute(players)
        self.assertEqual(deltas, {1: 0.0, 2: 0.0})

    def test_suelo(self):
        self.assertEqual(elo.apply(101.0, -50.0), 100.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
