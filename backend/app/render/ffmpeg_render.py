"""
Deterministic render node. Pure code — no LLM call. On failure it
raises RenderError with a short, specific message so the Recovery
Agent gets exactly the kind of string it's designed to diagnose.

Pipeline order matters:

  1. narrate every beat          -> exact per-beat audio duration
  2. fit narration to the window -> tempo + optional tail hold
  3. fetch + trim one clip/beat  -> each clip cut to ITS narration length
  4. concat video, concat audio  -> video length == narration length
  5. burn captions               -> timed from the same word boundaries
  6. copy the finished file out   -> so the dashboard can preview it

The output is guaranteed to land inside [MIN_REEL_SECONDS, MAX_REEL_SECONDS]
because step 2 measures the real synthesized audio and corrects for it.
The word-count estimate used earlier in the graph is only a cheap pre-check;
it cannot be trusted as the final length, since TTS speaking rate is not
exactly WORDS_PER_SECOND.
"""

import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx

from app.config import settings
from app.media import store_reel
from app.render.captions import build_caption_cues, write_ass
from app.render.tts import TTSError, all_words, narrate_beats, total_duration
from app.state import PipelineState
from app.tools.pexels_tool import PexelsNotFoundError, fetch_stock_clip

# Every intermediate clip is normalised to this before concatenation so the
# concat demuxer never has to re-encode mismatched streams.
WIDTH, HEIGHT, FPS = 1080, 1920, 30
PRESET = "veryfast"

# Tempo outside this range stops sounding like narration.
TEMPO_MIN, TEMPO_MAX = 0.85, 1.50

# Safety margin so rounding never pushes a finished reel outside the window.
EDGE = 0.3


class RenderError(Exception):
    pass


def plan_duration(narration_sec: float) -> tuple[float, float, float | None]:
    """
    Decide how to fit measured narration into the length window.

    Returns (tempo, tail_hold_sec, trim_to) where:
      tempo       atempo factor applied to the narration
      tail_hold   seconds of frozen final frame + silence, used to reach the
                  minimum when narration is too short to stretch into it
      trim_to     hard output ceiling, set only when narration is so long
                  that no acceptable tempo can bring it under the maximum

    The returned plan is what makes the 20-30s guarantee unconditional.
    """
    lo, hi = settings.min_reel_seconds, settings.max_reel_seconds

    if narration_sec > hi:
        tempo = narration_sec / (hi - EDGE)
        if tempo > TEMPO_MAX:
            # Too long to fit by pacing alone: hold max tempo and hard-trim
            # the muxed output so the file still lands inside the window.
            return TEMPO_MAX, 0.0, hi
        return tempo, 0.0, None

    if narration_sec >= lo:
        return 1.0, 0.0, None

    tempo = max(narration_sec / (lo + EDGE), TEMPO_MIN)
    stretched = narration_sec / tempo
    if stretched >= lo:
        return tempo, 0.0, None
    return tempo, round(lo - stretched, 3), None


def _require_ffmpeg() -> str:
    """
    Resolve ffmpeg before any work happens. Without this, a missing binary
    raises a bare FileNotFoundError, which escapes render_with_recovery_node
    (it only catches RenderError) and kills the whole graph — taking out the
    Recovery Agent that exists precisely to handle render failures.
    """
    resolved = shutil.which("ffmpeg")
    if resolved is None:
        raise RenderError(
            "ffmpeg was not found on PATH. Install it (Windows: "
            "`scoop install ffmpeg` or `winget install Gyan.FFmpeg`; "
            "macOS: `brew install ffmpeg`) and restart the backend."
        )
    return resolved


def _run(cmd: list[str], what: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = proc.stderr.strip().splitlines()[-3:] if proc.stderr else []
        raise RenderError(f"{what} failed: {' | '.join(tail) or 'unknown error'}")
    return proc


def _download(url: str, dest: Path) -> None:
    with httpx.stream("GET", url, timeout=30.0, follow_redirects=True) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)


def _normalise_clip(src: Path, dest: Path, seconds: float, ffmpeg: str) -> None:
    """
    Scale/crop to vertical 1080x1920, force a constant frame rate, and cut
    the clip to the length of the beat it belongs to. No audio: the
    narration is muxed in once at the end.
    """
    _run(
        [
            ffmpeg, "-y", "-i", str(src),
            "-t", f"{seconds:.3f}",
            "-vf",
            f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},fps={FPS}",
            "-an",
            "-c:v", "libx264", "-preset", PRESET, "-crf", "23",
            "-pix_fmt", "yuv420p",
            str(dest),
        ],
        "Clip normalisation",
    )


def _mux(
    video: Path,
    audio: Path,
    dest: Path,
    ffmpeg: str,
    tail_hold: float,
    trim_to: float | None = None,
) -> None:
    """
    Mux narration onto the silent video. When narration is too short to
    reach the minimum, clone the final frame and pad the audio with silence
    so the two tracks stay the same length. When trim_to is set, -t caps the
    output so an over-long narration still yields an in-window file.
    """
    video_filter = f"tpad=stop_mode=clone:stop_duration={tail_hold:.3f}" if tail_hold > 0 else "null"
    cmd = [
        ffmpeg, "-y", "-i", str(video), "-i", str(audio),
        "-vf", video_filter,
        "-af", f"apad=pad_dur={tail_hold:.3f}" if tail_hold > 0 else "anull",
        "-c:v", "libx264", "-preset", PRESET, "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
    ]
    if trim_to is not None:
        cmd += ["-t", f"{trim_to:.3f}"]
    cmd += ["-shortest", str(dest)]
    _run(cmd, "Audio mux")


def _burn_captions(video: Path, ass: Path, dest: Path, ffmpeg: str) -> None:
    escaped = str(ass).replace("\\", "/").replace(":", r"\:")
    _run(
        [
            ffmpeg, "-y", "-i", str(video),
            "-vf", f"subtitles='{escaped}'",
            "-c:v", "libx264", "-preset", PRESET, "-crf", "22",
            "-c:a", "copy",
            str(dest),
        ],
        "Caption burn-in",
    )


def _join_audio(parts: list[Path], dest: Path, tempo: float, ffmpeg: str) -> Path:
    """Concatenate beat narration, applying the tempo correction in one pass."""
    manifest = dest.parent / "audio_concat.txt"
    manifest.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in parts), encoding="utf-8"
    )
    af = f"atempo={tempo:.4f}" if abs(tempo - 1.0) > 0.01 else "anull"
    _run(
        [
            ffmpeg, "-y", "-f", "concat", "-safe", "0",
            "-i", str(manifest), "-af", af,
            "-c:a", "libmp3lame", "-q:a", "4", str(dest),
        ],
        "Narration assembly",
    )
    return dest


def render_node(state: PipelineState) -> dict:
    ffmpeg = _require_ffmpeg()
    script = state["script"]
    render_result = state.get("render_result", {})
    override_query = render_result.get("image_query_used")

    workdir = Path(tempfile.mkdtemp(prefix="reel_"))

    # 1. Narration first — it defines the length of everything downstream.
    try:
        narrated = asyncio.run(narrate_beats(script["beats"], workdir))
    except TTSError as e:
        raise RenderError(f"Narration failed: {e}") from e

    narration_sec = total_duration(narrated)
    tempo, tail_hold, trim_to = plan_duration(narration_sec)
    final_sec = round(min(narration_sec / tempo + tail_hold, trim_to or 1e9), 2)

    beats = script["beats"]
    by_name = {b.get("beat"): b for b in beats}
    index_by_name = {b.get("beat"): i for i, b in enumerate(beats)}

    # 2. One clip per narrated beat, trimmed to that beat's corrected length.
    clip_paths: list[Path] = []
    for n, voiced in enumerate(narrated):
        original = by_name.get(voiced.beat, {})
        query = (
            override_query
            if (override_query and n == 0)
            else original.get("image_query", "container ship")
        )
        try:
            clip_url = fetch_stock_clip(query)
        except PexelsNotFoundError as e:
            raise RenderError(str(e)) from e

        raw = workdir / f"raw_{index_by_name.get(voiced.beat, n)}.mp4"
        _download(clip_url, raw)

        trimmed = workdir / f"clip_{n}.mp4"
        _normalise_clip(raw, trimmed, voiced.duration / tempo, ffmpeg)
        clip_paths.append(trimmed)

    # 3. Concat video, fit narration, mux.
    video_manifest = workdir / "video_concat.txt"
    video_manifest.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in clip_paths), encoding="utf-8"
    )
    silent = workdir / "silent.mp4"
    _run(
        [
            ffmpeg, "-y", "-f", "concat", "-safe", "0",
            "-i", str(video_manifest), "-c", "copy", str(silent),
        ],
        "Clip assembly",
    )

    narration = _join_audio(
        [v.audio_path for v in narrated], workdir / "voiceover.mp3", tempo, ffmpeg
    )
    muxed = workdir / "muxed.mp4"
    _mux(silent, narration, muxed, ffmpeg, tail_hold, trim_to)

    # 4. Captions from the same word boundaries, rescaled by the tempo the
    #    narration was actually rendered at.
    output_path = workdir / "reel_output.mp4"
    cues: list[dict] = []
    if settings.captions_enabled:
        scaled = [
            {**w, "start": w["start"] / tempo, "end": w["end"] / tempo}
            for w in all_words(narrated)
        ]
        cues = build_caption_cues(scaled)
        ass = write_ass(cues, workdir / "captions.ass", WIDTH, HEIGHT)
        _burn_captions(muxed, ass, output_path, ffmpeg)
    else:
        _run([ffmpeg, "-y", "-i", str(muxed), "-c", "copy", str(output_path)], "Copy")

    # 5. The temp workdir is throwaway; the dashboard and the social adapters
    #    both need the finished file somewhere permanent.
    stored_path, video_url = output_path, ""
    try:
        stored_path, video_url = store_reel(output_path, state.get("run_id") or "reel")
    except OSError:
        pass  # preview unavailable, but the reel is still publishable from temp

    return {
        "render_result": {
            "status": "success",
            "output_path": str(stored_path),
            "video_url": video_url,
            "image_query_used": override_query,
            "duration_sec": final_sec,
            "narration_sec": narration_sec,
            "tempo": round(tempo, 3),
            "tail_hold_sec": tail_hold,
            "trimmed": trim_to is not None,
            "narrated": True,
            "voice": settings.tts_voice,
            "caption_cues": len(cues),
        },
        "status": "awaiting_approval",
    }
