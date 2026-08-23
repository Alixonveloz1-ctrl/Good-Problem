"""Media Assembly Engine (PRD 29, 31, 32).

Not an external service. A component of this system that runs on Google Cloud:
Cloud Run Jobs, FFmpeg and Cloud Storage.

It takes the approved master audio, the approved clips in storyboard order and
the editing instructions, and produces the 16:9 master plus the 9:16 reframe.
Vertical versions are derived from the master, so they cost nothing to generate.

When FFmpeg is not present, or the studio is in dry run, the engine still does
all of its real work except the encode: it resolves reused takes, orders the
timeline, computes offsets and writes the edit decision list. That artefact is
what the encode consumes, so a dry run exercises everything except the codec.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..clock import now_iso
from ..db.repositories import SCENES, SONGS, VIDEO_PROJECTS, VIDEOS, Repository
from ..domain.enums import CanonStatus
from ..errors import Conflict, DomainError
from ..providers.storage import content_path, project_path
from ..services import approvals
from . import ffmpeg_cmds as cmds

logger = logging.getLogger("aaus.assembly")


@dataclass
class TimelineEntry:
    index: int
    scene_id: str
    clip_id: str
    storage_path: str
    duration_seconds: int
    start_seconds: float
    reused_from: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "scene_id": self.scene_id,
            "clip_id": self.clip_id,
            "storage_path": self.storage_path,
            "duration_seconds": self.duration_seconds,
            "start_seconds": round(self.start_seconds, 3),
            "reused_from": self.reused_from,
        }


@dataclass
class EditDecisionList:
    project_id: str
    song_id: str
    master_audio_path: str
    entries: list[TimelineEntry] = field(default_factory=list)
    captions: list[tuple[float, float, str]] = field(default_factory=list)

    @property
    def total_seconds(self) -> float:
        return sum(e.duration_seconds for e in self.entries)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "song_id": self.song_id,
            "master_audio_path": self.master_audio_path,
            "total_seconds": self.total_seconds,
            "entries": [e.to_dict() for e in self.entries],
            "captions": [
                {"start": s, "end": e, "text": t} for s, e, t in self.captions
            ],
            "built_at": now_iso(),
        }


def ffmpeg_available() -> bool:
    return shutil.which(cmds.FFMPEG) is not None


def build_edl(studio, universe_id: str, project_id: str, *, captions: bool = False):
    """Resolve the timeline. Reused takes point at the clip of the scene they
    reuse, so nothing is generated twice (PRD 23)."""
    project = approvals.assert_ready_for_assembly(studio.db, universe_id, project_id)
    song = Repository(studio.db, universe_id, SONGS).require(project["song_id"])

    scenes = Repository(studio.db, universe_id, SCENES).list(
        where={"project_id": project_id}, order_by="index", descending=False
    )
    clips = {c["id"]: c for c in Repository(studio.db, universe_id, VIDEOS).list(limit=500)}
    by_scene = {s["id"]: s for s in scenes}

    edl = EditDecisionList(
        project_id=project_id,
        song_id=song["id"],
        master_audio_path=song["approved_master_path"],
    )
    cursor = 0.0
    for scene in scenes:
        source_scene = scene
        reused_from = None
        if scene.get("reuses_scene_id"):
            source_scene = by_scene.get(scene["reuses_scene_id"])
            if source_scene is None:
                raise Conflict(
                    f"La escena {scene['index']} reutiliza una toma que ya no existe."
                )
            reused_from = source_scene["id"]
        clip = clips.get(source_scene.get("clip_id") or "")
        if clip is None:
            raise Conflict(f"La escena {scene['index']} no tiene clip aprobado.")
        duration = int(clip.get("duration_seconds", 8))
        edl.entries.append(
            TimelineEntry(
                index=int(scene["index"]),
                scene_id=scene["id"],
                clip_id=clip["id"],
                storage_path=clip["storage_path"],
                duration_seconds=duration,
                start_seconds=cursor,
                reused_from=reused_from,
            )
        )
        if captions and scene.get("dialogue"):
            edl.captions.append((cursor, cursor + duration, scene["dialogue"]))
        cursor += duration
    return edl


def assemble_project(
    studio,
    universe_id: str,
    project_id: str,
    *,
    formats: list[str] | None = None,
    captions: bool = False,
) -> dict[str, Any]:
    formats = formats or ["16:9", "9:16"]
    edl = build_edl(studio, universe_id, project_id, captions=captions)

    edl_path = project_path(universe_id, project_id, "edl.json")
    studio.storage.write_bytes(
        edl_path,
        json.dumps(edl.to_dict(), indent=2, ensure_ascii=False).encode(),
        "application/json",
    )

    if studio.settings.dry_run or not ffmpeg_available():
        reason = "dry_run" if studio.settings.dry_run else "ffmpeg_no_disponible"
        logger.info("assembly_plan_only project=%s reason=%s", project_id, reason)
        Repository(studio.db, universe_id, VIDEO_PROJECTS).update(
            project_id, {"edl_path": edl_path}
        )
        return {
            "rendered": False,
            "reason": reason,
            "edl_path": edl_path,
            "total_seconds": edl.total_seconds,
            "clips": len(edl.entries),
            "reused": sum(1 for e in edl.entries if e.reused_from),
            "formats": formats,
        }

    outputs = _render(studio, universe_id, project_id, edl, formats=formats, captions=captions)
    patch: dict[str, Any] = {"edl_path": edl_path, "status": CanonStatus.DRAFT.value}
    if "16:9" in outputs:
        patch["master_16x9_path"] = outputs["16:9"]
    if "9:16" in outputs:
        patch["master_9x16_path"] = outputs["9:16"]
    Repository(studio.db, universe_id, VIDEO_PROJECTS).update(project_id, patch)
    return {
        "rendered": True,
        "edl_path": edl_path,
        "outputs": outputs,
        "total_seconds": edl.total_seconds,
        "clips": len(edl.entries),
        "reused": sum(1 for e in edl.entries if e.reused_from),
    }


def _run(command: list[str], *, cwd: Path) -> None:
    logger.info("ffmpeg %s", " ".join(command[:8]))
    process = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if process.returncode != 0:
        raise DomainError(
            "FFmpeg fallo durante el ensamblaje.",
            details={"command": command[:6], "stderr": process.stderr[-2000:]},
        )


def _render(
    studio,
    universe_id: str,
    project_id: str,
    edl: EditDecisionList,
    *,
    formats: list[str],
    captions: bool,
) -> dict[str, str]:
    outputs: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="aaus-assembly-") as tmp:
        work = Path(tmp)

        local_clips: list[str] = []
        for entry in edl.entries:
            local = work / f"{entry.index:04d}_{entry.clip_id}.mp4"
            local.write_bytes(studio.storage.read_bytes(entry.storage_path))
            local_clips.append(str(local))

        audio_local = work / "master_audio"
        audio_local.write_bytes(studio.storage.read_bytes(edl.master_audio_path))

        list_file = work / "concat.txt"
        list_file.write_text(cmds.concat_list_file(local_clips))

        silent = work / "picture.mp4"
        _run(cmds.concat(str(list_file), str(silent), cmds.LANDSCAPE_1080), cwd=work)

        landscape = work / "master_16x9.mp4"
        _run(
            cmds.mux_audio(str(silent), str(audio_local), str(landscape), cmds.LANDSCAPE_1080),
            cwd=work,
        )

        if captions and edl.captions:
            srt = work / "captions.srt"
            srt.write_text(cmds.build_srt(edl.captions), encoding="utf-8")
            captioned = work / "master_16x9_cc.mp4"
            _run(cmds.burn_captions(str(landscape), str(srt), str(captioned)), cwd=work)
            landscape = captioned

        if "16:9" in formats:
            path = project_path(universe_id, project_id, "master_16x9.mp4")
            studio.storage.write_bytes(path, landscape.read_bytes(), "video/mp4")
            outputs["16:9"] = path

        if "9:16" in formats:
            vertical = work / "master_9x16.mp4"
            _run(cmds.reframe_vertical(str(landscape), str(vertical)), cwd=work)
            path = project_path(universe_id, project_id, "master_9x16.mp4")
            studio.storage.write_bytes(path, vertical.read_bytes(), "video/mp4")
            outputs["9:16"] = path

    return outputs


def cut_short(
    studio,
    universe_id: str,
    project_id: str,
    *,
    start: float,
    duration: float,
    vertical: bool = True,
    name: str = "short_01.mp4",
) -> dict[str, Any]:
    """Shorts, Reels and TikToks come out of the approved master, so they cost
    nothing to generate (PRD 32, 33)."""
    project = Repository(studio.db, universe_id, VIDEO_PROJECTS).require(project_id)
    source_path = project.get("master_9x16_path") if vertical else project.get("master_16x9_path")
    if not source_path:
        raise Conflict("El proyecto todavia no tiene master del que recortar.")
    if studio.settings.dry_run or not ffmpeg_available():
        return {"rendered": False, "reason": "dry_run", "source": source_path}
    with tempfile.TemporaryDirectory(prefix="aaus-cut-") as tmp:
        work = Path(tmp)
        local = work / "source.mp4"
        local.write_bytes(studio.storage.read_bytes(source_path))
        out = work / name
        _run(cmds.cut(str(local), str(out), start=start, duration=duration), cwd=work)
        path = project_path(universe_id, project_id, f"cuts/{name}")
        studio.storage.write_bytes(path, out.read_bytes(), "video/mp4")
    return {"rendered": True, "storage_path": path}



def mix_content(studio, universe_id: str, content_id: str) -> dict[str, Any]:
    """Lay the cloned Chirp voice over footage generated without audio.

    This is what makes a BTS clip or an interview work: Veo produced the picture
    silently, Chirp produced the voice, and the edit puts them together
    (PRD 29, 34, 35).
    """
    from ..db.repositories import CONTENT

    repo = Repository(studio.db, universe_id, CONTENT)
    piece = repo.require(content_id)
    video_path = piece.get("storage_path")
    voice_path = piece.get("spoken_audio_path")
    if not video_path:
        raise Conflict("Esta pieza no tiene video sobre el que superponer la voz.")
    if not voice_path:
        raise Conflict("Esta pieza no tiene voz de Chirp. Generala antes de mezclar.")

    music_path = _bed_music_path(studio, universe_id, piece)

    if studio.settings.dry_run or not ffmpeg_available():
        return {
            "rendered": False,
            "reason": "dry_run" if studio.settings.dry_run else "ffmpeg_no_disponible",
            "video": video_path,
            "voice": voice_path,
            "music_bed": music_path,
        }

    with tempfile.TemporaryDirectory(prefix="aaus-mix-") as tmp:
        work = Path(tmp)
        video = work / "picture.mp4"
        video.write_bytes(studio.storage.read_bytes(video_path))
        voice = work / "voice.wav"
        voice.write_bytes(studio.storage.read_bytes(voice_path))
        out = work / "mixed.mp4"

        if music_path:
            music = work / "bed"
            music.write_bytes(studio.storage.read_bytes(music_path))
            _run(cmds.overlay_voice(str(video), str(music), str(voice), str(out)), cwd=work)
        else:
            _run(
                cmds.mux_audio(str(video), str(voice), str(out), cmds.VERTICAL_1080),
                cwd=work,
            )

        path = content_path(universe_id, f"{content_id}_final.mp4")
        studio.storage.write_bytes(path, out.read_bytes(), "video/mp4")

    repo.update(content_id, {"storage_path": path})
    return {"rendered": True, "storage_path": path, "music_bed": music_path}


def _bed_music_path(studio, universe_id: str, piece: dict[str, Any]) -> str | None:
    """The approved master, quiet under the voice, when the piece belongs to a
    song."""
    if not piece.get("song_id"):
        return None
    song = Repository(studio.db, universe_id, SONGS).get(piece["song_id"])
    return (song or {}).get("approved_master_path")
