"""Acceso al estudio (PRD 41).

Una sola persona entra: el propietario, con su cuenta de Google. No hay
registro, ni roles, ni recuperación de contraseña. Solo un botón de "Entrar con
Google" y una lista de correos permitidos que tiene exactamente un nombre.

Quien identifica es Firebase Authentication. El PRD daba por hecho IAM más
Identity Aware Proxy, "sin pantalla de consentimiento OAuth"; esa premisa no se
sostiene, porque IAP sobre una cuenta personal de Gmail exige crear a mano
exactamente esa pantalla y un cliente de OAuth, y hasta entonces el servicio
responde "Empty Google Account OAuth client ID(s)/secret(s)" y nada más.

Con Firebase el instalador lo consigue todo por API: activa Firebase sobre el
mismo proyecto, crea la aplicación web y lee su configuración. Nadie copia un
Client ID de setenta caracteres a mano, que es lo que hacía falta por el otro
camino.

Lo que sí se conserva del PRD: nadie se registra, no hay contraseñas, y la
identidad la pone Google.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from fastapi import Request

from .errors import Forbidden, SinSesion
from .settings import Settings

COOKIE = "aaus_session"
SESSION_DAYS = 30

# Lo único que responde sin sesión: la comprobación de vida y la propia puerta.
# Nadie puede identificarse si para identificarse hace falta estar ya dentro.
PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/api/health",
        "/api/auth/config",
        "/api/auth/session",
        "/api/auth/logout",
    }
)

# Por donde entra la cola de trabajos, que no trae cookie sino un token firmado
# por su cuenta de servicio.
SERVICE_PREFIX = "/api/internal/"

# Lo que el navegador tiene que poder cargar sin sesión, porque es justamente lo
# que dibuja la pantalla de entrada: el HTML, el JavaScript y los iconos. Los
# datos de detrás no.
GUARDED_PREFIXES = ("/api/", "/media/")


@dataclass(frozen=True)
class Owner:
    email: str
    verified: bool


# --- La cookie de sesión ----------------------------------------------------


def _sign(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def create_session(email: str, secret: str, *, days: int = SESSION_DAYS) -> str:
    """Una cookie firmada: si alguien la manipula, la firma deja de cuadrar."""
    payload = json.dumps(
        {"email": email, "exp": int(time.time()) + days * 86400}, separators=(",", ":")
    ).encode()
    cuerpo = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    return f"{cuerpo}.{_sign(payload, secret)}"


def read_session(cookie: str, secret: str) -> str | None:
    """Devuelve el correo de la sesión, o None si la cookie no vale."""
    if not cookie or "." not in cookie:
        return None
    cuerpo, firma = cookie.rsplit(".", 1)
    try:
        payload = base64.urlsafe_b64decode(cuerpo + "=" * (-len(cuerpo) % 4))
    except (ValueError, TypeError):
        return None
    # Comparación en tiempo constante: una normal filtra cuántos caracteres
    # acertó quien lo intenta.
    if not hmac.compare_digest(firma, _sign(payload, secret)):
        return None
    try:
        datos = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if int(datos.get("exp", 0)) < time.time():
        return None
    return datos.get("email")


# --- La identidad que pone Google ------------------------------------------


def verify_firebase_token(credential: str, project_id: str) -> str:
    """Comprueba el token del login y devuelve el correo.

    La verificación la hace la librería oficial: descarga las claves públicas de
    Google, comprueba la firma, la caducidad, el emisor y que el token vaya
    dirigido a este proyecto. Sin lo último valdría un token emitido por el
    Firebase de cualquier otro.
    """
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    try:
        datos = id_token.verify_firebase_token(
            credential, google_requests.Request(), project_id
        )
    except ValueError as exc:
        raise Forbidden(f"Google no dio por bueno ese acceso: {exc}") from exc

    if datos.get("iss") != f"https://securetoken.google.com/{project_id}":
        raise Forbidden("Ese token no lo emitió este estudio.")
    if not datos.get("email_verified"):
        raise Forbidden("Esa cuenta de Google no tiene el correo verificado.")
    correo = (datos.get("email") or "").strip().lower()
    if not correo:
        raise Forbidden("Google no devolvió ningún correo.")
    return correo


def verify_service_token(request: Request, settings: Settings) -> bool:
    """La cola de trabajos llamando de vuelta al worker.

    Cloud Tasks firma cada petición con un token de su cuenta de servicio. Se
    comprueba igual que el del navegador: firma, caducidad, destinatario, y que
    venga de la cuenta que se espera.
    """
    cabecera = request.headers.get("authorization", "")
    if not cabecera.startswith("Bearer ") or not settings.tasks_service_account:
        return False

    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    try:
        datos = id_token.verify_oauth2_token(
            cabecera[7:], google_requests.Request(), service_audience(settings)
        )
    except ValueError:
        return False
    return (datos.get("email") or "").lower() == settings.tasks_service_account.lower()


# --- El encargo firmado -----------------------------------------------------

COLA = "x-aaus-cola"
"""La cabecera con la que la cola demuestra que el encargo salio de aqui."""

ENCARGO_DIAS = 7


def firmar_encargo(universe_id: str, job_id: str, secret: str) -> str:
    """Un pase para un trabajo concreto, firmado con la clave del estudio.

    Antes esto lo hacia un token OIDC de Google, y era mejor en teoria. En la
    practica exigia un permiso —actuar en nombre de la cuenta de la cola— que
    solo se puede dar desde una consola o escribiendo ordenes a mano, y sin el
    ninguna generacion arrancaba. Un candado que hay que ir a montar a otro
    sitio es un candado que un dia no esta puesto.

    La firma no es mas debil que lo que ya protege el estudio entero: es la
    misma clave que firma la sesion del navegador. Quien la tuviera podria
    entrar como el dueño y lanzar generaciones por la puerta principal, asi que
    esta puerta no es el eslabon flojo.

    Va atado a un trabajo concreto y caduca, para que un encargo repescado no
    sirva de llave general.
    """
    payload = json.dumps(
        {"u": universe_id, "j": job_id, "exp": int(time.time()) + ENCARGO_DIAS * 86400},
        separators=(",", ":"),
    ).encode()
    cuerpo = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    return f"{cuerpo}.{_sign(payload, secret)}"


def leer_encargo(valor: str, secret: str) -> tuple[str, str] | None:
    """Devuelve (universo, trabajo) del pase, o None si no vale."""
    if not valor or "." not in valor or not secret:
        return None
    cuerpo, firma = valor.rsplit(".", 1)
    try:
        payload = base64.urlsafe_b64decode(cuerpo + "=" * (-len(cuerpo) % 4))
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(firma, _sign(payload, secret)):
        return None
    try:
        datos = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if int(datos.get("exp", 0)) < time.time():
        return None
    universo, trabajo = datos.get("u"), datos.get("j")
    if not universo or not trabajo:
        return None
    return str(universo), str(trabajo)


def service_audience(settings: Settings) -> str | None:
    """El destinatario del token de la cola, escrito una sola vez.

    Lo usan dos sitios: quien encarga la tarea y quien la recibe. Si cada uno lo
    calcula por su cuenta, una barra de más al final del ajuste basta para que
    ningún trabajo llegue a ejecutarse nunca, con un 401 por toda explicación.
    """
    return settings.tasks_target_url.rstrip("/") or None


# --- La puerta --------------------------------------------------------------


def is_open(settings: Settings) -> bool:
    """Sin correo de propietario configurado no hay puerta, que es lo que
    necesita un portátil."""
    return not settings.owner_email


def current_owner(request: Request, settings: Settings) -> Owner | None:
    if is_open(settings):
        return Owner(email=settings.owner_email or "dev@localhost", verified=False)
    correo = read_session(request.cookies.get(COOKIE, ""), settings.session_secret)
    if correo and correo == settings.owner_email.strip().lower():
        return Owner(email=correo, verified=True)
    return None


def identify(request: Request, settings: Settings) -> Owner:
    propietario = current_owner(request, settings)
    if propietario is None:
        raise SinSesion("Entra con tu cuenta de Google para usar el estudio.")
    return propietario


def gate(request: Request, settings: Settings) -> Forbidden | None:
    """La puerta, aplicada a una petición cualquiera.

    Vive aquí y no en cada ruta a propósito. Una ruta nueva se puede escribir
    sin acordarse de pedir identidad —de hecho pasó: /media/ servía cualquier
    archivo generado a quien acertara la ruta—. Un middleware no se olvida.

    Devuelve el error que hay que responder, o None si puede pasar.
    """
    if is_open(settings):
        return None

    ruta = request.url.path
    if ruta in PUBLIC_PATHS:
        return None

    if ruta.startswith(SERVICE_PREFIX):
        # Vale el pase firmado por el estudio o, si alguien monto la cola con
        # OIDC a mano, el token de Google. Cualquiera de los dos, no los dos.
        if leer_encargo(request.headers.get(COLA, ""), settings.session_secret):
            return None
        if verify_service_token(request, settings):
            return None
        return Forbidden("Esta ruta es solo para la cola de trabajos.")

    if not ruta.startswith(GUARDED_PREFIXES):
        return None  # el HTML y el JavaScript de la pantalla de entrada

    if current_owner(request, settings) is None:
        return SinSesion("Entra con tu cuenta de Google para usar el estudio.")
    return None
