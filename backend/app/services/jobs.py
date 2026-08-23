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
from collections.abc import Callable
from typing import Any

from ..clock import now_iso
from ..db.client import Database
from ..db.repositories import JOBS, Repository
from ..domain.enums import JobState
from ..domain.guards import assert_same_model_on_retry
from ..errors import Conflict, NotFound
from ..ids import new_id
from ..settings import Settings

logger = logging.getLogger("aaus.jobs")

JobRunner = Callable[[str, str], None]
"""(universe_id, job_id) -> None"""


class JobService:
    def __init__(self, db: Database, settings: Settings, runner: JobRunner | None = None):
        self.db = db
        self.settings = settings
        self.runner = runner
        self._threads: list[threading.Thread] = []

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
        return self.repo(universe_id).require(job_id)

    def list(self, universe_id: str, *, state: str | None = None, limit: int = 50):
        where = {"state": state} if state else None
        return self.repo(universe_id).list(where=where, limit=limit)

    def active(self, universe_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.repo(universe_id).list(limit=200)
        return [
            row
            for row in rows
            if row.get("state") in {JobState.QUEUED.value, JobState.PROCESSING.value}
        ][:limit]

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
        if self.settings.tasks_queue and self.settings.tasks_target_url:
            self._enqueue_cloud_task(universe_id, job_id)
            return
        self._run_inline(universe_id, job_id)

    def _enqueue_cloud_task(self, universe_id: str, job_id: str) -> None:
        from google.cloud import tasks_v2

        client = tasks_v2.CloudTasksClient()
        parent = client.queue_path(
            self.settings.project_id, self.settings.location, self.settings.tasks_queue
        )
        task: dict[str, Any] = {
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": f"{self.settings.tasks_target_url.rstrip('/')}/api/internal/jobs/run",
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"universe_id": universe_id, "job_id": job_id}).encode(),
            }
        }
        if self.settings.tasks_service_account:
            task["http_request"]["oidc_token"] = {
                "service_account_email": self.settings.tasks_service_account
            }
        client.create_task(request={"parent": parent, "task": task})
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
        """Test and local helper: block until inline jobs finish."""
        for thread in list(self._threads):
            thread.join(timeout)
        self._threads = [t for t in self._threads if t.is_alive()]
