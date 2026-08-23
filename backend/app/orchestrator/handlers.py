"""Job handlers: one per kind of generation.

A handler receives the studio, the universe and the job, does the work, writes
the artefact into Cloud Storage and the document into Firestore with status
DRAFT, and returns the real cost. It never approves anything: results land in
READY and wait for a human (PRD 36).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from ..clock import now_iso
from ..db.repositories import (
    CHARACTERS,
    CONTENT,
    IMAGES,
    LOCATIONS,
    SCENES,
    SONGS,
    VIDEO_PROJECTS,
    VIDEOS,
    WARDROBE,
    Repository,
)
from ..domain.enums import CanonStatus, LyricsAuthor
from ..domain.guards import assert_same_model_on_retry, resolve_clip_duration
from ..domain.pricing import estimate_images, estimate_song, estimate_speech, estimate_text
from ..domain.pricing import estimate_video as price_video
from ..domain.schemas import MASTER_SHOTS
from ..errors import Conflict, InvalidGenerationRequest, ProviderError
from ..ids import new_id
from ..providers import gemini_image, lyria, veo
from ..providers.storage import (
    character_path,
    content_path,
    location_path,
    scene_path,
    song_path,
    wardrobe_path,
)
from ..services import approvals
from ..services.context import load_bible, save_bible
from . import director
from .orchestrator import Outcome

logger = logging.getLogger("aaus.handlers")

VEO_POLL_SECONDS = 10
VEO_MAX_POLLS = 90  # 15 minutes


# --- helpers ---------------------------------------------------------------


def _payload(job: dict[str, Any]) -> dict[str, Any]:
    return (job.get("request") or {}).get("payload") or {}


def _load_references(studio, paths: list[str], kind: str = "character"):
    refs = []
    for path in paths:
        try:
            data = studio.storage.read_bytes(path)
        except (FileNotFoundError, OSError) as exc:
            logger.warning("reference_missing %s: %s", path, exc)
            continue
        refs.append(
            gemini_image.ReferenceImage(
                data=data,
                mime_type="image/png",
                kind=kind,  # type: ignore[arg-type]
                label=path.rsplit("/", 1)[-1],
            )
        )
    return refs


def _repo(studio, universe_id: str, collection: str) -> Repository:
    return Repository(studio.db, universe_id, collection)


# --- text: the Director ----------------------------------------------------


def handle_text(studio, universe_id: str, job: dict[str, Any]) -> Outcome:
    payload = _payload(job)
    task = payload.get("task", "")
    result = director.run(studio, universe_id, job["model"], payload)
    data = result.data or {}

    applied = _apply_director_result(studio, universe_id, job, task, data)

    cost = estimate_text(
        studio.registry,
        job["model"],
        input_tokens=result.prompt_tokens,
        output_tokens=result.output_tokens,
    )
    return Outcome(
        result={"task": task, "proposal": data, "applied": applied, "text": result.text[:4000]},
        cost=cost,
    )


def _apply_director_result(
    studio, universe_id: str, job: dict[str, Any], task: str, data: dict[str, Any]
) -> dict[str, Any]:
    target_id = job.get("target_id") or ""

    if task == "artist_bible":
        bible = load_bible(studio.db, universe_id)
        merged = bible.model_dump()
        for section in ("identity", "musical", "visual", "communication"):
            if isinstance(data.get(section), dict):
                merged[section] = {**merged.get(section, {}), **data[section]}
        if data.get("voice_profile_lines"):
            merged["voice_profile"] = {
                **merged.get("voice_profile", {}),
                "lines": data["voice_profile_lines"],
            }
        merged["status"] = CanonStatus.DRAFT.value
        merged["version"] = int(merged.get("version", 1)) + 1
        from ..domain.schemas import ArtistBible

        save_bible(studio.db, universe_id, ArtistBible.model_validate(merged))
        return {"entity": "artist_bible", "id": "current"}

    if task in {"music_concept", "lyrics_analysis"}:
        repo = _repo(studio, universe_id, SONGS)
        song = repo.require(target_id)
        concept = {
            **(song.get("concept") or {}),
            "title": data.get("title") or song.get("title", ""),
            "concept": data.get("concept") or data.get("summary", ""),
            "hook": data.get("hook") or ", ".join(data.get("hooks") or []),
            "genre": data.get("genre") or data.get("proposed_genre", ""),
            "bpm": data.get("bpm") or data.get("proposed_bpm"),
            "mood": data.get("mood", ""),
            "structure": data.get("structure") or [],
            "production": data.get("production") or data.get("proposed_production", ""),
            "interpretation": data.get("interpretation")
            or data.get("proposed_interpretation", ""),
            "visual_concept": data.get("visual_concept", ""),
            "status": CanonStatus.DRAFT.value,
        }
        repo.update(
            target_id,
            {
                "title": concept["title"] or song.get("title", ""),
                "concept": concept,
                "music_prompt": data.get("music_prompt", song.get("music_prompt", "")),
                "genre": concept["genre"],
                "bpm": concept["bpm"],
                "mood": concept["mood"],
                "structure": concept["structure"] or song.get("structure", []),
                "status": CanonStatus.DRAFT.value,
            },
        )
        return {"entity": "song", "id": target_id}

    if task == "lyrics":
        repo = _repo(studio, universe_id, SONGS)
        song = repo.require(target_id)
        author = (
            LyricsAuthor.MIXED.value
            if song.get("lyrics")
            else LyricsAuthor.AI.value
        )
        repo.update(
            target_id,
            {
                "lyrics": data.get("lyrics", ""),
                "lyrics_author": author,
                "lyrics_status": CanonStatus.DRAFT.value,
                "title": data.get("title") or song.get("title", ""),
            },
        )
        return {"entity": "song", "id": target_id}

    if task == "video_concept":
        repo = _repo(studio, universe_id, VIDEO_PROJECTS)
        repo.update(
            target_id,
            {
                "title": data.get("title", ""),
                "video_type": data.get("video_type", "narrative"),
                "concept": data.get("concept", ""),
                "story": {**(data.get("story") or {}), "status": CanonStatus.DRAFT.value},
                "status": CanonStatus.DRAFT.value,
            },
        )
        # Characters, locations and wardrobe stay as proposals until the user
        # says yes; creating them is an explicit action (PRD 17).
        return {
            "entity": "video_project",
            "id": target_id,
            "proposed_characters": data.get("needed_characters") or [],
            "proposed_locations": data.get("needed_locations") or [],
            "proposed_wardrobe": data.get("needed_wardrobe") or [],
        }

    if task == "storyboard":
        return _apply_storyboard(studio, universe_id, target_id, data)

    if task == "character":
        repo = _repo(studio, universe_id, CHARACTERS)
        prompts = {p["key"]: p["prompt"] for p in (data.get("master_prompts") or []) if "key" in p}
        shots = [
            {
                "key": key,
                "label": label,
                "image_id": None,
                "storage_path": None,
                "status": CanonStatus.DRAFT.value,
                "prompt": prompts.get(key, ""),
            }
            for key, label in MASTER_SHOTS
        ]
        patch = {
            "name": data.get("name", ""),
            "apparent_age": data.get("apparent_age", ""),
            "appearance": data.get("appearance", ""),
            "personality": data.get("personality", ""),
            "master_shots": shots,
            "status": CanonStatus.DRAFT.value,
        }
        if repo.get(target_id) is None:
            repo.create(target_id, patch)
        else:
            repo.update(target_id, patch)
        return {"entity": "character", "id": target_id}

    if task in {"content_script", "interview"}:
        repo = _repo(studio, universe_id, CONTENT)
        spoken = data.get("spoken_text") or "\n".join(
            e.get("answer", "") for e in (data.get("exchanges") or [])
        )
        patch = {
            "title": data.get("title", ""),
            "script": data.get("script") or _format_interview(data),
            "spoken_text": spoken,
            "video_prompt": data.get("video_prompt", ""),
            "status": CanonStatus.DRAFT.value,
        }
        if repo.get(target_id) is None:
            repo.create(target_id, patch)
        else:
            repo.update(target_id, patch)
        return {"entity": "content", "id": target_id}

    return {"entity": None}


def _format_interview(data: dict[str, Any]) -> str:
    return "\n\n".join(
        f"P: {e.get('question','')}\nR: {e.get('answer','')}" for e in (data.get("exchanges") or [])
    )


def _apply_storyboard(
    studio, universe_id: str, project_id: str, data: dict[str, Any]
) -> dict[str, Any]:
    project = _repo(studio, universe_id, VIDEO_PROJECTS).require(project_id)
    characters = {c["name"]: c["id"] for c in _repo(studio, universe_id, CHARACTERS).list()}
    locations = {loc["name"]: loc["id"] for loc in _repo(studio, universe_id, LOCATIONS).list()}
    outfits = {o["name"]: o["id"] for o in _repo(studio, universe_id, WARDROBE).list()}

    scenes_repo = _repo(studio, universe_id, SCENES)
    for old in scenes_repo.list(where={"project_id": project_id}):
        if old.get("status") != CanonStatus.APPROVED.value:
            scenes_repo.delete(old["id"])

    created: list[dict[str, Any]] = []
    index_to_id: dict[int, str] = {}
    for raw in sorted(data.get("scenes") or [], key=lambda s: int(s.get("index", 0))):
        index = int(raw.get("index", len(created)))
        scene_id = new_id("scene")
        index_to_id[index] = scene_id
        reuse_index = int(raw.get("reuses_scene_index", -1))
        if reuse_index == index:
            # A shot cannot reuse itself; that would leave the scene with no
            # source clip at assembly time.
            reuse_index = -1
        scene = scenes_repo.create(
            scene_id,
            {
                "project_id": project_id,
                "index": index,
                "duration_seconds": 8,
                "song_timestamp": raw.get("song_timestamp", ""),
                "character_ids": [
                    characters[name]
                    for name in raw.get("character_names", [])
                    if name in characters
                ],
                "location_id": locations.get(raw.get("location_name", "")),
                "wardrobe_ids": [
                    outfits[name] for name in raw.get("wardrobe_names", []) if name in outfits
                ],
                "action": raw.get("action", ""),
                "emotion": raw.get("emotion", ""),
                "camera": raw.get("camera", ""),
                "lighting": raw.get("lighting", ""),
                "environment": raw.get("environment", ""),
                "dialogue": raw.get("dialogue", ""),
                "visual_objective": raw.get("visual_objective", ""),
                "reuses_scene_id": index_to_id.get(reuse_index) if reuse_index >= 0 else None,
                "reuse_note": raw.get("reuse_note", ""),
                "image_prompt": raw.get("image_prompt", ""),
                "video_prompt": raw.get("video_prompt", ""),
                "status": CanonStatus.DRAFT.value,
            },
        )
        created.append(scene)

    _repo(studio, universe_id, VIDEO_PROJECTS).update(
        project_id,
        {"storyboard_status": CanonStatus.DRAFT.value, "storyboard_notes": data.get("notes", "")},
    )
    reused = sum(1 for s in created if s.get("reuses_scene_id"))
    logger.info(
        "storyboard_built project=%s scenes=%s reused=%s", project_id, len(created), reused
    )
    return {
        "entity": "storyboard",
        "id": project_id,
        "scenes": len(created),
        "reused": reused,
        "to_generate": len(created) - reused,
        "song_id": project.get("song_id"),
    }


# --- image -----------------------------------------------------------------


def handle_image(studio, universe_id: str, job: dict[str, Any]) -> Outcome:
    payload = _payload(job)
    purpose = payload.get("purpose", "scene")
    spec = studio.registry.require_active(job["model"], "image")
    variant = job.get("variant") or spec.default_variant

    prompt = payload.get("prompt", "").strip()
    if not prompt:
        raise InvalidGenerationRequest("Falta el prompt de imagen.")

    reference_paths: list[str] = list(payload.get("reference_paths") or [])
    references = _load_references(studio, reference_paths, kind="character")
    # A model that cannot hold a character reference should not silently drop
    # it; gemini_image raises, and that error reaches the user.
    if references and int(spec.cap("reference_characters_max", 0)) == 0:
        references = []
        logger.info("model_without_character_refs %s", spec.id)

    result = gemini_image.generate(
        studio.vertex,
        spec,
        prompt=prompt,
        variant=variant,
        references=references,
        aspect_ratio=payload.get("aspect_ratio", "16:9"),
        negative_prompt=payload.get("negative_prompt", ""),
    )

    stored, doc = _store_image(studio, universe_id, job, purpose, payload, result, reference_paths)
    cost = estimate_images(studio.registry, spec.id, variant, images=1)
    return Outcome(
        result={
            "purpose": purpose,
            "storage_path": stored.path,
            "url": studio.storage.signed_url(stored.path),
            "image_id": doc.get("id") if doc else None,
            "model": spec.id,
            "variant": variant,
            "references": reference_paths,
        },
        cost=cost,
    )


def _store_image(studio, universe_id, job, purpose, payload, result, reference_paths):
    target_id = job.get("target_id") or ""
    suffix = "png" if "png" in result.mime_type else "jpg"

    if purpose == "scene":
        scene = _repo(studio, universe_id, SCENES).require(target_id)
        version = int(payload.get("version") or 0) or _next_version(
            studio, universe_id, IMAGES, {"scene_id": target_id}
        )
        path = scene_path(universe_id, target_id, f"image_v{version}.{suffix}")
        stored = studio.storage.write_bytes(path, result.data, result.mime_type)
        image = _repo(studio, universe_id, IMAGES).create(
            new_id("img"),
            {
                "scene_id": target_id,
                "project_id": scene.get("project_id"),
                "storage_path": stored.path,
                "prompt": result.prompt,
                "model": result.model,
                "variant": result.variant,
                "references": reference_paths,
                "parameters": result.parameters,
                "version": version,
                "status": CanonStatus.DRAFT.value,
                "locked": False,
                "job_id": job["id"],
                "provenance": {
                    "parent_id": target_id,
                    "model": result.model,
                    "variant": result.variant,
                    "prompt": result.prompt,
                    "references": reference_paths,
                    "parameters": result.parameters,
                    "timestamp": now_iso(),
                    "version": version,
                },
            },
        )
        _repo(studio, universe_id, SCENES).update(
            target_id, {"image_id": image["id"], "image_status": CanonStatus.DRAFT.value}
        )
        return stored, image

    if purpose == "character_master":
        shot_key = payload.get("shot_key", "portrait")
        path = character_path(universe_id, f"{target_id}_{shot_key}.{suffix}")
        stored = studio.storage.write_bytes(path, result.data, result.mime_type)
        repo = _repo(studio, universe_id, CHARACTERS)
        character = repo.require(target_id)
        shots = list(character.get("master_shots") or [])
        found = False
        for shot in shots:
            if shot.get("key") == shot_key:
                shot["storage_path"] = stored.path
                shot["status"] = CanonStatus.DRAFT.value
                found = True
        if not found:
            shots.append(
                {
                    "key": shot_key,
                    "label": shot_key,
                    "storage_path": stored.path,
                    "status": CanonStatus.DRAFT.value,
                }
            )
        repo.update(target_id, {"master_shots": shots})
        return stored, {"id": None}

    if purpose == "wardrobe":
        path = wardrobe_path(universe_id, f"{target_id}.{suffix}")
        stored = studio.storage.write_bytes(path, result.data, result.mime_type)
        _repo(studio, universe_id, WARDROBE).update(
            target_id, {"image_path": stored.path, "status": CanonStatus.DRAFT.value}
        )
        return stored, {"id": None}

    if purpose == "location":
        path = location_path(universe_id, f"{target_id}_{new_id('ref')}.{suffix}")
        stored = studio.storage.write_bytes(path, result.data, result.mime_type)
        repo = _repo(studio, universe_id, LOCATIONS)
        location = repo.require(target_id)
        refs = list(location.get("reference_paths") or [])
        refs.append(stored.path)
        repo.update(target_id, {"reference_paths": refs[-6:], "status": CanonStatus.DRAFT.value})
        return stored, {"id": None}

    if purpose == "content":
        path = content_path(universe_id, f"{target_id}_still.{suffix}")
        stored = studio.storage.write_bytes(path, result.data, result.mime_type)
        _repo(studio, universe_id, CONTENT).update(
            target_id, {"source_image_path": stored.path}
        )
        return stored, {"id": target_id}

    if purpose == "cover":
        path = song_path(universe_id, target_id, f"cover.{suffix}")
        stored = studio.storage.write_bytes(path, result.data, result.mime_type)
        _repo(studio, universe_id, SONGS).update(target_id, {"cover_path": stored.path})
        return stored, {"id": target_id}

    raise InvalidGenerationRequest(f"Proposito de imagen desconocido: '{purpose}'.")


def _next_version(studio, universe_id: str, collection: str, where: dict[str, Any]) -> int:
    rows = _repo(studio, universe_id, collection).list(where=where, limit=200)
    return max((int(r.get("version", 1)) for r in rows), default=0) + 1


# --- music -----------------------------------------------------------------


def handle_music(studio, universe_id: str, job: dict[str, Any]) -> Outcome:
    payload = _payload(job)
    song_id = job.get("target_id") or ""
    repo = _repo(studio, universe_id, SONGS)
    song = repo.require(song_id)

    # Lyria is not called until the lyrics are approved (PRD 14).
    approvals.assert_lyrics_approved(studio.db, universe_id, song_id)

    bible = load_bible(studio.db, universe_id)
    voice_lines = song.get("voice_profile", {}).get("lines") or bible.voice_profile.lines
    prompt = _compose_music_prompt(song, voice_lines, payload)
    duration = int(payload.get("duration_seconds") or song.get("requested_duration_seconds") or 150)

    result = lyria.generate_song(
        studio.vertex,
        model=job["model"],
        prompt=prompt,
        duration_seconds=duration,
        lyrics=song.get("lyrics", ""),
        negative_prompt=payload.get("negative_prompt", ""),
        seed=payload.get("seed"),
    )

    version = len(song.get("versions") or []) + 1
    extension = "wav" if "wav" in result.mime_type else "mp3"
    stored = studio.storage.write_bytes(
        song_path(universe_id, song_id, f"version_{version}.{extension}"),
        result.data,
        result.mime_type,
    )
    cost = estimate_song(studio.registry, attempts=1)
    versions = list(song.get("versions") or [])
    versions.append(
        {
            "version": version,
            "job_id": job["id"],
            "audio_path": stored.path,
            "duration_seconds": duration,
            "model": result.model,
            "parameters": result.parameters,
            "cost_usd": round(cost.amount_usd, 4),
            "status": CanonStatus.DRAFT.value,
            "created_at": now_iso(),
        }
    )
    repo.update(
        song_id,
        {
            "versions": versions,
            "music_prompt": prompt,
            "model": result.model,
            "requested_duration_seconds": duration,
            "voice_profile": {"lines": voice_lines},
            "cost_usd": round(float(song.get("cost_usd", 0.0)) + cost.amount_usd, 4),
            "status": CanonStatus.DRAFT.value,
        },
    )
    return Outcome(
        result={
            "song_id": song_id,
            "version": version,
            "storage_path": stored.path,
            "url": studio.storage.signed_url(stored.path),
            "duration_seconds": duration,
            "model": result.model,
        },
        cost=cost,
    )


def _compose_music_prompt(song: dict[str, Any], voice_lines: list[str], payload) -> str:
    """US English, Voice Profile verbatim (PRD 10, 14)."""
    if payload.get("prompt"):
        base = payload["prompt"]
    else:
        base = song.get("music_prompt") or ""
    concept = song.get("concept") or {}
    parts = [base.strip()] if base.strip() else []
    descriptors = [
        f"Genre: {song.get('genre') or concept.get('genre', '')}",
        f"BPM: {song.get('bpm') or concept.get('bpm', '')}",
        f"Mood: {song.get('mood') or concept.get('mood', '')}",
        f"Production: {concept.get('production', '')}",
        f"Structure: {', '.join(song.get('structure') or concept.get('structure') or [])}",
    ]
    parts.extend(d for d in descriptors if not d.endswith(": "))
    if voice_lines:
        parts.append("Lead vocal:\n" + "\n".join(voice_lines))
    return "\n".join(parts).strip()


# --- video -----------------------------------------------------------------


def handle_video(studio, universe_id: str, job: dict[str, Any]) -> Outcome:
    if job.get("target_type") == "content":
        return _handle_content_video(studio, universe_id, job)
    payload = _payload(job)
    scene_id = job.get("target_id") or ""
    scenes = _repo(studio, universe_id, SCENES)
    scene = scenes.require(scene_id)

    approvals.assert_scene_not_reused(scene)
    approvals.assert_scene_image_locked(studio.db, universe_id, scene_id)

    image_doc = _repo(studio, universe_id, IMAGES).require(scene["image_id"])
    source_bytes = studio.storage.read_bytes(image_doc["storage_path"])

    spec = studio.registry.require_active(job["model"], "video")
    variant = job.get("variant") or spec.default_variant

    reference_paths = list(payload.get("reference_paths") or [])[
        : int(spec.cap("reference_images_max", 3))
    ]
    references = [
        veo.SourceImage(data=studio.storage.read_bytes(p))
        for p in reference_paths
        if studio.storage.exists(p)
    ]

    duration = resolve_clip_duration(
        payload.get("duration_seconds") or scene.get("duration_seconds"),
        resolution=variant,
        reference_image_count=len(references) + 1,
    )
    aspect_ratio = payload.get("aspect_ratio", "16:9")
    prompt = payload.get("prompt") or scene.get("video_prompt") or _scene_prompt(scene)

    operation = veo.start_generation(
        studio.vertex,
        spec,
        prompt=prompt,
        variant=variant,
        source_image=veo.SourceImage(
            data=source_bytes, mime_type=image_doc.get("mime_type", "image/png")
        ),
        reference_images=references,
        duration_seconds=duration,
        aspect_ratio=aspect_ratio,
        negative_prompt=payload.get("negative_prompt", ""),
    )
    video = _await_video(studio, operation)

    version = _next_version(studio, universe_id, VIDEOS, {"scene_id": scene_id})
    data = video.data if video and video.data else _placeholder_clip(spec.id, duration)
    stored = studio.storage.write_bytes(
        scene_path(universe_id, scene_id, f"clip_v{version}.mp4"), data, "video/mp4"
    )

    cost = price_video(studio.registry, spec.id, variant, seconds=duration, clips=1)
    clip = _repo(studio, universe_id, VIDEOS).create(
        new_id("clip"),
        {
            "scene_id": scene_id,
            "project_id": scene.get("project_id"),
            "storage_path": stored.path,
            "source_image_id": image_doc["id"],
            "prompt": prompt,
            "model": spec.id,
            "variant": variant,
            "duration_seconds": duration,
            "aspect_ratio": aspect_ratio,
            "generate_audio": False,
            "references": reference_paths,
            "parameters": operation.parameters,
            "version": version,
            "status": CanonStatus.DRAFT.value,
            "locked": False,
            "cost_usd": round(cost.amount_usd, 4),
            "job_id": job["id"],
            "provenance": {
                "parent_id": scene_id,
                "model": spec.id,
                "variant": variant,
                "prompt": prompt,
                "references": reference_paths,
                "parameters": operation.parameters,
                "timestamp": now_iso(),
                "version": version,
                "cost_usd": round(cost.amount_usd, 4),
            },
        },
    )
    scenes.update(
        scene_id,
        {
            "clip_id": clip["id"],
            "clip_status": CanonStatus.DRAFT.value,
            "cost_usd": round(float(scene.get("cost_usd", 0.0)) + cost.amount_usd, 4),
        },
    )
    return Outcome(
        result={
            "scene_id": scene_id,
            "clip_id": clip["id"],
            "storage_path": stored.path,
            "url": studio.storage.signed_url(stored.path),
            "duration_seconds": duration,
            "model": spec.id,
            "variant": variant,
            "generate_audio": False,
        },
        cost=cost,
    )


def _handle_content_video(studio, universe_id: str, job: dict[str, Any]) -> Outcome:
    """Footage for a BTS clip, an interview or an announcement.

    Same rules as a scene: a still first, then Veo, always without audio. The
    voice is laid over it afterwards (PRD 34, 35).
    """
    payload = _payload(job)
    content_id = job.get("target_id") or ""
    repo = _repo(studio, universe_id, CONTENT)
    piece = repo.require(content_id)

    still_path = piece.get("source_image_path")
    if not still_path:
        raise Conflict(
            "Genera primero la imagen de esta pieza. El video parte siempre de una imagen."
        )

    spec = studio.registry.require_active(job["model"], "video")
    variant = job.get("variant") or spec.default_variant
    aspect_ratio = payload.get("aspect_ratio") or piece.get("aspect_ratio", "9:16")
    duration = resolve_clip_duration(
        payload.get("duration_seconds"), resolution=variant, reference_image_count=1
    )
    prompt = payload.get("prompt") or piece.get("video_prompt") or piece.get("script", "")[:500]

    operation = veo.start_generation(
        studio.vertex,
        spec,
        prompt=prompt,
        variant=variant,
        source_image=veo.SourceImage(data=studio.storage.read_bytes(still_path)),
        duration_seconds=duration,
        aspect_ratio=aspect_ratio,
    )
    video = _await_video(studio, operation)
    data = video.data if video and video.data else _placeholder_clip(spec.id, duration)
    stored = studio.storage.write_bytes(
        content_path(universe_id, f"{content_id}.mp4"), data, "video/mp4"
    )
    cost = price_video(studio.registry, spec.id, variant, seconds=duration, clips=1)
    repo.update(
        content_id,
        {
            "storage_path": stored.path,
            "cost_usd": round(float(piece.get("cost_usd", 0.0)) + cost.amount_usd, 4),
            "provenance": {
                "parent_id": content_id,
                "model": spec.id,
                "variant": variant,
                "prompt": prompt,
                "parameters": operation.parameters,
                "timestamp": now_iso(),
                "cost_usd": round(cost.amount_usd, 4),
            },
        },
    )
    return Outcome(
        result={
            "content_id": content_id,
            "storage_path": stored.path,
            "url": studio.storage.signed_url(stored.path),
            "duration_seconds": duration,
            "model": spec.id,
            "variant": variant,
            "generate_audio": False,
        },
        cost=cost,
    )


def _scene_prompt(scene: dict[str, Any]) -> str:
    bits = [
        scene.get("action", ""),
        f"Camera: {scene.get('camera','')}" if scene.get("camera") else "",
        f"Lighting: {scene.get('lighting','')}" if scene.get("lighting") else "",
        f"Environment: {scene.get('environment','')}" if scene.get("environment") else "",
        f"Emotion: {scene.get('emotion','')}" if scene.get("emotion") else "",
    ]
    return "\n".join(b for b in bits if b)


def _await_video(studio, operation, *, poll_seconds: int = VEO_POLL_SECONDS):
    for attempt in range(VEO_MAX_POLLS):
        result = veo.poll(studio.vertex, operation)
        if result is not None:
            return result
        if studio.settings.dry_run:
            break
        time.sleep(poll_seconds)
        logger.info("veo_poll %s attempt=%s", operation.name, attempt + 1)
    raise ProviderError("Veo no termino la generacion dentro del tiempo previsto.")


def _placeholder_clip(model: str, seconds: int) -> bytes:
    """Dry runs never produce real footage. The placeholder says so out loud so
    it cannot be mistaken for a take."""
    import json

    return json.dumps(
        {"dry_run": True, "model": model, "seconds": seconds, "audio": False}, indent=2
    ).encode()


# --- speech ----------------------------------------------------------------


def handle_speech(studio, universe_id: str, job: dict[str, Any]) -> Outcome:
    payload = _payload(job)
    text = (payload.get("text") or "").strip()
    if not text:
        raise InvalidGenerationRequest("No hay texto que sintetizar.")

    bible = load_bible(studio.db, universe_id)
    secret_name = bible.voice_profile.speaking_voice_secret
    if not secret_name and not studio.settings.dry_run:
        raise Conflict(
            "Este artista no tiene voz hablada clonada. Crea la clave de Chirp 3 antes de "
            "generar contenido hablado."
        )
    key = studio.secrets.read(secret_name) if secret_name else "DRY_RUN_VOICE_CLONING_KEY"

    result = studio.chirp.synthesize(
        text=text,
        voice_cloning_key=key,
        language_code=payload.get("language_code", "es-ES"),
    )
    target_id = job.get("target_id") or new_id("speech")
    stored = studio.storage.write_bytes(
        content_path(universe_id, f"{target_id}_voice.wav"), result.data, result.mime_type
    )
    if _repo(studio, universe_id, CONTENT).get(target_id):
        _repo(studio, universe_id, CONTENT).update(target_id, {"spoken_audio_path": stored.path})

    cost = estimate_speech(studio.registry, "chirp-3-instant-custom-voice", characters=len(text))
    return Outcome(
        result={
            "storage_path": stored.path,
            "url": studio.storage.signed_url(stored.path),
            "characters": len(text),
        },
        cost=cost,
    )


# --- assembly --------------------------------------------------------------


def handle_assembly(studio, universe_id: str, job: dict[str, Any]) -> Outcome:
    from ..assembly.engine import assemble_project

    project_id = job.get("target_id") or ""
    payload = _payload(job)
    result = assemble_project(
        studio,
        universe_id,
        project_id,
        formats=payload.get("formats") or ["16:9", "9:16"],
        captions=bool(payload.get("captions", False)),
        transition_seconds=float(payload.get("transition_seconds", 0.0)),
    )
    return Outcome(result=result, cost=None)


def handle_video_extend(studio, universe_id: str, job: dict[str, Any]) -> Outcome:
    """Alarga una toma ya aprobada, +7 s (PRD 26).

    Veo no acepta imagenes de referencia aqui: solo recibe el clip anterior y un
    texto, y deduce quien es el personaje del ultimo segundo de ese clip. Por eso
    solo se permite sobre un clip aprobado, y por eso la pantalla avisa de que
    si la toma acaba sin ver la cara, puede salir otra persona.
    """
    payload = _payload(job)
    scene_id = job.get("target_id") or ""
    scenes = _repo(studio, universe_id, SCENES)
    scene = scenes.require(scene_id)

    if scene.get("clip_status") != CanonStatus.APPROVED.value or not scene.get("clip_id"):
        raise Conflict("Solo se alarga una toma que ya hayas aprobado.")
    clip = _repo(studio, universe_id, VIDEOS).require(scene["clip_id"])

    if not studio.settings.use_gcs and not studio.settings.dry_run:
        raise Conflict(
            "Alargar una toma requiere que el video este en Cloud Storage: Veo lo lee de alli."
        )

    # La continuacion tiene que salir del mismo modelo que hizo la toma.
    assert_same_model_on_retry(clip["model"], job["model"])
    spec = studio.registry.require_active(clip["model"], "video")
    current = int(clip.get("duration_seconds", 8))
    prompt = payload.get("prompt") or scene.get("video_prompt") or _scene_prompt(scene)

    operation = veo.start_extension(
        studio.vertex,
        spec,
        prompt=prompt,
        video_uri=studio.storage.uri(clip["storage_path"]),
        aspect_ratio=clip.get("aspect_ratio", "16:9"),
        current_seconds=current,
    )
    video = _await_video(studio, operation)

    # Veo devuelve un unico archivo con el clip original y la continuacion.
    total = current + operation.seconds
    version = _next_version(studio, universe_id, VIDEOS, {"scene_id": scene_id})
    data = video.data if video and video.data else _placeholder_clip(spec.id, total)
    stored = studio.storage.write_bytes(
        scene_path(universe_id, scene_id, f"clip_v{version}.mp4"), data, "video/mp4"
    )

    cost = price_video(
        studio.registry, spec.id, _extension_variant(spec), seconds=operation.seconds, clips=1
    )
    nuevo_clip = _repo(studio, universe_id, VIDEOS).create(
        new_id("clip"),
        {
            "scene_id": scene_id,
            "project_id": scene.get("project_id"),
            "storage_path": stored.path,
            "source_image_id": clip.get("source_image_id", ""),
            "extends_clip_id": clip["id"],
            "prompt": prompt,
            "model": spec.id,
            "variant": veo.EXTENSION_RESOLUTION,
            "duration_seconds": total,
            "aspect_ratio": clip.get("aspect_ratio", "16:9"),
            "generate_audio": False,
            "references": [],
            "parameters": operation.parameters,
            "version": version,
            "status": CanonStatus.DRAFT.value,
            "locked": False,
            "cost_usd": round(cost.amount_usd, 4),
            "job_id": job["id"],
        },
    )
    # La toma alargada vuelve a estar pendiente de aprobacion: dura mas y llega
    # a 720p, asi que hay que mirarla otra vez.
    scenes.update(
        scene_id,
        {
            "clip_id": nuevo_clip["id"],
            "clip_status": CanonStatus.DRAFT.value,
            "duration_seconds": total,
        },
    )
    return Outcome(
        result={
            "scene_id": scene_id,
            "clip_id": nuevo_clip["id"],
            "storage_path": stored.path,
            "url": studio.storage.signed_url(stored.path),
            "added_seconds": operation.seconds,
            "duration_seconds": total,
            "resolution": veo.EXTENSION_RESOLUTION,
            "model": spec.id,
            "generate_audio": False,
        },
        cost=cost,
    )


def _extension_variant(spec) -> str:
    """La extension llega a 720p. Si el modelo no tiene tarifa de 720p, se toma
    la mas barata que tenga: es una estimacion, no una factura."""
    for variant in spec.variants:
        if variant.key == veo.EXTENSION_RESOLUTION:
            return variant.key
    return min(spec.variants, key=lambda v: v.price).key


def handle_cut(studio, universe_id: str, job: dict[str, Any]) -> Outcome:
    """A Short, Reel or TikTok taken out of the approved master. Derived, so it
    costs nothing to generate (PRD 32, 33)."""
    from ..assembly.engine import cut_short

    payload = _payload(job)
    content_id = job.get("target_id") or ""
    repo = _repo(studio, universe_id, CONTENT)
    piece = repo.require(content_id)
    project_id = payload.get("project_id") or piece.get("project_id")
    if not project_id:
        raise Conflict("Esta pieza no esta asociada a ningun videoclip del que recortar.")

    vertical = piece.get("aspect_ratio", "9:16") == "9:16"
    result = cut_short(
        studio,
        universe_id,
        project_id,
        start=float(payload.get("start", 0.0)),
        duration=float(payload.get("duration", 15.0)),
        vertical=vertical,
        name=f"{content_id}.mp4",
    )
    if result.get("storage_path"):
        repo.update(content_id, {"storage_path": result["storage_path"]})
    return Outcome(result=result, cost=None)


def handle_mix(studio, universe_id: str, job: dict[str, Any]) -> Outcome:
    """Chirp voice over footage generated without audio (PRD 34, 35)."""
    from ..assembly.engine import mix_content

    return Outcome(result=mix_content(studio, universe_id, job.get("target_id") or ""), cost=None)


HANDLERS: dict[str, Callable[..., Outcome]] = {
    "text": handle_text,
    "image": handle_image,
    "music": handle_music,
    "video": handle_video,
    "speech": handle_speech,
    "assembly": handle_assembly,
    "cut": handle_cut,
    "mix": handle_mix,
    "video_extend": handle_video_extend,
}
