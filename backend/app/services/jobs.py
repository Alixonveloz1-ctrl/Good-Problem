"""Generation queue (PRD 37).

Jobs keep running in Google Cloud whether or not Safari stays open, so the queue
is Cloud Tasks pushing back into this same Cloud Run service. Without a queue
configured the job runs in a background thread instead, which is what a laptop
and the test suite need.

A failed job retries with the model that was requested. The system never
substitutes a different or weaker model, so ``retry`` asserts that.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from ..clock import now, now_iso
from ..db.client import Database
from ..db.repositories import JOBS, Repository
from ..domain.enums import JobState
from ..domain.guards import assert_same_model_on_retry
from ..errors import Conflict, NotFound, ProviderError
from ..ids import new_id
from ..settings import Settings

logger = logging.getLogger("aaus.jobs")

JobRunner = Callable[[str, str], None]
"""(universe_id, job_id) -> None"""

SIN_ENTREGAR_TRAS_SEGUNDOS = 600
"""Diez minutos «en cola» sin un solo intento = la entrega no llego."""

MENSAJE_COLA_NO_ENTREGO = "La cola no llegó a entregar este trabajo"
"""El motivo visible cuando ni el re-encolado del vigilante llego."""


class JobService:
    def __init__(self, db: Database, settings: Settings, runner: JobRunner | None = None):
        self.db = db
        self.settings = settings
        self.runner = runner
        self._threads: list[threading.Thread] = []
        self._vigilando = False

    def repo(self, universe_id: str) -> Repository:
        return Repository(self.db, universe_id, JOBS)

    # -- lifecycle ---------------------------------------------------------
    def create(
        self,
        universe_id: str,
        *,
        kind: str,
        model: str,
        variant: str,
        target_type: str,
        target_id: str,
        request: dict[str, Any],
        estimated_cost_usd: float,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        job_id = new_id("job")
        return self.repo(universe_id).create(
            job_id,
            {
                "kind": kind,
                "state": JobState.QUEUED.value,
                "model": model,
                "variant": variant,
                "target_type": target_type,
                "target_id": target_id,
                "request": request,
                "result": None,
                "error": None,
                "attempts": 0,
                "max_attempts": 3,
                "idempotency_key": idempotency_key,
                "estimated_cost_usd": round(estimated_cost_usd, 4),
                "actual_cost_usd": 0.0,
                "started_at": None,
                "finished_at": None,
            },
        )

    def get(self, universe_id: str, job_id: str) -> dict[str, Any]:
        self.vigilar(universe_id)
        return self.repo(universe_id).require(job_id)

    def list(self, universe_id: str, *, state: str | None = None, limit: int = 50):
        self.vigilar(universe_id)
        where = {"state": state} if state else None
        return self.repo(universe_id).list(where=where, limit=limit)

    def active(self, universe_id: str, limit: int = 50) -> list[dict[str, Any]]:
        self.vigilar(universe_id)
        rows = self.repo(universe_id).list(limit=200)
        return [
            row
            for row in rows
            if row.get("state") in {JobState.QUEUED.value, JobState.PROCESSING.value}
        ][:limit]

    # -- vigilante de entregas ----------------------------------------------
    @staticmethod
    def _segundos_desde(marca: Any) -> float | None:
        if not marca:
            return None
        try:
            desde = datetime.fromisoformat(str(marca))
        except ValueError:
            return None
        if desde.tzinfo is None:
            desde = desde.replace(tzinfo=UTC)
        return (now() - desde).total_seconds()

    def vigilar(self, universe_id: str) -> None:
        """Rescata los trabajos que la cola nunca entrego.

        El documento se escribe «en cola» antes de encargarlo, y todo fallo
        DENTRO del servicio deja rastro (PROCESSING, FAILED con su error).
        El punto ciego esta entre la cola y este codigo: la entrega es un
        intento contra este servicio, y si ese intento cae en un despliegue
        o en un 503, la tarea muere y el trabajo se queda en QUEUED para
        siempre, sin error y sin que nadie lo mire — paso dos veces seguidas
        con la reescritura de la Biblia de un artista real.

        Al leer trabajos, el vigilante mira ese punto ciego: un QUEUED con
        ``attempts == 0`` (nadie lo llego a procesar) y mas de diez minutos
        se re-encola UNA vez; si tras otros diez minutos sigue sin
        entregarse, se marca FAILED con el motivo a la vista. Un fallo
        visible siempre es mejor que una espera eterna.
        """
        if self._vigilando:
            return
        self._vigilando = True
        try:
            try:
                filas = self.repo(universe_id).list(limit=200)
            except Exception:  # pragma: no cover - el vigilante nunca tumba una lectura
                return
            for job in filas:
                if job.get("state") != JobState.QUEUED.value:
                    continue
                if int(job.get("attempts", 0)) != 0:
                    continue
                edad = self._segundos_desde(job.get("created_at"))
                if edad is None or edad < SIN_ENTREGAR_TRAS_SEGUNDOS:
                    continue
                reencolado = job.get("watchdog_requeued_at")
                if not reencolado:
                    self.repo(universe_id).update(
                        job["id"], {"watchdog_requeued_at": now_iso()}
                    )
                    try:
                        self.enqueue(universe_id, job["id"])
                    except Exception:
                        # enqueue ya dejo el trabajo FAILED con el motivo
                        # del encargo: visible, que es lo que se busca.
                        logger.exception(
                            "vigilante: no se pudo re-encolar %s", job["id"]
                        )
                    continue
                desde_reencolado = self._segundos_desde(reencolado)
                if (
                    desde_reencolado is not None
                    and desde_reencolado >= SIN_ENTREGAR_TRAS_SEGUNDOS
                ):
                    self.mark_failed(
                        universe_id, job["id"], MENSAJE_COLA_NO_ENTREGO
                    )
        finally:
            self._vigilando = False

    def mark_processing(self, universe_id: str, job_id: str) -> dict[str, Any]:
        job = self.get(universe_id, job_id)
        if job["state"] not in {JobState.QUEUED.value, JobState.PROCESSING.value}:
            raise Conflict(f"El job {job_id} esta en estado {job['state']}.")
        return self.repo(universe_id).update(
            job_id,
            {
                "state": JobState.PROCESSING.value,
                "attempts": int(job.get("attempts", 0)) + 1,
                "started_at": job.get("started_at") or now_iso(),
            },
        )

    def mark_ready(
        self, universe_id: str, job_id: str, result: dict[str, Any], *, cost_usd: float = 0.0
    ) -> dict[str, Any]:
        return self.repo(universe_id).update(
            job_id,
            {
                "state": JobState.READY.value,
                "result": result,
                "actual_cost_usd": round(cost_usd, 4),
                "finished_at": now_iso(),
                "error": None,
            },
        )

    def mark_failed(self, universe_id: str, job_id: str, error: str) -> dict[str, Any]:
        return self.repo(universe_id).update(
            job_id,
            {"state": JobState.FAILED.value, "error": error[:2000], "finished_at": now_iso()},
        )

    def mark_state(self, universe_id: str, job_id: str, state: JobState) -> dict[str, Any]:
        """Used by the approval flow: READY -> APPROVED or REJECTED."""
        return self.repo(universe_id).update(job_id, {"state": state.value})

    def cancel(self, universe_id: str, job_id: str) -> dict[str, Any]:
        job = self.get(universe_id, job_id)
        if JobState(job["state"]).is_terminal:
            raise Conflict(f"El job {job_id} ya termino ({job['state']}).")
        return self.repo(universe_id).update(
            job_id, {"state": JobState.CANCELLED.value, "finished_at": now_iso()}
        )

    def retry(self, universe_id: str, job_id: str, *, model: str | None = None) -> dict[str, Any]:
        job = self.get(universe_id, job_id)
        if job["state"] != JobState.FAILED.value:
            raise Conflict("Solo se reintentan jobs fallidos.")
        # PRD 37: same model, always.
        assert_same_model_on_retry(job["model"], model or job["model"])
        if int(job.get("attempts", 0)) >= int(job.get("max_attempts", 3)):
            raise Conflict(
                f"El job {job_id} agoto sus {job.get('max_attempts', 3)} intentos. "
                "Lanza una generacion nueva si quieres insistir."
            )
        updated = self.repo(universe_id).update(
            job_id, {"state": JobState.QUEUED.value, "error": None, "finished_at": None}
        )
        self.enqueue(universe_id, job_id)
        return updated

    # -- dispatch ----------------------------------------------------------
    def enqueue(self, universe_id: str, job_id: str) -> None:
        """Encarga el trabajo, y si no se puede lo deja marcado como fallido.

        El documento se escribe como "en cola" antes de encolarlo de verdad. Si
        el encargo falla y nadie corrige ese estado, la pantalla se queda
        diciendo "EN COLA" para siempre sobre un trabajo que nunca existio.
        Eso paso: un permiso que faltaba, y la app mintiendo tan tranquila.

        Un estado falso es peor que un error: con el error se sabe que hacer, y
        con el estado falso se espera.
        """
        try:
            if self.settings.tasks_queue and self.settings.tasks_target_url:
                self._enqueue_cloud_task(universe_id, job_id)
            else:
                self._run_inline(universe_id, job_id)
        except Exception as exc:
            self.mark_failed(universe_id, job_id, f"No se pudo encargar: {exc}")
            raise

    def build_task(self, universe_id: str, job_id: str, http_method: Any) -> dict[str, Any]:
        """La tarea que se le entrega a Cloud Tasks.

        Separada de la llamada para poder comprobarla sin red: es el punto donde
        un detalle mal puesto deja los trabajos sin ejecutarse.
        """
        from ..auth import COLA, firmar_encargo

        # El pase va firmado con la clave del estudio, no con un token de
        # Google. El token OIDC era mejor sobre el papel, pero para emitirlo
        # hacia falta el permiso de actuar en nombre de la cuenta de la cola, y
        # eso no se puede dar desde el codigo: hay que ir a darlo a mano. Sin
        # el, ni una imagen, ni una cancion, ni un video llegaban a empezar.
        return {
            "http_request": {
                "http_method": http_method,
                "url": f"{self.settings.tasks_target_url.rstrip('/')}/api/internal/jobs/run",
                "headers": {
                    "Content-Type": "application/json",
                    COLA: firmar_encargo(universe_id, job_id, self.settings.session_secret),
                },
                "body": json.dumps({"universe_id": universe_id, "job_id": job_id}).encode(),
            }
        }

    def _enqueue_cloud_task(self, universe_id: str, job_id: str) -> None:
        from google.cloud import tasks_v2

        client = tasks_v2.CloudTasksClient()
        parent = client.queue_path(
            self.settings.project_id, self.settings.location, self.settings.tasks_queue
        )
        task = self.build_task(universe_id, job_id, tasks_v2.HttpMethod.POST)
        try:
            client.create_task(request={"parent": parent, "task": task})
        except Exception as exc:
            # Ya no hace falta ningun permiso especial para encargar: el pase lo
            # firma la propia aplicacion. Si aun asi Google dice que no, lo que
            # falta es la cola, y eso si lo monta el instalador.
            if "PermissionDenied" in type(exc).__name__ or "NotFound" in type(exc).__name__:
                raise ProviderError(
                    f"La cola de trabajos no responde ({self.settings.tasks_queue}). "
                    "Ejecuta ./setup.sh una vez en Cloud Shell."
                ) from exc
            raise
        logger.info("job_enqueued %s %s", universe_id, job_id)

    def _run_inline(self, universe_id: str, job_id: str) -> None:
        if self.runner is None:
            raise NotFound("No hay ejecutor de jobs configurado.")
        thread = threading.Thread(
            target=self._safe_run, args=(universe_id, job_id), daemon=True, name=f"job-{job_id}"
        )
        self._threads.append(thread)
        thread.start()

    def _safe_run(self, universe_id: str, job_id: str) -> None:
        try:
            self.runner(universe_id, job_id)  # type: ignore[misc]
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("job_failed %s %s", job_id, exc)
            try:
                self.mark_failed(universe_id, job_id, str(exc))
            except Exception:
                pass

    def wait_for_idle(self, timeout: float = 30.0) -> None:
        """Test and local helper: block until inline jobs finish.

        Un trabajo puede encadenar otro al terminar —el de creacion
        encarga el diseno del personaje cuando sus analisis ya estan
        guardados—, y ese hilo nuevo se suma a la lista mientras se
        espera. Esperar solo los hilos que habia al llamar dejaria la
        cadena a medias y la prueba siguiente leeria un estado que
        todavia no es el final: se espera hasta que no quede ninguno
        vivo o hasta agotar el tiempo, lo primero que pase.
        """
        limite = time.monotonic() + timeout
        while True:
            vivos = [t for t in self._threads if t.is_alive()]
            if not vivos:
                self._threads = []
                return
            for thread in vivos:
                restante = limite - time.monotonic()
                if restante <= 0:
                    self._threads = vivos
                    return
                thread.join(restante)
