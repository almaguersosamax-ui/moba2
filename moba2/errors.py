"""Errores de aplicación con equivalencia HTTP (formato Problem del cliente)."""
from __future__ import annotations


class ApiError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, message: str = "", *, code: str | None = None, status: int | None = None):
        super().__init__(message or self.code)
        self.message = message or self.code
        if code:
            self.code = code
        if status:
            self.status = status

    def to_problem(self) -> dict:
        return {"title": self.message, "status": self.status, "code": self.code}


class Unauthorized(ApiError):
    status = 401
    code = "unauthorized"


class NotFound(ApiError):
    status = 404
    code = "not_found"


class Conflict(ApiError):
    status = 409
    code = "conflict"


class PayloadTooLarge(ApiError):
    status = 413
    code = "payload_too_large"


class UnprocessableEntity(ApiError):
    status = 422
    code = "invalid"
