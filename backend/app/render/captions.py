"""
Burned-in captions.

Word timings from edge-tts get grouped into short cues (a couple of words
per beat of speech reads better than a full sentence held on screen), then
emitted as an ASS subtitle file. libass renders it with the same
1080x1920 geometry as the video, so text lands in the lower third where
platform UI won't cover it.
"""

from pathlib import Path

from app.config import settings

# libass colour codes are &HAABBGGRR (alpha, blue, green, red).
WHITE = "&H00FFFFFF"
OUTLINE_BLACK = "&H00000000"

# A caption line this wide at 64px on a 1080-wide frame stays readable
# without wrapping unpredictably.
_HARD_MAX = settings.caption_max_chars


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{int(hours):d}:{int(minutes):02d}:{secs:05.2f}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ").strip()


def _group_words(words: list[dict]) -> list[list[dict]]:
    """
    Chunk words into cues of at most _HARD_MAX characters, never splitting
    a cue across a pause (gap > 0.45s) or past a comma, and keeping cues to
    roughly even lengths so the screen does not flicker between one and
    four words.
    """
    if not words:
        return []

    cues: list[list[dict]] = []
    current: list[dict] = []
    length = 0

    for i, word in enumerate(words):
        token = word["text"].strip()
        if not token:
            continue

        addition = len(token) + (1 if current else 0)
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (nxt["start"] - word["end"]) if nxt else 0.0
        ends_sentence = token.endswith((".", "!", "?"))

        # Break before exceeding the width, after a long pause, or at a
        # clause boundary once the cue is already a readable length.
        too_long = current and length + addition > _HARD_MAX
        pause = current and gap > 0.45
        clause = current and length >= _HARD_MAX // 2 and token.endswith((",", ";", ":"))

        if too_long or pause or clause or ends_sentence:
            if current:
                cues.append(current)
            current, length = [], 0
            addition = len(token)

        current.append(word)
        length += addition

    if current:
        cues.append(current)

    return cues


def build_caption_cues(words: list[dict]) -> list[dict]:
    """[{start, end, text}] on the full video timeline."""
    cues = []
    for group in _group_words(words):
        text = " ".join(w["text"].strip() for w in group).strip()
        if not text:
            continue
        cues.append(
            {
                "start": round(group[0]["start"], 3),
                "end": round(group[-1]["end"], 3),
                "text": text,
            }
        )
    return cues


def write_ass(cues: list[dict], dest: Path, width: int = 1080, height: int = 1920) -> Path:
    size = settings.caption_font_size
    font = settings.caption_font.replace("\\", "/").rsplit("/", 1)[-1].removesuffix(".ttf")

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{size},{WHITE},{WHITE},{OUTLINE_BLACK},{OUTLINE_BLACK},-1,0,0,0,100,100,0,0,1,{settings.caption_outline},1,2,80,80,{settings.caption_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [
        f"Dialogue: 0,{_ass_time(c['start'])},{_ass_time(c['end'])},Cap,,0,0,0,,"
        f"{{\\fad(80,80)}}{_escape(c['text'])}"
        for c in cues
    ]
    dest.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return dest
