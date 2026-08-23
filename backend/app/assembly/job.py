"""Cloud Run Job entrypoint for the Media Assembly Engine (PRD 29).

Heavy renders do not belong in a request. This module is the container entry
point for a Cloud Run Job: it reads what to assemble from the environment, runs
the engine and writes the outcome back onto the Job document, so the phone sees
the same states as any other job (PRD 37).

    gcloud run jobs execute aaus-assembly \\
      --update-env-vars UNIVERSE_ID=uni_x,PROJECT_ID=vp_y,JOB_ID=job_z
"""

from __future__ import annotations

import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("aaus.assembly.job")


def main() -> int:
    from ..container import Studio
    from ..domain.enums import JobState
    from .engine import assemble_project

    universe_id = os.environ.get("UNIVERSE_ID", "")
    project_id = os.environ.get("PROJECT_ID", "")
    job_id = os.environ.get("JOB_ID", "")
    formats = [f.strip() for f in os.environ.get("FORMATS", "16:9,9:16").split(",") if f.strip()]
    captions = os.environ.get("CAPTIONS", "").lower() in {"1", "true", "yes"}

    if not universe_id or not project_id:
        logger.error("UNIVERSE_ID y PROJECT_ID son obligatorios")
        return 2

    studio = Studio()
    if job_id:
        studio.jobs.mark_processing(universe_id, job_id)
    try:
        result = assemble_project(
            studio, universe_id, project_id, formats=formats, captions=captions
        )
    except Exception as exc:  # noqa: BLE001 - reported through the job document
        logger.exception("assembly_failed")
        if job_id:
            studio.jobs.mark_failed(universe_id, job_id, str(exc))
        return 1

    logger.info("assembly_done %s", result)
    if job_id:
        studio.jobs.mark_ready(universe_id, job_id, result)
    else:
        logger.info("sin JOB_ID: no se actualizo ningun job (%s)", JobState.READY.value)
    return 0


if __name__ == "__main__":
    sys.exit(main())
