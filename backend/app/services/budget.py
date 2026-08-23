"""Cost control (PRD 44).

Two things separate this from a dashboard:

* the cutoff is real. When the budget is reached new jobs are rejected, not
  merely flagged;
* the welcome credit expires 90 days after sign up whether or not it is spent,
  so the Home screen shows the days left, not only the dollars left.

Every generation writes a row to the spend ledger of its universe, which is what
makes "comparar el costo real con el estimado" (acceptance test 35) answerable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from ..clock import parse_date, today
from ..db.client import Database
from ..db.repositories import CONFIG_BUDGET, SPEND, Repository, universe_path
from ..domain.pricing import CostEstimate
from ..errors import BudgetExceeded
from ..ids import new_id
from ..settings import Settings


@dataclass
class BudgetStatus:
    total_usd: float
    spent_usd: float
    remaining_usd: float
    hard_stop: bool
    credit_total_usd: float
    credit_started_on: str | None
    credit_expires_on: str | None
    credit_days_left: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_usd": round(self.total_usd, 2),
            "spent_usd": round(self.spent_usd, 2),
            "remaining_usd": round(self.remaining_usd, 2),
            "hard_stop": self.hard_stop,
            "credit_total_usd": round(self.credit_total_usd, 2),
            "credit_started_on": self.credit_started_on,
            "credit_expires_on": self.credit_expires_on,
            "credit_days_left": self.credit_days_left,
        }


class BudgetService:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings

    # -- configuration -----------------------------------------------------
    def config(self) -> dict[str, Any]:
        doc = self.db.get(CONFIG_BUDGET)
        if doc is None:
            doc = {
                "id": "budget",
                "total_usd": self.settings.credit_total_usd,
                "spent_usd": 0.0,
                "hard_stop_enabled": True,
                "credit_started_on": self.settings.credit_started_on or None,
                "credit_total_usd": self.settings.credit_total_usd,
                "credit_days": self.settings.credit_days,
            }
            self.db.set(CONFIG_BUDGET, doc)
        return doc

    def update_config(self, patch: dict[str, Any]) -> dict[str, Any]:
        self.config()
        allowed = {
            k: v
            for k, v in patch.items()
            if k in {"total_usd", "hard_stop_enabled", "credit_started_on", "credit_total_usd",
                     "credit_days"}
        }
        return self.db.update(CONFIG_BUDGET, allowed)

    # -- status ------------------------------------------------------------
    def status(self) -> BudgetStatus:
        doc = self.config()
        total = float(doc.get("total_usd", 0.0))
        spent = float(doc.get("spent_usd", 0.0))
        started = parse_date(doc.get("credit_started_on") or "")
        days = int(doc.get("credit_days", self.settings.credit_days))
        expires = started + timedelta(days=days) if started else None
        days_left = (expires - today()).days if expires else None
        return BudgetStatus(
            total_usd=total,
            spent_usd=spent,
            remaining_usd=max(total - spent, 0.0),
            hard_stop=bool(doc.get("hard_stop_enabled", True)),
            credit_total_usd=float(doc.get("credit_total_usd", total)),
            credit_started_on=doc.get("credit_started_on"),
            credit_expires_on=expires.isoformat() if expires else None,
            credit_days_left=days_left,
        )

    # -- enforcement -------------------------------------------------------
    def assert_can_spend(
        self, amount_usd: float, *, universe_id: str | None = None, label: str = "esta generacion"
    ) -> None:
        """Hard cutoff. Called before a job is created, never after."""
        status = self.status()
        if status.credit_days_left is not None and status.credit_days_left < 0:
            raise BudgetExceeded(
                "El credito caduco. Pasa la cuenta a modo de pago para seguir generando.",
                details={"credit_expires_on": status.credit_expires_on},
            )
        if status.hard_stop and amount_usd > status.remaining_usd:
            raise BudgetExceeded(
                f"El presupuesto no cubre {label}: faltan "
                f"${amount_usd - status.remaining_usd:,.2f}.",
                details={
                    "needed_usd": round(amount_usd, 2),
                    "remaining_usd": round(status.remaining_usd, 2),
                },
            )
        if universe_id:
            universe = self.db.get(universe_path(universe_id)) or {}
            ceiling = universe.get("budget_usd")
            if ceiling is not None:
                spent = float(universe.get("spend_usd", 0.0))
                if spent + amount_usd > float(ceiling):
                    raise BudgetExceeded(
                        f"El presupuesto de este artista no cubre {label}.",
                        details={
                            "needed_usd": round(amount_usd, 2),
                            "remaining_usd": round(float(ceiling) - spent, 2),
                        },
                    )

    # -- ledger ------------------------------------------------------------
    def record(
        self,
        universe_id: str,
        estimate: CostEstimate,
        *,
        kind: str,
        job_id: str | None = None,
        target_type: str = "",
        target_id: str = "",
        note: str = "",
    ) -> dict[str, Any]:
        entry_id = new_id("spend")
        repo = Repository(self.db, universe_id, SPEND)
        entry = repo.create(
            entry_id,
            {
                "job_id": job_id,
                "kind": kind,
                "model": estimate.model,
                "variant": estimate.variant,
                "quantity": estimate.quantity,
                "unit": estimate.unit,
                "amount_usd": round(estimate.amount_usd, 4),
                "target_type": target_type,
                "target_id": target_id,
                "note": note or estimate.detail,
            },
        )
        doc = self.config()
        self.db.update(
            CONFIG_BUDGET,
            {"spent_usd": round(float(doc.get("spent_usd", 0.0)) + estimate.amount_usd, 4)},
        )
        universe = self.db.get(universe_path(universe_id))
        if universe is not None:
            self.db.update(
                universe_path(universe_id),
                {
                    "spend_usd": round(
                        float(universe.get("spend_usd", 0.0)) + estimate.amount_usd, 4
                    )
                },
            )
        return entry

    def universe_spend(self, universe_id: str) -> float:
        universe = self.db.get(universe_path(universe_id)) or {}
        return float(universe.get("spend_usd", 0.0))

    def ledger(self, universe_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        return Repository(self.db, universe_id, SPEND).list(limit=limit)
