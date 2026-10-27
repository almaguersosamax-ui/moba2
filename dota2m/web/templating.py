"""Renderizado mínimo de plantillas HTML ({{var}} escapado, {{var|raw}} sin escapar)."""
from __future__ import annotations

import html
import re
from pathlib import Path

TEMPLATES = Path(__file__).parent / "templates"
_TOKEN = re.compile(r"\{\{\s*(\w+)(\|raw)?\s*\}\}")
_cache: dict[str, str] = {}


def _load(name: str) -> str:
    if name not in _cache:
        _cache[name] = (TEMPLATES / name).read_text(encoding="utf-8")
    return _cache[name]


def render(_template: str, /, **context) -> str:
    """Renderiza sin colisión de nombres: el 1er argumento es solo posicional."""
    def sub(match: re.Match) -> str:
        value = context.get(match.group(1), "")
        text = "" if value is None else str(value)
        return text if match.group(2) else html.escape(text)

    return _TOKEN.sub(sub, _load(_template))
