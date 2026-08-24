"""La puerta del estudio (PRD 41).

Tres rutas, las tres públicas por necesidad: nadie puede identificarse si para
identificarse hace falta estar ya dentro. Quien está dentro se pregunta en
/api/me, que sí pide sesión.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from ..auth import (
    COOKIE,
    SESSION_DAYS,
    create_session,
    current_owner,
    verify_firebase_token,
)
from ..errors import Forbidden
from .deps import StudioDep

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/config")
def auth_config(request: Request, studio: StudioDep) -> dict[str, Any]:
    """Lo que el navegador necesita antes de pintar nada.

    Se entrega sin sesión a propósito: es la pantalla de entrada la que lo pide.
    Y se entrega en caliente, no incrustado al construir la imagen: cuando se
    construye, el proyecto de Google todavía puede no existir, y llegarían
    valores vacíos al navegador sin ningún error útil en los registros.

    Esta configuración no es secreta —está pensada para ir en el cliente, igual
    que en cualquier sitio que use "Entrar con Google"—; lo que protege el
    estudio es el correo del dueño y la firma de la cookie.
    """
    settings = studio.settings
    propietario = current_owner(request, settings)
    return {
        "login_required": settings.login_required,
        "firebase": settings.firebase,
        "signed_in": propietario is not None,
        "email": propietario.email if propietario else None,
    }


class SessionIn(BaseModel):
    credential: str
    """El idToken que devuelve Firebase al entrar con Google."""


@router.post("/session")
def open_session(
    request: Request, studio: StudioDep, body: SessionIn, response: Response
) -> dict[str, Any]:
    """Canjea el token de Firebase por la cookie de sesión.

    Dos comprobaciones, y las dos importan: que el token es auténtico y va
    dirigido a este proyecto, y que el correo que trae es el del propietario. La
    primera sola dejaría entrar a cualquiera con una cuenta de Google.
    """
    settings = studio.settings
    if not settings.login_required:
        raise Forbidden("Este estudio no tiene puerta configurada.")
    if not settings.firebase_project:
        raise Forbidden("Falta la configuración de Firebase. Vuelve a pasar el instalador.")

    correo = verify_firebase_token(body.credential, settings.firebase_project)
    if correo != settings.owner_email.strip().lower():
        # Sin decir cuál es el correo que sí vale: quien prueba cuentas ajenas no
        # tiene por qué llevarse la respuesta.
        raise Forbidden("Esa cuenta de Google no es la dueña de este estudio.")

    response.set_cookie(
        COOKIE,
        create_session(correo, settings.session_secret),
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        # Con puerta configurada siempre hay https delante. Mirar sólo el esquema
        # dependería de que las cabeceras del proxy lleguen bien, y si no llegan
        # la cookie pierde la marca sin que nada falle a la vista.
        secure=settings.login_required or request.url.scheme == "https",
        samesite="lax",
        path="/",
    )
    return {"email": correo, "days": SESSION_DAYS}


@router.post("/logout")
def close_session(response: Response) -> dict[str, str]:
    response.delete_cookie(COOKIE, path="/")
    return {"status": "fuera"}
