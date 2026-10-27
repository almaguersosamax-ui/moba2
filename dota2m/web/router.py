"""Router mínimo sobre http.server: rutas por método + patrón con parámetros."""
from __future__ import annotations

import json
import re
from typing import Callable

from ..errors import ApiError

Handler = Callable[..., tuple[int, object, str]]


class Request:
    __slots__ = ("method", "path", "query", "headers", "body", "params", "client")

    def __init__(self, method: str, path: str, query: dict, headers: dict, body: bytes, client: str):
        self.method = method
        self.path = path
        self.query = query
        self.headers = headers
        self.body = body
        self.client = client
        self.params: dict[str, str] = {}

    def json(self) -> dict:
        if not self.body:
            return {}
        try:
            data = json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError("JSON inválido", code="invalid_json") from exc
        return data if isinstance(data, dict) else {"value": data}

    def q(self, name: str, default: str = "") -> str:
        values = self.query.get(name)
        return (values[0] if isinstance(values, list) and values else default) or default

    def q_int(self, name: str, default: int, *, minimum: int = 0, maximum: int = 500) -> int:
        try:
            value = int(self.q(name, str(default)))
        except ValueError:
            return default
        return max(minimum, min(maximum, value))

    def header(self, name: str) -> str:
        return self.headers.get(name.lower(), "")

    def bearer(self) -> str | None:
        auth = self.header("authorization")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return None


class Router:
    """Colección ordenada de rutas. Los patrones usan {param}."""

    def __init__(self) -> None:
        self._routes: list[tuple[str, str, re.Pattern[str], Handler]] = []

    def add(self, method: str, pattern: str, handler: Handler) -> "Router":
        regex = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern) + "$")
        self._routes.append((method.upper(), pattern, regex, handler))
        return self

    def extend(self, other: "Router") -> "Router":
        self._routes.extend(other._routes)
        return self

    def route(self, method: str, path: str) -> tuple[Handler, dict] | None:
        method = method.upper()
        for verb, _pattern, regex, handler in self._routes:
            if verb != method:
                continue
            match = regex.match(path)
            if match:
                return handler, match.groupdict()
        return None

    @property
    def patterns(self) -> list[str]:
        return [pattern for _verb, pattern, _regex, _handler in self._routes]
