"""Lo que un paso necesita del anterior es que EXISTA, no que este aprobado.

Regla del estudio, corregida por su dueno: no hay aprobaciones. Lo generado
nace en uso y ningun estado bloquea el paso siguiente. Las condiciones que
quedan son de existencia —la cancion tiene audio, la cancion tiene letra, la
escena tiene imagen— y estas pruebas las fijan.
"""

from __future__ import annotations

import pytest

from app.assembly import ffmpeg_cmds as cmds
from app.assembly.engine import build_edl
from app.domain.enums import CanonStatus
from app.errors import ApprovalRequired, Conflict


def _song(client, uid, *, with_lyrics: bool):
    song = client.post(f"/api/universes/{uid}/songs", json={"title": "Neon"}).json()
    if with_lyrics:
        client.put(
            f"/api/universes/{uid}/songs/{song['id']}/lyrics",
            json={"lyrics": "[Verse]\nx", "author": "user"},
        )
    return song


def test_a_song_without_audio_does_not_trigger_a_video(client, universe):
    """Sin audio generado no hay nada sobre lo que montar el videoclip."""
    song = _song(client, universe, with_lyrics=True)
    response = client.post(
        f"/api/universes/{universe}/video-projects", json={"song_id": song["id"]}
    )
    assert response.status_code == 409
    assert "audio" in response.json()["error"]["message"]


def test_a_generated_song_triggers_its_video_without_approving_anything(
    client, studio, universe
):
    """La cancion recien generada ya es la vigente: su videoclip arranca sin
    aprobar la letra, sin aprobar la version y sin aprobar la cancion. Y el
    viejo gesto de rechazar ya no bloquea nada."""
    song = _song(client, universe, with_lyrics=True)
    client.post(f"/api/universes/{universe}/songs/{song['id']}/generate", json={})
    studio.jobs.wait_for_idle(30)
    generada = client.get(f"/api/universes/{universe}/songs/{song['id']}").json()
    assert generada["approved_master_path"], "la version generada no quedo como master"

    client.post(f"/api/universes/{universe}/songs/{song['id']}/reject")
    response = client.post(
        f"/api/universes/{universe}/video-projects", json={"song_id": song["id"]}
    )
    assert response.status_code == 200, response.text


def test_lyria_is_not_called_before_there_are_lyrics(client, universe):
    song = _song(client, universe, with_lyrics=False)
    response = client.post(f"/api/universes/{universe}/songs/{song['id']}/generate", json={})
    assert response.status_code == 409
    assert "letra" in response.json()["error"]["message"]


def test_images_do_not_wait_for_any_storyboard_approval(client, studio, universe):
    """La escena existe porque hay storyboard: eso basta para su imagen."""
    scene = _scene_without_storyboard(studio, universe)
    response = client.post(
        f"/api/universes/{universe}/scenes/{scene['id']}/image", json={"prompt": "x"}
    )
    assert response.status_code == 200, response.text


def test_veo_waits_for_the_reference_image(client, studio, universe):
    scene = _scene_without_storyboard(studio, universe)
    response = client.post(f"/api/universes/{universe}/scenes/{scene['id']}/clip", json={})
    assert response.status_code == 409
    assert "imagen de referencia" in response.json()["error"]["message"]

    # Con la imagen generada —sin aprobarla ni bloquearla a mano— el clip
    # ya puede pedirse.
    studio.db.set(
        f"universes/{universe}/images/img_1",
        {"id": "img_1", "universe_id": universe, "storage_path": "x.png",
         "status": CanonStatus.DRAFT.value, "locked": False},
    )
    studio.db.update(
        f"universes/{universe}/scenes/{scene['id']}",
        {"image_id": "img_1", "image_status": CanonStatus.DRAFT.value},
    )
    response = client.post(f"/api/universes/{universe}/scenes/{scene['id']}/clip", json={})
    assert response.status_code == 200, response.text


def test_a_reused_take_is_not_generated_again(client, studio, universe):
    project_id = "vp_test"
    studio.db.set(
        f"universes/{universe}/video_projects/{project_id}",
        {"id": project_id, "universe_id": universe, "song_id": "song_x",
         "storyboard_status": CanonStatus.APPROVED.value},
    )
    source = _scene(studio, universe, project_id, 0)
    reuse = _scene(studio, universe, project_id, 1, reuses=source["id"])
    response = client.post(
        f"/api/universes/{universe}/scenes/{reuse['id']}/image", json={"prompt": "x"}
    )
    assert response.status_code == 409
    assert "reutilizar" in response.json()["error"]["message"]

    # ...unless the user forces it (PRD 23).
    client.post(
        f"/api/universes/{universe}/scenes/{reuse['id']}/reuse",
        json={"reuses_scene_id": source["id"], "force_generate": True},
    )
    forced = client.post(
        f"/api/universes/{universe}/scenes/{reuse['id']}/image", json={"prompt": "x"}
    )
    assert forced.status_code == 200


def test_assembly_waits_for_every_clip(studio, universe):
    project_id = "vp_a"
    studio.db.set(
        f"universes/{universe}/video_projects/{project_id}",
        {"id": project_id, "universe_id": universe, "song_id": "song_a"},
    )
    studio.db.set(
        f"universes/{universe}/songs/song_a",
        {"id": "song_a", "universe_id": universe, "status": CanonStatus.APPROVED.value,
         "approved_master_path": "universes/x/songs/song_a/version_1.wav"},
    )
    _scene(studio, universe, project_id, 0)
    with pytest.raises(ApprovalRequired):
        build_edl(studio, universe, project_id)


def test_the_edl_resolves_reused_takes_to_the_original_clip(studio, universe):
    project_id = "vp_b"
    studio.db.set(
        f"universes/{universe}/video_projects/{project_id}",
        {"id": project_id, "universe_id": universe, "song_id": "song_b"},
    )
    studio.db.set(
        f"universes/{universe}/songs/song_b",
        {"id": "song_b", "universe_id": universe, "status": CanonStatus.APPROVED.value,
         "approved_master_path": "universes/x/songs/song_b/version_1.wav"},
    )
    first = _scene(studio, universe, project_id, 0)
    _attach_clip(studio, universe, project_id, first, "clip_1")
    _scene(studio, universe, project_id, 1, reuses=first["id"])

    edl = build_edl(studio, universe, project_id)
    assert [e.clip_id for e in edl.entries] == ["clip_1", "clip_1"]
    assert [e.start_seconds for e in edl.entries] == [0.0, 8.0]
    assert edl.entries[1].reused_from == first["id"]
    assert edl.total_seconds == 16


def test_a_missing_reuse_target_is_an_error(studio, universe):
    project_id = "vp_c"
    studio.db.set(
        f"universes/{universe}/video_projects/{project_id}",
        {"id": project_id, "universe_id": universe, "song_id": "song_c"},
    )
    studio.db.set(
        f"universes/{universe}/songs/song_c",
        {"id": "song_c", "universe_id": universe, "status": CanonStatus.APPROVED.value,
         "approved_master_path": "p.wav"},
    )
    scene = _scene(studio, universe, project_id, 0, reuses="scene_ghost")
    studio.db.update(
        f"universes/{universe}/scenes/{scene['id']}",
        {"clip_status": CanonStatus.APPROVED.value},
    )
    with pytest.raises(Conflict):
        build_edl(studio, universe, project_id)


def test_vertical_is_a_reframe_of_the_master_not_a_generation():
    command = " ".join(cmds.reframe_vertical("master.mp4", "vertical.mp4"))
    assert "crop=ih*9/16:ih" in command and "scale=1080:1920" in command


def test_the_master_audio_is_muxed_not_generated():
    command = cmds.mux_audio("picture.mp4", "master.wav", "out.mp4", cmds.LANDSCAPE_1080)
    assert "-map" in command and "1:a:0" in command
    assert "-c:v" in command and command[command.index("-c:v") + 1] == "copy"


# --- helpers ---------------------------------------------------------------


def _scene(studio, universe, project_id, index, *, reuses=None):
    from app.ids import new_id

    scene_id = new_id("scene")
    return studio.db.set(
        f"universes/{universe}/scenes/{scene_id}",
        {
            "id": scene_id,
            "universe_id": universe,
            "project_id": project_id,
            "index": index,
            "duration_seconds": 8,
            "image_prompt": "x",
            "reuses_scene_id": reuses,
            "status": CanonStatus.DRAFT.value,
            "image_status": CanonStatus.DRAFT.value,
            "clip_status": CanonStatus.DRAFT.value,
        },
    )


def _scene_without_storyboard(studio, universe):
    project_id = "vp_draft"
    studio.db.set(
        f"universes/{universe}/video_projects/{project_id}",
        {"id": project_id, "universe_id": universe, "song_id": "song_x",
         "storyboard_status": CanonStatus.DRAFT.value},
    )
    return _scene(studio, universe, project_id, 0)


def _attach_clip(studio, universe, project_id, scene, clip_id):
    studio.db.set(
        f"universes/{universe}/videos/{clip_id}",
        {"id": clip_id, "universe_id": universe, "scene_id": scene["id"],
         "project_id": project_id, "storage_path": f"universes/{universe}/scenes/x/clip.mp4",
         "duration_seconds": 8, "status": CanonStatus.APPROVED.value},
    )
    studio.db.update(
        f"universes/{universe}/scenes/{scene['id']}",
        {"clip_id": clip_id, "clip_status": CanonStatus.APPROVED.value},
    )


def test_a_scene_cannot_reuse_itself(studio, universe):
    """The Director can emit a self reference; that would leave the scene with
    no source clip at assembly time."""
    from app.orchestrator.handlers import _apply_storyboard

    project_id = "vp_self"
    studio.db.set(
        f"universes/{universe}/video_projects/{project_id}",
        {"id": project_id, "universe_id": universe, "song_id": "song_s"},
    )
    _apply_storyboard(
        studio,
        universe,
        project_id,
        {"scenes": [{"index": 0, "action": "x", "reuses_scene_index": 0}]},
    )
    scenes = studio.db.list(f"universes/{universe}/scenes")
    assert scenes[0]["reuses_scene_id"] is None


def test_el_editor_decide_los_cortes_no_el_usuario(studio, universe):
    """PRD 43. El montaje lo decide el rol Editor a partir del storyboard y de
    la cancion; en la pantalla no hay ningun selector de transiciones."""
    from app.assembly.engine import assemble_project

    _preparar_proyecto(studio, universe, "vp_ed", clips=3)
    resultado = assemble_project(studio, universe, "vp_ed")

    assert "edit" in resultado
    assert resultado["edit"]["hard_cuts"] + resultado["edit"]["transitions"] == 2
    assert len(resultado["edit"]["joins"]) == 2
    assert resultado["picture_seconds"] <= resultado["total_seconds"]


def test_sin_plan_utilizable_se_monta_a_corte_seco(studio, universe):
    """Si el Editor no responde algo aprovechable, se monta a corte seco: es lo
    que hace la mayoria de los videoclips y nunca estropea un montaje."""
    from app.assembly.engine import build_edl, plan_edit
    from app.errors import ProviderError

    _preparar_proyecto(studio, universe, "vp_fallo", clips=3)
    edl = build_edl(studio, universe, "vp_fallo")

    def revienta(*_args, **_kwargs):
        raise ProviderError("Gemini no responde")

    import app.orchestrator.director as director

    original = director.run
    director.run = revienta
    try:
        uniones, notas, coste = plan_edit(studio, universe, "vp_fallo", edl)
    finally:
        director.run = original

    assert all(u.es_corte for u in uniones)
    assert coste is None
    assert "corte seco" in notas


def test_cortes_y_fundidos_conviven_en_una_sola_pasada():
    """Encadenar codificaciones degradaria la imagen una vez por cada corte, asi
    que el montaje entero va en un solo comando."""
    from app.assembly import ffmpeg_cmds as cmds

    uniones = [cmds.Union("cut"), cmds.Union("fadeblack", 0.6), cmds.Union("cut")]
    comando = cmds.build_timeline(
        ["a.mp4", "b.mp4", "c.mp4", "d.mp4"], [8, 8, 8, 8], uniones, "out.mp4",
        cmds.LANDSCAPE_1080,
    )
    assert comando.count("-filter_complex") == 1
    filtro = comando[comando.index("-filter_complex") + 1]
    assert filtro.count("concat=n=2") == 2
    assert "xfade=transition=fadeblack:duration=0.6:offset=15.400" in filtro
    assert cmds.timeline_duration([8, 8, 8, 8], uniones) == 31.4


def test_el_editor_no_puede_pedir_un_fundido_absurdo():
    from app.assembly import ffmpeg_cmds as cmds

    assert cmds.Union("fade", 9.0).normalizada().segundos == cmds.MAX_TRANSICION
    assert cmds.Union("fade", 0.01).normalizada().segundos == cmds.MIN_TRANSICION
    assert cmds.Union("remolino", 0.5).normalizada().es_corte, "un tipo inventado es corte seco"


def _preparar_proyecto(studio, universe, project_id, *, clips):
    studio.db.set(
        f"universes/{universe}/video_projects/{project_id}",
        {"id": project_id, "universe_id": universe, "song_id": f"song_{project_id}"},
    )
    studio.db.set(
        f"universes/{universe}/songs/song_{project_id}",
        {"id": f"song_{project_id}", "universe_id": universe,
         "status": CanonStatus.APPROVED.value, "approved_master_path": "p.wav"},
    )
    for indice in range(clips):
        escena = _scene(studio, universe, project_id, indice)
        _attach_clip(studio, universe, project_id, escena, f"clip_{project_id}_{indice}")
