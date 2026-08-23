"""Readable, sortable identifiers.

Prefix + timestamp + random suffix keeps Firestore document ids self
describing when read from the console on a phone.
"""

from __future__ import annotations

import secrets
import unicodedata
from datetime import UTC, datetime

_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"


def new_id(prefix: str) -> str:
    stamp = datetime.now(UTC).strftime("%y%m%d%H%M%S")
    tail = "".join(secrets.choice(_ALPHABET) for _ in range(5))
    return f"{prefix}_{stamp}{tail}"


def slugify(value: str, *, max_length: int = 40) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    out: list[str] = []
    for ch in normalized.lower().strip():
        if ch.isalnum():
            out.append(ch)
        elif ch in " -_/" and out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")[:max_length] or "untitled"
