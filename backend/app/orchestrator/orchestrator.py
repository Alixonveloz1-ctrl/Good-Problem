"""Generation Orchestrator (PRD 42).

Every generation in the system goes through ``submit`` and then ``run_job``, in
that order, and does the fifteen things the PRD lists:

  1. receive the request with an idempotency key so a dropped connection on a
     phone cannot bill twice;
  2. identify the Universe;
  3. recover the Artist Bible;
  4. recover the Canon;
  5. recover assets and references;
  6. determine the creative role;
  7. resolve the model: what the user chose, otherwise the Artist Bible's
     preference, otherwise the registry default;
  8. build structured instructions;
  9. run the model;
 10. create the Job;
 11. record what the generation cost, as part of provenance (PRD 46);
 12. store the result;
 13. wait for approval;
 14. continue when told to.

The studio keeps no running total and enforces no ceiling: spending is watched
in the Google Cloud console. What each piece cost is still written onto the Job
and onto the asset's provenance, because that is part of knowing where an asset
came from.

Nothing here advances a stage on its own. Results land in READY and stay there
until a human approves them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..clock import now_iso
from ..db.repositories import universe_path
from ..domain.enums import CreativeRole, JobState, ModelKind
from ..domain.guards import assert_music_model, resolve_clip_duration
from ..domain.pricing import (
    CostEstimate,
    estimate_images,
    estimate_song,
    estimate_text,
    estimate_video,
)
from ..domain.registry import ModelSpec
from ..errors import Conflict, DomainError, InvalidGenerationRequest, NotFound
from ..services.context import load_bible

if TYPE_CHECKING:  # pragma: no cover
    from ..container import Studio

logger = logging.getLogger("aaus.orchestrator")

# Rough token budget used for the pre-flight estimate of a Director call. The
# real cost is recorded from usageMetadata once the call returns.
TEXT_ESTIMATE_INPUT_TOKENS = 6_000
TEXT_ESTIMATE_OUTPUT_TOKENS = 2_500


@dataclass
class GenerationRequest:
    universe_id: str
    kind: str
    """One of: text, image, music, video, assembly."""
    target_type: str = ""
    target_id: str = ""
    model: str | None = None
    variant: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None
    role: CreativeRole = CreativeRole.DIRECTOR

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "model": self.model,
            "variant": self.variant,
            "payload": self.payload,
            "role": self.role.value,
        }


@dataclass
class ResolvedModel:
    spec: ModelSpec
    variant: str
    source: str
    """Where the choice came from: 'user', 'bible' or 'registry'."""


LOCAL_KINDS: frozenset[str] = frozenset({"assembly", "creation"})
"""Kinds handled by our own components rather than resolved against the model
registry at submit time: the assembly by our FFmpeg component, and the
creation job, which analyses the new artist's reference links and only then
commissions the character design (the analysis resolves its text model
itself, inside the job, exactly as it always has)."""

_KIND_TO_MODEL_KIND: dict[str, ModelKind] = {
    "text": ModelKind.TEXT,
    "image": ModelKind.IMAGE,
    "music": ModelKind.MUSIC,
    "video": ModelKind.VIDEO,
}


class Orchestrator:
    def __init__(self, studio: Studio):
        self.studio = studio

    # -- 2. universe -------------------------------------------------------
    def require_universe(self, universe_id: str) -> dict[str, Any]:
        universe = self.studio.db.get(universe_path(universe_id))
        if universe is None:
            raise NotFound(f"El universe {universe_id} no existe.")
        return universe

    # -- 8. model resolution ----------------------------------------------
    def resolve_model(self, request: GenerationRequest) -> ResolvedModel:
        registry = self.studio.registry
        if request.kind in LOCAL_KINDS:
            raise InvalidGenerationRequest(f"'{request.kind}' no usa un modelo generativo.")
        model_kind = _KIND_TO_MODEL_KIND.get(request.kind)
        if model_kind is None:
            raise InvalidGenerationRequest(f"Tipo de generacion desconocido: '{request.kind}'.")

        if model_kind is ModelKind.MUSIC:
            # La musica no se negocia: el modelo es el de la puerta que
            # este abierta — Lyria 3.5 si el dueno puso su clave de
            # Gemini, Lyria 3 Pro por Vertex si no — y ningun fallo
            # cambia a otro a escondidas.
            spec = registry.require_active(
                assert_music_model(
                    request.model or "",
                    gemini=bool(self.studio.gemini_api_key()),
                ),
                model_kind,
            )
            return ResolvedModel(spec, spec.variant(request.variant).key, "system")

        if request.model:
            spec = registry.require_active(request.model, model_kind)
            return ResolvedModel(spec, spec.variant(request.variant).key, "user")

        bible = load_bible(self.studio.db, request.universe_id)
        preferred_id, preferred_variant = _bible_preference(bible, model_kind)
        if preferred_id:
            try:
                spec = registry.require_active(preferred_id, model_kind)
                return ResolvedModel(
                    spec, spec.variant(request.variant or preferred_variant).key, "bible"
                )
            except (NotFound, Conflict):
                logger.warning("bible_preference_unavailable %s", preferred_id)

        spec = registry.default_for(model_kind)
        if spec is None:
            raise NotFound(f"No hay modelos de tipo {model_kind} en el registro.")
        return ResolvedModel(spec, spec.variant(request.variant).key, "registry")

    # -- 3. estimate -------------------------------------------------------
    def estimate(self, request: GenerationRequest, resolved: ResolvedModel | None = None):
        resolved = resolved or self.resolve_model(request)
        registry = self.studio.registry
        payload = request.payload
        if request.kind == "image":
            return estimate_images(
                registry, resolved.spec.id, resolved.variant, images=int(payload.get("count", 1))
            )
        if request.kind == "video":
            seconds = resolve_clip_duration(
                payload.get("duration_seconds"),
                resolution=resolved.variant,
                reference_image_count=len(payload.get("reference_paths") or []) + 1,
            )
            return estimate_video(
                registry, resolved.spec.id, resolved.variant, seconds=seconds, clips=1
            )
        if request.kind == "music":
            return estimate_song(registry, attempts=1, model_id=resolved.spec.id)
        return estimate_text(
            registry,
            resolved.spec.id,
            input_tokens=int(payload.get("estimated_input_tokens", TEXT_ESTIMATE_INPUT_TOKENS)),
            output_tokens=int(payload.get("estimated_output_tokens", TEXT_ESTIMATE_OUTPUT_TOKENS)),
        )

    # -- 1, 11: submit -----------------------------------------------------
    def submit(self, request: GenerationRequest) -> dict[str, Any]:
        self.require_universe(request.universe_id)

        if request.idempotency_key:
            existing = self.studio.idempotency.lookup(
                request.universe_id, request.idempotency_key
            )
            if existing:
                logger.info("idempotent_hit %s", existing)
                return self.studio.jobs.get(request.universe_id, existing)

        resolved = self.resolve_model(request)
        estimate = self.estimate(request, resolved)

        job = self.studio.jobs.create(
            request.universe_id,
            kind=request.kind,
            model=resolved.spec.id,
            variant=resolved.variant,
            target_type=request.target_type,
            target_id=request.target_id,
            request={**request.to_dict(), "model_source": resolved.source},
            estimated_cost_usd=estimate.amount_usd,
            idempotency_key=request.idempotency_key,
        )
        # La marca de creacion: emparejada con la de entrada del endpoint,
        # deja en los registros la prueba de que este envio concreto si
        # creo su trabajo, y de cual. Un envio sin esta linea murio antes.
        logger.info(
            "job_created %s kind=%s universe=%s target=%s/%s",
            job["id"],
            request.kind,
            request.universe_id,
            request.target_type,
            request.target_id,
        )
        if request.idempotency_key:
            self.studio.idempotency.remember(
                request.universe_id, request.idempotency_key, job["id"], request.to_dict()
            )
        self.studio.jobs.enqueue(request.universe_id, job["id"])
        return job

    def submit_local(
        self, request: GenerationRequest, *, model: str = "ffmpeg"
    ) -> dict[str, Any]:
        """Work our own components do: assembling a video, cutting a Short out
        of an approved master, laying the Chirp voice over silent footage — or
        finishing a creation whose reference links still need analysing. No
        model resolution and no generation cost at submit time, but still a
        Job the phone can watch (PRD 29, 32, 33). The creation job passes the
        text model its analyses will use, so the job sheet names the model
        that really does the work; the FFmpeg kinds keep the default."""
        if request.kind not in LOCAL_KINDS:
            raise InvalidGenerationRequest(f"'{request.kind}' no es un trabajo local.")
        self.require_universe(request.universe_id)
        if request.idempotency_key:
            existing = self.studio.idempotency.lookup(
                request.universe_id, request.idempotency_key
            )
            if existing:
                return self.studio.jobs.get(request.universe_id, existing)
        job = self.studio.jobs.create(
            request.universe_id,
            kind=request.kind,
            model=model,
            variant="cloud-run-job",
            target_type=request.target_type,
            target_id=request.target_id,
            request=request.to_dict(),
            estimated_cost_usd=0.0,
            idempotency_key=request.idempotency_key,
        )
        if request.idempotency_key:
            self.studio.idempotency.remember(
                request.universe_id, request.idempotency_key, job["id"], request.to_dict()
            )
        self.studio.jobs.enqueue(request.universe_id, job["id"])
        return job

    # -- 10, 12, 13: run ---------------------------------------------------
    def run_job(self, universe_id: str, job_id: str) -> dict[str, Any]:
        from .handlers import HANDLERS

        job = self.studio.jobs.get(universe_id, job_id)
        if job["state"] == JobState.CANCELLED.value:
            return job
        job = self.studio.jobs.mark_processing(universe_id, job_id)
        handler = HANDLERS.get(job["kind"])
        if handler is None:
            return self.studio.jobs.mark_failed(
                universe_id, job_id, f"No hay handler para '{job['kind']}'."
            )
        try:
            outcome = handler(self.studio, universe_id, job)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user as job.error
            logger.exception("handler_failed %s", job_id)
            return self.studio.jobs.mark_failed(
                universe_id, job_id, _error_para_el_trabajo(exc)
            )

        cost = outcome.cost
        return self.studio.jobs.mark_ready(
            universe_id,
            job_id,
            {**outcome.result, "completed_at": now_iso()},
            cost_usd=cost.amount_usd if cost else 0.0,
        )


@dataclass
class Outcome:
    """What a handler gives back: the payload to store on the job and the real
    cost to bill."""

    result: dict[str, Any]
    cost: CostEstimate | None = None


def _error_para_el_trabajo(exc: Exception) -> str:
    """The error stored on a failed job, with the provider's detail attached.

    A failed job is all the owner sees when a generation goes wrong. Providers
    put what Google actually answered in ``DomainError.details`` (a response
    excerpt, an HTTP body), and this used to throw that away and store only
    the headline — which is how a blocked Lyria request reached the screen as
    an empty "sin respuesta" with the real reason nowhere in the system. The
    detail now travels inside the stored error; errors that carry no detail
    are stored exactly as before.
    """
    mensaje = str(exc)
    if not isinstance(exc, DomainError) or not exc.details:
        return mensaje
    extracto = exc.details.get("response") or exc.details.get("body")
    if extracto:
        return f"{mensaje} Detalle de la respuesta de Google: {extracto}"
    return f"{mensaje} Detalles: {exc.details}"


def _bible_preference(bible, model_kind: ModelKind) -> tuple[str | None, str | None]:
    prefs = bible.preferences
    if model_kind is ModelKind.IMAGE:
        return prefs.preferred_image_model, prefs.preferred_image_variant
    if model_kind is ModelKind.VIDEO:
        return prefs.preferred_video_model, prefs.preferred_video_variant
    return None, None

