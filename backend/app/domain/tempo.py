"""El tempo real: la velocidad natural de cada genero y la medida de la letra.

El problema que esto resuelve, dicho por el dueno el 2026-11-07: la
cancion salia «a mil por hora» escogiera el genero que escogiera. Por
dentro habia dos causas sumadas:

1. No existia un control de tempo de verdad. El unico numero que
   llegaba a Lyria era el BPM que el Director inventaba al crear el
   concepto — sin relacion con los generos que el dueno escoge ni con
   ninguna orden de fraseo —, asi que cambiar de genero no cambiaba
   la velocidad.
2. La letra nacia sin medida: la estructura completa de siempre
   (versos largos, tercer verso, coro repetido) suma unas 650
   palabras, que cantadas con calma piden 4-5 minutos, pero la
   duracion pedida era de 180 segundos. Lyria obedece la duracion, y
   la unica forma de meter todo era acelerar.

Aqui vive la respuesta a las dos:

- ``GENERO_TEMPO``: por cada genero escogible, su BPM representativo,
  su paso de canto (espacioso / medio / rapido) y su frase de entrega
  en ingles para el encargo. Si el genero ES rapido, rapido canta —
  pero firme y controlado, que es lo que el dueno pidio: «si el
  genero amerita que se cante rapido, no hay ningun problema; el
  problema es que no hay un control real».
- ``presupuesto_palabras``: cuantas palabras caben cantadas bien en
  los segundos pedidos al paso del genero. La letra y su revision
  reciben esa medida y escriben dentro de ella.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TempoGenero:
    bpm: int
    """El BPM representativo del genero, el que viaja en el encargo."""

    paso: str
    """Su clase de paso al cantar: «espacioso», «medio» o «rapido»."""

    palabras_por_minuto: int
    """Palabras que caben cantadas bien en un minuto a ese paso."""

    frase: str
    """La entrega natural del genero, en ingles, para el encargo."""


GENERO_TEMPO: dict[str, TempoGenero] = {
    "pop": TempoGenero(110, "medio", 150, "steady pop phrasing, clear and unhurried"),
    "rock": TempoGenero(128, "medio", 145, "driving rock phrasing with air between the lines"),
    "balada": TempoGenero(68, "espacioso", 115, "slow ballad phrasing: long pauses, every line breathed"),
    "bachata": TempoGenero(130, "medio", 140, "romantic bachata phrasing, smooth and unhurried"),
    "salsa": TempoGenero(175, "rapido", 175, "salsa phrasing: energetic and articulated, with call-and-response space"),
    "merengue": TempoGenero(150, "rapido", 170, "fast merengue phrasing, punchy and rhythmic"),
    "regueton": TempoGenero(88, "medio", 140, "reggaeton perreo groove: phrasing behind the beat, relaxed, never rushed"),
    "trap": TempoGenero(140, "espacioso", 125, "trap half-time feel: sparse, spacious phrasing with pauses between bars"),
    "rap": TempoGenero(92, "rapido", 185, "hip-hop flow at a steady head-nod tempo: the flow may be dense, the tempo never moves"),
    "rnb": TempoGenero(85, "espacioso", 125, "smooth R&B phrasing, melismatic and unhurried"),
    "corridos": TempoGenero(145, "medio", 145, "corrido storytelling phrasing with air between verses"),
    "regional": TempoGenero(95, "espacioso", 120, "ranchera phrasing: big held notes and long pauses"),
    "cumbia": TempoGenero(105, "medio", 140, "cumbia phrasing: laid-back and danceable, lines with air"),
    "vallenato": TempoGenero(128, "medio", 140, "vallenato storytelling phrasing, unhurried"),
    "electronica": TempoGenero(126, "medio", 135, "EDM phrasing: few, spaced vocal lines over the beat"),
    "synthwave": TempoGenero(105, "medio", 135, "synthwave phrasing, cool and spaced"),
    "jazz": TempoGenero(110, "espacioso", 125, "jazz phrasing behind the beat, with lots of air"),
    "blues": TempoGenero(80, "espacioso", 120, "blues phrasing: slow, dragged, long pauses"),
    "country": TempoGenero(105, "medio", 145, "country storytelling phrasing, clear and unhurried"),
    "metal": TempoGenero(160, "rapido", 160, "metal phrasing: powerful, articulated lines with space between them"),
    "punk": TempoGenero(172, "rapido", 175, "punk phrasing: fast and raw, short shouted lines"),
    "indie": TempoGenero(115, "medio", 140, "indie phrasing, relaxed and conversational"),
    "folk": TempoGenero(100, "medio", 140, "folk storytelling phrasing, clear and unhurried"),
    "flamenco": TempoGenero(130, "medio", 135, "flamenco phrasing inside its compas, melisma and dramatic pauses"),
}

PASO_POR_DEFECTO = 145
"""Palabras por minuto cuando el genero no esta en la tabla (texto libre)."""


def tempo_de_la_cancion(generos: list[str] | None) -> TempoGenero | None:
    """El tempo que manda: el del primer genero escogido que este en la tabla.

    La mezcla la ordena el dueno en la pantalla; el primer genero es
    el principal y es el que pone la velocidad. Si ninguno esta en la
    tabla (solo texto libre), no hay numero que mandar: None.
    """
    for clave in generos or []:
        if clave in GENERO_TEMPO:
            return GENERO_TEMPO[clave]
    return None


def linea_tempo(generos: list[str] | None) -> str:
    """La linea de tempo del encargo a Lyria, o vacia si no hay tabla."""
    tempo = tempo_de_la_cancion(generos)
    if tempo is None:
        return ""
    return f"Tempo: {tempo.bpm} BPM. Delivery: {tempo.frase}."


def presupuesto_palabras(duracion_segundos: int, tempo: TempoGenero | None) -> int:
    """Cuantas palabras caben cantadas bien en esa duracion a ese paso.

    Redondeado a la decena: es una medida de trabajo para quien
    escribe, no una cifra de laboratorio.
    """
    por_minuto = tempo.palabras_por_minuto if tempo is not None else PASO_POR_DEFECTO
    return max(60, round(duracion_segundos * por_minuto / 60 / 10) * 10)


def contar_palabras(letra: str) -> int:
    """Las palabras cantadas de una letra: fuera las marcas de seccion."""
    total = 0
    for linea in (letra or "").splitlines():
        linea = linea.strip()
        if not linea or (linea.startswith("[") and linea.endswith("]")):
            continue
        total += len(linea.split())
    return total
