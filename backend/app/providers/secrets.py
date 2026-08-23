"""Secret Manager access.

Exactly one secret exists in this project: the Chirp 3 voice cloning key. It is
an API identifier, not a credential for the account. No service account JSON key
is generated, downloaded or stored anywhere in the system (PRD 40).
"""

from __future__ import annotations

from ..errors import ProviderError


class SecretStore:
    def __init__(self, project: str, *, dry_run: bool = True):
        self.project = project
        self.dry_run = dry_run or not project
        self._local: dict[str, str] = {}

    def read(self, name: str, version: str = "latest") -> str:
        if self.dry_run:
            return self._local.get(name, "DRY_RUN_VOICE_CLONING_KEY")
        try:
            from google.cloud import secretmanager
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ProviderError(
                "google-cloud-secret-manager no esta instalado en esta imagen."
            ) from exc
        client = secretmanager.SecretManagerServiceClient()
        path = f"projects/{self.project}/secrets/{name}/versions/{version}"
        return client.access_secret_version(request={"name": path}).payload.data.decode()

    def write(self, name: str, value: str) -> None:
        if self.dry_run:
            self._local[name] = value
            return
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        parent = f"projects/{self.project}"
        secret_path = f"{parent}/secrets/{name}"
        try:
            client.get_secret(request={"name": secret_path})
        except Exception:
            client.create_secret(
                request={
                    "parent": parent,
                    "secret_id": name,
                    "secret": {"replication": {"automatic": {}}},
                }
            )
        client.add_secret_version(
            request={"parent": secret_path, "payload": {"data": value.encode()}}
        )


def build_secret_store(settings) -> SecretStore:
    return SecretStore(settings.project_id, dry_run=settings.dry_run)
