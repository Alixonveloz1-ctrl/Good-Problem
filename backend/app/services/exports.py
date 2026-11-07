"""Export Package (PRD 49).

Everything a launch needs, in the folder layout the PRD specifies, written under
``/universes/{id}/exports/`` and downloadable from the phone into Files.

A zip is produced when the package is small enough to build in memory;
otherwise the manifest of signed URLs is the deliverable and the files are
downloaded one by one. Either way nothing has to be assembled on a computer.
"""

from __future__ import annotations

import io
import json
import logging
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from ..clock import now_iso
from ..db.repositories import EXPORTS, SONGS, VIDEO_PROJECTS, Repository
from ..domain.enums import CanonStatus
from ..errors import Conflict
from ..ids import new_id, slugify
from ..providers.storage import export_path, song_path
from .approvals import current_audio_path

logger = logging.getLogger("aaus.exports")

MAX_ZIP_BYTES = 200 * 1024 * 1024


def build_package(studio, universe_id: str, song_id: str) -> dict[str, Any]:
    universe = studio.orchestrator.require_universe(universe_id)
    song = Repository(studio.db, universe_id, SONGS).require(song_id)
    if not current_audio_path(song):
        raise Conflict(
            "La cancion todavia no tiene audio generado: no hay nada que exportar."
        )

    artist = slugify(universe.get("name") or universe_id).upper()
    song_folder = slugify(song.get("title") or song_id).upper()
    root = f"{artist}/{song_folder}"

    project = (
        Repository(studio.db, universe_id, VIDEO_PROJECTS).get(song["video_project_id"])
        if song.get("video_project_id")
        else None
    )
    files: list[dict[str, Any]] = []

    def add(folder: str, name: str, source_path: str | None) -> None:
        if not source_path or not studio.storage.exists(source_path):
            return
        files.append(
            {
                "folder": folder,
                "name": name,
                "source_path": source_path,
                "package_path": f"{root}/{folder}/{name}",
                "url": studio.storage.signed_url(source_path),
            }
        )

    # El PRD 49 pide los dos: wav para trabajar y mp3 para subir a cualquier
    # sitio. Lyria devuelve uno solo, asi que el otro se convierte aqui.
    for nombre, ruta in _audio_masters(studio, universe_id, song).items():
        add("AUDIO", nombre, ruta)
    add("COVER", "cover.jpg", song.get("cover_path"))
    if project:
        add("MUSIC_VIDEO", "youtube_16x9.mp4", project.get("master_16x9_path"))
        add("MUSIC_VIDEO", "vertical_9x16.mp4", project.get("master_9x16_path"))

    metadata = {
        "artist": universe.get("name"),
        "universe_id": universe_id,
        "song": {
            "id": song_id,
            "title": song.get("title"),
            "genre": song.get("genre"),
            "bpm": song.get("bpm"),
            "mood": song.get("mood"),
            "structure": song.get("structure"),
            "lyrics_author": song.get("lyrics_author"),
            "duration_seconds": song.get("requested_duration_seconds"),
            "model": song.get("model"),
            "cost_usd": song.get("cost_usd"),
        },
        "video_project": {
            "id": project.get("id"),
            "video_type": project.get("video_type"),
            "cost_usd": project.get("cost_usd"),
        }
        if project
        else None,
        "files": [{"path": f["package_path"], "source": f["source_path"]} for f in files],
        "exported_at": now_iso(),
    }

    metadata_path = export_path(universe_id, f"{root}/METADATA/metadata.json")
    studio.storage.write_bytes(
        metadata_path,
        json.dumps(metadata, indent=2, ensure_ascii=False).encode(),
        "application/json",
    )
    info_path = export_path(universe_id, f"{root}/METADATA/song_info.txt")
    studio.storage.write_bytes(info_path, _song_info(song, universe).encode(), "text/plain")
    files.append(
        {
            "folder": "METADATA",
            "name": "metadata.json",
            "source_path": metadata_path,
            "package_path": f"{root}/METADATA/metadata.json",
            "url": studio.storage.signed_url(metadata_path),
        }
    )
    files.append(
        {
            "folder": "METADATA",
            "name": "song_info.txt",
            "source_path": info_path,
            "package_path": f"{root}/METADATA/song_info.txt",
            "url": studio.storage.signed_url(info_path),
        }
    )

    archive_path = _maybe_zip(studio, universe_id, root, files)

    record = Repository(studio.db, universe_id, EXPORTS).create(
        new_id("exp"),
        {
            "song_id": song_id,
            "project_id": project.get("id") if project else None,
            "root_path": root,
            "files": files,
            "manifest_path": metadata_path,
            "archive_path": archive_path,
            "status": CanonStatus.APPROVED.value,
        },
    )
    return {
        **record,
        "archive_url": studio.storage.signed_url(archive_path) if archive_path else None,
        "tree": render_tree(root, files),
    }


def _audio_masters(studio, universe_id: str, song: dict[str, Any]) -> dict[str, str]:
    """Devuelve {"master.wav": ruta, "master.mp3": ruta}, convirtiendo el que
    falte. Si FFmpeg no esta disponible se entrega solo el original, y el
    paquete lo dice en lugar de fingir que estan los dos."""
    from ..assembly import ffmpeg_cmds as cmds
    from ..assembly.engine import ffmpeg_available

    original = current_audio_path(song)
    if not original:
        return {}
    es_wav = str(original).lower().endswith(".wav")
    salida = {"master.wav" if es_wav else "master.mp3": original}

    faltante = "master.mp3" if es_wav else "master.wav"
    destino = song_path(universe_id, song["id"], faltante)
    if studio.storage.exists(destino):
        salida[faltante] = destino
        return salida
    if studio.settings.dry_run or not ffmpeg_available():
        logger.info("export_audio_sin_convertir %s", faltante)
        return salida

    with tempfile.TemporaryDirectory(prefix="aaus-audio-") as tmp:
        trabajo = Path(tmp)
        entrada = trabajo / ("master.wav" if es_wav else "master.mp3")
        entrada.write_bytes(studio.storage.read_bytes(original))
        convertido = trabajo / faltante
        comando = (
            cmds.to_mp3(str(entrada), str(convertido))
            if faltante.endswith(".mp3")
            else cmds.to_wav(str(entrada), str(convertido))
        )
        proceso = subprocess.run(comando, cwd=trabajo, capture_output=True, text=True)
        if proceso.returncode != 0:
            logger.warning("export_audio_conversion_fallida %s", proceso.stderr[-500:])
            return salida
        studio.storage.write_bytes(
            destino,
            convertido.read_bytes(),
            "audio/mpeg" if faltante.endswith(".mp3") else "audio/wav",
        )
    salida[faltante] = destino
    return salida


def _song_info(song: dict[str, Any], universe: dict[str, Any]) -> str:
    concept = song.get("concept") or {}
    return "\n".join(
        [
            f"ARTISTA: {universe.get('name','')}",
            f"TITULO: {song.get('title','')}",
            f"GENERO: {song.get('genre','')}",
            f"BPM: {song.get('bpm','')}",
            f"MOOD: {song.get('mood','')}",
            f"ESTRUCTURA: {', '.join(song.get('structure') or [])}",
            f"AUTOR DE LA LETRA: {song.get('lyrics_author','')}",
            f"MODELO DE MUSICA: {song.get('model','')}",
            "",
            "CONCEPTO:",
            concept.get("concept", ""),
            "",
            "LETRA:",
            song.get("lyrics", ""),
        ]
    )


def _maybe_zip(studio, universe_id: str, root: str, files: list[dict[str, Any]]) -> str | None:
    """One archive to drop into Files, when the package is small enough to build
    in memory. Each file is read once, and the moment the total goes over the
    ceiling the archive is abandoned in favour of the per-file links."""
    buffer = io.BytesIO()
    total = 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for entry in files:
            try:
                data = studio.storage.read_bytes(entry["source_path"])
            except (FileNotFoundError, OSError):
                continue
            total += len(data)
            if total > MAX_ZIP_BYTES:
                logger.info("export_zip_skipped bytes=%s", total)
                return None
            archive.writestr(entry["package_path"], data)
    path = export_path(universe_id, f"{root.replace('/', '_')}.zip")
    studio.storage.write_bytes(path, buffer.getvalue(), "application/zip")
    return path


def render_tree(root: str, files: list[dict[str, Any]]) -> str:
    """The layout from PRD 49, rendered for the phone."""
    lines = [f"{root.split('/')[0]}/", f"  {root.split('/')[-1]}/"]
    by_folder: dict[str, list[str]] = {}
    for entry in files:
        by_folder.setdefault(entry["folder"], []).append(entry["name"])
    for folder in ["AUDIO", "COVER", "MUSIC_VIDEO", "METADATA"]:
        names = by_folder.get(folder)
        if not names:
            continue
        lines.append(f"    {folder}/")
        lines.extend(f"      {name}" for name in sorted(names))
    return "\n".join(lines)
