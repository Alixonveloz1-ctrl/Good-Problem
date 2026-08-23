"""Time helpers.

Isolated so tests can freeze time without patching datetime globally.
"""

from __future__ import annotations

from datetime import UTC, datetime


def now() -> datetime:
    return datetime.now(UTC)


def now_iso() -> str:
    return now().isoformat(timespec="seconds")
