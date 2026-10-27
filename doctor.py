#!/usr/bin/env python3
"""Diagnóstico de la cadena teléfono → PC → servidor.

    python doctor.py                          # usa http://192.168.1.105:8080
    python doctor.py --url http://192.168.1.105:8080 --apk dist\\dota2mobile-patched-....apk

Comprueba, en orden:
  1. IPs de este PC (para detectar si parcheaste con una IP equivocada)
  2. si el servidor responde en localhost
  3. si responde en la IP de LAN (esto es lo que ve el teléfono)
  4. si la APK parcheada contiene la URL correcta, el permiso de HTTP en claro
     y los hashes de language.json coherentes
"""
from __future__ import annotations

import argparse
import json
import socket
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

OK, WARN, FAIL = "OK  ", "AVISO", "FALLO"
results: list[tuple[str, str]] = []


def add(level: str, text: str) -> None:
    results.append((level, text))
    print(f"[{level}] {text}")


# --------------------------------------------------------------- utilidades
def primary_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def local_ips() -> list[str]:
    ips = {primary_ip()}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(i for i in ips if not i.startswith("169.254"))


def http_get(url: str, timeout: float = 3.0) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read(200).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(200).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}"


# -------------------------------------------------------------------- APK
PADDED_SUFFIX = "/"


def check_apk(path: Path, expect_ip: str, expect_port: int) -> None:
    if not path.is_file():
        add(FAIL, f"no existe la APK: {path}")
        return
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        add(FAIL, f"la APK está corrupta: {path}")
        return
    with z:
        names = set(z.namelist())
        meta = "assets/bin/Data/Managed/Metadata/global-metadata.dat"
        nested = "assets/apkvision/en-assets.apk"
        if meta not in names:
            add(FAIL, "la APK no tiene global-metadata.dat (¿está mal decodificada?)")
            return
        blob = z.read(meta)
        prefix = f"http://{expect_ip}:{expect_port}".encode() if expect_port else f"http://{expect_ip}".encode()
        found = prefix in blob
        add(OK if found else FAIL, f"metadata principal contiene {prefix.decode()}")
        if b"177-3-221-114.sslip.io" in blob:
            add(FAIL, "el metadata principal AÚN tiene la URL original del servidor oficial")
        else:
            add(OK, "la URL original no aparece en el metadata principal")

        if nested in names:
            inner = zipfile.ZipFile(__import__("io").BytesIO(z.read(nested))).read(meta)
            add(OK if prefix in inner else FAIL, "el overlay inglés contiene la URL del servidor local")
            if b"177-3-221-114.sslip.io" in inner:
                add(FAIL, "el overlay AÚN tiene la URL original")
        else:
            add(WARN, "no hay overlay de idioma (en-assets.apk): solo se usará el metadata principal")

        # parche nativo de Unity (insecureHttpOption)
        libs = [n for n in names if n.endswith("lib/arm64-v8a/libunity.so")]
        if libs:
            so = z.read(libs[0])
            patched = b"\x55\x00\x80\x52" in so[:0] or _unity_patched(so)
            add(OK if patched else WARN,
                "libunity.so con insecureHttpOption=AlwaysAllowed (permite http://)"
                if patched else "libunity.so SIN el parche --allow-http (Unity bloqueará http://)")

        # permiso de HTTP en claro
        man = z.read("AndroidManifest.xml")
        cleartext = struct.pack("<I", 0x010104EC) in man   # android:usesCleartextTraffic
        add(OK if cleartext else FAIL,
            "manifest con android:usesCleartextTraffic (necesario para http://)")

        # hashes de language.json
        try:
            lang = json.loads(z.read("assets/apkvision/language.json"))
            inner_apk = z.read(nested)
            inner_meta = zipfile.ZipFile(__import__("io").BytesIO(inner_apk)).read(meta)
            import hashlib
            checks = {
                "overlay_sha256": hashlib.sha256(inner_apk).hexdigest(),
                "metadata_sha256": hashlib.sha256(inner_meta).hexdigest(),
                "source_metadata_sha256": hashlib.sha256(blob).hexdigest(),
            }
            bad = [k for k, v in checks.items() if lang.get(k) != v]
            add(OK if not bad else FAIL,
                "hashes de language.json coherentes" if not bad
                else f"language.json desajustado en {bad} → la app dirá 'Could not prepare texts'")
        except KeyError:
            pass


def _unity_patched(so: bytes) -> bool:
    """Comprueba la instrucción `mov w21,#2` en 0x949EC8 (o busca el patrón equivalente)."""
    try:
        e_phoff = struct.unpack_from("<Q", so, 0x20)[0]
        entsize, phnum = struct.unpack_from("<HH", so, 0x36)
        for i in range(phnum):
            off = e_phoff + i * entsize
            p_type = struct.unpack_from("<I", so, off)[0]
            p_offset, p_vaddr, _p, p_filesz = struct.unpack_from("<QQQQ", so, off + 8)
            if p_type == 1 and p_vaddr <= 0x949EC8 < p_vaddr + p_filesz:
                foff = p_offset + (0x949EC8 - p_vaddr)
                return struct.unpack_from("<I", so, foff)[0] == 0x52800055
    except Exception:
        return False
    return False


# -------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="Diagnóstico teléfono → PC → servidor")
    ap.add_argument("--url", default="http://192.168.1.105:8080",
                    help="URL que espera el cliente (la del parche)")
    ap.add_argument("--apk", help="APK parcheada a inspeccionar (opcional pero recomendable)")
    a = ap.parse_args()

    target = urllib.parse.urlparse(a.url)
    host, port = target.hostname or "192.168.1.105", target.port or 80

    print("\n=== 1) Red de este PC")
    ips = local_ips()
    add(OK, f"IPs locales: {', '.join(ips)}")
    if host in ips:
        add(OK, f"la IP del parche ({host}) es de este PC")
    else:
        add(FAIL, f"la IP del parche ({host}) NO está en este PC. "
                  f"Parcheaste con una IP que no es la tuya: vuelve a parchear con {primary_ip()}")

    print("\n=== 2) Servidor en localhost")
    status, body = http_get(f"http://127.0.0.1:{port}/healthz")
    if status == 200:
        add(OK, f"responde en 127.0.0.1:{port} → {body[:80]}")
    else:
        add(FAIL, f"no responde en 127.0.0.1:{port} ({body[:80]}) → ¿está arrancado server.py?")

    print("\n=== 3) Servidor en la IP de LAN (lo que ve el teléfono)")
    status, body = http_get(f"http://{host}:{port}/healthz")
    if status == 200:
        add(OK, f"responde en {host}:{port}")
    else:
        add(FAIL, f"no responde en {host}:{port} ({body[:80]})")
        add(WARN, "si en localhost sí responde: es el firewall o el bind. "
                  "Windows: permite Python en redes privadas; arranca con --bind 0.0.0.0")

    print("\n=== 4) Puerto en escucha")
    s = socket.socket()
    s.settimeout(2)
    listening = s.connect_ex((host, port)) == 0
    s.close()
    add(OK if listening else FAIL, f"puerto {port} {'abierto' if listening else 'cerrado'} en {host}")

    if a.apk:
        print("\n=== 5) APK parcheada")
        check_apk(Path(a.apk), host, port)

    fails = sum(1 for level, _ in results if level == FAIL)
    warns = sum(1 for level, _ in results if level == WARN)
    print(f"\n=== Resumen: {len(results) - fails - warns} OK · {warns} avisos · {fails} fallos")
    if fails:
        print("Arregla primero los FALLO de arriba, en orden.")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
