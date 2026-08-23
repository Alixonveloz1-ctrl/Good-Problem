from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.container import Studio, set_studio
from app.db.client import MemoryDatabase
from app.providers.chirp import ChirpClient
from app.providers.secrets import SecretStore
from app.providers.storage import LocalStorage
from app.providers.vertex import VertexClient
from app.settings import Settings


@pytest.fixture
def tmp_root():
    path = Path(tempfile.mkdtemp(prefix="aaus-test-"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def settings(tmp_root) -> Settings:
    return Settings(
        project_id="",
        owner_email="",
        dry_run=True,
        local_data_dir=str(tmp_root),
        static_dir=str(tmp_root / "no-frontend"),
    )


@pytest.fixture
def studio(settings, tmp_root) -> Studio:
    instance = Studio(
        settings,
        db=MemoryDatabase(),
        storage=LocalStorage(str(tmp_root / "media")),
        vertex=VertexClient("test-project", dry_run=True),
        chirp=ChirpClient("test-project", dry_run=True),
        secrets=SecretStore("test-project", dry_run=True),
    )
    instance.vertex.calls = instance.calls
    instance.ensure_registry_seeded()
    set_studio(instance)
    yield instance
    set_studio(None)


@pytest.fixture
def client(studio) -> TestClient:
    from app.main import app

    app.state.studio = studio
    with TestClient(app) as test_client:
        yield test_client
    app.state.studio = None


@pytest.fixture
def universe(client) -> str:
    response = client.post("/api/universes", json={"name": "Nova"})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def wait_for_jobs(studio, timeout: float = 30.0) -> None:
    studio.jobs.wait_for_idle(timeout)
