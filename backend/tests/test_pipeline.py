"""Acceptance walk-through (PRD 53), end to end, in dry run.

Every step here maps to a numbered step of the acceptance test. If a step needed
a computer, it would not be an HTTP call.
"""

from __future__ import annotations

from app.domain.enums import CanonStatus, JobState


def _run(client, studio, method: str, url: str, **kwargs):
    response = getattr(client, method)(url, **kwargs)
    assert response.status_code == 200, f"{url} -> {response.status_code} {response.text}"
    body = response.json()
    if isinstance(body, dict) and body.get("state") in {JobState.QUEUED.value,
                                                        JobState.PROCESSING.value}:
        studio.jobs.wait_for_idle(30)
        job = client.get(
            f"/api/universes/{body['universe_id']}/jobs/{body['id']}"
        ).json()
        assert job["state"] == JobState.READY.value, job.get("error")
        return job
    return body


def test_full_production_from_a_phone(client, studio):
    # 1-2. Crear Universe y artista.
    universe = _run(client, studio, "post", "/api/universes", json={"name": "Nova"})
    uid = universe["id"]

    # 3. Crear Artist Bible.
    job = _run(
        client, studio, "post", f"/api/universes/{uid}/bible/generate",
        json={"brief": "Cantante de synth pop nocturno"},
    )
    assert job["result"]["applied"]["entity"] == "artist_bible"
    # La voz cantada fija del artista: un solo texto que viajara palabra por
    # palabra en cada encargo a Lyria.
    _run(client, studio, "put", f"/api/universes/{uid}/bible/singing-voice",
         json={"sex": "Mujer", "apparent_age": "25", "pitch": "Media",
               "timbre": "Calida, con aire", "language_accent": "Espanol neutro",
               "singing_style": "Intima"})
    _run(client, studio, "post", f"/api/universes/{uid}/bible/approve")

    # 4-5. Character Master y aprobacion. El artista ya existe: nacio con el
    # universo, y es el unico personaje posible.
    character = client.get(f"/api/universes/{uid}/characters").json()[0]
    assert character["id"] == universe["lead_character_id"]
    _run(client, studio, "post",
         f"/api/universes/{uid}/characters/{character['id']}/master/portrait",
         json={"prompt": "portrait of Nova"})
    approved = _run(client, studio, "post",
                    f"/api/universes/{uid}/characters/{character['id']}/approve")
    assert approved["status"] == CanonStatus.APPROVED.value
    assert approved["reference_image_paths"], "el master aprobado alimenta las referencias"

    # 8. Concepto musical.
    song = _run(client, studio, "post", f"/api/universes/{uid}/songs",
                json={"title": "Neon", "requested_duration_seconds": 150})
    sid = song["id"]
    _run(client, studio, "post", f"/api/universes/{uid}/songs/{sid}/concept",
         json={"brief": "Una noche que no termina"})

    # 10. Cambiar el genero que propuso el Director y ver que rehace la propuesta.
    rebuilt = _run(client, studio, "post", f"/api/universes/{uid}/songs/{sid}/concept",
                   json={"overrides": {"genre": "hip hop"}})
    prompt_sent = studio.calls.all()[-1].payload["contents"][0]["parts"][0]["text"]
    assert "USER OVERRIDES" in prompt_sent and "hip hop" in prompt_sent
    assert rebuilt["state"] == JobState.READY.value

    _run(client, studio, "post", f"/api/universes/{uid}/songs/{sid}/concept/approve")

    # 9. Letra propia.
    _run(client, studio, "put", f"/api/universes/{uid}/songs/{sid}/lyrics",
         json={"lyrics": "[Verse 1]\nLuces de neon", "author": "user"})
    _run(client, studio, "post", f"/api/universes/{uid}/songs/{sid}/lyrics/analyze", json={})

    # 11. Aprobar letra.
    _run(client, studio, "post", f"/api/universes/{uid}/songs/{sid}/lyrics/approve")

    # 12. Generar cancion con Lyria 3 Pro a la duracion pedida.
    music_job = _run(client, studio, "post", f"/api/universes/{uid}/songs/{sid}/generate",
                     json={"duration_seconds": 150})
    assert music_job["model"] == "lyria-3-pro-preview"
    assert music_job["result"]["duration_seconds"] == 150

    # 15. Aprobar cancion.
    approved_song = _run(client, studio, "post",
                         f"/api/universes/{uid}/songs/{sid}/versions/1/approve")
    assert approved_song["approved_master_path"]

    # 16. Solicitar propuesta de videoclip.
    project = _run(client, studio, "post", f"/api/universes/{uid}/video-projects",
                   json={"song_id": sid, "video_type": "narrative"})
    pid = project["id"]
    _run(client, studio, "post", f"/api/universes/{uid}/video-projects/{pid}/concept", json={})

    # 17. Aprobar historia.
    studio.db.update(
        f"universes/{uid}/video_projects/{pid}",
        {"story": {"premise": "Una noche", "status": CanonStatus.DRAFT.value}},
    )
    _run(client, studio, "post", f"/api/universes/{uid}/video-projects/{pid}/story/approve")

    # 18-19. No hay paso de reparto: el proyecto nace con el artista dentro,
    # y el vestuario y los sitios van escritos en las escenas del storyboard.
    assert project["character_ids"] == [character["id"]]

    # 20. Storyboard con tomas reutilizadas.
    _seed_storyboard(studio, uid, pid)
    _run(client, studio, "post", f"/api/universes/{uid}/video-projects/{pid}/storyboard/approve")

    scenes = client.get(f"/api/universes/{uid}/video-projects/{pid}").json()["scenes"]
    assert len(scenes) == 3
    generated = [s for s in scenes if not s["reuses_scene_id"]]
    assert len(generated) == 2, "una toma se reutiliza"

    # 21-24. Imagenes de escena, con eleccion de modelo, y aprobacion.
    for index, scene in enumerate(generated):
        model = "gemini-3.1-flash-image" if index == 0 else "gemini-3-pro-image"
        image_job = _run(client, studio, "post",
                         f"/api/universes/{uid}/scenes/{scene['id']}/image",
                         json={"model": model, "variant": "1K"})
        assert image_job["model"] == model  # 22. cambiar el modelo en una generacion concreta
        _run(client, studio, "post", f"/api/universes/{uid}/scenes/{scene['id']}/image/approve")

    # 25-29. Clips con Veo, cambio de modelo y aprobacion.
    for index, scene in enumerate(generated):
        model = "veo-3.1-fast-generate-001" if index == 0 else "veo-3.1-lite-generate-001"
        clip_job = _run(client, studio, "post",
                        f"/api/universes/{uid}/scenes/{scene['id']}/clip",
                        json={"model": model, "variant": "1080p"})
        assert clip_job["model"] == model
        assert clip_job["result"]["generate_audio"] is False
        _run(client, studio, "post", f"/api/universes/{uid}/scenes/{scene['id']}/clip/approve")

    # 27. Comprobar en los logs que ninguna llamada a Veo pidio audio.
    diagnostics = client.get("/api/diagnostics/vertex-calls?prefix=veo").json()
    assert diagnostics["count"] >= 2
    assert diagnostics["calls_requesting_audio"] == 0
    for call in diagnostics["calls"]:
        if call["method"] == "predictLongRunning":
            assert call["payload"]["parameters"]["generateAudio"] is False

    # 30-32. Ensamblaje y formatos.
    assembly = _run(client, studio, "post",
                    f"/api/universes/{uid}/video-projects/{pid}/assemble",
                    json={"formats": ["16:9", "9:16"]})
    assert assembly["result"]["clips"] == 3
    assert assembly["result"]["reused"] == 1

    # 33. Sin MP4 renderizado no hay proyecto que aprobar: en seco el montaje
    # solo produce el plan (EDL), y un plan no es un videoclip terminado.
    sin_render = client.post(f"/api/universes/{uid}/video-projects/{pid}/approve")
    assert sin_render.status_code == 409
    assert "MP4" in sin_render.json()["error"]["message"]

    # 35. El estudio no lleva cuentas: el gasto se mira en Google Cloud. Lo que
    # si queda es lo que costo cada pieza, como parte de su procedencia (PRD 46).
    assert client.get(f"/api/universes/{uid}/spend").status_code != 200
    jobs = client.get(f"/api/universes/{uid}/jobs?limit=100").json()
    billed = [j for j in jobs if j["actual_cost_usd"] > 0]
    assert billed, "cada generacion deja constancia de lo que costo"
    for job in billed:
        assert job["estimated_cost_usd"] >= 0

    # 36-37. Exportar y descargar.
    export = _run(client, studio, "post", f"/api/universes/{uid}/exports/songs/{sid}")
    names = {f["name"] for f in export["files"]}
    assert "metadata.json" in names and "song_info.txt" in names
    assert any(f["folder"] == "AUDIO" for f in export["files"])
    assert export["archive_url"], "el paquete se descarga como un solo archivo desde el iPhone"


def _seed_storyboard(studio, uid, pid):
    """The Director's dry run cannot invent scenes, so the storyboard is written
    directly here in the shape its handler produces."""
    from app.orchestrator.handlers import _apply_storyboard

    _apply_storyboard(
        studio,
        uid,
        pid,
        {
            "notes": "El estribillo repite el plano 0.",
            "scenes": [
                {
                    "index": 0, "action": "Nova mira la ciudad", "camera": "wide",
                    "character_names": ["Nova"],
                    "location_description": "Azotea de noche, luces de la ciudad",
                    "wardrobe_description": "Abrigo negro de firma",
                    "planos": ["Plano general: Nova entra cantando",
                               "Primer plano a los 4 segundos"],
                    "image_prompt": "Nova on a rooftop at night",
                    "video_prompt": "slow push in", "reuses_scene_index": -1,
                },
                {
                    "index": 1, "action": "Primer plano", "camera": "close up",
                    "character_names": ["Nova"],
                    "location_description": "La misma azotea",
                    "wardrobe_description": "Abrigo negro de firma",
                    "planos": ["Primer plano cantando"],
                    "image_prompt": "close up of Nova", "video_prompt": "handheld",
                    "reuses_scene_index": -1,
                },
                {
                    "index": 2, "action": "Repite el plano del estribillo", "camera": "wide",
                    "character_names": ["Nova"],
                    "location_description": "Azotea de noche",
                    "wardrobe_description": "Abrigo negro de firma",
                    "planos": ["Plano general del estribillo"],
                    "image_prompt": "", "video_prompt": "", "reuses_scene_index": 0,
                    "reuse_note": "Mismo encuadre que la escena 0",
                },
            ],
        },
    )
