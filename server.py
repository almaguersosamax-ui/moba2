#!/usr/bin/env python3
"""Punto de entrada del servidor LAN + estadísticas de MOBA2.

Ejemplos:
    python3 server.py --host-ip 192.168.1.105                     # API y panel en :8080
    python3 server.py --host-ip 192.168.1.105 --port 80            # requiere root
    python3 server.py --migrate-only                               # solo aplica migraciones
    D2M_HOST_IP=192.168.1.105 D2M_HTTP_PORT=8080 python3 server.py
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace
from pathlib import Path

from moba2.config import Config
from moba2.db import connection as db
from moba2.db import migrations
from moba2.web.app import serve


def parse_args(argv: list[str] | None = None) -> tuple[Config, bool]:
    base = Config.from_env()
    ap = argparse.ArgumentParser(description="Servidor LAN + estadísticas para MOBA2")
    ap.add_argument("--bind", default=base.bind, help="interfaz de escucha (0.0.0.0)")
    ap.add_argument("--port", type=int, default=base.http_port, help="puerto HTTP")
    ap.add_argument("--host-ip", default=base.host_ip,
                    help="IP que se entrega al cliente para la partida UDP")
    ap.add_argument("--udp-port", type=int, default=base.udp_port, help="puerto UDP de la partida")
    ap.add_argument("--db", default=str(base.db_path), help="ruta del fichero SQLite")
    ap.add_argument("--report-key", default=base.report_hmac_key,
                    help="clave HMAC para validar la firma de los reportes de partida")
    ap.add_argument("--public-url", default=base.public_base_url, help="URL pública para el panel")
    ap.add_argument("--log-level", default=base.log_level)
    ap.add_argument("--no-access-log", action="store_true")
    ap.add_argument("--tls-cert", default=base.tls_cert, help="certificado PEM para HTTPS")
    ap.add_argument("--tls-key", default=base.tls_key, help="clave PEM para HTTPS")
    ap.add_argument("--trace", metavar="FILE", default=base.trace_path,
                    help="graba todas las peticiones en FILE (JSONL) para diagnosticar el cliente")
    ap.add_argument("--migrate-only", action="store_true", help="aplica migraciones y sale")
    a = ap.parse_args(argv)
    cfg = replace(base, bind=a.bind, http_port=a.port, host_ip=a.host_ip, udp_port=a.udp_port,
                  db_path=Path(a.db), report_hmac_key=a.report_key,
                  public_base_url=a.public_url, log_level=a.log_level,
                  access_log=not a.no_access_log, trace_path=a.trace,
                  tls_cert=a.tls_cert, tls_key=a.tls_key)
    return cfg, a.migrate_only


def main(argv: list[str] | None = None) -> int:
    cfg, migrate_only = parse_args(argv)
    logging.basicConfig(level=cfg.log_level.upper(),
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    db.configure(cfg.db_path)
    applied = migrations.migrate()
    version = migrations.current_version()
    if applied:
        logging.getLogger("moba2.db").info("migraciones aplicadas: %s (versión %d)",
                                            applied, version)
    if migrate_only:
        print(f"esquema en versión {version} · {cfg.db_path}")
        return 0
    serve(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
