"""Gemini as the creative team (PRD 11, 43).

One model, several roles. The role is a system instruction, not a separate
service: the MVP does not need seven agents.

Prompts are written in US English because that is what the generators respond
to best (PRD 14); everything the user reads stays in Spanish.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..errors import ProviderError
from .vertex import VertexClient


@dataclass
class TextResult:
    text: str
    data: dict[str, Any] | None
    model: str
    prompt_tokens: int = 0
    output_tokens: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


def _parts_from_references(references: list[tuple[bytes, str]]) -> list[dict[str, Any]]:
    import base64

    return [
        {"inlineData": {"mimeType": mime, "data": base64.b64encode(blob).decode()}}
        for blob, mime in references
    ]


def generate(
    client: VertexClient,
    model: str,
    *,
    system_instruction: str,
    prompt: str,
    schema: dict[str, Any] | None = None,
    references: list[tuple[bytes, str]] | None = None,
    temperature: float = 0.9,
    max_output_tokens: int = 8192,
) -> TextResult:
    parts: list[dict[str, Any]] = [{"text": prompt}]
    parts.extend(_parts_from_references(references or []))

    generation_config: dict[str, Any] = {
        "temperature": temperature,
        "maxOutputTokens": max_output_tokens,
    }
    if schema is not None:
        generation_config["responseMimeType"] = "application/json"
        generation_config["responseSchema"] = schema

    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "generationConfig": generation_config,
    }
    response = client.call(model, "generateContent", payload)

    candidates = response.get("candidates") or []
    if not candidates:
        raise ProviderError(
            "Gemini no devolvio ninguna respuesta.", details={"response": response}
        )
    text = "".join(
        part.get("text", "")
        for part in candidates[0].get("content", {}).get("parts", [])
    ).strip()

    data: dict[str, Any] | None = None
    if schema is not None:
        data = _parse_json(text)

    usage = response.get("usageMetadata", {})
    return TextResult(
        text=text,
        data=data,
        model=model,
        prompt_tokens=int(usage.get("promptTokenCount", 0)),
        output_tokens=int(usage.get("candidatesTokenCount", 0)),
        raw=response,
    )


def _parse_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        cleaned = cleaned.rsplit("```", 1)[0]
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ProviderError(
            "Gemini devolvio algo que no es JSON valido.",
            details={"text": cleaned[:1000]},
        ) from exc
    if not isinstance(parsed, dict):
        return {"value": parsed}
    return parsed
