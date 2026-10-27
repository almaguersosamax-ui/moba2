"""Validaciones de entrada compartidas."""
from __future__ import annotations

import ipaddress
import re

NAME_MIN = 3
NAME_MAX = 24
_NAME_RE = re.compile(r"^[\w \-.\[\]]{%d,%d}$" % (NAME_MIN, NAME_MAX), re.UNICODE)
_RESERVED = {"admin", "administrador", "root", "system", "server", "apkvision", "valve", "anónimo"}


class ValidationError(ValueError):
    """Error de validación con un código estable para la API."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def clean_text(value: object, limit: int = 64) -> str:
    if value is None:
        return ""
    text = "".join(ch for ch in str(value) if ch.isprintable() and ch not in "\r\n\t")
    return text.strip()[:limit]


def validate_name(value: object) -> str:
    name = clean_text(value, NAME_MAX)
    if len(name) < NAME_MIN:
        raise ValidationError("too_short", f"El nombre necesita al menos {NAME_MIN} caracteres")
    if not _NAME_RE.match(name):
        raise ValidationError("invalid_chars", "Solo letras, números, espacio y - _ . [ ]")
    if name.casefold() in _RESERVED:
        raise ValidationError("reserved", "Ese nombre está reservado")
    return name


def validate_lobby_code(value: object) -> str:
    code = clean_text(value, 8).upper()
    if not re.fullmatch(r"[ABCDEFGHJKLMNPQRSTUVWXYZ]{4,8}", code):
        raise ValidationError("invalid_code", "Código de sala inválido (4 letras, sin I ni O)")
    return code


def validate_hero(value: object) -> str:
    hero = clean_text(value, 64).lower()
    if not re.fullmatch(r"[a-z0-9_]{0,64}", hero):
        raise ValidationError("invalid_hero", "Héroe inválido")
    return hero


def validate_ip(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value))
    except ValueError as exc:
        raise ValidationError("invalid_ip", f"IP inválida: {value}") from exc


def validate_port(value: object, *, minimum: int = 1, maximum: int = 65535) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("invalid_port", "Puerto inválido") from exc
    if not minimum <= port <= maximum:
        raise ValidationError("invalid_port", "Puerto fuera de rango")
    return port
