"""Job handlers: one per kind of generation.

A handler receives the studio, the universe and the job, does the work, writes
the artefact into Cloud Storage and the document into Firestore with status
DRAFT, and returns the real cost. Results land in READY and wait for a human
(PRD 36) — with one exception decided by the studio's owner: the artist's own
Character Master images. Those are approved and in use the moment they are
generated (see ``_store_image``), because the owner regenerates instead of
reviewing: a generated face is the face until he asks for another one.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from ..clock import now_iso
from ..db.repositories import (
    CHARACTERS,
    IMAGES,
    SCENES,
    SONGS,
    VIDEO_PROJECTS,
    VIDEOS,
    Repository,
)
from ..domain import artist as artist_domain
from ..domain import tempo as tempo_domain
from ..domain.enums import CanonStatus, CreativeRole, LyricsAuthor
from ..domain.guards import resolve_clip_duration
from ..domain.pricing import estimate_images, estimate_song, estimate_text
from ..domain.pricing import estimate_video as price_video
from ..domain.schemas import MASTER_SHOTS
from ..errors import InvalidGenerationRequest, ProviderError
from ..ids import new_id
from ..providers import gemini_image, lyria, veo
from ..providers.storage import character_path, scene_path, song_path
from ..services import approvals
from ..services import inspiration as inspiration_service
from ..services.context import (
    load_bible,
    nombre_en_su_ficha,
    save_bible,
    sync_bible_identity,
)
from ..services.inspiration import inspiracion_utilizable
from . import director
from .orchestrator import GenerationRequest, Outcome

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


def _exigir_que_devolvio_algo(
    data: dict[str, Any], claves: tuple[str, ...], mensaje: str
) -> None:
    """Un «exito» vacio es un fallo que se calla.

    Cada rama de ``_apply_director_result`` escribe con valores por defecto
    cuando el Director no devuelve una clave: si no devuelve NINGUNA, la rama
    «aplica» un texto hecho de huecos encima de lo que ya habia, y el trabajo
    termina LISTO como si hubiera pasado algo. Paso con la Biblia de un
    artista real: dos trabajos «terminaron» sin tocar ni una palabra, y
    nadie vio un error en ninguna parte. Un Director que no devuelve nada
    no ha hecho el trabajo: eso es un fallo del proveedor, con su motivo a
    la vista, no un exito.
    """
    if not any(data.get(clave) for clave in claves):
        raise ProviderError(mensaje)


_SECCIONES_BIBLIA = ("identity", "musical", "communication", "visual")


def _seccion_comparable(seccion: str, datos: dict[str, Any]) -> dict[str, Any]:
    copia = dict(datos or {})
    if seccion == "identity":
        # La edad aparente no cuenta como cambio ni como conservacion: no
        # la escribe el Director, la sincroniza sync_bible_identity desde
        # los rasgos de la ficha. Una «reescritura» que solo la moviera no
        # habria reescrito nada, y una que la conserve no es un eco por eso.
        copia.pop("apparent_age", None)
    return copia


def _biblia_sin_cambios(previa: dict[str, Any], merged: dict[str, Any]) -> bool:
    """La red contra el eco, un nivel por encima de la guardia de vacio.

    La guardia de «no devolvio nada» no basta: el Director puede devolver
    las secciones llenas… con el texto de la Biblia que ya habia, porque
    la recibia como canon y la transcribia. La fusion aplicaba entonces
    valores identicos encima de si mismos y el trabajo terminaba LISTO
    sin cambiar ni una palabra — paso tres veces en vivo. Si el conjunto
    de secciones de contenido queda identico al que habia, no hubo
    reescritura: es un fallo con su motivo, no un exito. La comparacion
    es del conjunto, no campo a campo: un cambio parcial legitimo (que
    conserve el origen, la voz o lo que sea) pasa sin problema.
    """
    return all(
        _seccion_comparable(seccion, previa.get(seccion) or {})
        == _seccion_comparable(seccion, merged.get(seccion) or {})
        for seccion in _SECCIONES_BIBLIA
    )


def _apply_director_result(
    studio, universe_id: str, job: dict[str, Any], task: str, data: dict[str, Any]
) -> dict[str, Any]:
    target_id = job.get("target_id") or ""

    if task == "artist_bible":
        # Las secciones que esta rama de verdad fusiona. Si el Director no
        # trae ninguna —JSON vacio o sin secciones—, «aplicar» seria subir
        # la version y devolver exito sin tocar ni una palabra de la
        # Biblia: el exito vacio que dejo dos trabajos «LISTO» con la
        # Biblia intacta. Eso es un fallo, y se dice.
        trae_seccion = any(
            isinstance(data.get(seccion), dict) and data[seccion]
            for seccion in ("identity", "musical", "communication", "visual")
        )
        if not trae_seccion and not data.get("voice_profile_lines"):
            raise ProviderError(
                "El Director no devolvió la Biblia: vuelve a intentarlo."
            )
        bible = load_bible(studio.db, universe_id)
        previa = bible.model_dump()
        merged = bible.model_dump()
        for section in ("identity", "musical", "communication"):
            if isinstance(data.get(section), dict):
                merged[section] = {**merged.get(section, {}), **data[section]}
        if isinstance(data.get("visual"), dict):
            # The visual style is the user's choice, not the Director's: a
            # Bible proposal never overwrites style_key or the photo style.
            visual = {**merged.get("visual", {}), **data["visual"]}
            for clave in ("style_key", "style_label", "photo_style_description", "master_stale"):
                if merged.get("visual", {}).get(clave):
                    visual[clave] = merged["visual"][clave]
                elif clave in merged.get("visual", {}):
                    visual[clave] = merged["visual"][clave]
            merged["visual"] = visual
        # El nombre del artista no lo escribe el Director: vive en la
        # ficha del personaje, en su campo, y la fusion restaura hacia
        # el valor que manda — el de la ficha si ya tiene un nombre de
        # verdad; si no (la ficha aun lleva el del formulario de
        # creacion), el guardado en la identidad, que es el que hay.
        # En la primera reescritura real tras el arreglo del eco, el
        # Director devolvio como nombre artistico el nombre del UNIVERSO
        # («Verso Oscuro» en vez de «K-Ronte») y la fusion lo pinto
        # encima del bueno: como el estilo visual y la voz fija, lo que
        # ya tiene nombre puesto se queda con su nombre.
        nombre_ficha = nombre_en_su_ficha(studio.db, universe_id)
        identidad_previa = previa.get("identity") or {}
        if nombre_ficha:
            merged["identity"]["stage_name"] = nombre_ficha
            merged["identity"]["fictional_name"] = nombre_ficha
        else:
            for clave in ("stage_name", "fictional_name"):
                if identidad_previa.get(clave):
                    merged["identity"][clave] = identidad_previa[clave]
        # El genero de la identidad musical es la etiqueta corta del
        # genero principal («Rap / hip-hop»), no la combinacion entera:
        # en esa misma reescritura volvio dentro del campo genre el texto
        # largo de «Suena a» — la mezcla libre del usuario, palabra por
        # palabra. Si lo devuelto esta contaminado (es ese texto, o no
        # cabe en una etiqueta), se conserva el guardado SANEADO: si el
        # guardado tambien era el contaminado —la primera reescritura lo
        # dejo asi antes de que existiera esta guardia—, conservarlo tal
        # cual conservaria la contaminacion para siempre; manda la
        # etiqueta del primer genero elegido en la ficha.
        genero_devuelto = (merged.get("musical") or {}).get("genre") or ""
        texto_libre = (merged.get("music_genre_free") or "").strip()
        if artist_domain.genero_contaminado(genero_devuelto, texto_libre):
            merged["musical"]["genre"] = artist_domain.etiqueta_genero_principal(
                previa.get("music_genres"),
                (previa.get("musical") or {}).get("genre") or "",
                texto_libre,
            )
        if data.get("voice_profile_lines"):
            merged["voice_profile"] = {
                **merged.get("voice_profile", {}),
                "lines": data["voice_profile_lines"],
            }
            # The Director may propose voice lines only until the user writes
            # the fixed singing voice; from then on that text is untouchable.
            if not (merged.get("singing_voice") or {}).get("text"):
                merged["singing_voice"] = {
                    **merged.get("singing_voice", {}),
                    "text": "\n".join(data["voice_profile_lines"]),
                }
        # Y la red contra el eco: secciones llenas pero identicas a las
        # que ya habia no son una reescritura, son la transcripcion que
        # dejo tres trabajos «LISTO» con la Biblia intacta. Fallo visible,
        # con la Biblia —esta vez de verdad— intacta.
        if _biblia_sin_cambios(previa, merged):
            raise ProviderError(
                "El Director devolvió la Biblia sin cambios: vuelve a intentarlo."
            )
        merged["status"] = CanonStatus.DRAFT.value
        merged["version"] = int(merged.get("version", 1)) + 1
        from ..domain.schemas import ArtistBible

        save_bible(studio.db, universe_id, ArtistBible.model_validate(merged))
        # La identidad que el Director reescribe toma enseguida los datos
        # que viven en otras fichas (la edad, de los rasgos): reescribirla
        # no puede resucitar un dato viejo.
        sync_bible_identity(studio.db, universe_id)
        return {"entity": "artist_bible", "id": "current"}

    if task in {"music_concept", "lyrics_analysis"}:
        # El mismo exito vacio: sin ninguna de las claves que esta rama
        # lee, el concepto se reconstruiria con huecos encima del que ya
        # habia y naceria «en uso». Si el Director no devolvio concepto,
        # el trabajo fallo.
        _exigir_que_devolvio_algo(
            data,
            (
                "title", "concept", "summary", "hook", "hooks", "genre",
                "proposed_genre", "bpm", "proposed_bpm", "mood", "structure",
                "production", "proposed_production", "interpretation",
                "proposed_interpretation", "visual_concept", "music_prompt",
            ),
            "El Director no devolvió el concepto de la canción: vuelve a intentarlo.",
        )
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
            # El concepto recien escrito es el que vale: nace en uso.
            "status": CanonStatus.APPROVED.value,
        }
        repo.update(
            target_id,
            {
                "title": concept["title"] or song.get("title", ""),
                "concept": concept,
                "music_prompt": _impose_music_blocks(
                    studio, universe_id, song, data.get("music_prompt", "")
                ),
                "genre": concept["genre"],
                "bpm": concept["bpm"],
                "mood": concept["mood"],
                "structure": concept["structure"] or song.get("structure", []),
                "status": CanonStatus.DRAFT.value,
            },
        )
        return {"entity": "song", "id": target_id}

    if task == "lyrics":
        # Sin letra no hay nada que aplicar: escribir "" encima de la
        # letra que hubiera y marcarla «en uso» seria un exito vacio y
        # encima destructivo.
        if not str(data.get("lyrics") or "").strip():
            raise ProviderError("El Director no devolvió la letra: vuelve a intentarlo.")
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
                # La letra recien escrita es la que vale: nace en uso y
                # Lyria puede llamarse con ella sin aprobar nada.
                "lyrics_status": CanonStatus.APPROVED.value,
                "title": data.get("title") or song.get("title", ""),
            },
        )
        return {"entity": "song", "id": target_id}

    if task == "video_concept":
        # Sin titulo, concepto, historia ni notas no hay propuesta: la
        # rama escribiria huecos encima del proyecto y una historia vacia
        # «en uso». (video_type no cuenta: tiene valor por defecto.)
        _exigir_que_devolvio_algo(
            data,
            ("title", "concept", "story", "wardrobe_notes", "location_notes"),
            "El Director no devolvió el concepto del video: vuelve a intentarlo.",
        )
        repo = _repo(studio, universe_id, VIDEO_PROJECTS)
        repo.update(
            target_id,
            {
                "title": data.get("title", ""),
                "video_type": data.get("video_type", "narrative"),
                "concept": data.get("concept", ""),
                "story": {**(data.get("story") or {}), "status": CanonStatus.APPROVED.value},
                # Wardrobe and locations are text inside this proposal now,
                # in use together with the story. There are no wardrobe or
                # location sections any more.
                "wardrobe_notes": data.get("wardrobe_notes", ""),
                "location_notes": data.get("location_notes", ""),
                "status": CanonStatus.DRAFT.value,
            },
        )
        return {"entity": "video_project", "id": target_id}

    if task == "storyboard":
        return _apply_storyboard(studio, universe_id, target_id, data)

    if task == "character":
        # El mismo hueco: sin nombre, descripcion ni prompts, la rama
        # escribiria una ficha vacia encima de la que ya habia.
        _exigir_que_devolvio_algo(
            data,
            ("name", "apparent_age", "appearance", "personality", "master_prompts"),
            "El Director no devolvió el personaje: vuelve a intentarlo.",
        )
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
        # Y por encima de todo, lo que el usuario ya habia decidido. Al Director
        # se le pide en el prompt que lo respete, pero un prompt es una peticion:
        # esto es la garantia. El nombre que se escribio es el nombre, y el pelo
        # que se eligio es el pelo.
        anterior = repo.get(target_id) or {}
        for clave in ("name", "gender", "rasgos"):
            if anterior.get(clave):
                patch[clave] = anterior[clave]
        if repo.get(target_id) is None:
            repo.create(target_id, patch)
        else:
            repo.update(target_id, patch)
        return {"entity": "character", "id": target_id}

    return {"entity": None}


def _apply_storyboard(
    studio, universe_id: str, project_id: str, data: dict[str, Any]
) -> dict[str, Any]:
    # Sin escenas no hay storyboard que aplicar, y esta rama SUSTITUYE el
    # anterior entero: un resultado vacio borraria las escenas que hubiera
    # y dejaria el proyecto «en uso» sin una sola. Es el exito vacio mas
    # destructivo de todos: un fallo, con su motivo, antes de tocar nada.
    if not data.get("scenes"):
        raise ProviderError("El Director no devolvió el storyboard: vuelve a intentarlo.")
    project = _repo(studio, universe_id, VIDEO_PROJECTS).require(project_id)
    characters = {c["name"]: c["id"] for c in _repo(studio, universe_id, CHARACTERS).list()}
    # The only character a storyboard can name is the artist. Anyone else the
    # Director mentions stays out of the cast: one Universe, one artist.
    lead_id = (project.get("character_ids") or [None])[0]

    scenes_repo = _repo(studio, universe_id, SCENES)
    # Un storyboard nuevo SUSTITUYE al anterior entero, escenas viejas
    # incluidas: lo que esta actualmente es lo que vale, y dejar las escenas
    # de la version anterior conviviendo con las nuevas mezclaria dos
    # montajes distintos en el mismo proyecto.
    for old in scenes_repo.list(where={"project_id": project_id}):
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
                    if name in characters and characters[name] == lead_id
                ]
                or ([lead_id] if lead_id else []),
                "location_description": raw.get("location_description", ""),
                "wardrobe_description": raw.get("wardrobe_description", ""),
                "planos": raw.get("planos") or [],
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
                # El storyboard recien hecho es el que vale: nace en uso.
                "status": CanonStatus.APPROVED.value,
            },
        )
        created.append(scene)

    _repo(studio, universe_id, VIDEO_PROJECTS).update(
        project_id,
        {"storyboard_status": CanonStatus.APPROVED.value, "storyboard_notes": data.get("notes", "")},
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

    if purpose in {"scene", "character_master"}:
        # The artist's visual style is fixed and travels inside every image
        # prompt, master and shots alike. If a stored prompt already carries
        # it (the Bible summary feeds the Director), nothing is added twice.
        bloque = artist_domain.style_block(load_bible(studio.db, universe_id))
        if bloque and bloque not in prompt:
            prompt = f"{prompt}\n\n{bloque}"

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
                # La imagen recien generada es la de la escena: nace en uso
                # y es la que Veo recibe, sin aprobarla ni bloquearla a mano.
                "status": CanonStatus.APPROVED.value,
                "locked": True,
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
            target_id, {"image_id": image["id"], "image_status": CanonStatus.APPROVED.value}
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
                shot["status"] = CanonStatus.APPROVED.value
                # La ruta no cambia al regenerar: la version si, y es la
                # marca que la vista pone en la URL para no ensenar la
                # imagen anterior desde la cache del telefono.
                shot["version"] = int(shot.get("version") or 0) + 1
                found = True
        if not found:
            shots.append(
                {
                    "key": shot_key,
                    "label": shot_key,
                    "storage_path": stored.path,
                    "status": CanonStatus.APPROVED.value,
                    "version": 1,
                }
            )
        # Regla del estudio, decidida por su dueno: lo que se genera queda
        # aprobado y en uso, sin pasos de revision ni de adopcion. La imagen
        # recien generada ES la toma: entra en las referencias del artista y
        # el Master queda aprobado con ella, sustituyendo a la anterior si
        # la habia (regenerar reemplaza; si no gusta, se regenera otra vez).
        # Es lo mismo que hacia aprobar el Master a mano, hecho en el acto.
        con_imagen = [s for s in shots if s.get("storage_path")]
        for shot in con_imagen:
            shot["status"] = CanonStatus.APPROVED.value
        service = approvals.ApprovalService(studio.db)
        service.approve(
            universe_id,
            CHARACTERS,
            target_id,
            note="Automatico: imagen generada, queda aprobada y en uso.",
            master_shots=shots,
            reference_image_paths=[s["storage_path"] for s in con_imagen],
            master_stale=False,
        )
        bible = load_bible(studio.db, universe_id)
        if bible.visual.master_stale:
            bible.visual.master_stale = False
            save_bible(studio.db, universe_id, bible)
        service.save_to_canon(
            universe_id,
            entity_type="character",
            entity_id=target_id,
            label=character.get("name", ""),
            storage_path=con_imagen[0]["storage_path"],
        )
        return stored, {"id": None}

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

    # Lyria se llama cuando la cancion tiene letra: esa es la condicion.
    approvals.assert_lyrics_ready(studio.db, universe_id, song_id)

    bible = load_bible(studio.db, universe_id)
    voice_lines = song.get("voice_profile", {}).get("lines") or bible.voice_profile.lines
    prompt = _compose_music_prompt(song, voice_lines, payload, bible)
    duration = int(payload.get("duration_seconds") or song.get("requested_duration_seconds") or 150)

    result = lyria.generate_song(
        studio.vertex,
        model=job["model"],
        gemini_api_key=studio.gemini_api_key(),
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
    cost = estimate_song(studio.registry, attempts=1, model_id=result.model)
    # La version recien generada ES la cancion: queda como master vigente en
    # el acto y las anteriores pasan a archivo. Regenerar sustituye; nadie
    # aprueba nada para que el videoclip o la descarga la puedan usar.
    versions = list(song.get("versions") or [])
    for anterior in versions:
        anterior["status"] = CanonStatus.ARCHIVED.value
    versions.append(
        {
            "version": version,
            "job_id": job["id"],
            "audio_path": stored.path,
            "duration_seconds": duration,
            "model": result.model,
            "parameters": result.parameters,
            "cost_usd": round(cost.amount_usd, 4),
            "status": CanonStatus.APPROVED.value,
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
            "status": CanonStatus.APPROVED.value,
            "approved_version": version,
            "approved_master_path": stored.path,
        },
    )
    return Outcome(
        result={
            "song_id": song_id,
            "version": version,
            "storage_path": stored.path,
            "duration_seconds": duration,
            "model": result.model,
        },
        cost=cost,
    )


def _fixed_music_texts(studio, universe_id: str, song: dict[str, Any]) -> dict[str, str]:
    """The texts that are FIXED for this artist and this song.

    The singing voice, the genre combination and the inspiration summaries.
    They are imposed on whatever the Director or a hand-edited prompt says:
    a prompt is a request, this is the guarantee.
    """
    bible = load_bible(studio.db, universe_id)
    voz = (bible.singing_voice.text or "").strip() or bible.voice_profile.as_prompt()
    generos = artist_domain.genres_text(
        song.get("genres") or bible.music_genres,
        song.get("genre_free") or bible.music_genre_free,
    )
    inspiraciones: list[str] = []
    for inspiracion in bible.inspirations:
        # Tampoco por esta puerta entra un resumen fabricado: solo los
        # resumenes que de verdad vienen de su cancion alimentan la letra
        # y el encargo a Lyria.
        if inspiracion.summary_text and inspiracion_utilizable(inspiracion):
            inspiraciones.append(inspiracion.summary_text)
    if (song.get("inspiration_summary") or "").strip():
        inspiraciones.append(song["inspiration_summary"].strip())
    return {
        "voz": voz,
        "generos": generos,
        "inspiracion": "\n\n".join(inspiraciones),
    }


def _impose_music_blocks(studio, universe_id: str, song: dict[str, Any], base: str) -> str:
    """Append the fixed blocks to a Director-written music prompt, verbatim,
    when they are not already in it word for word."""
    fijos = _fixed_music_texts(studio, universe_id, song)
    partes = [base.strip()] if (base or "").strip() else []
    if fijos["generos"] and fijos["generos"] not in base:
        partes.append(f"Genres: {fijos['generos']}")
    if fijos["voz"] and fijos["voz"] not in base:
        partes.append("Lead vocal (fixed description, keep verbatim):\n" + fijos["voz"])
    if fijos["inspiracion"] and fijos["inspiracion"] not in base:
        partes.append(
            "Reference inspiration (style only; original material, never copy "
            f"lyrics or melody):\n{fijos['inspiracion']}"
        )
    return "\n\n".join(partes).strip()


def _compose_music_prompt(
    song: dict[str, Any], voice_lines: list[str], payload, bible=None
) -> str:
    """US English, fixed singing voice verbatim (PRD 10, 14)."""
    if payload.get("prompt"):
        base = payload["prompt"]
    else:
        base = song.get("music_prompt") or ""
    concept = song.get("concept") or {}
    parts = [base.strip()] if base.strip() else []
    descriptors = [
        f"Genre: {song.get('genre') or concept.get('genre', '')}",
        f"Mood: {song.get('mood') or concept.get('mood', '')}",
        f"Production: {concept.get('production', '')}",
        f"Structure: {', '.join(song.get('structure') or concept.get('structure') or [])}",
    ]
    parts.extend(d for d in descriptors if not d.endswith(": "))
    # El tempo REAL: el del genero principal que el dueno escogio, de
    # la tabla de tempo natural. El BPM que el Director inventaba en
    # el concepto ya NO viaja: era un numero sin relacion con el
    # genero ni con el fraseo, y la cancion salia a la velocidad que
    # saliera. Sin genero de la tabla (solo texto libre), no se manda
    # ningun numero: manda la orden de ritmo del proveedor.
    linea_tempo = tempo_domain.linea_tempo(
        song.get("genres") or (bible.music_genres if bible is not None else None)
    )
    if linea_tempo:
        parts.append(linea_tempo)
    # The artist's genre combination, fixed on the Bible and adjustable per
    # song, goes in as its own line so Lyria hears the mix, not one genre.
    generos = artist_domain.genres_text(
        song.get("genres"),
        song.get("genre_free")
        or (bible.music_genre_free if bible is not None else ""),
    )
    if generos and generos not in "\n".join(parts):
        parts.append(f"Genres: {generos}")
    # The singing voice: the fixed text of the Bible, word for word. The
    # per-song lines snapshot only survives as a fallback for songs created
    # before the fixed text existed.
    voz = ""
    if bible is not None:
        voz = (bible.singing_voice.text or "").strip()
    if not voz and voice_lines:
        voz = "\n".join(voice_lines)
    if voz and voz not in "\n".join(parts):
        parts.append("Lead vocal:\n" + voz)
    inspiracion = (song.get("inspiration_summary") or "").strip()
    if inspiracion and inspiracion not in "\n".join(parts):
        parts.append(
            "Reference inspiration (style only; original material):\n" + inspiracion
        )
    return "\n".join(parts).strip()


# --- video -----------------------------------------------------------------


def handle_video(studio, universe_id: str, job: dict[str, Any]) -> Outcome:
    payload = _payload(job)
    scene_id = job.get("target_id") or ""
    scenes = _repo(studio, universe_id, SCENES)
    scene = scenes.require(scene_id)

    approvals.assert_scene_not_reused(scene)
    approvals.assert_scene_image_ready(studio.db, universe_id, scene_id)

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
    # Veo prompts carry the artist's fixed visual style too, so the look of a
    # clip matches the look of its first frame.
    bloque = artist_domain.style_block(load_bible(studio.db, universe_id))
    if bloque and bloque not in prompt:
        prompt = f"{prompt}\n\n{bloque}"

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
            # El clip recien generado es el de la escena: nace en uso y es
            # el que monta el ensamblaje, sin aprobarlo a mano.
            "status": CanonStatus.APPROVED.value,
            "locked": True,
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
            "clip_status": CanonStatus.APPROVED.value,
            "cost_usd": round(float(scene.get("cost_usd", 0.0)) + cost.amount_usd, 4),
        },
    )
    return Outcome(
        result={
            "scene_id": scene_id,
            "clip_id": clip["id"],
            "storage_path": stored.path,
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
        f"Location: {scene.get('location_description','')}"
        if scene.get("location_description")
        else "",
        f"Wardrobe: {scene.get('wardrobe_description','')}"
        if scene.get("wardrobe_description")
        else "",
        f"Camera: {scene.get('camera','')}" if scene.get("camera") else "",
        f"Lighting: {scene.get('lighting','')}" if scene.get("lighting") else "",
        f"Environment: {scene.get('environment','')}" if scene.get("environment") else "",
        f"Emotion: {scene.get('emotion','')}" if scene.get("emotion") else "",
    ]
    planos = scene.get("planos") or []
    if planos:
        bits.append(
            "Cut inside this clip, in this order: "
            + " THEN CUT TO ".join(str(p) for p in planos)
        )
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


# --- creation: the analyses the create request used to wait for -----------


def _enlace_resuelto(bible, enlace: str) -> bool:
    """El enlace ya tiene su sitio en la Biblia: resumen o fallo visible.

    Se casa por el video, no por la cadena: el mismo video pegado con
    otra forma de enlace (youtu.be, music.youtube.com…) es el mismo
    enlace, y volver a analizarlo duplicaria su resumen.
    """
    video_id = inspiration_service.youtube_video_id(enlace)
    guardados = [i.url for i in bible.inspirations] + list(bible.inspirations_failed)
    for guardado in guardados:
        if guardado == enlace:
            return True
        if video_id and inspiration_service.youtube_video_id(guardado) == video_id:
            return True
    return False


def handle_creation(studio, universe_id: str, job: dict[str, Any]) -> Outcome:
    """Termina de crear al artista: analiza sus enlaces y encarga su diseno.

    Crear el artista analizaba los enlaces dentro de la peticion de
    creacion, en serie, y un analisis tarda mas que los 45 segundos que
    la pantalla espera: la creacion SI se completaba en el servidor,
    pero la pantalla contestaba «el estudio tardo demasiado», y el
    reintento creaba un artista duplicado. Ahora la creacion contesta
    enseguida y este trabajo hace lo lento, en la cola:

    1. analiza los enlaces que la creacion dejo como pendientes, en el
       mismo orden y con la misma semantica visible de siempre: cada
       resumen se guarda en la Biblia, y cada fallo en su lista visible
       de fallidos — un enlace malo no tumba ni la creacion ni el resto;
    2. limpia la marca de pendientes (quedan solo los que no se
       llegaron a procesar, si alguna vez los hay);
    3. SOLO ENTONCES encarga el diseno del personaje, con los resumenes
       ya guardados: el orden analisis→Biblia→diseno es el de siempre,
       y cualquier llamada posterior del Director lee los resumenes
       que de verdad entraron.

    Es reintentable sin duplicar: un enlace ya resuelto (resumen o
    fallo) no se vuelve a analizar, y si el encargo del diseno falla,
    el trabajo falla A LA VISTA y su reintento solo repite ese encargo.
    """
    payload = _payload(job)
    enlaces = [e for e in (payload.get("inspiration_urls") or []) if e]

    guardados = 0
    fallidos: list[str] = []
    for enlace in enlaces:
        if _enlace_resuelto(load_bible(studio.db, universe_id), enlace):
            continue
        try:
            inspiracion = inspiration_service.analyse_youtube(studio, enlace)
        except Exception:
            # La misma semantica de la creacion de siempre: el enlace
            # queda en la lista visible de fallidos, para volver a
            # pegarlo desde la ficha. Ni tumba el trabajo ni desaparece.
            logger.exception("no se pudo analizar la inspiracion %s", enlace)
            bible = load_bible(studio.db, universe_id)
            if not _enlace_resuelto(bible, enlace):
                bible.inspirations_failed.append(enlace)
                save_bible(studio.db, universe_id, bible)
            fallidos.append(enlace)
            continue
        bible = load_bible(studio.db, universe_id)
        if not _enlace_resuelto(bible, enlace):
            bible.inspirations.append(inspiracion)
            save_bible(studio.db, universe_id, bible)
        guardados += 1

    bible = load_bible(studio.db, universe_id)
    restantes = [e for e in bible.inspirations_pending if not _enlace_resuelto(bible, e)]
    if restantes != bible.inspirations_pending:
        bible.inspirations_pending = restantes
        save_bible(studio.db, universe_id, bible)

    # Y se pone a trabajar solo, como hacia la creacion: sin el diseno no
    # hay prompts, y sin prompts ningun boton de «Generar» funciona. Aqui
    # el encargo NO se traga su fallo: si no sale, el trabajo entero ha
    # fallado y se ve, y reintentarlo es seguro (los analisis ya
    # guardados no se repiten).
    encargo = studio.orchestrator.submit(
        GenerationRequest(
            universe_id=universe_id,
            kind="text",
            target_type="character",
            target_id=str(payload.get("character_id") or ""),
            role=CreativeRole.CASTING_DIRECTOR,
            payload={
                "task": "character",
                "brief": str(payload.get("brief") or ""),
                "locked": payload.get("locked") or {},
            },
        )
    )
    return Outcome(
        result={
            "inspirations": guardados,
            "inspirations_failed": fallidos,
            "job": encargo,
        },
        cost=None,
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
    )
    # El Editor decide los cortes, y esa propuesta la escribe un modelo de texto.
    coste = result.pop("editor_cost", None)
    return Outcome(result=result, cost=coste)


HANDLERS: dict[str, Callable[..., Outcome]] = {
    "text": handle_text,
    "image": handle_image,
    "music": handle_music,
    "video": handle_video,
    "assembly": handle_assembly,
    "creation": handle_creation,
}
