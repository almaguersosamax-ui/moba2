"""Paquete de idioma: aplica traducciones al overlay de textos del juego.

Dos capas:

1. `gamedata`  -> claves de `assets/GameData/localization/*_english.json` (UI, ítems, habilidades).
   Se sustituye el VALOR de la clave; el cliente carga esos ficheros para cualquier locale ≠ ru.
2. `metadata`  -> literales de `global-metadata.dat` dentro de `assets/apkvision/en-assets.apk`.
   Aquí sí pueden crecer los textos (ver moba2/tools/metadata.py).

Uso:
    python3 -m moba2.tools.es_pack export --decoded build/decoded --out lang/es_template.json
    python3 -m moba2.tools.es_pack apply  --decoded build/decoded --strings lang/es.json
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import zipfile

from . import metadata as meta

META_MAIN = os.path.join("assets", "bin", "Data", "Managed", "Metadata", "global-metadata.dat")
NESTED = os.path.join("assets", "apkvision", "en-assets.apk")
INNER = "assets/bin/Data/Managed/Metadata/global-metadata.dat"
LANG_JSON = os.path.join("assets", "apkvision", "language.json")
GAMEDATA = os.path.join("assets", "GameData", "localization")


def _load_strings(path: str) -> tuple[dict, dict]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data.get("metadata", {}), data.get("gamedata", {})


def apply_gamedata(decoded: str, translations: dict) -> int:
    """Sustituye valores en los *_english.json que contengan las claves."""
    if not translations:
        return 0
    folder = os.path.join(decoded, GAMEDATA)
    if not os.path.isdir(folder):
        return 0
    changed = 0
    for name in sorted(os.listdir(folder)):
        if not name.endswith("_english.json"):
            continue
        path = os.path.join(folder, name)
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            continue
        hits = 0
        for key, value in translations.items():
            if key in data and isinstance(data[key], str) and data[key] != value:
                data[key] = value
                hits += 1
        if hits:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
            changed += hits
            print(f"  {name}: {hits} textos")
    return changed


def apply_metadata(decoded: str, translations: dict) -> int:
    """Traduce literales dentro del overlay y actualiza los hashes de language.json."""
    if not translations:
        return 0
    nested = os.path.join(decoded, NESTED)
    if not os.path.isfile(nested):
        print("  (sin en-assets.apk: se omite la capa de metadata)")
        return 0
    with zipfile.ZipFile(nested) as z:
        inner = z.read(INNER)

    new_inner, changed = meta.apply_translations(inner, translations)
    if not changed:
        return 0

    tmp = nested + ".tmp"
    with zipfile.ZipFile(nested) as zin, zipfile.ZipFile(tmp, "w") as zout:
        for info in zin.infolist():
            data = new_inner if info.filename == INNER else zin.read(info.filename)
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zout.writestr(zi, data)
    shutil.move(tmp, nested)

    _refresh_language_json(decoded, new_inner)
    return changed


def _refresh_language_json(decoded: str, inner_meta: bytes) -> None:
    path = os.path.join(decoded, LANG_JSON)
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    with open(os.path.join(decoded, NESTED), "rb") as fh:
        overlay = fh.read()
    with open(os.path.join(decoded, META_MAIN), "rb") as fh:
        main = fh.read()
    data["overlay_sha256"] = hashlib.sha256(overlay).hexdigest()
    data["metadata_sha256"] = hashlib.sha256(inner_meta).hexdigest()
    data["source_metadata_sha256"] = hashlib.sha256(main).hexdigest()
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))


def apply_all(decoded: str, strings_path: str) -> tuple[int, int]:
    md, gd = _load_strings(strings_path)
    print(f"[idioma] aplicando {len(gd)} claves de GameData y {len(md)} literales de metadata")
    n_md = apply_metadata(decoded, md)
    n_gd = apply_gamedata(decoded, gd)
    print(f"[idioma] total: {n_gd} textos de juego + {n_md} literales")
    return n_md, n_gd


def export(decoded: str, out: str, limit: int = 4000) -> None:
    """Genera una plantilla con los textos traducibles (para completar a mano)."""
    gd: dict[str, str] = {}
    folder = os.path.join(decoded, GAMEDATA)
    if os.path.isdir(folder):
        with open(os.path.join(folder, "dota_english.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        for key, value in list(data.items())[:limit]:
            if isinstance(value, str) and value.strip():
                gd[key] = ""
    nested = os.path.join(decoded, NESTED)
    md: dict[str, str] = {}
    if os.path.isfile(nested):
        with zipfile.ZipFile(nested) as z:
            inner = z.read(INNER)
        seen = set()
        for lit in meta.Metadata(inner).literals():
            text = lit.text
            if text in seen or not (3 <= len(text) <= 60) or "{" in text:
                continue
            seen.add(text)
            md[text] = ""
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"_meta": {"language": "", "cobertura": ""}, "metadata": md,
                   "gamedata": gd}, fh, ensure_ascii=False, indent=1)
    print(f"plantilla: {out} ({len(md)} literales, {len(gd)} claves de GameData)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Paquete de idioma para MOBA2")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--decoded", required=True)
    e.add_argument("--out", required=True)
    e.add_argument("--limit", type=int, default=4000)
    a = sub.add_parser("apply")
    a.add_argument("--decoded", required=True)
    a.add_argument("--strings", required=True)
    args = ap.parse_args()
    if args.cmd == "export":
        export(args.decoded, args.out, args.limit)
    else:
        apply_all(args.decoded, args.strings)


if __name__ == "__main__":
    main()
