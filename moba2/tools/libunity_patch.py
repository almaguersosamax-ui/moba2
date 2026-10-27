"""Permite HTTP en claro saltando el chequeo de Unity (`insecureHttpOption`).

Unity rechaza `http://` a nivel de motor antes de abrir el socket:

    W/Unity: Non-secure network connections disabled in Player Settings
    E/Unity: InvalidOperationException: Insecure connection not allowed

El flag se consulta en libunity.so en una función que lee el enum desde el objeto de
PlayerSettings (`+0xE4`) y lo compara con 1 (solo desarrollo) y 2 (permitido). Aquí se
sustituye esa carga por `mov w21, #2` (AlwaysAllowed), que es una sola instrucción y no
toca ninguna otra lógica.

La dirección está verificada sobre la build v1.1 (`libunity.so` con
`ldr w21, [x0, #0xe4]` = 0xB940E415 en 0x949EC8). Si la instrucción no coincide,
el parche se aborta sin tocar nada.
"""
from __future__ import annotations

import struct

# (VA, bytes esperados, bytes nuevos, descripción)
KNOWN_PATCHES = [
    (0x949EC8, 0xB940E415, 0x52800055,          # ldr w21,[x0,#0xe4] -> mov w21,#2
     "insecureHttpOption = AlwaysAllowed"),
]

MESSAGE = b"Insecure connection not allowed"


def _segments(data: bytes) -> list[tuple[int, int, int, int]]:
    if data[:4] != b"\x7fELF" or data[4] != 2:
        raise ValueError("libunity.so no es un ELF64")
    phoff = struct.unpack_from("<Q", data, 0x20)[0]
    entsize, phnum = struct.unpack_from("<HH", data, 0x36)
    out = []
    for i in range(phnum):
        off = phoff + i * entsize
        p_type, p_flags = struct.unpack_from("<II", data, off)
        p_offset, p_vaddr, _paddr, p_filesz, _memsz = struct.unpack_from("<QQQQQ", data, off + 8)
        if p_type == 1:
            out.append((p_offset, p_filesz, p_vaddr, p_flags))
    return out


def _v2f(segs, vaddr: int) -> int | None:
    for off, filesz, vaddr0, _ in segs:
        if vaddr0 <= vaddr < vaddr0 + filesz:
            return off + (vaddr - vaddr0)
    return None


def find_fallback(data: bytes) -> list[tuple[int, int, int, str]]:
    """Si la dirección conocida no sirve, busca el patrón `ldr wN,[xM,#0xE4]` + cmp 1/2."""
    segs = _segments(data)
    hits = []
    for off, filesz, vaddr0, flags in segs:
        if not flags & 1:
            continue
        for i in range(0, filesz - 32, 4):
            w0 = struct.unpack_from("<I", data, off + i)[0]
            if (w0 & 0xFFFFFC00) != 0xB940E400:      # ldr wN, [xM, #0xE4]
                continue
            w1, w2, w3, w4 = struct.unpack_from("<IIII", data, off + i + 8)
            # cmp wN,#1 ; b.eq ... ; cmp wN,#2 ; b.ne ...
            if (w1 & 0xFFC003FF) == 0x7100041F and (w2 & 0xFF00001F) == 0x54000000:
                rn = (w0 >> 5) & 0x1F
                hits.append((vaddr0 + i, w0, (0x52800000 | (2 << 5) | rn), "variante detectada"))
    return hits


def patch(path: str) -> tuple[bool, str]:
    """Aplica el parche. Devuelve (aplicado, mensaje)."""
    with open(path, "rb") as fh:
        data: bytes | bytearray = bytearray(fh.read())
    if MESSAGE not in bytes(data):
        return False, "el fichero no parece libunity.so (no contiene el mensaje esperado)"
    segs = _segments(bytes(data))
    applied = []
    for vaddr, expected, new, desc in KNOWN_PATCHES:
        foff = _v2f(segs, vaddr)
        if foff is None:
            return False, f"dirección {vaddr:#x} fuera de los segmentos"
        current = struct.unpack_from("<I", data, foff)[0]
        if current != expected:
            continue
        struct.pack_into("<I", data, foff, new)
        applied.append(f"{desc} @ {vaddr:#x}")
    if not applied:
        for vaddr, current, new, desc in find_fallback(bytes(data)):
            foff = _v2f(segs, vaddr)
            struct.pack_into("<I", data, foff, new)
            applied.append(f"{desc} @ {vaddr:#x}")
    if not applied:
        return False, "no se encontró la comprobación (¿otra versión de libunity?)"
    with open(path, "wb") as fh:
        fh.write(data)
    return True, "; ".join(applied)
