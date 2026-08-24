"""Object graph.

One ``Studio`` per process, built at startup and injected into the routers.
Tests build their own with an in memory database and dry run providers.
"""

from __future__ import annotations

import logging
from typing import Any

from .db.client import Database, build_database
from .db.repositories import CONFIG_MODELS
from .domain.registry import ModelRegistry, load_seed
from .providers.chirp import ChirpClient, build_chirp_client
from .providers.secrets import SecretStore, build_secret_store
from .providers.storage import Storage, build_storage
from .providers.vertex import CallLog, VertexClient, build_vertex_client
from .services.idempotency import IdempotencyStore
from .services.jobs import JobService
from .settings import Settings, get_settings

logger = logging.getLogger("aaus")


class Studio:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        db: Database | None = None,
        storage: Storage | None = None,
        vertex: VertexClient | None = None,
        chirp: ChirpClient | None = None,
        secrets: SecretStore | None = None,
    ):
        self.settings = settings or get_settings()
        self.db = db or build_database(self.settings)
        self.storage = storage or build_storage(self.settings)
        self.calls = CallLog()
        self.vertex = vertex or build_vertex_client(self.settings, self.calls)
        self.chirp = chirp or build_chirp_client(self.settings)
        self.secrets = secrets or build_secret_store(self.settings)

        self.idempotency = IdempotencyStore(self.db)
        self.jobs = JobService(self.db, self.settings)

        # Late import: the orchestrator imports services, which import the
        # container's building blocks but not the container itself.
        from .orchestrator.orchestrator import Orchestrator

        self.orchestrator = Orchestrator(self)
        self.jobs.runner = self.orchestrator.run_job

        self._registry: ModelRegistry | None = None

    # -- model registry ----------------------------------------------------
    def ensure_registry_seeded(self) -> dict[str, Any]:
        """Siembra el registro, y lo reescribe cuando la semilla trae una
        version mas nueva.

        Antes solo escribia si no habia nada, y eso dejo una correccion muerta:
        los identificadores de los modelos estaban mal -eran nombres
        comerciales y no los que Vertex reconoce-, se arreglaron en la semilla,
        y en una instalacion que ya existia no cambio nada. El documento seguia
        con los nombres viejos y cada generacion habria muerto en un 404.

        Solo pisa lo guardado cuando schema_version sube, asi que una edicion
        hecha a mano en Firestore sobrevive a los despliegues normales, que es
        justo para lo que ese documento existe.
        """
        guardado = self.db.get(CONFIG_MODELS)
        semilla = load_seed()
        version_guardada = int((guardado or {}).get("schema_version", 0))
        version_semilla = int(semilla.get("schema_version", 0))

        if guardado is not None and version_guardada >= version_semilla:
            return guardado

        semilla["id"] = "models"
        self.db.set(CONFIG_MODELS, semilla)
        logger.info(
            "model_registry_seeded de v%s a v%s", version_guardada, version_semilla
        )
        self._registry = None
        return semilla

    @property
    def registry(self) -> ModelRegistry:
        if self._registry is None:
            self._registry = ModelRegistry(self.ensure_registry_seeded())
        return self._registry

    def reload_registry(self) -> ModelRegistry:
        """Called after the config document is edited, so nothing redeploys."""
        self._registry = None
        return self.registry

    def replace_registry_document(self, document: dict[str, Any]) -> ModelRegistry:
        document = {**document, "id": "models"}
        self.db.set(CONFIG_MODELS, document)
        return self.reload_registry()


_studio: Studio | None = None


def get_studio() -> Studio:
    global _studio
    if _studio is None:
        _studio = Studio()
    return _studio


def set_studio(studio: Studio | None) -> None:
    global _studio
    _studio = studio
