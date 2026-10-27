#!/usr/bin/env python3
"""
Sistema de parcheo de "Dota 2 Mobile" (com.temka.dota2mobile) para apuntar el juego
a un servidor propio (LAN por defecto: http://192.168.1.105:8080).

Qué hace:
  1. Decodifica la APK original con apktool (sin tocar el smali: -s).
  2. Sustituye el literal de la URL del backend en AMBOS global-metadata.dat:
       - el original (idioma ruso)      assets/bin/Data/Managed/Metadata/global-metadata.dat
       - el overlay inglés (APKVISION)  assets/apkvision/en-assets.apk -> global-metadata.dat
     El literal original son 30 bytes; la nueva URL debe caber en 30 bytes.
     La cadena se reescribe "en sitio" (longitud + bytes), sin mover ninguna sección
     del metadata -> el binario sigue siendo válido.
  3. Añade android:usesCleartextTraffic="true" (necesario para HTTP en claro con targetSdk 36).
  4. Reconstruye, alinea y firma la APK.
  5. Verifica el resultado leyendo la APK final.

Uso (re-ejecutable cada vez que cambie la IP del servidor, siempre sobre la APK ORIGINAL):
    python3 patch_dota2m.py --apk Dota-2-Mobile-v1.1-APKVISION.apk --ip 192.168.1.105
    python3 patch_dota2m.py --apk ... --ip 192.168.1.105 --port 8080 --out dist/
    python3 patch_dota2m.py --apk ... --ip 192.168.1.105 --port 0        # servidor en :80
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from dota2m.tools import metadata as _metadata      # reescritor que permite URLs largas
except Exception:                                        # pragma: no cover
    _metadata = None

ORIGINAL_URL = b"https://177-3-221-114.sslip.io"
MAX_LEN = len(ORIGINAL_URL)          # 30 bytes: límite duro del literal
META_MAIN = "assets/bin/Data/Managed/Metadata/global-metadata.dat"
NESTED_APK = "assets/apkvision/en-assets.apk"
META_INNER = "assets/bin/Data/Managed/Metadata/global-metadata.dat"
MANIFEST = "AndroidManifest.xml"


# --------------------------------------------------------------------- util
def log(msg):
    print(f"[patch] {msg}", flush=True)


def run(cmd, **kw):
    log("$ " + " ".join(cmd))
    try:
        r = subprocess.run(cmd, **kw)
    except FileNotFoundError:
        sys.exit("ERROR: no encuentro 'java'. Instala un JRE/JDK 8+ y comprueba que 'java -version' funciona.")
    if r.returncode != 0:
        sys.exit(f"ERROR: el comando falló con código {r.returncode}")
    return r


def java_cmd(tool, *args):
    """Devuelve el comando para lanzar una herramienta.

    Si es un .jar (apktool.jar, uber-apk-signer.jar) se ejecuta con 'java -jar';
    si es un .bat/.cmd/.exe o el nombre de un comando en el PATH (apktool en Windows),
    se ejecuta directamente.
    """
    low = tool.lower()
    if low.endswith((".bat", ".cmd", ".exe")) or (not low.endswith(".jar") and os.sep not in tool):
        return [tool, *args]
    return ["java", "-jar", tool, *args]


def _default(tool):
    """Busca la herramienta en ./vendor y, si no, en el directorio actual o el PATH."""
    for candidate in (os.path.join("vendor", tool), tool):
        if os.path.isfile(candidate):
            return candidate
    return tool


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------- metadata IL2CPP
def build_url(ip, port):
    """Devuelve la URL con EXACTAMENTE MAX_LEN bytes (relleno inocuo en la ruta).

    El literal y el valor por defecto del metadata miden 30 bytes; mantener la misma
    longitud permite reescribir "en sitio" sin tocar tablas de offsets ni longitudes.
    El relleno es un segmento de ruta que el servidor descarta (busca '/v1/' dentro
    de la ruta), así que no rompe ninguna llamada.
    """
    scheme = "https" if str(ip).startswith(("https://", "http://")) else "http://"
    if scheme in str(ip):
        base = str(ip)
    else:
        base = f"http://{ip}" + (f":{port}" if port else "")
    if len(base) > MAX_LEN:
        return base.encode()          # se parchea con el reescritor (URL larga)
    if len(base) == MAX_LEN:
        return base.encode()
    pad = MAX_LEN - len(base) - 1          # 1 byte para '/'
    if pad < 0:
        return None
    return (base + "/" + "p" * pad).encode()


def long_url_ok(new_url) -> bool:
    return _metadata is not None and len(new_url) > MAX_LEN


def literal_indices(blob, needle: bytes) -> list[int]:
    """Índices de la tabla de literales cuyo contenido es exactamente `needle` (sin materializar todo)."""
    if _metadata is None:
        return []
    md = _metadata.Metadata(blob)
    table_off, count = md.literal_table
    data_off, _size = md.literal_data
    out = []
    for i in range(count):
        length, di = struct.unpack_from("<II", md.blob, table_off + i * 8)
        if length != len(needle):
            continue
        if bytes(md.blob[data_off + di:data_off + di + length]) == needle:
            out.append(i)
    return out


def patch_literal_table(blob, new_url):
    """Sustituye el literal del servidor por una URL MÁS LARGA (crece el blob de literales)."""
    if _metadata is None:
        raise RuntimeError("falta dota2m/tools/metadata.py para URLs largas")
    indices = literal_indices(blob, ORIGINAL_URL)
    if not indices:
        return blob, False
    md = _metadata.Metadata(blob)
    for i in indices:
        md.set_literal(i, new_url.decode())
    log(f"  literal(es) reescritos con URL larga: {len(indices)} ({len(new_url)} bytes)")
    return md.to_bytes(), True


def find_and_patch_literal(blob, new_url):
    """Sustituye TODAS las apariciones del literal original (misma longitud exacta).

    El metadata v31 guarda la URL dos veces: en la tabla de literales de cadena y en
    el bloque fieldAndParamDefaultData (valores por defecto). Al conservar los 30 bytes
    no hay que recalcular longitudes ni desplazar ninguna sección.
    """
    if len(new_url) > MAX_LEN:
        return patch_literal_table(blob, new_url)
    if len(new_url) != MAX_LEN:
        # acolchamos con un segmento de ruta inocuo para no tocar longitudes
        pad = MAX_LEN - len(new_url) - 1
        if pad < 0:
            raise ValueError(f"la URL no cabe: {len(new_url)} > {MAX_LEN}")
        new_url = new_url + b"/" + b"p" * pad
    if len(blob) < 32 or struct.unpack_from("<I", blob, 0)[0] != 0xFAB11BAF:
        raise ValueError("no parece un global-metadata.dat de IL2CPP")
    count = blk_count = 0
    buf = bytearray(blob)
    pos = buf.find(ORIGINAL_URL)
    while pos != -1:
        buf[pos:pos + MAX_LEN] = new_url
        count += 1
        pos = buf.find(ORIGINAL_URL, pos + MAX_LEN)
    if count:
        log(f"  {count} aparición(es) reescritas: {new_url.decode()} ({MAX_LEN} bytes)")
    return bytes(buf), count > 0


def patch_metadata_file(path, new_url):
    with open(path, "rb") as f:
        blob = f.read()
    out, changed = find_and_patch_literal(blob, new_url)
    if not changed:
        raise ValueError(f"no se encontró el literal original en {path}")
    with open(path, "wb") as f:
        f.write(out)
    return changed


def patch_nested_apk(path, new_url):
    """Reescribe el metadata dentro del en-assets.apk del overlay de idioma."""
    tmp_fd, tmp = tempfile.mkstemp(suffix=".apk")
    os.close(tmp_fd)
    patched_any = False
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == META_INNER:
                data, changed = find_and_patch_literal(data, new_url)
                patched_any = patched_any or changed
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zout.writestr(zi, data)
    if not patched_any:
        os.unlink(tmp)
        raise ValueError("no se encontró el literal dentro de en-assets.apk")
    shutil.move(tmp, path)


# ------------------------------------------------------------ language.json
def update_language_json(decoded, url_b):
    """Recalcula los SHA-256 que el loader de APKVISION verifica antes de extraer nada.

    LanguageAssets.prepare() comprueba:
      overlay_sha256        -> SHA-256 del fichero en-assets.apk completo
      metadata_sha256       -> SHA-256 del metadata DENTRO de en-assets.apk (inglés)
      source_metadata_sha256-> SHA-256 del metadata principal (ruso)
    Si no coinciden, lanza IOException y la app muestra "Could not prepare texts".
    """
    lang_path = os.path.join(decoded, "assets", "apkvision", "language.json")
    nested = os.path.join(decoded, NESTED_APK)
    main_meta = os.path.join(decoded, META_MAIN)
    if not os.path.isfile(lang_path):
        log("  (sin language.json: nada que recalcular)")
        return
    with zipfile.ZipFile(nested) as z:
        inner_meta = z.read(META_INNER)
    with open(lang_path, encoding="utf-8") as fh:
        data = json.load(fh)
    data["overlay_sha256"] = sha256(nested)
    data["metadata_sha256"] = hashlib.sha256(inner_meta).hexdigest()
    data["source_metadata_sha256"] = hashlib.sha256(open(main_meta, "rb").read()).hexdigest()
    with open(lang_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    log(f"  language.json: overlay={data['overlay_sha256'][:12]}… "
        f"metadata={data['metadata_sha256'][:12]}… source={data['source_metadata_sha256'][:12]}…")


# --------------------------------------------------------------- manifest
def patch_manifest(path):
    with open(path, "r", encoding="utf-8") as f:
        xml = f.read()
    if "usesCleartextTraffic" in xml:
        log("  usesCleartextTraffic ya presente")
    else:
        xml, n = re.subn(r"(<application\b)",
                         r'\1 android:usesCleartextTraffic="true"', xml, count=1)
        if n != 1:
            raise ValueError("no se pudo localizar <application> en el manifiesto")
        log('  android:usesCleartextTraffic="true" añadido')
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)


# ---------------------------------------------------------------- verify
def verify(apk_path, new_url):
    ok = True
    with zipfile.ZipFile(apk_path) as z:
        bad = z.testzip()
        if bad:
            ok = False
            log(f"  ZIP corrupto en {bad}")
        blob = z.read(META_MAIN)
        # comprobar que la URL nueva está presente y la original ya no
        has_new = new_url in blob
        old_left = bool(literal_indices(blob, ORIGINAL_URL))
        if len(new_url) > MAX_LEN:
            has_old = old_left          # con URL larga solo importa la tabla de literales
        else:
            has_old = ORIGINAL_URL in blob
        inner = zipfile.ZipFile(__import__("io").BytesIO(z.read(NESTED_APK))).read(META_INNER)
        inner_new = new_url in inner
        inner_old = ORIGINAL_URL in inner
        # hashes del overlay de idioma (la causa de "Could not prepare texts")
        try:
            lang = json.loads(z.read("assets/apkvision/language.json"))
            inner_apk = z.read(NESTED_APK)
            inner_meta2 = zipfile.ZipFile(__import__("io").BytesIO(inner_apk)).read(META_INNER)
            checks = {
                "overlay_sha256": hashlib.sha256(inner_apk).hexdigest(),
                "metadata_sha256": hashlib.sha256(inner_meta2).hexdigest(),
                "source_metadata_sha256": hashlib.sha256(blob).hexdigest(),
            }
            bad = [k for k, v in checks.items() if lang.get(k) != v]
            log("  hashes language.json : " + ("OK" if not bad else f"DESAJUSTE {bad}"))
            ok = ok and not bad
        except KeyError:
            log("  language.json: no presente (nada que verificar)")
        man = z.read(MANIFEST)
        # el manifiesto compilado guarda el atributo como id de recurso; se comprueba en el texto
        # decodificado aparte, aquí solo confirmamos que la APK trae el fichero
    log(f"  metadata principal : nueva={has_new} original={has_old}")
    log(f"  metadata overlay   : nueva={inner_new} original={inner_old}")
    ok = ok and has_new and not has_old and inner_new and not inner_old
    log(f"  tamaño             : {os.path.getsize(apk_path)/1e6:.1f} MB")
    log(f"  sha256             : {sha256(apk_path)}")
    return ok


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description="Parchea Dota 2 Mobile para usar tu servidor local.")
    ap.add_argument("--apk", required=True, help="APK original (sin parchear)")
    ap.add_argument("--ip", required=True, help="IP del servidor, p.ej. 192.168.1.105")
    ap.add_argument("--port", type=int, default=8080, help="puerto HTTP (0 = omitir, servidor en :80)")
    ap.add_argument("--apktool", default=os.environ.get("APKTOOL", _default("apktool.jar")))
    ap.add_argument("--signer", default=os.environ.get("UBER_APK_SIGNER", _default("uber-apk-signer.jar")),
                    help="jar de uber-apk-signer, 'apksigner' si lo tienes en el PATH, o 'none'")
    ap.add_argument("--allow-http", action="store_true",
                    help="permite HTTP en claro (parchea libunity.so: insecureHttpOption=AlwaysAllowed)")
    ap.add_argument("--es", default=None, metavar="ES_JSON",
                    help="paquete de idioma español (p.ej. lang/es.json)")
    ap.add_argument("--work", default="build_dota2m", help="directorio de trabajo")
    ap.add_argument("--out", default="dist", help="directorio de salida")
    ap.add_argument("--keep", action="store_true", help="conservar el árbol decodificado")
    a = ap.parse_args()

    url_b = build_url(a.ip, a.port)
    if url_b is None:
        sys.exit(f"ERROR: http://{a.ip}{':' + str(a.port) if a.port else ''} no cabe en {MAX_LEN} bytes.\n"
                 f"       Usa --port 0 (servidor en :80) o un nombre/IP más corto.")
    url = url_b.decode()
    log(f"URL objetivo: {url}  ({len(url_b)}/{MAX_LEN} bytes, relleno ignorado por el servidor)")
    if len(url_b) > MAX_LEN:
        sys.exit(f"ERROR: {url} ocupa {len(url_b)} bytes y el literal solo admite {MAX_LEN}.\n"
                 f"       Pruebas: usar --port 0 (servidor en :80) o una IP más corta.")

    if os.name == "nt":
        log("Windows detectado: usa 'python' (no 'python3') y, si no tienes los jars en vendor/, "
            "indica --apktool y --signer")
    if not os.path.isfile(a.apk):
        sys.exit(f"ERROR: no existe {a.apk}")
    os.makedirs(a.out, exist_ok=True)
    decoded = os.path.join(a.work, "decoded")

    # 0) comprobar que la APK de entrada está sin parchear
    with zipfile.ZipFile(a.apk) as z:
        main_blob = z.read(META_MAIN)
    if ORIGINAL_URL not in main_blob:
        sys.exit("ERROR: la APK de entrada no contiene la URL original; parece ya parcheada.\n"
                 "       Vuelve a ejecutar el parche SIEMPRE sobre la APK original.")

    # 1) decodificar
    if os.path.isdir(decoded):
        shutil.rmtree(decoded)
    os.makedirs(a.work, exist_ok=True)
    log("decodificando con apktool (-s: no toca el smali)")
    run(java_cmd(a.apktool, "d", "-f", "-s", "-o", decoded, a.apk))

    # 2) parchear metadatos (original + overlay de idioma)
    log("parcheando metadata principal")
    patch_metadata_file(os.path.join(decoded, META_MAIN), url_b)
    log("parcheando metadata del overlay inglés")
    patch_nested_apk(os.path.join(decoded, NESTED_APK), url_b)

    # 3) manifiesto: permitir HTTP en claro
    if a.es:
        if not os.path.isfile(a.es):
            sys.exit(f"ERROR: no existe el paquete de idioma {a.es}")
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from dota2m.tools.es_pack import apply_all
        log(f"aplicando paquete de idioma: {a.es}")
        apply_all(decoded, a.es)

    if a.allow_http:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from dota2m.tools.libunity_patch import patch as patch_libunity
        log("permitiendo HTTP en claro en libunity.so")
        for abi in sorted(os.listdir(os.path.join(decoded, "lib"))):
            so = os.path.join(decoded, "lib", abi, "libunity.so")
            if not os.path.isfile(so):
                continue
            ok, msg = patch_libunity(so)
            log(f"  {abi}: {'OK' if ok else 'NO APLICADO'} · {msg}")
            if not ok:
                log("  aviso: si el juego usa http:// seguirá fallando con "
                    "'Insecure connection not allowed'")

    log("recalculando hashes de language.json")
    update_language_json(decoded, url_b)

    log("parcheando manifiesto")
    patch_manifest(os.path.join(decoded, MANIFEST))

    # 4) reconstruir
    unsigned = os.path.join(a.work, "dota2m-unsigned.apk")
    log("reconstruyendo con apktool")
    run(java_cmd(a.apktool, "b", "-f", "-o", unsigned, decoded))

    # 5) firmar
    produced = unsigned
    if a.signer.lower() != "none":
        if a.signer.endswith(".jar") or os.path.isfile(a.signer):
            if not os.path.isfile(a.signer):
                sys.exit(f"ERROR: no existe el firmador {a.signer}")
            log("firmando con uber-apk-signer (zipalign + v1/v2/v3)")
            run(java_cmd(a.signer, "--apks", unsigned, "--out", a.out, "--allowResign"))
            cands = [f for f in os.listdir(a.out) if f.endswith(".apk") and "signed" in f.lower()]
            if not cands:
                sys.exit("ERROR: el firmador no generó ninguna APK")
            produced = os.path.join(a.out, sorted(cands)[-1])
        else:
            log("firmando con apksigner del PATH")
            produced = os.path.join(a.out, "dota2m-patched-signed.apk")
            run(["apksigner", "sign", "--out", produced, unsigned])

    final = os.path.join(a.out, f"dota2mobile-patched-{a.ip.replace('.', '_')}"
                                f"{('-p%d' % a.port) if a.port else ''}.apk")
    if os.path.abspath(produced) != os.path.abspath(final):
        shutil.move(produced, final)

    # 6) verificar
    log("verificando resultado")
    ok = verify(final, url_b)
    if not a.keep:
        shutil.rmtree(a.work, ignore_errors=True)
    print()
    log(("LISTO: " if ok else "AVISO: verificación incompleta: ") + os.path.abspath(final))
    if not ok:
        sys.exit(2)


if __name__ == "__main__":
    main()
