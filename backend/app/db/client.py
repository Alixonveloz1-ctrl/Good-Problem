"""Document store abstraction.

Two implementations behind one small interface:

* ``FirestoreDatabase`` for Cloud Run, using Application Default Credentials.
* ``MemoryDatabase`` for tests and for running the app on a laptop or in a
  container without any Google Cloud project attached.

Paths are Firestore paths with an even number of segments, e.g.
``universes/uni_1/songs/song_2``. Collection paths have an odd number.
"""

from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from typing import Any, Protocol

Document = dict[str, Any]


class Database(Protocol):
    def get(self, path: str) -> Document | None: ...

    def set(self, path: str, data: Document) -> Document: ...

    def update(self, path: str, patch: Document) -> Document: ...

    def delete(self, path: str) -> None: ...

    def list(
        self,
        collection: str,
        *,
        where: dict[str, Any] | None = None,
        order_by: str | None = None,
        descending: bool = True,
        limit: int | None = None,
    ) -> list[Document]: ...


def _split(path: str) -> list[str]:
    parts = [p for p in path.strip("/").split("/") if p]
    if not parts:
        raise ValueError("empty path")
    return parts


def _sort_key(doc: Document, field: str) -> tuple[int, Any]:
    value = doc.get(field)
    if value is None:
        return (0, "")
    return (1, value)


class MemoryDatabase:
    """Dict backed store. Optionally persists to disk so a local dev session
    survives a restart of the server."""

    def __init__(self, persist_dir: str | None = None):
        self._lock = threading.RLock()
        self._docs: dict[str, Document] = {}
        self._file = Path(persist_dir) / "firestore.json" if persist_dir else None
        if self._file and self._file.exists():
            self._docs = json.loads(self._file.read_text())

    # -- internals ---------------------------------------------------------
    def _flush(self) -> None:
        if not self._file:
            return
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._file.write_text(json.dumps(self._docs, indent=2, ensure_ascii=False, default=str))

    # -- Database ----------------------------------------------------------
    def get(self, path: str) -> Document | None:
        _split(path)
        with self._lock:
            doc = self._docs.get(path)
            return copy.deepcopy(doc) if doc is not None else None

    def set(self, path: str, data: Document) -> Document:
        parts = _split(path)
        with self._lock:
            payload = copy.deepcopy(data)
            payload["id"] = payload.get("id") or parts[-1]
            self._docs[path] = payload
            self._flush()
            return copy.deepcopy(payload)

    def update(self, path: str, patch: Document) -> Document:
        with self._lock:
            current = self._docs.get(path)
            if current is None:
                raise KeyError(path)
            merged = {**current, **copy.deepcopy(patch)}
            self._docs[path] = merged
            self._flush()
            return copy.deepcopy(merged)

    def delete(self, path: str) -> None:
        with self._lock:
            self._docs.pop(path, None)
            prefix = path.rstrip("/") + "/"
            for key in [k for k in self._docs if k.startswith(prefix)]:
                self._docs.pop(key, None)
            self._flush()

    def list(
        self,
        collection: str,
        *,
        where: dict[str, Any] | None = None,
        order_by: str | None = None,
        descending: bool = True,
        limit: int | None = None,
    ) -> list[Document]:
        depth = len(_split(collection)) + 1
        prefix = collection.strip("/") + "/"
        with self._lock:
            rows = [
                copy.deepcopy(doc)
                for path, doc in self._docs.items()
                if path.startswith(prefix) and len(_split(path)) == depth
            ]
        for field, value in (where or {}).items():
            rows = [r for r in rows if r.get(field) == value]
        if order_by:
            rows.sort(key=lambda d: _sort_key(d, order_by), reverse=descending)
        return rows[:limit] if limit else rows


class FirestoreDatabase:
    """Thin wrapper over google-cloud-firestore."""

    def __init__(self, project: str, database: str = "(default)"):
        from google.cloud import firestore  # imported lazily: heavy dependency

        self._client = firestore.Client(project=project, database=database)

    def _ref(self, path: str):
        return self._client.document("/".join(_split(path)))

    def get(self, path: str) -> Document | None:
        snap = self._ref(path).get()
        return snap.to_dict() if snap.exists else None

    def set(self, path: str, data: Document) -> Document:
        parts = _split(path)
        payload = {**data, "id": data.get("id") or parts[-1]}
        self._ref(path).set(payload)
        return payload

    def update(self, path: str, patch: Document) -> Document:
        ref = self._ref(path)
        snap = ref.get()
        if not snap.exists:
            raise KeyError(path)
        ref.update(patch)
        return {**snap.to_dict(), **patch}

    def delete(self, path: str) -> None:
        self._ref(path).delete()

    def list(
        self,
        collection: str,
        *,
        where: dict[str, Any] | None = None,
        order_by: str | None = None,
        descending: bool = True,
        limit: int | None = None,
    ) -> list[Document]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        query = self._client.collection("/".join(_split(collection)))
        for field, value in (where or {}).items():
            query = query.where(filter=FieldFilter(field, "==", value))
        if order_by:
            direction = "DESCENDING" if descending else "ASCENDING"
            query = query.order_by(order_by, direction=direction)
        if limit:
            query = query.limit(limit)
        return [snap.to_dict() for snap in query.stream()]


def build_database(settings) -> Database:
    if settings.use_firestore:
        return FirestoreDatabase(settings.project_id, settings.firestore_database)
    return MemoryDatabase(settings.local_data_dir)
