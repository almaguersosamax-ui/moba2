"""AES-256-CBC con PKCS#7 en Python puro (sin dependencias).

Solo se usa para el ticket de conexión: payloads de menos de 200 bytes, así que la
velocidad no importa. Validado contra `openssl enc -aes-256-cbc` (ver tests).
"""
from __future__ import annotations

SBOX = bytes.fromhex(
    "637c777bf26b6fc53001672bfed7ab76ca82c97dfa5947f0add4a2af9ca472c0"
    "b7fd9326363ff7cc34a5e5f171d8311504c723c31896059a071280e2eb27b275"
    "09832c1a1b6e5aa0523bd6b329e32f8453d100ed20fcb15b6acbbe394a4c58cf"
    "d0efaafb434d338545f9027f503c9fa851a3408f929d38f5bcb6da2110fff3d2"
    "cd0c13ec5f974417c4a77e3d645d197360814fdc222a908846eeb814de5e0bdb"
    "e0323a0a4906245cc2d3ac629195e479e7c8376d8dd54ea96c56f4ea657aae08"
    "ba78252e1ca6b4c6e8dd741f4bbd8b8a703eb5664803f60e613557b986c11d9e"
    "e1f8981169d98e949b1e87e9ce5528df8ca1890dbfe6426841992d0fb054bb16")
INV_SBOX = bytes(SBOX.index(i) for i in range(256))
RCON = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36, 0x6C, 0xD8, 0xAB, 0x4D)

BLOCK = 16
ROUNDS = 14          # AES-256


def _xtime(a: int) -> int:
    a <<= 1
    return (a ^ 0x11B) & 0xFF if a & 0x100 else a


def _mul(a: int, b: int) -> int:
    out = 0
    while b:
        if b & 1:
            out ^= a
        a = _xtime(a)
        b >>= 1
    return out


_MUL = {k: bytes(_mul(x, k) for x in range(256)) for k in (2, 3, 9, 11, 13, 14)}


def _expand_key(key: bytes) -> list[list[int]]:
    if len(key) != 32:
        raise ValueError("AES-256 requiere clave de 32 bytes")
    words = [list(key[i:i + 4]) for i in range(0, 32, 4)]
    for i in range(8, 4 * (ROUNDS + 1)):
        temp = words[i - 1][:]
        if i % 8 == 0:
            temp = temp[1:] + temp[:1]
            temp = [SBOX[b] for b in temp]
            temp[0] ^= RCON[i // 8 - 1]
        elif i % 8 == 4:
            temp = [SBOX[b] for b in temp]
        words.append([words[i - 8][j] ^ temp[j] for j in range(4)])
    return [sum(words[r * 4:r * 4 + 4], []) for r in range(ROUNDS + 1)]


def _add_round_key(state: list[int], rk: list[int]) -> None:
    for i in range(16):
        state[i] ^= rk[i]


def _encrypt_block(block: bytes, round_keys: list[list[int]]) -> bytes:
    s = list(block)
    _add_round_key(s, round_keys[0])
    for rnd in range(1, ROUNDS + 1):
        s = [SBOX[b] for b in s]
        s = [s[(i + 4 * (i % 4)) % 16] for i in range(16)]          # ShiftRows
        if rnd != ROUNDS:
            t = []
            for c in range(4):
                a = s[4 * c:4 * c + 4]
                t += [_MUL[2][a[0]] ^ _MUL[3][a[1]] ^ a[2] ^ a[3],
                      a[0] ^ _MUL[2][a[1]] ^ _MUL[3][a[2]] ^ a[3],
                      a[0] ^ a[1] ^ _MUL[2][a[2]] ^ _MUL[3][a[3]],
                      _MUL[3][a[0]] ^ a[1] ^ a[2] ^ _MUL[2][a[3]]]
            s = t
        _add_round_key(s, round_keys[rnd])
    return bytes(s)


def _decrypt_block(block: bytes, round_keys: list[list[int]]) -> bytes:
    s = list(block)
    _add_round_key(s, round_keys[ROUNDS])
    for rnd in range(ROUNDS - 1, -1, -1):
        s = [s[(i - 4 * (i % 4)) % 16] for i in range(16)]          # InvShiftRows
        s = [INV_SBOX[b] for b in s]
        _add_round_key(s, round_keys[rnd])
        if rnd != 0:
            t = []
            for c in range(4):
                a = s[4 * c:4 * c + 4]
                t += [_MUL[14][a[0]] ^ _MUL[11][a[1]] ^ _MUL[13][a[2]] ^ _MUL[9][a[3]],
                      _MUL[9][a[0]] ^ _MUL[14][a[1]] ^ _MUL[11][a[2]] ^ _MUL[13][a[3]],
                      _MUL[13][a[0]] ^ _MUL[9][a[1]] ^ _MUL[14][a[2]] ^ _MUL[11][a[3]],
                      _MUL[11][a[0]] ^ _MUL[13][a[1]] ^ _MUL[9][a[2]] ^ _MUL[14][a[3]]]
            s = t
    return bytes(s)


def cbc_encrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    if len(iv) != BLOCK:
        raise ValueError("IV de 16 bytes")
    rk = _expand_key(key)
    pad = BLOCK - len(data) % BLOCK
    data = data + bytes([pad]) * pad
    out, prev = bytearray(), iv
    for i in range(0, len(data), BLOCK):
        block = bytes(a ^ b for a, b in zip(data[i:i + BLOCK], prev))
        prev = _encrypt_block(block, rk)
        out += prev
    return bytes(out)


def cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    if len(iv) != BLOCK or len(data) % BLOCK:
        raise ValueError("IV/datos inválidos")
    rk = _expand_key(key)
    out, prev = bytearray(), iv
    for i in range(0, len(data), BLOCK):
        block = data[i:i + BLOCK]
        plain = _decrypt_block(block, rk)
        out += bytes(a ^ b for a, b in zip(plain, prev))
        prev = block
    pad = out[-1]
    if not 1 <= pad <= BLOCK or out[-pad:] != bytes([pad]) * pad:
        raise ValueError("padding PKCS#7 inválido")
    return bytes(out[:-pad])
