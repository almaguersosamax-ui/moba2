"""Ticket de conexión (ConnectTicket v2) del cliente MOBA2.

Estructura recuperada por desensamblado de `Dota.Gameplay.ConnectTicket` en
libil2cpp.so (métodos Create / TryOpen / NewAes):

    offset  tamaño  campo
    0       32      MAC  (HMAC-SHA256 sobre cabecera+cifrado)
    32      1       versión (1 = sin sala, 2 = con sala)     <- verificado en TryOpen
    33      8       userId (big-endian)
    41      2       port   (big-endian)
    43      2       longitud del cifrado (big-endian, múltiplo de 16)  <- verificado
    45      N       payload cifrado (AES-256-CBC, PKCS#7)
    total = 45 + N   (el cliente suma 0x4d = 77 en su comprobación de longitud:
                      pendiente confirmar si incluye IV/nonce; ver README)

Constantes del cliente: KeySize 32, NonceSize 16, IvSize 16, MacSize 32, HeaderSize 45,
MaxBytes 237, MaxLifetimeSeconds 300, MaxNameBytes 96, MaxLobbyBytes 8.

Payload en claro (bytes, big-endian):
    expiresUnix  8
    nonce       16
    sessionKey  32
    nameLen      1 + name
    lobbyLen     1 + lobby (solo versión 2)

El MAC se calcula con una clave derivada de la maestra (clave HMAC = SHA-256(master)).
El cliente acepta la clave maestra por el argumento de arranque `-dotaticketkey`.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import struct
import time
from dataclasses import dataclass

VERSION_NO_LOBBY = 1
VERSION_LOBBY = 2
MAC_SIZE = 32
HEADER_SIZE = 45          # MAC(32) + cabecera(13)
MAX_BYTES = 237
MAX_LIFETIME = 300
MIN_PAYLOAD = 8 + 16 + 32 + 1 + 1


class TicketError(ValueError):
    """Ticket inválido (versión, MAC, caducidad, tamaño...)."""


@dataclass(slots=True)
class TicketInfo:
    user_id: int
    name: str
    port: int
    expires_unix: int
    nonce: bytes
    session_key: bytes
    lobby: str


def _mac_key(master: bytes) -> bytes:
    return hashlib.sha256(b"moba2-ticket-mac|" + master).digest()


def _aes_key(master: bytes) -> bytes:
    return hashlib.sha256(b"moba2-ticket-aes|" + master).digest()


def _aes_encrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    from .aes import cbc_encrypt
    return cbc_encrypt(key, iv, data)


def _aes_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    from .aes import cbc_decrypt
    return cbc_decrypt(key, iv, data)


def create(master: bytes, user_id: int, name: str, port: int, expires_unix: int,
           lobby: str = "", *, nonce: bytes | None = None,
           session_key: bytes | None = None) -> tuple[bytes, bytes, bytes]:
    """Devuelve (ticket, nonce, sessionKey). El ticket se entrega en Base64 al cliente."""
    if not (0 < port <= 0xFFFF):
        raise TicketError("puerto fuera de rango")
    if expires_unix - int(time.time()) > MAX_LIFETIME:
        raise TicketError("la caducidad no puede superar 300 s")
    lobby = (lobby or "").upper()[:8]
    name_b = (name or "").encode("utf-8")[:96]
    nonce = nonce or os.urandom(16)
    session_key = session_key or os.urandom(32)
    version = VERSION_LOBBY if lobby else VERSION_NO_LOBBY

    header = struct.pack(">B", version) + struct.pack(">Q", user_id & 0xFFFFFFFFFFFFFFFF) \
        + struct.pack(">H", port)
    payload = (struct.pack(">Q", expires_unix & 0xFFFFFFFFFFFFFFFF) + nonce + session_key
               + bytes([len(name_b)]) + name_b
               + (bytes([len(lobby)]) + lobby.encode() if version == VERSION_LOBBY else b""))
    if len(payload) < MIN_PAYLOAD:
        raise TicketError("payload demasiado corto")
    # PKCS#7 explícito (el cifrado puede rellenar, pero fijamos los 16 bytes de IV = nonce)
    ct = _aes_encrypt(_aes_key(master), _iv(master, header), payload)
    if len(ct) % 16:
        raise TicketError("cifrado no alineado")

    header = header + struct.pack(">H", len(ct))
    body = header + ct
    if HEADER_SIZE + len(ct) > MAX_BYTES:
        raise TicketError(f"ticket demasiado grande ({HEADER_SIZE + len(ct)} > {MAX_BYTES})")
    mac = hmac.new(_mac_key(master), body, hashlib.sha256).digest()
    return mac + body, nonce, session_key


def open_ticket(master: bytes, data: bytes, *, expect_port: int | None = None,
                now_unix: int | None = None) -> TicketInfo:
    """Valida el ticket igual que el anfitrión (TryOpen). Lanza TicketError si no cuadra."""
    if len(data) < HEADER_SIZE or len(data) > MAX_BYTES:
        raise TicketError(f"tamaño inválido: {len(data)}")
    mac, body = data[:MAC_SIZE], data[MAC_SIZE:]
    expected = hmac.new(_mac_key(master), body, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        raise TicketError("MAC inválido")
    version, user_id, port, ct_len = struct.unpack(">BQHH", body[:13])
    if version not in (VERSION_NO_LOBBY, VERSION_LOBBY):
        raise TicketError(f"versión no soportada: {version}")
    if ct_len == 0 or ct_len % 16:
        raise TicketError("longitud de cifrado inválida")
    if len(data) != HEADER_SIZE + ct_len:
        raise TicketError("longitud total incoherente")
    if expect_port is not None and port != expect_port:
        raise TicketError(f"puerto del ticket ({port}) != esperado ({expect_port})")

    ct = data[HEADER_SIZE:]
    payload = _aes_decrypt(_aes_key(master), _iv(master, body[:11]), ct)
    expires_unix = struct.unpack(">Q", payload[0:8])[0]
    nonce = payload[8:24]
    session_key = payload[24:56]
    name_len = payload[56]
    name = payload[57:57 + name_len].decode("utf-8", "replace")
    lobby = ""
    if version == VERSION_LOBBY:
        off = 57 + name_len
        lobby_len = payload[off]
        lobby = payload[off + 1:off + 1 + lobby_len].decode("utf-8", "replace")
    now = now_unix or int(time.time())
    if expires_unix and expires_unix < now:
        raise TicketError("ticket caducado")
    return TicketInfo(user_id, name, port, expires_unix, nonce, session_key, lobby)


def _iv(master: bytes, header_clear: bytes) -> bytes:
    """IV derivado de la parte en claro de la cabecera (versión+userId+port).

    El cliente no transmite el IV: se deriva de datos que el anfitrión ya tiene antes
    de descifrar, así el descifrado es determinista y no hay bytes extra.
    """
    return hashlib.sha256(b"moba2-ticket-iv|" + master + header_clear).digest()[:16]
