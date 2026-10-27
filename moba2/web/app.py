"""Capa HTTP: enlaza router + API + panel y sirve con ThreadingHTTPServer."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
import mimetypes
import signal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from ..config import Config
from ..db import connection as db
from ..errors import ApiError, NotFound
from . import dashboard
from .api_v1 import build_router
from .router import Request, Router

log = logging.getLogger("moba2.http")
MAX_BODY = 2 * 1024 * 1024


def build(config: Config) -> Router:
    api = build_router(config)
    web = Router()

    def page_index(req: Request):
        return 200, dashboard.index(config), "text/html; charset=utf-8"

    def page_heroes(req: Request):
        return 200, dashboard.heroes_page(config), "text/html; charset=utf-8"

    def page_player(req: Request):
        return 200, dashboard.player_page(config, int(req.params["user_id"])), "text/html; charset=utf-8"

    def page_match(req: Request):
        return 200, dashboard.match_page(config, req.params["match_id"]), "text/html; charset=utf-8"

    def static(req: Request):
        path = dashboard.STATIC / req.params["file"]
        if not path.is_file() or ".." in req.params["file"]:
            raise NotFound("recurso no encontrado")
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return 200, path.read_bytes(), ctype

    web.add("GET", "/", page_index)
    web.add("GET", "/heroes", page_heroes)
    web.add("GET", "/player/{user_id}", page_player)
    web.add("GET", "/match/{match_id}", page_match)
    web.add("GET", "/static/{file}", static)

    web.extend(api)
    return web


def _trace_write(config: Config, record: dict) -> None:
    """Añade una línea JSONL con la petición/respuesta (para diagnosticar el cliente)."""
    path = config.trace_path
    if not path:
        return
    record["at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    try:
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass
    log.info("TRACE %s %s -> %s", record.get("method"), record.get("path"), record.get("status"))
    if record.get("body"):
        log.info("      body: %s", str(record["body"])[:400])
    if record.get("res_body") and record.get("status", 200) >= 400:
        log.info("      resp: %s", str(record["res_body"])[:300])


def make_server(config: Config) -> ThreadingHTTPServer:
    router = build(config)

    class Handler(BaseHTTPRequestHandler):
        server_version = "moba2/1.0"
        protocol_version = "HTTP/1.1"

        def _dispatch(self) -> None:
            parsed = urlparse(self.path)
            rec = {"method": self.command, "path": parsed.path, "query": parsed.query,
                   "client": self.client_address[0], "status": None}
            path = parsed.path.rstrip("/") or "/"
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self._send(413, {"title": "payload demasiado grande", "status": 413})
            body = self.rfile.read(length) if length else b""
            if config.trace_path:
                rec["headers"] = {k.lower(): v for k, v in self.headers.items()
                                  if k.lower() in ("authorization", "content-type", "user-agent",
                                                   "x-dota-timestamp", "x-dota-signature")}
                try:
                    rec["body"] = json.loads(body.decode("utf-8")) if body else None
                except Exception:
                    rec["body"] = body[:600].decode("utf-8", "replace")
            headers = {k.lower(): v for k, v in self.headers.items()}
            req = Request(self.command, path, parse_qs(parsed.query), headers, body,
                          self.client_address[0])
            try:
                found = router.route(self.command, path)
                if not found and "/v1/" in path:
                    # tolera prefijos añadidos por el parche (http://ip:puerto/<prefijo>/v1/...)
                    trimmed = "/v1/" + path.split("/v1/", 1)[1]
                    found = router.route(self.command, trimmed)
                    if found:
                        req.path = trimmed
                if not found:
                    raise NotFound("ruta no encontrada")
                handler, params = found
                req.params = params
                status, payload, ctype = handler(req)
                self._send(status, payload, ctype)
                rec["status"] = status
                if config.trace_path:
                    rec["res_body"] = payload if isinstance(payload, (dict, list)) else str(payload)[:200]
            except ApiError as exc:
                self._send(exc.status, exc.to_problem())
                rec["status"] = exc.status
                if config.trace_path:
                    rec["res_body"] = exc.to_problem()
            except NotFound as exc:
                self._send(404, {"title": str(exc), "status": 404, "code": "not_found"})
            except Exception:  # pragma: no cover
                log.exception("error no controlado en %s %s", self.command, path)
                self._send(500, {"title": "error interno", "status": 500, "code": "internal"})
            finally:
                if config.trace_path:
                    _trace_write(config, rec)

        def _send(self, status: int, payload, ctype: str = "application/json") -> None:
            if isinstance(payload, bytes):
                body = payload
            elif ctype.startswith("application/json"):
                body = json.dumps(payload, ensure_ascii=False, default=str).encode()
            else:
                body = str(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self._dispatch()

        do_POST = do_PUT = do_DELETE = do_PATCH = do_GET

        def log_message(self, fmt: str, *args) -> None:
            if config.access_log:
                log.info("%s %s", self.client_address[0], fmt % args)

    ThreadingHTTPServer.allow_reuse_address = True
    httpd = ThreadingHTTPServer((config.bind, config.http_port), Handler)
    if config.tls_cert and config.tls_key:
        import ssl as _ssl
        ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(config.tls_cert, config.tls_key)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        log.info("TLS activo: certificado %s", config.tls_cert)
    return httpd


def serve(config: Config) -> None:
    db.configure(config.db_path)
    server = make_server(config)
    signal.signal(signal.SIGTERM, lambda *_: server.shutdown())
    log.info("API y panel en http://%s:%d  ·  UDP de partida %s:%d",
             config.bind, config.http_port, config.host_ip, config.udp_port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
