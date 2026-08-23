"""Binary asset storage.

Layout follows PRD 48::

    /universes/{universe_id}/
      character/ wardrobe/ locations/ songs/{song_id}/ video-projects/{project_id}/
      scenes/{scene_id}/ content/ references/ exports/ temp/

``GcsStorage`` runs on Cloud Run with the attached service account.
``LocalStorage`` writes under ``.localdata/media`` so the whole pipeline can be
exercised without a bucket.
"""

from __future__ import annotations

import mimetypes
import shutil
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class StoredObject:
    path: str
    """Object path inside the bucket, without the gs:// prefix."""
    uri: str
    """Canonical URI: gs://bucket/path locally rewritten to file://."""
    size: int
    content_type: str

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "uri": self.uri,
            "size": self.size,
            "content_type": self.content_type,
        }


class Storage(Protocol):
    def write_bytes(self, path: str, data: bytes, content_type: str | None = None) -> StoredObject:
        ...

    def read_bytes(self, path: str) -> bytes: ...

    def exists(self, path: str) -> bool: ...

    def signed_url(self, path: str, *, minutes: int = 60) -> str: ...

    def uri(self, path: str) -> str: ...


def guess_content_type(path: str, fallback: str = "application/octet-stream") -> str:
    guessed, _ = mimetypes.guess_type(path)
    return guessed or fallback


class LocalStorage:
    def __init__(self, root: str, public_prefix: str = "/media"):
        self.root = Path(root)
        self.public_prefix = public_prefix.rstrip("/")
        self.root.mkdir(parents=True, exist_ok=True)

    def _full(self, path: str) -> Path:
        clean = path.strip("/")
        if ".." in clean.split("/"):
            raise ValueError(f"unsafe path: {path}")
        return self.root / clean

    def write_bytes(self, path: str, data: bytes, content_type: str | None = None) -> StoredObject:
        target = self._full(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return StoredObject(
            path=path.strip("/"),
            uri=target.as_uri(),
            size=len(data),
            content_type=content_type or guess_content_type(path),
        )

    def read_bytes(self, path: str) -> bytes:
        return self._full(path).read_bytes()

    def exists(self, path: str) -> bool:
        return self._full(path).exists()

    def signed_url(self, path: str, *, minutes: int = 60) -> str:
        # Served by the app itself in local mode; see routers/media.py.
        return f"{self.public_prefix}/{path.strip('/')}"

    def uri(self, path: str) -> str:
        return self._full(path).as_uri()

    def clear(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)


class GcsStorage:
    def __init__(self, bucket: str, project: str | None = None):
        from google.cloud import storage  # lazy import

        self.bucket_name = bucket
        self._client = storage.Client(project=project) if project else storage.Client()
        self._bucket = self._client.bucket(bucket)

    def write_bytes(self, path: str, data: bytes, content_type: str | None = None) -> StoredObject:
        blob = self._bucket.blob(path.strip("/"))
        ctype = content_type or guess_content_type(path)
        blob.upload_from_string(data, content_type=ctype)
        return StoredObject(
            path=path.strip("/"), uri=self.uri(path), size=len(data), content_type=ctype
        )

    def read_bytes(self, path: str) -> bytes:
        return self._bucket.blob(path.strip("/")).download_as_bytes()

    def exists(self, path: str) -> bool:
        return self._bucket.blob(path.strip("/")).exists()

    def signed_url(self, path: str, *, minutes: int = 60) -> str:
        blob = self._bucket.blob(path.strip("/"))
        # V4 signing works with the Cloud Run service account through the IAM
        # signBlob API, so no service account key file is involved (PRD 40).
        return blob.generate_signed_url(version="v4", expiration=timedelta(minutes=minutes))

    def uri(self, path: str) -> str:
        return f"gs://{self.bucket_name}/{path.strip('/')}"


def build_storage(settings) -> Storage:
    if settings.use_gcs:
        return GcsStorage(settings.bucket, settings.project_id or None)
    return LocalStorage(str(Path(settings.local_data_dir) / "media"))


# --- Path helpers (PRD 48) -------------------------------------------------


def universe_prefix(universe_id: str) -> str:
    return f"universes/{universe_id}"


def character_path(universe_id: str, filename: str) -> str:
    return f"{universe_prefix(universe_id)}/character/{filename}"


def wardrobe_path(universe_id: str, filename: str) -> str:
    return f"{universe_prefix(universe_id)}/wardrobe/{filename}"


def location_path(universe_id: str, filename: str) -> str:
    return f"{universe_prefix(universe_id)}/locations/{filename}"


def song_path(universe_id: str, song_id: str, filename: str) -> str:
    return f"{universe_prefix(universe_id)}/songs/{song_id}/{filename}"


def project_path(universe_id: str, project_id: str, filename: str) -> str:
    return f"{universe_prefix(universe_id)}/video-projects/{project_id}/{filename}"


def scene_path(universe_id: str, scene_id: str, filename: str) -> str:
    return f"{universe_prefix(universe_id)}/scenes/{scene_id}/{filename}"


def content_path(universe_id: str, filename: str) -> str:
    return f"{universe_prefix(universe_id)}/content/{filename}"


def reference_path(universe_id: str, filename: str) -> str:
    return f"{universe_prefix(universe_id)}/references/{filename}"


def export_path(universe_id: str, filename: str) -> str:
    return f"{universe_prefix(universe_id)}/exports/{filename}"


def temp_path(universe_id: str, filename: str) -> str:
    return f"{universe_prefix(universe_id)}/temp/{filename}"
