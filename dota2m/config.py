"""Configuración del servidor (CLI + variables de entorno)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(slots=True)
class Config:
    # red
    bind: str = "0.0.0.0"
    http_port: int = 8080
    host_ip: str = "127.0.0.1"      # IP que se devuelve al cliente en /v1/play
    udp_port: int = 27015           # puerto UDP real de la partida (NetConfig.DefaultPort)
    public_base_url: str = ""       # p.ej. http://192.168.1.105:8080 (para el panel)
    # datos
    db_path: Path = field(default_factory=lambda: Path("data/dota2m.db"))
    # seguridad
    report_hmac_key: str = ""
    token_ttl_days: int = 30
    admin_token: str = ""
    lobby_ttl_hours: int = 6
    # juego
    protocol: int = 6
    server_version: str = "1.1"
    # logs
    log_level: str = "INFO"
    access_log: bool = True
    tls_cert: str = ""
    tls_key: str = ""
    trace_path: str = ""      # si no está vacío, graba todas las peticiones en JSONL

    @classmethod
    def from_env(cls) -> "Config":
        c = cls()
        c.bind = _env("D2M_BIND", c.bind)
        c.http_port = int(_env("D2M_HTTP_PORT", str(c.http_port)))
        c.host_ip = _env("D2M_HOST_IP", c.host_ip)
        c.udp_port = int(_env("D2M_UDP_PORT", str(c.udp_port)))
        c.db_path = Path(_env("D2M_DB", str(c.db_path)))
        c.report_hmac_key = _env("D2M_REPORT_KEY", c.report_hmac_key)
        c.admin_token = _env("D2M_ADMIN_TOKEN", c.admin_token)
        c.log_level = _env("D2M_LOG_LEVEL", c.log_level)
        c.access_log = _env("D2M_ACCESS_LOG", "1") == "1"
        return c

    @property
    def base_url(self) -> str:
        if self.public_base_url:
            return self.public_base_url.rstrip("/")
        host = self.host_ip if self.host_ip not in ("0.0.0.0", "127.0.0.1") else "localhost"
        return f"http://{host}:{self.http_port}"
