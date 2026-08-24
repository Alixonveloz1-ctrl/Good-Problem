"""La puerta del estudio (PRD 41).

Cuatro rutas, todas publicas por necesidad: nadie puede identificarse si para
identificarse hace falta estar ya dentro. Quien esta dentro se pregunta en
/api/me, que si pide sesion.

La de setup existe por una limitacion real y no por comodidad: Google no publica
ninguna API para crear un cliente OAuth de tipo web ni para anadirle origenes de
JavaScript. Hay que crearlo a mano en la consola, y lo que sale de ahi son
setenta caracteres que en un movil no se pueden pegar dentro de Cloud Shell. Asi
que el Client ID entra por aqui, desde el navegador, donde pegar si funciona.
"""

from __future__ import annotations

import hmac
import re
import time
from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from ..auth import (
    COOKIE,
    SESSION_DAYS,
    create_session,
    current_owner,
    verify_google_token,
)
from ..errors import Forbidden, InvalidGenerationRequest
from .deps import StudioDep

router = APIRouter(prefix="/api/auth", tags=["auth"])

CLIENT_ID = re.compile(r"^[0-9]+-[a-z0-9]+\.apps\.googleusercontent\.com$")

# Adivinar el codigo son 30^8 intentos, que no se hacen por HTTP ni en varias
# vidas. El contador esta igualmente: cuesta cuatro lineas y convierte "no da
# tiempo" en "no se puede".
FALLOS_MAX = 5
CASTIGO = 900.0
_fallos: list[float] = []


@router.get("/config")
def auth_config(request: Request, studio: StudioDep) -> dict[str, Any]:
    """Lo que el navegador necesita antes de pintar nada.

    Se entrega sin sesion a proposito: es la pantalla de entrada la que lo pide.
    El client ID no es un secreto —va escrito en el HTML de cualquier sitio que
    use Google Sign-In—; lo que protege es el par de claves que se queda en
    Google.
    """
    settings = studio.settings
    propietario = current_owner(request, settings)
    client_id = studio.oauth_client_id
    return {
        "login_required": settings.login_required,
        "client_id": client_id,
        "needs_setup": settings.login_required and not client_id,
        "signed_in": propietario is not None,
        "email": propietario.email if propietario else None,
    }


class SetupIn(BaseModel):
    client_id: str
    code: str


@router.post("/setup")
def setup(request: Request, studio: StudioDep, body: SetupIn) -> dict[str, Any]:
    """Guarda el Client ID que se acaba de crear en la consola.

    Con el estudio ya instalado esto solo lo puede hacer quien esta dentro. Sin
    instalar, lo autoriza el codigo que el instalador enseno en Cloud Shell: una
    direccion de Cloud Run es adivinable, y sin codigo el primero que pasara por
    ella podria dejar al dueno fuera de su propio estudio.
    """
    settings = studio.settings
    if not settings.login_required:
        raise Forbidden("Este estudio no tiene puerta configurada.")

    # El codigo sigue valiendo despues de instalar, y es a proposito. Un Client
    # ID mal copiado deja la pantalla de entrada sin boton, y entonces "entra
    # primero para poder corregirlo" es imposible: la unica salida seria volver
    # a Cloud Shell, que es justo lo que este rodeo evita. El codigo solo lo ve
    # quien puede leer la configuracion del servicio.
    if current_owner(request, settings) is None:
        ahora = time.monotonic()
        _fallos[:] = [t for t in _fallos if ahora - t < CASTIGO]
        if len(_fallos) >= FALLOS_MAX:
            raise Forbidden("Demasiados intentos. Espera un cuarto de hora.")
        # Comparacion en tiempo constante: una normal deja adivinar el codigo
        # caracter a caracter.
        if not settings.setup_code or not hmac.compare_digest(
            body.code.strip().upper(), settings.setup_code.strip().upper()
        ):
            _fallos.append(ahora)
            raise Forbidden("Ese codigo no es el que salio en Cloud Shell.")
        _fallos.clear()

    client_id = body.client_id.strip()
    if not CLIENT_ID.match(client_id):
        raise InvalidGenerationRequest(
            "Eso no parece un Client ID. Termina en .apps.googleusercontent.com"
        )

    studio.save_oauth_client_id(client_id)
    return {"client_id": client_id}


class SessionIn(BaseModel):
    credential: str
    """El token que devuelve el boton de Google."""


@router.post("/session")
def open_session(
    request: Request, studio: StudioDep, body: SessionIn, response: Response
) -> dict[str, Any]:
    """Canjea el token de Google por la cookie de sesion.

    Dos comprobaciones, y las dos importan: que Google firmo ese token para esta
    aplicacion, y que el correo que trae es el del propietario. La primera sola
    dejaria entrar a cualquiera que tenga una cuenta de Google.
    """
    settings = studio.settings
    if not settings.login_required:
        raise Forbidden("Este estudio no tiene puerta configurada.")

    client_id = studio.oauth_client_id
    if not client_id:
        raise Forbidden("Todavia falta el Client ID de Google. Termina la instalacion.")

    correo = verify_google_token(body.credential, client_id)
    if correo != settings.owner_email.strip().lower():
        # Sin decir cual es el correo que si vale: quien prueba cuentas ajenas no
        # tiene por que llevarse la respuesta.
        raise Forbidden("Esa cuenta de Google no es la duena de este estudio.")

    response.set_cookie(
        COOKIE,
        create_session(correo, settings.session_secret),
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        # Con puerta configurada siempre hay https delante. Mirar solo el esquema
        # dependeria de que las cabeceras del proxy lleguen bien, y si no llegan
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
