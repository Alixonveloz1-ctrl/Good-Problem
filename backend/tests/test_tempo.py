"""El tempo real y la medida de la letra (2026-11-07).

El dueno reporto que la cancion salia «a mil por hora» escogiera el
genero que escogiera, y acepto el arreglo con su matiz: si el genero
amerita cantar rapido, que cante rapido — el problema era que no
habia un control real. Lo que estas pruebas fijan:

- la tabla de tempo cubre TODOS los generos escogibles de la app;
- en una mezcla manda el genero principal (el primero que escogio);
- el presupuesto de palabras sale de la duracion y del paso del
  genero (una balada cabe menos palabras que un rap en los mismos
  segundos — es la cuenta de por que la letra larga salia corriendo);
- el encargo a Lyria lleva el tempo del genero y ya NO lleva el BPM
  que el Director inventaba en el concepto;
- el texto que Lyria recibe lleva la orden de ritmo: tempo firme,
  prohibido acelerar para que quepa la letra;
- la instruccion de escribir la letra lleva su medida en palabras, y
  contar palabras no cuenta las marcas de seccion.
"""

from __future__ import annotations

from app.domain import artist as artist_domain
from app.domain import tempo as tempo_domain
from app.orchestrator import director, handlers


def test_la_tabla_cubre_todos_los_generos_escogibles():
    assert set(tempo_domain.GENERO_TEMPO) == set(artist_domain.MUSIC_GENRE_KEYS)


def test_en_la_mezcla_manda_el_genero_principal():
    tempo = tempo_domain.tempo_de_la_cancion(["regueton", "trap"])
    assert tempo is not None
    assert tempo.bpm == 88
    linea = tempo_domain.linea_tempo(["regueton", "trap"])
    assert "Tempo: 88 BPM" in linea
    # Sin genero de la tabla no se inventa ningun numero.
    assert tempo_domain.tempo_de_la_cancion([]) is None
    assert tempo_domain.linea_tempo(["genero inventado"]) == ""


def test_el_presupuesto_sale_de_la_duracion_y_del_paso():
    regueton = tempo_domain.GENERO_TEMPO["regueton"]  # 140 palabras/min
    balada = tempo_domain.GENERO_TEMPO["balada"]  # 115 palabras/min
    rap = tempo_domain.GENERO_TEMPO["rap"]  # 185 palabras/min
    assert tempo_domain.presupuesto_palabras(180, regueton) == 420
    assert tempo_domain.presupuesto_palabras(180, balada) < 420
    assert tempo_domain.presupuesto_palabras(180, rap) > 420
    # La letra de unas 650 palabras no cabe en 180 segundos a paso
    # natural: esa era la cuenta del problema.
    assert tempo_domain.presupuesto_palabras(180, regueton) < 650


def test_contar_palabras_sin_las_marcas_de_seccion():
    letra = "[Verso 1]\nuna dos tres\n\n[Coro]\ncuatro cinco\n"
    assert tempo_domain.contar_palabras(letra) == 5


def test_el_encargo_lleva_el_tempo_del_genero_y_no_el_inventado():
    cancion = {
        "music_prompt": "trap oscuro y callejero",
        "genre": "Trap",
        "bpm": 999,
        "genres": ["regueton"],
        "concept": {"genre": "Trap", "bpm": 888, "mood": "oscuro"},
    }
    prompt = handlers._compose_music_prompt(cancion, [], {}, bible=None)
    assert "Tempo: 88 BPM" in prompt
    assert "999" not in prompt
    assert "888" not in prompt


def test_la_instruccion_de_la_letra_lleva_su_medida():
    prompt = director.build_prompt(
        "lyrics",
        {
            "concept": {"title": "Neon"},
            "duration_seconds": 180,
            "genre_keys": ["regueton"],
            "genres_text": "Reguetón",
        },
    )
    assert "THE MEASURE OF THIS LYRIC" in prompt
    assert "420 words" in prompt
    assert "sung rushed" in prompt


def test_el_texto_de_lyria_lleva_la_orden_de_ritmo(client, studio):
    creado = client.post("/api/universes", json={"name": "Nova"}).json()
    studio.jobs.wait_for_idle(20)
    uid = creado["id"]
    cancion = client.post(
        f"/api/universes/{uid}/songs", json={"title": "Neon"}
    ).json()
    sid = cancion["id"]
    client.put(
        f"/api/universes/{uid}/songs/{sid}/lyrics",
        json={"lyrics": "una letra de prueba, con su rima puesta", "author": "user"},
    )
    respuesta = client.post(f"/api/universes/{uid}/songs/{sid}/generate", json={})
    assert respuesta.status_code == 200, respuesta.text
    studio.jobs.wait_for_idle(20)

    llamada = [c for c in studio.calls.all() if c.method == "interactions"][-1]
    texto = llamada.payload["input"][0]["text"]
    assert "PACING:" in texto
    assert "Never speed up" in texto
    assert "the tempo never moves" in texto
