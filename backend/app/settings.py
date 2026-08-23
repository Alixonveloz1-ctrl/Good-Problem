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
    tasks_service_account: str = ""

    # --- Modes --------------------------------------------------------------
    dry_run: bool = True
    """When true no paid API is called; providers return deterministic stubs.

    Defaults to true so that a misconfigured deploy cannot spend money by
    accident. Production sets AAUS_DRY_RUN=false explicitly.
    """
    local_data_dir: str = str(BACKEND_ROOT / ".localdata")
    static_dir: str = str(REPO_ROOT / "frontend" / "dist")

    # --- Credit window (PRD 44) ---------------------------------------------
    credit_started_on: str = ""
    """ISO date the $300 welcome credit started. Drives the 90 day countdown."""
    credit_total_usd: float = 300.0
    credit_days: int = 90

    @property
    def use_firestore(self) -> bool:
        return bool(self.project_id)

    @property
    def use_gcs(self) -> bool:
        return bool(self.bucket)


@lru_cache
def get_settings() -> Settings:
    return Settings()
