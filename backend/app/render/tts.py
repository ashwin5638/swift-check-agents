"""
Narration via edge-tts (free, no API key, Microsoft's public Edge read-aloud
service). Each beat is synthesized SEPARATELY on purpose: the render node
needs to know exactly how long each beat's narration lasts so it can trim
that beat's stock clip to match. Synthesizing the whole script as one block
would only give a total duration, which is what caused reels to run 2-3x
over the intended length.

WordBoundary events carry per-word offsets/durations, which the caption
builder turns into karaoke-style timed cues.
"""

import asyncio
from pathlib import Path

import edge_tts

from app.config import settings


class TTSError(Exception):
    pass


class NarratedBeat:
    """One beat's audio plus the word timings needed to caption it."""

    __slots__ = ("beat", "text", "audio_path", "duration", "words")

    def __init__(
        self,
        beat: str,
        text: str,
        audio_path: Path,
        duration: float,
        words: list[dict],
    ) -> None:
        self.beat = beat
        self.text = text
        self.audio_path = audio_path
        self.duration = duration
        self.words = words  # [{start, end, text}] relative to this beat


async def _synth_one(text: str, out_path: Path) -> list[dict]:
    """Stream one utterance to mp3, returning relative word timings."""
    communicate = edge_tts.Communicate(
        text,
        settings.tts_voice,
        rate=settings.tts_rate,
        boundary="WordBoundary",
    )

    audio = bytearray()
    words: list[dict] = []

    async for chunk in communicate.stream():
        kind = chunk["type"]
        if kind == "audio":
            audio.extend(chunk["data"])
        elif kind == "WordBoundary":
            start = chunk["offset"] / 1e7
            words.append(
                {
                    "start": start,
                    "end": start + chunk["duration"] / 1e7,
                    "text": chunk["text"],
                }
            )

    if not audio:
        raise TTSError(f"TTS returned no audio for: {text[:60]!r}")

    out_path.write_bytes(bytes(audio))
    return words


def _probe_duration(path: Path) -> float:
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffprobe") or shutil.which("ffmpeg")
    if ffmpeg is None:
        raise TTSError("ffprobe/ffmpeg not found on PATH, cannot measure narration")

    proc = subprocess.run(
        [ffmpeg, "-i", str(path)],
        capture_output=True,
        text=True,
    )
    for line in proc.stderr.splitlines():
        if "Duration:" in line:
            stamp = line.split("Duration:")[1].split(",")[0].strip()
            hours, minutes, seconds = stamp.split(":")
            return round(int(hours) * 3600 + int(minutes) * 60 + float(seconds), 3)
    raise TTSError(f"Could not read duration of {path.name}")


async def narrate_beats(beats: list[dict], workdir: Path) -> list[NarratedBeat]:
    """
    Synthesize every beat in order. Returns beats annotated with absolute
    timings across the concatenated narration timeline, so callers can map
    caption cues straight onto the final video.
    """
    narrated: list[NarratedBeat] = []
    cursor = 0.0

    for i, beat in enumerate(beats):
        text = (beat.get("voiceover") or "").strip()
        if not text:
            continue

        out_path = workdir / f"vo_{i}.mp3"
        words = await _synth_one(text, out_path)
        duration = _probe_duration(out_path)

        narrated.append(
            NarratedBeat(
                beat=beat.get("beat", f"beat_{i}"),
                text=text,
                audio_path=out_path,
                duration=duration,
                words=[
                    {**w, "start": cursor + w["start"], "end": cursor + w["end"]}
                    for w in words
                ],
            )
        )
        cursor += duration

    if not narrated:
        raise TTSError("Every beat had an empty voiceover, nothing to narrate")

    return narrated


def total_duration(narrated: list[NarratedBeat]) -> float:
    return round(sum(b.duration for b in narrated), 3)


def all_words(narrated: list[NarratedBeat]) -> list[dict]:
    return [w for b in narrated for w in b.words]
