"""Chirp 3 Instant Custom Voice, Cloud Text-to-Speech (PRD 4, 34, 35).

The sung voice cannot be pinned; the spoken voice can. Chirp clones a voice from
a ten second sample and returns a reusable key, so interviews, BTS, the artist
diary and announcements all sound like the same person every time.

The key is an API identifier, not an access credential, and it is the only thing
this project keeps in Secret Manager (PRD 40).

Both steps need paperwork before they work: access has to be requested, and a
consent recording has to be supplied.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..errors import ProviderError

TTS_HOST = "https://texttospeech.googleapis.com"
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

CONSENT_SCRIPT = (
    "I am the owner of this voice and I consent to Google using this voice to create a "
    "synthetic voice model."
)


@dataclass
class SpeechResult:
    data: bytes
    mime_type: str
    model: str
    characters: int
    parameters: dict[str, Any] = field(default_factory=dict)


class ChirpClient:
    def __init__(self, project: str, *, dry_run: bool = True, timeout: float = 120.0):
        self.project = project
        self.dry_run = dry_run or not project
        self.timeout = timeout
        self._credentials = None

    def _token(self) -> str:
        import google.auth
        from google.auth.transport.requests import Request as AuthRequest

        if self._credentials is None:
            self._credentials, _ = google.auth.default(scopes=SCOPES)
        if not self._credentials.valid:
            self._credentials.refresh(AuthRequest())
        return self._credentials.token

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = httpx.post(
                f"{TTS_HOST}{path}",
                json=payload,
                timeout=self.timeout,
                headers={
                    "Authorization": f"Bearer {self._token()}",
                    "Content-Type": "application/json",
                    "x-goog-user-project": self.project,
                },
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"No se pudo contactar con Cloud TTS: {exc}") from exc
        if response.status_code >= 400:
            raise ProviderError(
                f"Cloud TTS devolvio {response.status_code}",
                details={"body": response.text[:1500]},
            )
        return response.json()

    def create_voice_clone_key(
        self,
        *,
        sample_wav: bytes,
        consent_wav: bytes,
        language_code: str = "es-ES",
    ) -> str:
        """Returns the reusable voice cloning key. Store it in Secret Manager."""
        if self.dry_run:
            return "DRY_RUN_VOICE_CLONING_KEY"
        payload = {
            "reference_audio": {
                "audio_config": {"audio_encoding": "LINEAR16", "sample_rate_hertz": 24000},
                "content": base64.b64encode(sample_wav).decode(),
            },
            "voice_talent_consent": {
                "audio_config": {"audio_encoding": "LINEAR16", "sample_rate_hertz": 24000},
                "content": base64.b64encode(consent_wav).decode(),
            },
            "consent_script": CONSENT_SCRIPT,
            "language_code": language_code,
        }
        response = self._post("/v1beta1/voices:generateVoiceCloningKey", payload)
        key = response.get("voiceCloningKey")
        if not key:
            raise ProviderError("Cloud TTS no devolvio una clave de voz clonada.")
        return key

    def synthesize(
        self,
        *,
        text: str,
        voice_cloning_key: str,
        language_code: str = "es-ES",
        encoding: str = "LINEAR16",
        speaking_rate: float = 1.0,
    ) -> SpeechResult:
        parameters = {
            "language_code": language_code,
            "encoding": encoding,
            "speaking_rate": speaking_rate,
        }
        if self.dry_run:
            from .vertex import _wav

            return SpeechResult(
                data=_wav(seconds=max(1, len(text) // 15)),
                mime_type="audio/wav",
                model="chirp-3-instant-custom-voice",
                characters=len(text),
                parameters=parameters,
            )
        payload = {
            "input": {"text": text},
            "voice": {
                "language_code": language_code,
                "voice_clone": {"voice_cloning_key": voice_cloning_key},
            },
            "audio_config": {"audio_encoding": encoding, "speaking_rate": speaking_rate},
        }
        response = self._post("/v1beta1/text:synthesize", payload)
        encoded = response.get("audioContent")
        if not encoded:
            raise ProviderError("Cloud TTS no devolvio audio.")
        return SpeechResult(
            data=base64.b64decode(encoded),
            mime_type="audio/wav" if encoding == "LINEAR16" else "audio/mpeg",
            model="chirp-3-instant-custom-voice",
            characters=len(text),
            parameters=parameters,
        )


def build_chirp_client(settings) -> ChirpClient:
    return ChirpClient(settings.project_id, dry_run=settings.dry_run)
