"""Duplicate protection (PRD 42.1, 44).

A dropped response on a phone must not bill a second video. The client sends an
idempotency key with every generation request; the first request that arrives
with a given key wins and every later one returns the same job.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..clock import now_iso
from ..db.client import Database
from ..db.repositories import IDEMPOTENCY, doc_path


def fingerprint(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


def key_id(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()[:32]


CREATION_KEYS = "creation_keys"
"""El indice de las creaciones de universo, por su clave de idempotencia.

Las claves de los trabajos viven dentro de su universo, pero la creacion
todavia no tiene universo cuando la clave llega: sin un indice propio no
habria manera de saber, ante un reintento, QUE universo creo ya aquella
clave. Vive fuera de ``universes/`` para no aparecer como un artista mas
en ninguna lista."""


class IdempotencyStore:
    def __init__(self, db: Database):
        self.db = db

    def lookup(self, universe_id: str, raw_key: str) -> str | None:
        doc = self.db.get(doc_path(universe_id, IDEMPOTENCY, key_id(raw_key)))
        return doc.get("job_id") if doc else None

    def remember(self, universe_id: str, raw_key: str, job_id: str, request: dict) -> None:
        self.db.set(
            doc_path(universe_id, IDEMPOTENCY, key_id(raw_key)),
            {
                "id": key_id(raw_key),
                "universe_id": universe_id,
                "job_id": job_id,
                "fingerprint": fingerprint(request),
                "created_at": now_iso(),
            },
        )

    # -- creaciones de universo --------------------------------------------
    def lookup_creation(self, raw_key: str) -> str | None:
        """El universo que ESTA clave ya creo, si creo alguno."""
        doc = self.db.get(f"{CREATION_KEYS}/{key_id(raw_key)}")
        return doc.get("universe_id") if doc else None

    def remember_creation(self, raw_key: str, universe_id: str, request: dict) -> None:
        self.db.set(
            f"{CREATION_KEYS}/{key_id(raw_key)}",
            {
                "id": key_id(raw_key),
                "universe_id": universe_id,
                "fingerprint": fingerprint(request),
                "created_at": now_iso(),
            },
        )
