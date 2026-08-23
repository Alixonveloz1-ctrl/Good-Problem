"""Time helpers.

Isolated so tests can freeze time without patching datetime globally.
"""

from __future__ import annotations

from datetime import UTC, date, datetime


def now() -> datetime:
    return datetime.now(UTC)


def now_iso() -> str:
    return now().isoformat(timespec="seconds")


def today() -> date:
    return now().date()


def parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None
