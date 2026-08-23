"""Model registry (PRD 41).

Models are not constants in the code. They live in a Firestore document at
``config/models`` with name, price, capabilities and status. The app reads it to
fill the selector and to estimate costs. When Google turns a model off or adds
one, that document is edited and nothing is redeployed.

The seed in ``backend/seed/model_registry.json`` is what a fresh project starts
with. Loading always runs the registry through ``guards`` so an edit cannot put
a 30 second Lyria clip model back into the selector.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import ModelNotAllowed, NotFound
from ..settings import BACKEND_ROOT
from .enums import ModelKind
from .guards import BANNED_MODEL_IDS, MUSIC_MODEL_ID, assert_not_banned

SEED_PATH = BACKEND_ROOT / "seed" / "model_registry.json"


@dataclass(frozen=True)
class Variant:
    key: str
    label: str
    unit: str
    price: float = 0.0
    price_input: float = 0.0
    price_output: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        data = {"key": self.key, "label": self.label, "unit": self.unit}
        if self.unit == "1m_tokens":
            data["price_input"] = self.price_input
            data["price_output"] = self.price_output
        else:
            data["price"] = self.price
        return data


@dataclass(frozen=True)
class ModelSpec:
    id: str
    kind: ModelKind
    label: str
    status: str
    variants: tuple[Variant, ...]
    capabilities: dict[str, Any] = field(default_factory=dict)
    default_variant: str | None = None
    role_hint: str = ""

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    def variant(self, key: str | None) -> Variant:
        wanted = key or self.default_variant or (self.variants[0].key if self.variants else None)
        for variant in self.variants:
            if variant.key == wanted:
                return variant
        raise NotFound(f"El modelo {self.id} no tiene la variante '{key}'.")

    def cap(self, name: str, default: Any = None) -> Any:
        return self.capabilities.get(name, default)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": str(self.kind),
            "label": self.label,
            "status": self.status,
            "role_hint": self.role_hint,
            "default_variant": self.default_variant,
            "variants": [v.to_dict() for v in self.variants],
            "capabilities": self.capabilities,
        }


class ModelRegistry:
    def __init__(self, document: dict[str, Any]):
        self.raw = document
        self.currency = document.get("currency", "USD")
        self.excluded: list[dict[str, Any]] = list(document.get("excluded", []))
        self._models: dict[str, ModelSpec] = {}
        for entry in document.get("models", []):
            spec = _parse_model(entry)
            if spec.id in BANNED_MODEL_IDS:
                # A registry edit cannot resurrect a banned model.
                self.excluded.append(
                    {
                        "id": spec.id,
                        "kind": str(spec.kind),
                        "reason": "Bloqueado en el codigo (app/domain/guards.py).",
                    }
                )
                continue
            self._models[spec.id] = spec

    # -- lookup ------------------------------------------------------------
    def all(self, kind: ModelKind | str | None = None, *, active_only: bool = True):
        specs = list(self._models.values())
        if kind is not None:
            specs = [s for s in specs if s.kind == str(kind)]
        if active_only:
            specs = [s for s in specs if s.is_active]
        return sorted(specs, key=lambda s: (str(s.kind), s.id))

    def get(self, model_id: str) -> ModelSpec:
        assert_not_banned(model_id)
        spec = self._models.get(model_id)
        if spec is None:
            raise NotFound(f"El modelo '{model_id}' no esta en el registro.")
        return spec

    def require_active(self, model_id: str, kind: ModelKind | str | None = None) -> ModelSpec:
        spec = self.get(model_id)
        if not spec.is_active:
            raise ModelNotAllowed(
                f"El modelo '{model_id}' esta marcado como '{spec.status}' en el registro."
            )
        if kind is not None and spec.kind != str(kind):
            raise ModelNotAllowed(
                f"El modelo '{model_id}' es de tipo {spec.kind}, se esperaba {kind}."
            )
        return spec

    def default_for(self, kind: ModelKind | str) -> ModelSpec | None:
        options = self.all(kind)
        return options[0] if options else None

    def music_model(self) -> ModelSpec:
        """There is exactly one, by design."""
        return self.require_active(MUSIC_MODEL_ID, ModelKind.MUSIC)

    def selector_payload(self) -> dict[str, Any]:
        """What the bottom sheet on the phone renders (PRD 39)."""
        return {
            "currency": self.currency,
            "models": [spec.to_dict() for spec in self.all(active_only=True)],
            "excluded": self.excluded,
        }


def _parse_model(entry: dict[str, Any]) -> ModelSpec:
    variants = tuple(
        Variant(
            key=v["key"],
            label=v.get("label", v["key"]),
            unit=v.get("unit", "unit"),
            price=float(v.get("price", 0.0)),
            price_input=float(v.get("price_input", 0.0)),
            price_output=float(v.get("price_output", 0.0)),
        )
        for v in entry.get("variants", [])
    )
    return ModelSpec(
        id=entry["id"],
        kind=ModelKind(entry["kind"]),
        label=entry.get("label", entry["id"]),
        status=entry.get("status", "active"),
        variants=variants,
        capabilities=dict(entry.get("capabilities", {})),
        default_variant=entry.get("default_variant"),
        role_hint=entry.get("role_hint", ""),
    )


def load_seed(path: Path = SEED_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
