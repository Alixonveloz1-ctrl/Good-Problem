"""FFmpeg command builders.

Pure functions returning argument lists. Kept separate from the engine so the
command line for every operation can be asserted in a test without FFmpeg being
installed.
"""

from __future__ import annotations

from dataclasses import dataclass

FFMPEG = "ffmpeg"


@dataclass(frozen=True)
class RenderProfile:
    width: int
    height: int
    fps: int = 24
    video_bitrate: str = "12M"
    audio_bitrate: str = "192k"

    @property
    def size(self) -> str:
        return f"{self.width}x{self.height}"


LANDSCAPE_1080 = RenderProfile(1920, 1080)
VERTICAL_1080 = RenderProfile(1080, 1920)
LANDSCAPE_4K = RenderProfile(3840, 2160, video_bitrate="45M")


def concat_list_file(paths: list[str]) -> str:
    """Body of the concat demuxer list. Single quotes are escaped the way the
    demuxer expects."""
    lines = []
    for path in paths:
        escaped = path.replace("'", r"'\''")
        lines.append(f"file '{escaped}'")
    return "\n".join(lines) + "\n"


def concat(list_path: str, output: str, profile: RenderProfile) -> list[str]:
    """Join the approved clips in storyboard order.

    Re-encodes rather than stream copying: clips can come from three different
    Veo models at three different resolutions, and stream copy would refuse or
    produce a broken file.
    """
    return [
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0", "-i", list_path,
        "-vf", f"scale={profile.width}:{profile.height}:force_original_aspect_ratio=decrease,"
               f"pad={profile.width}:{profile.height}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
               f"fps={profile.fps}",
        "-an",
        "-c:v", "libx264", "-preset", "medium", "-b:v", profile.video_bitrate,
        "-pix_fmt", "yuv420p",
        output,
    ]


def crossfade_chain(
    inputs: list[str],
    durations: list[int],
    output: str,
    profile: RenderProfile,
    *,
    transition: float = 0.5,
) -> list[str]:
    """Todos los planos encadenados con un fundido entre cada dos (PRD 29).

    Cada fundido se come ``transition`` segundos de metraje, asi que la imagen
    sale mas corta que la suma de los clips. ``chain_duration`` calcula cuanto.
    """
    if len(inputs) != len(durations):
        raise ValueError("un clip, una duracion")
    if len(inputs) == 1:
        return concat_single(inputs[0], output, profile)

    comando = [FFMPEG, "-y"]
    for ruta in inputs:
        comando += ["-i", ruta]

    escala = (
        f"scale={profile.width}:{profile.height}:force_original_aspect_ratio=decrease,"
        f"pad={profile.width}:{profile.height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={profile.fps}"
    )
    partes = [f"[{i}:v]{escala}[v{i}]" for i in range(len(inputs))]

    anterior = "[v0]"
    acumulado = 0.0
    for i in range(1, len(inputs)):
        acumulado += durations[i - 1]
        offset = max(acumulado - i * transition, 0.0)
        etiqueta = f"[x{i}]" if i < len(inputs) - 1 else "[out]"
        partes.append(
            f"{anterior}[v{i}]xfade=transition=fade:duration={transition}:"
            f"offset={offset:.3f}{etiqueta}"
        )
        anterior = etiqueta

    comando += [
        "-filter_complex", ";".join(partes),
        "-map", "[out]", "-an",
        "-c:v", "libx264", "-preset", "medium", "-b:v", profile.video_bitrate,
        "-pix_fmt", "yuv420p", output,
    ]
    return comando


def concat_single(source: str, output: str, profile: RenderProfile) -> list[str]:
    """Un solo plano: no hay nada que encadenar, solo normalizar el tamano."""
    return [
        FFMPEG, "-y", "-i", source,
        "-vf", f"scale={profile.width}:{profile.height}:force_original_aspect_ratio=decrease,"
               f"pad={profile.width}:{profile.height}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
               f"fps={profile.fps}",
        "-an", "-c:v", "libx264", "-preset", "medium", "-b:v", profile.video_bitrate,
        "-pix_fmt", "yuv420p", output,
    ]


def chain_duration(durations: list[int], transition: float) -> float:
    """Lo que dura la imagen con fundidos: cada uno se come ``transition``."""
    if not durations:
        return 0.0
    return max(sum(durations) - (len(durations) - 1) * transition, 0.0)


def mux_audio(video: str, audio: str, output: str, profile: RenderProfile) -> list[str]:
    """Put the approved master audio on the picture.

    The video never carries audio of its own: Veo is always called with audio
    disabled, so there is nothing to overwrite (PRD 26, 30).
    """
    return [
        FFMPEG, "-y", "-i", video, "-i", audio,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-b:a", profile.audio_bitrate,
        "-shortest", output,
    ]


def overlay_voice(video: str, music: str, voice: str, output: str, *, voice_gain: float = 1.0,
                  music_gain: float = 0.25) -> list[str]:
    """Spoken Chirp voice over a bed of music, for BTS and interviews (PRD 29)."""
    return [
        FFMPEG, "-y", "-i", video, "-i", music, "-i", voice,
        "-filter_complex",
        f"[1:a]volume={music_gain}[bed];[2:a]volume={voice_gain}[vox];"
        "[bed][vox]amix=inputs=2:duration=longest:dropout_transition=0[a]",
        "-map", "0:v:0", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-shortest", output,
    ]


def reframe_vertical(source: str, output: str, profile: RenderProfile = VERTICAL_1080) -> list[str]:
    """9:16 from the 16:9 master by centre crop and scale.

    Derived from the master, so it costs nothing to generate (PRD 32).
    """
    return [
        FFMPEG, "-y", "-i", source,
        "-vf", f"crop=ih*9/16:ih,scale={profile.width}:{profile.height},setsar=1",
        "-c:v", "libx264", "-preset", "medium", "-b:v", profile.video_bitrate,
        "-c:a", "copy", output,
    ]


def cut(source: str, output: str, *, start: float, duration: float) -> list[str]:
    """A Short, Reel or teaser taken out of the master."""
    return [
        FFMPEG, "-y", "-ss", f"{start:.3f}", "-i", source, "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-c:a", "aac", output,
    ]


def burn_captions(source: str, srt_path: str, output: str) -> list[str]:
    escaped = srt_path.replace(":", r"\:").replace("'", r"\'")
    return [
        FFMPEG, "-y", "-i", source,
        "-vf", f"subtitles='{escaped}':force_style='Fontsize=18,Outline=2,Alignment=2'",
        "-c:a", "copy", output,
    ]


def to_wav(source: str, output: str) -> list[str]:
    return [FFMPEG, "-y", "-i", source, "-ar", "48000", "-ac", "2", output]


def to_mp3(source: str, output: str, bitrate: str = "320k") -> list[str]:
    return [FFMPEG, "-y", "-i", source, "-b:a", bitrate, output]


def srt_timestamp(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def build_srt(cues: list[tuple[float, float, str]]) -> str:
    blocks = []
    for index, (start, end, text) in enumerate(cues, start=1):
        blocks.append(
            f"{index}\n{srt_timestamp(start)} --> {srt_timestamp(end)}\n{text.strip()}\n"
        )
    return "\n".join(blocks)
