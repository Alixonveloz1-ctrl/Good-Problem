"""Domain errors, mapped to HTTP status codes in main.py."""

from __future__ import annotations


class DomainError(Exception):
    status_code = 400
    code = "domain_error"

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_payload(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


class NotFound(DomainError):
    status_code = 404
    code = "not_found"


class Forbidden(DomainError):
    status_code = 403
    code = "forbidden"


class SinSesion(Forbidden):
    """No hay sesion, que no es lo mismo que "esto no se puede".

    Comparten codigo HTTP porque los dos son 403, pero el navegador tiene que
    distinguirlos: ante el primero vuelve a la pantalla de entrada, y ante el
    segundo se queda donde esta y ensena el motivo. Sin esta distincion, la
    primera regla del dominio que conteste 403 echa al usuario de la aplicacion
    sin ninguna explicacion.
    """

    code = "sin_sesion"


class Conflict(DomainError):
    status_code = 409
    code = "conflict"


class ModelNotAllowed(DomainError):
    """A caller asked for a model the system refuses to use (PRD 14, 24)."""

    status_code = 422
    code = "model_not_allowed"


class InvalidGenerationRequest(DomainError):
    status_code = 422
    code = "invalid_generation_request"


class ApprovalRequired(DomainError):
    """A stage tried to advance without human approval (PRD 3, 36)."""

    status_code = 409
    code = "approval_required"


class ProviderError(DomainError):
    status_code = 502
    code = "provider_error"
