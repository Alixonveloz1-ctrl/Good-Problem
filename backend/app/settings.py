"""Runtime configuration.

Everything that changes between local, staging and production lives here and is
read from the environment. No credentials: on Cloud Run the attached service
account provides identity through Application Default Credentials (PRD 40).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AAUS_", extra="ignore")

    # --- Identity -----------------------------------------------------------
    project_id: str = ""
    location: str = "us-central1"
    owner_email: str = ""
    """The single user of the system (PRD 41). Empty means dev mode: no gate."""

    # --- Backends -----------------------------------------------------------
    firestore_database: str = "(default)"
    bucket: str = ""
    tasks_queue: str = ""
    """Cloud Tasks queue name. Empty runs jobs in-process, which is fine locally."""
    tasks_target_url: str = ""
    """URL publica del servicio. Tambien es el destinatario del token OIDC con
    el que Cloud Tasks vuelve a entrar, asi que un token robado de otro sitio no
    sirve aqui."""
    tasks_service_account: str = ""

    # --- Entrada con Google (PRD 41) ---------------------------------------
    oauth_client_id: str = ""
    """Client ID del cliente OAuth de tipo web.

    Lo usa el navegador para pedirle a Google que identifique a la persona, y lo
    usa el servidor para comprobar que el token que llega fue emitido para esta
    aplicacion y no para otra distinta.
    """
    session_secret: str = ""
    """Clave con la que se firma la cookie de sesion.

    La genera el instalador y vive como variable de entorno del servicio. Si se
    cambia, todas las sesiones abiertas caducan, que es justo lo que se quiere
    si alguna vez hay que echar a alguien.
    """
    setup_code: str = ""
    """Codigo de un solo uso para pegar el Client ID desde el propio telefono.

    Google no ofrece ninguna API para crear un cliente OAuth de tipo web: hay que
    crearlo a mano en la consola. Lo que sale de ahi es una cadena de setenta
    caracteres, y Cloud Shell en un movil no deja pegar. Asi que el Client ID
    entra por una pantalla del navegador, donde pegar si funciona, y este codigo
    —ocho caracteres, se leen de la pantalla y se escriben— es lo que impide que
    lo haga cualquiera que pase por la direccion antes que su dueno.

    Deja de valer en cuanto hay un Client ID guardado.
    """

    # --- Modes --------------------------------------------------------------
    dry_run: bool = True
    """When true no paid API is called; providers return deterministic stubs.

    Defaults to true so that a misconfigured deploy cannot spend money by
    accident. Production sets AAUS_DRY_RUN=false explicitly.
    """
    local_data_dir: str = str(BACKEND_ROOT / ".localdata")
    static_dir: str = str(REPO_ROOT / "frontend" / "dist")

    @property
    def use_firestore(self) -> bool:
        return bool(self.project_id)

    @property
    def use_gcs(self) -> bool:
        return bool(self.bucket)

    @property
    def login_required(self) -> bool:
        """Hay puerta cuando se sabe a quien hay que dejar entrar."""
        return bool(self.owner_email)

    def check(self) -> list[str]:
        """Fallos de configuracion que dejarian el estudio abierto de par en par.

        Se comprueban al arrancar y no al recibir la primera peticion: un
        despliegue mal puesto tiene que fallar en el momento del despliegue, no
        media hora despues cuando alguien pasa por delante de la puerta.
        """
        problemas: list[str] = []
        if self.login_required:
            if not self.oauth_client_id and len(self.setup_code) < 6:
                problemas.append(
                    "AAUS_OWNER_EMAIL esta puesto pero no hay ni AAUS_OAUTH_CLIENT_ID "
                    "ni AAUS_SETUP_CODE: nadie podria entrar ni terminar de instalar."
                )
            if len(self.session_secret) < 32:
                problemas.append(
                    "AAUS_SESSION_SECRET falta o es demasiado corto (minimo 32 "
                    "caracteres): las sesiones se podrian falsificar."
                )
        return problemas


@lru_cache
def get_settings() -> Settings:
    return Settings()
