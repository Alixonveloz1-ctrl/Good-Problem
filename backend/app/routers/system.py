"""Health, identity, model registry and the Home screen."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Query
from fastapi.responses import FileResponse, RedirectResponse, Response

from ..container import Studio
from ..db.repositories import (
    CHARACTERS,
    JOBS,
    SONGS,
    UNIVERSES,
    VIDEO_PROJECTS,
    Repository,
)
from ..domain.enums import CanonStatus, JobState, StageStatus
from ..errors import NotFound
from ..providers.storage import LocalStorage
from ..providers.vertex import redact
from .deps import OwnerDep, StudioDep

router = APIRouter(prefix="/api", tags=["system"])

logger = logging.getLogger("aaus.media")


@router.get("/health")
def health(studio: StudioDep) -> dict[str, Any]:
    return {
        "status": "ok",
        "dry_run": studio.settings.dry_run,
        "project": studio.settings.project_id or None,
        "location": studio.settings.location,
        "firestore": studio.settings.use_firestore,
        "storage": "gcs" if studio.settings.use_gcs else "local",
    }


@router.get("/me")
def me(owner: OwnerDep, studio: StudioDep) -> dict[str, Any]:
    return {
        "email": owner.email,
        "verified": owner.verified,
        "single_user": bool(studio.settings.owner_email),
        "dry_run": studio.settings.dry_run,
    }


# --- Model registry (PRD 41) ----------------------------------------------


@router.get("/registry/models")
def list_models(owner: OwnerDep, studio: StudioDep) -> dict[str, Any]:
    return studio.registry.selector_payload()


@router.put("/registry/models")
def replace_models(
    owner: OwnerDep, studio: StudioDep, document: dict[str, Any] = Body(...)
) -> dict[str, Any]:
    """Editing this document is how a model is added, repriced or turned off.
    No code changes, no redeploy."""
    registry = studio.replace_registry_document(document)
    return registry.selector_payload()


@router.post("/registry/reload")
def reload_models(owner: OwnerDep, studio: StudioDep) -> dict[str, Any]:
    return studio.reload_registry().selector_payload()


# --- Home (PRD 38) ---------------------------------------------------------


MAX_ARTISTAS = 12
"""Cuantos artistas se pintan en la portada.

No es un limite de la aplicacion: es lo que cabe en una pantalla antes de que
haya que desplazarse un rato. Y cada uno cuesta consultas, asi que sin tope la
portada se vuelve mas lenta cuanto mas trabajo hay hecho, que es justo al reves
de como tiene que ser.
"""


@router.get("/home")
def home(owner: OwnerDep, studio: StudioDep) -> dict[str, Any]:
    """La portada, con UNA lectura por coleccion y artista.

    Antes eran cinco, dos de ellas leyendo lo mismo dos veces, y sin limite de
    tiempo: bastaba que una se quedara colgada para que la pantalla se quedara
    girando indefinidamente, sin datos y sin error. Eso paso.
    """
    universes = studio.db.list(UNIVERSES, order_by="updated_at", limit=MAX_ARTISTAS)

    tarjetas: list[dict[str, Any]] = []
    active_jobs: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    proyectos_todos: list[dict[str, Any]] = []

    for universe in universes:
        uid = universe["id"]
        nombre = universe.get("name", uid)

        # Una lectura de trabajos, no dos: de la misma lista salen los que estan
        # en marcha y los que esperan una decision.
        trabajos = Repository(studio.db, uid, JOBS).list(limit=60)
        for job in trabajos:
            estado = job.get("state")
            if estado in {JobState.QUEUED.value, JobState.PROCESSING.value}:
                active_jobs.append({**job, "universe_name": nombre})
            elif estado == JobState.READY.value:
                pending.append(
                    {
                        "job_id": job["id"],
                        "universe_id": uid,
                        "universe_name": nombre,
                        "kind": job["kind"],
                        "target_type": job.get("target_type", ""),
                        "target_id": job.get("target_id", ""),
                        "model": job.get("model", ""),
                        "finished_at": job.get("finished_at"),
                    }
                )

        # Y una lectura de videoclips, que sirve para la tarjeta y para la lista
        # de abajo. Antes se leian dos veces los mismos documentos.
        proyectos = Repository(studio.db, uid, VIDEO_PROJECTS).list(limit=50)
        tarjetas.append(_tarjeta(studio, universe, proyectos))
        if proyectos:
            # La portada de un videoclip es la de su cancion. Se piden todas de
            # una vez: preguntarlo proyecto por proyecto seria una lectura por
            # fila. Y si no hay videoclips no hace falta preguntar nada.
            portadas = {
                cancion["id"]: cancion.get("cover_path") or ""
                for cancion in Repository(studio.db, uid, SONGS).list(limit=100)
            }
            proyectos_todos.extend(_filas(universe, proyectos, portadas))

    return {
        "universes": tarjetas,
        "active_jobs": sorted(active_jobs, key=lambda j: j.get("created_at", ""), reverse=True),
        "pending_approvals": sorted(
            pending, key=lambda j: j.get("finished_at") or "", reverse=True
        ),
        "recent_projects": sorted(
            proyectos_todos, key=lambda f: f.get("updated_at") or "", reverse=True
        )[:8],
    }


def _tarjeta(
    studio: Studio, universe: dict[str, Any], proyectos: list[dict[str, Any]]
) -> dict[str, Any]:
    """Lo que la pantalla de inicio ensena de cada artista: su cara y su estado.

    La cara se calcula aqui y no en el navegador: pedirla artista por artista
    serian tantas peticiones como artistas, y desde un movil eso se nota.
    """
    uid = universe["id"]
    personajes = Repository(studio.db, uid, CHARACTERS).list(limit=50)
    protagonista = next((p for p in personajes if p.get("role") == "lead"), None)
    if protagonista is None and personajes:
        protagonista = personajes[0]

    # La cara de la tarjeta es el RETRATO vigente del artista, derivado de
    # su ficha en cada lectura —nunca una copia guardada al crear— y con su
    # marca de version: la ruta no cambia al regenerar, asi que sin la
    # version el telefono seguiria ensenando la foto vieja desde su cache.
    tomas = (protagonista or {}).get("master_shots", [])
    retrato = next(
        (t for t in tomas if t.get("key") == "portrait" and t.get("storage_path")),
        None,
    ) or next((t for t in tomas if t.get("storage_path")), None)
    portada = retrato["storage_path"] if retrato else ""
    version_portada = int(retrato.get("version") or 0) if retrato else 0

    # En marcha = todavia sin su MP4 final. Un proyecto esta terminado
    # cuando el MP4 existe; no depende de ningun estado de aprobacion.
    en_marcha = sum(1 for p in proyectos if not p.get("master_16x9_path"))
    return {
        **universe,
        "cover_path": portada,
        "cover_version": version_portada,
        "artist_name": (protagonista or {}).get("name", ""),
        "projects_active": en_marcha,
        "projects_total": len(proyectos),
    }


def _filas(
    universe: dict[str, Any],
    proyectos: list[dict[str, Any]],
    portadas: dict[str, str],
) -> list[dict[str, Any]]:
    """Los videoclips de un artista, como los ensena la portada.

    Juntos con los de los demas es lo que ahorra entrar artista por artista para
    acordarse de que habia a medias.
    """
    uid = universe["id"]
    nombre = universe.get("name", uid)
    return [
        {
            "id": proyecto["id"],
            "universe_id": uid,
            "universe_name": nombre,
            "title": proyecto.get("title") or "Sin titulo",
            "status": proyecto.get("status", ""),
            "stage": _etapa_actual(proyecto),
            "cover_path": portadas.get(proyecto.get("song_id", ""), ""),
            "updated_at": proyecto.get("updated_at", ""),
        }
        for proyecto in proyectos
    ]


def _etapa_actual(proyecto: dict[str, Any]) -> str:
    """Por donde va el videoclip: la primera etapa que aun no esta hecha.

    "BORRADOR" no dice nada; "Storyboard" dice que toca hacer hoy.
    """
    for etapa in proyecto.get("stages", []):
        if etapa.get("status") != StageStatus.APPROVED.value:
            return str(etapa.get("label") or etapa.get("key") or "")
    return "Terminado"


# --- Diagnostics -----------------------------------------------------------


@router.get("/diagnostics/vertex-calls")
def vertex_calls(
    owner: OwnerDep,
    studio: StudioDep,
    prefix: str = Query("", description="Filtra por prefijo de modelo, por ejemplo 'veo'"),
    limit: int = Query(50, le=500),
) -> dict[str, Any]:
    """Acceptance test 27: comprobar que ninguna llamada a Veo pidio audio.

    Every request this process sent is here, with the payload as it went out.
    """
    calls = studio.calls.for_model_prefix(prefix) if prefix else studio.calls.all()
    rows = [
        {**call.to_dict(), "payload": redact(call.payload)} for call in calls[-limit:]
    ]
    audio_requests = [
        row
        for row in rows
        if (row["payload"].get("parameters") or {}).get("generateAudio") is True
    ]
    return {
        "count": len(rows),
        "calls": rows,
        "calls_requesting_audio": len(audio_requests),
    }


# --- Media -----------------------------------------------------------------

media_router = APIRouter(tags=["media"])


@media_router.get("/media/{path:path}")
def media(path: str, studio: StudioDep):
    """Por donde el iPhone se descarga lo generado.

    Con bucket lo normal es mandarlo directo a Google con un enlace firmado: no
    pasa por aqui y no cuesta ni memoria ni tiempo de esta aplicacion.

    Pero firmar necesita un permiso que hay que tener puesto, y si falta, lo que
    se ve es una imagen rota sin ninguna explicacion. Asi que si la firma falla,
    el archivo sale por aqui igualmente. Mas lento, pero se ve.
    """
    storage = studio.storage
    if not isinstance(storage, LocalStorage):
        try:
            return RedirectResponse(storage.signed_url(path))
        except Exception:
            logger.exception("no se pudo firmar %s; se sirve desde la aplicacion", path)
            datos = storage.read_bytes(path)
            from ..providers.storage import guess_content_type

            return Response(content=datos, media_type=guess_content_type(path))
    full = storage.root / path
    if not full.exists():
        raise NotFound(f"No existe {path}")
    return FileResponse(full)

