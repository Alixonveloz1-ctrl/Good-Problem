"""Vertex AI transport.

Calls go over the REST API with Application Default Credentials. On Cloud Run
that is the attached service account: no key file, no credential in an
environment variable (PRD 40).

Every request is recorded before it leaves the process. That is what makes
acceptance test 53.27 checkable — "comprobar en los logs que ninguna llamada a
Veo pidio audio" — without trusting a code review.
"""

from __future__ import annotations

import base64
import json
import logging
import struct
import zlib
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..clock import now_iso
from ..errors import ProviderError

logger = logging.getLogger("aaus.vertex")

SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
_REDACTED = "<bytes>"
_MAX_LOGGED_REQUESTS = 500


@dataclass
class VertexCall:
    model: str
    method: str
    url: str
    payload: dict[str, Any]
    at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {"model": self.model, "method": self.method, "url": self.url,
                "payload": self.payload, "at": self.at}


def redact(value: Any) -> Any:
    """Drop base64 blobs so logs stay readable and small."""
    if isinstance(value, dict):
        return {
            k: (_REDACTED if k in {"bytesBase64Encoded", "data", "image_bytes"} else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str) and len(value) > 512:
        return f"{value[:64]}...<{len(value)} chars>"
    return value


class CallLog:
    """In-process ring buffer of the requests this instance has sent."""

    def __init__(self, maxlen: int = _MAX_LOGGED_REQUESTS):
        self._calls: deque[VertexCall] = deque(maxlen=maxlen)

    def record(self, call: VertexCall) -> None:
        self._calls.append(call)
        logger.info(
            "vertex_request %s",
            json.dumps(
                {"model": call.model, "method": call.method, "payload": redact(call.payload)},
                ensure_ascii=False,
            ),
        )

    def all(self) -> list[VertexCall]:
        return list(self._calls)

    def for_model_prefix(self, prefix: str) -> list[VertexCall]:
        return [c for c in self._calls if c.model.startswith(prefix)]

    def clear(self) -> None:
        self._calls.clear()


# --- Deterministic stand-in media for dry runs -----------------------------


def _png(width: int = 8, height: int = 8, rgb: tuple[int, int, int] = (32, 32, 40)) -> bytes:
    """A real, valid PNG. Small enough to keep in memory, decodable by anything."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _wav(seconds: int = 1, sample_rate: int = 8000) -> bytes:
    """A real, valid silent WAV."""
    frames = b"\x00\x00" * sample_rate * max(seconds, 1)
    header = b"RIFF" + struct.pack("<I", 36 + len(frames)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
    header += b"data" + struct.pack("<I", len(frames))
    return header + frames


def _video_stub(model: str, seconds: int) -> bytes:
    """Not a playable MP4. Dry runs never produce real footage, and pretending
    otherwise would hide the difference in the assembly stage."""
    return json.dumps(
        {"dry_run": True, "model": model, "seconds": seconds, "audio": False}
    ).encode()


class VertexClient:
    def __init__(
        self,
        project: str,
        location: str = "us-central1",
        *,
        dry_run: bool = True,
        timeout: float = 300.0,
        call_log: CallLog | None = None,
    ):
        self.project = project
        self.location = location
        self.dry_run = dry_run or not project
        self.timeout = timeout
        self.calls = call_log or CallLog()
        self._credentials = None

    # -- plumbing ----------------------------------------------------------
    def _host(self) -> str:
        if self.location == "global":
            return "https://aiplatform.googleapis.com"
        return f"https://{self.location}-aiplatform.googleapis.com"

    def model_url(self, model: str, method: str) -> str:
        return (
            f"{self._host()}/v1/projects/{self.project}/locations/{self.location}"
            f"/publishers/google/models/{model}:{method}"
        )

    def _token(self) -> str:
        import google.auth
        from google.auth.transport.requests import Request as AuthRequest

        if self._credentials is None:
            self._credentials, _ = google.auth.default(scopes=SCOPES)
        if not self._credentials.valid:
            self._credentials.refresh(AuthRequest())
        return self._credentials.token

    # -- calls -------------------------------------------------------------
    def call(self, model: str, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = self.model_url(model, method)
        self.calls.record(VertexCall(model=model, method=method, url=url, payload=payload))
        if self.dry_run:
            return self._simulate(model, method, payload)
        try:
            response = httpx.post(
                url,
                json=payload,
                timeout=self.timeout,
                headers={
                    "Authorization": f"Bearer {self._token()}",
                    "Content-Type": "application/json",
                },
            )
        except httpx.HTTPError as exc:  # network level
            raise ProviderError(f"No se pudo contactar con Vertex AI: {exc}") from exc
        if response.status_code >= 400:
            raise ProviderError(
                f"Vertex AI devolvio {response.status_code} para {model}:{method}",
                details={"body": response.text[:2000]},
            )
        return response.json()

    def fetch_operation(self, model: str, operation_name: str) -> dict[str, Any]:
        """Veo returns a long running operation; this polls it."""
        payload = {"operationName": operation_name}
        if self.dry_run:
            self.calls.record(
                VertexCall(
                    model=model,
                    method="fetchPredictOperation",
                    url=self.model_url(model, "fetchPredictOperation"),
                    payload=payload,
                )
            )
            return {"done": True, "name": operation_name, "response": {"videos": []}}
        return self.call(model, "fetchPredictOperation", payload)

    # -- dry run -----------------------------------------------------------
    def _simulate(self, model: str, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        if method == "generateContent":
            wants_image = "IMAGE" in (
                payload.get("generationConfig", {}).get("responseModalities") or []
            )
            if wants_image:
                return {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "inlineData": {
                                            "mimeType": "image/png",
                                            "data": base64.b64encode(_png()).decode(),
                                        }
                                    }
                                ]
                            },
                            "finishReason": "STOP",
                        }
                    ],
                    "usageMetadata": {"promptTokenCount": 800, "candidatesTokenCount": 0},
                }
            return {
                "candidates": [
                    {
                        "content": {"parts": [{"text": _simulated_text(payload)}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"promptTokenCount": 1200, "candidatesTokenCount": 900},
            }
        if method == "predict":
            instance = (payload.get("instances") or [{}])[0]
            seconds = int(
                payload.get("parameters", {}).get("duration_seconds")
                or instance.get("duration_seconds")
                or 30
            )
            return {
                "predictions": [
                    {
                        "bytesBase64Encoded": base64.b64encode(
                            _wav(seconds=min(seconds, 3))
                        ).decode(),
                        "mimeType": "audio/wav",
                    }
                ]
            }
        if method == "predictLongRunning":
            return {"name": f"projects/{self.project}/operations/dry-{model}"}
        return {}


def _simulated_text(payload: dict[str, Any]) -> str:
    """Echo back a JSON object when the caller asked for one, so the parsing
    path is exercised in dry runs too."""
    config = payload.get("generationConfig", {})
    if config.get("responseMimeType") == "application/json":
        schema = config.get("responseSchema") or {}
        return json.dumps(_stub_from_schema(schema), ensure_ascii=False)
    return "DRY RUN: no se llamo a ningun modelo."


def _stub_from_schema(schema: dict[str, Any]) -> Any:
    kind = schema.get("type", "OBJECT").upper()
    if kind == "OBJECT":
        return {
            name: _stub_from_schema(sub) for name, sub in (schema.get("properties") or {}).items()
        }
    if kind == "ARRAY":
        return [_stub_from_schema(schema.get("items", {"type": "STRING"}))]
    if kind in {"INTEGER", "NUMBER"}:
        return 0
    if kind == "BOOLEAN":
        return False
    enum = schema.get("enum")
    return enum[0] if enum else "DRY RUN"


def build_vertex_client(settings, call_log: CallLog | None = None) -> VertexClient:
    return VertexClient(
        project=settings.project_id,
        location=settings.location,
        dry_run=settings.dry_run,
        call_log=call_log,
    )
