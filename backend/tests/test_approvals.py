"""Nothing critical advances without a human (PRD 3, 36)."""

from __future__ import annotations

import pytest

from app.assembly import ffmpeg_cmds as cmds
from app.assembly.engine import build_edl
from app.domain.enums import CanonStatus
from app.errors import ApprovalRequired, Conflict


def _song(client, uid, *, approved: bool):
    song = client.post(f"/api/universes/{uid}/songs", json={"title": "Neon"}).json()
    if approved:
        client.put(
            f"/api/universes/{uid}/songs/{song['id']}/lyrics",
            json={"lyrics": "[Verse]\nx", "author": "user"},
        )
        client.post(f"/api/universes/{uid}/songs/{song['id']}/lyrics/approve")
    return song


def test_a_rejected_song_does_not_trigger_a_video(client, universe):
    song = _song(client, universe, approved=True)
    client.post(f"/api/universes/{universe}/songs/{song['id']}/reject")
    response = client.post(
        f"/api/universes/{universe}/video-projects", json={"song_id": song["id"]}
    )
    assert response.status_code == 409
    assert "aprobada" in response.json()["error"]["message"]


def test_lyria_is_not_called_before_the_lyrics_are_approved(client, universe):
    song = _song(client, universe, approved=False)
    response = client.post(f"/api/universes/{universe}/songs/{song['id']}/generate", json={})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "approval_required"


def test_images_wait_for_an_approved_storyboard(client, studio, universe):
    scene = _scene_without_storyboard(studio, universe)
    response = client.post(
        f"/api/universes/{universe}/scenes/{scene['id']}/image", json={"prompt": "x"}
    )
    assert response.status_code == 409


def test_veo_waits_for_a_locked_image(client, studio, universe):
    scene = _scene_without_storyboard(studio, universe)
    response = client.post(f"/api/universes/{universe}/scenes/{scene['id']}/clip", json={})
    assert response.status_code == 409
    assert "imagen de referencia" in response.json()["error"]["message"]


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
