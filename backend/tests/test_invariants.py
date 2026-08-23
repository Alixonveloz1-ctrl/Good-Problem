"""The rules PRD v2.1 exists to enforce. If one of these fails, the system is
spending money the wrong way or shipping the wrong artefact.
"""

from __future__ import annotations

import pytest

from app.domain import guards
from app.domain.enums import JobState, ModelKind
from app.domain.pricing import estimate_images, estimate_song, estimate_text, estimate_video
from app.domain.registry import ModelRegistry, load_seed
from app.errors import BudgetExceeded, InvalidGenerationRequest, ModelNotAllowed
from app.orchestrator.orchestrator import GenerationRequest
from app.providers import lyria, veo
from app.providers.vertex import VertexClient


@pytest.fixture
def registry() -> ModelRegistry:
    return ModelRegistry(load_seed())


# --- 1. Music is Lyria 3 Pro, never a 30 second clip model (PRD 14) --------


@pytest.mark.parametrize("banned", ["lyria-3", "lyria-2", "lyria-002"])
def test_clip_music_models_are_refused_everywhere(banned, registry, studio):
    with pytest.raises(ModelNotAllowed):
        guards.assert_music_model(banned)
    with pytest.raises(ModelNotAllowed):
        lyria.generate_song(
            VertexClient("p", dry_run=True), model=banned, prompt="x", duration_seconds=30
        )
    with pytest.raises(ModelNotAllowed):
        studio.orchestrator.resolve_model(
            GenerationRequest(universe_id="u", kind="music", model=banned)
        )


def test_banned_models_cannot_be_re_enabled_from_the_registry():
    document = load_seed()
    document["models"].append(
        {
            "id": "lyria-3",
            "kind": "music",
            "label": "Lyria 3",
            "status": "active",
            "variants": [{"key": "clip", "unit": "song", "price": 0.02}],
        }
    )
    registry = ModelRegistry(document)
    assert "lyria-3" not in [m.id for m in registry.all(ModelKind.MUSIC, active_only=False)]
    assert any(entry["id"] == "lyria-3" for entry in registry.excluded)


def test_music_selector_offers_exactly_one_model(registry):
    assert [m.id for m in registry.all(ModelKind.MUSIC)] == ["lyria-3-pro"]


def test_music_falls_back_to_nothing(studio):
    """A failed music job retries with the same model; there is no weaker one to
    fall back to (PRD 37)."""
    resolved = studio.orchestrator.resolve_model(
        GenerationRequest(universe_id="u", kind="music", model=None)
    )
    assert resolved.spec.id == "lyria-3-pro"
    assert resolved.source == "system"


# --- 2. Veo audio is always off (PRD 5, 26) -------------------------------


def test_every_veo_request_disables_audio(registry):
    client = VertexClient("p", dry_run=True)
    for model_id in ("veo-3.1", "veo-3.1-fast", "veo-3.1-lite"):
        veo.start_generation(
            client,
            registry.get(model_id),
            prompt="scene",
            variant="1080p",
            source_image=veo.SourceImage(data=b"x"),
        )
    for call in client.calls.for_model_prefix("veo"):
        assert call.payload["parameters"]["generateAudio"] is False


def test_asking_for_audio_is_an_error():
    with pytest.raises(InvalidGenerationRequest):
        guards.enforce_video_audio_disabled({"generateAudio": True})
    with pytest.raises(InvalidGenerationRequest):
        guards.enforce_video_audio_disabled({"generate_audio": True})


# --- 3. Clip durations (PRD 23, 26) ---------------------------------------


@pytest.mark.parametrize("resolution", ["1080p", "4K"])
def test_eight_seconds_is_mandatory_at_high_resolution(resolution):
    assert guards.resolve_clip_duration(8, resolution=resolution) == 8
    for bad in (4, 6):
        with pytest.raises(InvalidGenerationRequest):
            guards.resolve_clip_duration(bad, resolution=resolution)


def test_eight_seconds_is_mandatory_with_reference_images():
    with pytest.raises(InvalidGenerationRequest):
        guards.resolve_clip_duration(6, resolution="720p", reference_image_count=1)
    assert guards.resolve_clip_duration(6, resolution="720p") == 6


def test_unsupported_durations_are_refused():
    with pytest.raises(InvalidGenerationRequest):
        guards.resolve_clip_duration(5, resolution="720p")


def test_lite_cannot_extend_a_scene(registry):
    with pytest.raises(InvalidGenerationRequest):
        veo.start_extension(
            VertexClient("p", dry_run=True),
            registry.get("veo-3.1-lite"),
            prompt="more",
            variant="1080p",
            video_uri="gs://bucket/clip.mp4",
        )


def test_at_most_three_reference_images(registry):
    with pytest.raises(InvalidGenerationRequest):
        veo.start_generation(
            VertexClient("p", dry_run=True),
            registry.get("veo-3.1"),
            prompt="x",
            variant="1080p",
            reference_images=[veo.SourceImage(data=b"a") for _ in range(4)],
        )


# --- 4. Retries keep the model (PRD 37) -----------------------------------


def test_retry_never_substitutes_the_model(studio, client):
    uid = client.post("/api/universes", json={"name": "Nova"}).json()["id"]
    job = studio.jobs.create(
        uid, kind="video", model="veo-3.1", variant="1080p", target_type="scene",
        target_id="scene_x", request={}, estimated_cost_usd=1.6,
    )
    studio.jobs.mark_failed(uid, job["id"], "boom")
    with pytest.raises(ModelNotAllowed):
        studio.jobs.retry(uid, job["id"], model="veo-3.1-lite")


def test_retry_stops_after_max_attempts(studio, client):
    uid = client.post("/api/universes", json={"name": "Nova"}).json()["id"]
    job = studio.jobs.create(
        uid, kind="text", model="gemini-3-pro", variant="default", target_type="song",
        target_id="s", request={}, estimated_cost_usd=0.01,
    )
    studio.db.update(
        f"universes/{uid}/jobs/{job['id']}",
        {"attempts": 3, "state": JobState.FAILED.value},
    )
    with pytest.raises(Exception) as excinfo:
        studio.jobs.retry(uid, job["id"])
    assert "intentos" in str(excinfo.value)


# --- Pricing matches the PRD's own reference numbers (PRD 44) -------------


def test_reference_cost_of_a_three_minute_video(registry):
    """PRD 44: 24 escenas, dos intentos por pieza, gemini-3.1-flash-image y
    veo-3.1-fast 1080p sin audio."""
    song = estimate_song(registry, attempts=15)
    images = estimate_images(registry, "gemini-3.1-flash-image", "1K", images=42)
    video = estimate_video(registry, "veo-3.1-fast", "1080p", seconds=8, clips=36)
    director = estimate_text(registry, "gemini-3-pro", input_tokens=900_000,
                             output_tokens=100_000)
    assert round(song.amount_usd, 2) == 1.20
    assert round(images.amount_usd, 2) == 2.81
    assert round(video.amount_usd, 2) == 28.80
    assert director.amount_usd == pytest.approx(2.125)  # el PRD lo redondea a ~$2,00
    total = song.amount_usd + images.amount_usd + video.amount_usd + director.amount_usd + 1.00
    assert 34.0 < total < 36.5


def test_video_is_billed_per_second_not_per_clip(registry):
    """The Vertex console labels the unit '1 count'. It is not per video."""
    one_clip = estimate_video(registry, "veo-3.1-lite", "1080p", seconds=8, clips=1)
    assert one_clip.amount_usd == 0.40
    assert one_clip.quantity == 8


def test_switching_model_is_the_main_lever(registry):
    """PRD 44: the same video is about $15 on lite 720p and about $65 on
    veo-3.1 1080p."""
    cheap = estimate_video(registry, "veo-3.1-lite", "720p", seconds=8, clips=36)
    dear = estimate_video(registry, "veo-3.1", "1080p", seconds=8, clips=36)
    assert round(cheap.amount_usd, 2) == 8.64
    assert round(dear.amount_usd, 2) == 57.60
    assert dear.amount_usd / cheap.amount_usd > 6


# --- Budget cutoff is real (PRD 44) ---------------------------------------


def test_budget_cutoff_rejects_new_jobs(studio, client):
    uid = client.post("/api/universes", json={"name": "Nova"}).json()["id"]
    studio.budget.update_config({"total_usd": 0.10, "hard_stop_enabled": True})
    with pytest.raises(BudgetExceeded):
        studio.orchestrator.submit(
            GenerationRequest(
                universe_id=uid, kind="video", target_type="scene", target_id="x",
                model="veo-3.1", variant="4K",
            )
        )


def test_per_artist_ceiling(studio, client):
    uid = client.post(
        "/api/universes", json={"name": "Nova", "budget_usd": 0.05}
    ).json()["id"]
    with pytest.raises(BudgetExceeded):
        studio.orchestrator.submit(
            GenerationRequest(
                universe_id=uid, kind="image", target_type="scene", target_id="x",
                model="gemini-3-pro-image", variant="4K",
            )
        )


def test_expired_credit_stops_everything(studio, client):
    uid = client.post("/api/universes", json={"name": "Nova"}).json()["id"]
    studio.budget.update_config({"credit_started_on": "2020-01-01", "credit_days": 90})
    with pytest.raises(BudgetExceeded) as excinfo:
        studio.orchestrator.submit(
            GenerationRequest(universe_id=uid, kind="image", target_type="scene", target_id="x")
        )
    assert "caduco" in str(excinfo.value)


def test_credit_countdown_is_visible(client, studio):
    studio.budget.update_config({"credit_started_on": "2026-08-01", "credit_days": 90})
    body = client.get("/api/budget").json()
    assert body["credit_expires_on"] == "2026-10-30"
    assert body["credit_days_left"] is not None


# --- Idempotency (PRD 42.1) -----------------------------------------------


def test_the_same_key_never_generates_twice(studio, client):
    uid = client.post("/api/universes", json={"name": "Nova"}).json()["id"]
    request = GenerationRequest(
        universe_id=uid, kind="text", target_type="artist_bible", target_id="current",
        idempotency_key="abc-123", payload={"task": "artist_bible"},
    )
    first = studio.orchestrator.submit(request)
    second = studio.orchestrator.submit(request)
    assert first["id"] == second["id"]
    studio.jobs.wait_for_idle(20)
    assert len(studio.jobs.list(uid, limit=50)) == 1


# --- Model resolution order (PRD 42.8) ------------------------------------


def test_user_choice_beats_the_bible_preference(studio, client):
    uid = client.post("/api/universes", json={"name": "Nova"}).json()["id"]
    client.put(
        f"/api/universes/{uid}/bible/preferences",
        json={"preferred_image_model": "gemini-3.1-flash-lite-image"},
    )
    chosen = studio.orchestrator.resolve_model(
        GenerationRequest(universe_id=uid, kind="image", model="gemini-3-pro-image")
    )
    assert (chosen.spec.id, chosen.source) == ("gemini-3-pro-image", "user")

    fallback = studio.orchestrator.resolve_model(
        GenerationRequest(universe_id=uid, kind="image")
    )
    assert (fallback.spec.id, fallback.source) == ("gemini-3.1-flash-lite-image", "bible")
