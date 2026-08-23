"""Collection paths and generic CRUD scoped to a Universe.

Every entity carries ``universe_id`` (PRD 8). Nothing in this module can read
across universes without being handed the id explicitly.
"""

from __future__ import annotations

from typing import Any

from ..clock import now_iso
from ..errors import NotFound
from .client import Database, Document

CONFIG_MODELS = "config/models"
CONFIG_BUDGET = "config/budget"
UNIVERSES = "universes"

# Sub collections of a universe (PRD 47).
CHARACTERS = "characters"
WARDROBE = "wardrobe"
LOCATIONS = "locations"
SONGS = "songs"
VIDEO_PROJECTS = "video_projects"
SCENES = "scenes"
IMAGES = "images"
VIDEOS = "videos"
CONTENT = "content"
CANON = "canon"
JOBS = "jobs"
SPEND = "spend"
EXPORTS = "exports"
IDEMPOTENCY = "idempotency"


def universe_path(universe_id: str) -> str:
    return f"{UNIVERSES}/{universe_id}"


def collection_path(universe_id: str, collection: str) -> str:
    return f"{UNIVERSES}/{universe_id}/{collection}"


def doc_path(universe_id: str, collection: str, doc_id: str) -> str:
    return f"{UNIVERSES}/{universe_id}/{collection}/{doc_id}"


class Repository:
    """CRUD for one sub collection of one universe."""

    def __init__(self, db: Database, universe_id: str, collection: str):
        self.db = db
        self.universe_id = universe_id
        self.collection = collection

    def path(self, doc_id: str) -> str:
        return doc_path(self.universe_id, self.collection, doc_id)

    def create(self, doc_id: str, data: Document) -> Document:
        payload = {
            **data,
            "id": doc_id,
            "universe_id": self.universe_id,
            "created_at": data.get("created_at") or now_iso(),
            "updated_at": now_iso(),
        }
        return self.db.set(self.path(doc_id), payload)

    def get(self, doc_id: str) -> Document | None:
        return self.db.get(self.path(doc_id))

    def require(self, doc_id: str) -> Document:
        doc = self.get(doc_id)
        if doc is None:
            raise NotFound(f"{self.collection}/{doc_id} no existe en {self.universe_id}")
        return doc

    def update(self, doc_id: str, patch: Document) -> Document:
        self.require(doc_id)
        return self.db.update(self.path(doc_id), {**patch, "updated_at": now_iso()})

    def replace(self, doc_id: str, data: Document) -> Document:
        return self.db.set(self.path(doc_id), {**data, "updated_at": now_iso()})

    def delete(self, doc_id: str) -> None:
        self.db.delete(self.path(doc_id))

    def list(
        self,
        *,
        where: dict[str, Any] | None = None,
        order_by: str | None = "created_at",
        descending: bool = True,
        limit: int | None = None,
    ) -> list[Document]:
        return self.db.list(
            collection_path(self.universe_id, self.collection),
            where=where,
            order_by=order_by,
            descending=descending,
            limit=limit,
        )
