"""Runtime configuration.

Everything that changes between local, staging and production lives here and is
read from the environment. No credentials: on Cloud Run the attached service
account provides identity through Application Default Credentials (PRD 40).
"""

from __future__ import annotations

import json
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
    firebase_config: str = ""
    """La configuracion web de Firebase, tal cual la devuelve su API.

    Un JSON con apiKey, authDomain y projectId. No es secreta: esta pensada
    para ir escrita en el navegador, igual que en cualquier sitio que use
    "Entrar con Google". Lo que protege el estudio es el correo del dueno y la
    firma de la cookie.

    Viene entera del instalador, que la lee de la API de Firebase. Nadie la
    copia a mano.
    """
    session_secret: str = ""
    """Clave con la que se firma la cookie de sesion.

    La genera el instalador y vive como variable de entorno del servicio. Si se
    cambia, todas las sesiones abiertas caducan, que es justo lo que se quiere
    si alguna vez hay que echar a alguien.
    """

    gemini_api_key: str = ""
    """La clave de Gemini del dueno (AAUS_GEMINI_API_KEY).

    Vive como variable de entorno del servicio, puesta una sola vez por
    el dueno en la consola de Google Cloud, escribiendola el mismo. Con
    ella, la musica va por la API de Gemini con Lyria 3.5; sin ella, por
    Vertex con Lyria 3 Pro. La app no la guarda ni la muestra: ningun
    GET la devuelve.
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
    def firebase(self) -> dict[str, str]:
        """La configuracion de Firebase ya leida, o vacia si no hay o esta rota."""
        if not self.firebase_config:
            return {}
        try:
            datos = json.loads(self.firebase_config)
        except json.JSONDecodeError:
            return {}
        return datos if isinstance(datos, dict) else {}

    @property
    def firebase_project(self) -> str:
        """El proyecto al que van dirigidos los tokens del login.

        Es el destinatario que hay que exigirle a cada token: sin comprobarlo,
        valdria un token emitido por el Firebase de cualquier otro.
        """
        return str(self.firebase.get("projectId", ""))

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
            if not self.firebase_project:
                problemas.append(
                    "AAUS_OWNER_EMAIL esta puesto pero falta AAUS_FIREBASE_CONFIG: "
                    "nadie podria entrar."
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
