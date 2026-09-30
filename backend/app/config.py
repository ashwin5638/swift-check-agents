"""
Central configuration.

Every value is read from backend/.env through one resolver that accepts
the aliases each provider's dashboard actually spells out — Groq vs xAI
for the LLM, Facebook's page-token naming, LinkedIn member vs org — so a
populated .env loads without hand-editing names, and the LLM base URL /
model default to whatever provider is actually configured instead of
guessing at call time.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _env(*names: str, default: str = "") -> str:
    """First non-empty value among `names`, else `default`."""
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default


# Provider presets. Model defaults are pinned to a general-purpose chat
# model, not the guard/whisper models the provider also serves.
_LLM_PRESETS = {
    "groq": {
        "key": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "openai/gpt-oss-120b",
    },
    "xai": {
        "key": "GROK_API_KEY",
        "base_url": "https://api.x.ai/v1",
        "model": "grok-4-fast",
    },
}


def _llm() -> dict[str, str]:
    """Resolve (provider, api_key, base_url, model) from whichever key exists."""
    for provider, preset in _LLM_PRESETS.items():
        key = _env(preset["key"])
        if key:
            prefix = preset["key"].removesuffix("_API_KEY")
            return {
                "provider": provider,
                "api_key": key,
                "base_url": _env(f"{prefix}_BASE_URL", default=preset["base_url"]),
                "model": _env(f"{prefix}_MODEL", default=preset["model"]),
            }
    preset = _LLM_PRESETS["groq"]
    return {
        "provider": "groq",
        "api_key": "",
        "base_url": _env("GROQ_BASE_URL", default=preset["base_url"]),
        "model": _env("GROQ_MODEL", default=preset["model"]),
    }


def _linkedin_author_urn() -> str:
    """Personal member profiles are the common case; orgs still work."""
    org = _env("LINKEDIN_ORG_URN")
    if org:
        return org
    member = _env("LINKEDIN_MEMBER_ID")
    return f"urn:li:person:{member}" if member else ""


_llm_settings = _llm()

DEFAULT_RSS_FEEDS = (
    # Shipping, logistics & cargo
    "https://gcaptain.com/feed/,"
    "https://theloadstar.com/feed/,"
    "https://shippingtelegraph.com/feed/,"
    "https://www.hellenicshippingnews.com/feed/,"
    "https://container-news.com/feed/,"
    # Crew, safety & classification
    "https://www.marineinsight.com/feed/,"
    "https://www.dnv.com/news/rss/,"
    # Offshore energy
    "https://splash247.com/feed/,"
    "https://www.offshorewind.biz/feed/"
)


@dataclass(frozen=True)
class Settings:
    # LLM (Groq or xAI, both OpenAI-compatible)
    llm_provider: str = _llm_settings["provider"]
    llm_api_key: str = _llm_settings["api_key"]
    llm_base_url: str = _llm_settings["base_url"]
    llm_model: str = _llm_settings["model"]

    pexels_api_key: str = _env("PEXELS_API_KEY")

    # Narration (edge-tts). British voice reads nautical terms correctly.
    tts_voice: str = _env("TTS_VOICE", default="en-GB-SoniaNeural")
    tts_rate: str = _env("TTS_RATE", default="+8%")

    # Burned-in captions
    captions_enabled: bool = _env("CAPTIONS_ENABLED", default="true").lower() == "true"
    caption_font: str = _env(
        "CAPTION_FONT", default=r"C:\Windows\Fonts\arialbd.ttf"
    )
    caption_font_size: int = int(_env("CAPTION_FONT_SIZE", default="64"))
    caption_outline: int = int(_env("CAPTION_OUTLINE", default="4"))
    caption_margin_v: int = int(_env("CAPTION_MARGIN_V", default="260"))
    caption_max_chars: int = int(_env("CAPTION_MAX_CHARS", default="26"))

    facebook_page_id: str = _env("FACEBOOK_PAGE_ID")
    facebook_access_token: str = _env(
        "FACEBOOK_PAGE_ACCESS_TOKEN", "FACEBOOK_ACCESS_TOKEN"
    )
    facebook_graph_version: str = _env("FACEBOOK_GRAPH_VERSION", default="v21.0")

    linkedin_author_urn: str = _linkedin_author_urn()
    linkedin_access_token: str = _env("LINKEDIN_ACCESS_TOKEN")
    linkedin_api_version: str = _env("LINKEDIN_API_VERSION", default="202405")

    # Reel length window. The word-count estimate gates the graph cheaply;
    # the render node then measures real TTS audio and forces the finished
    # file inside this window, so the estimate never has to be exact.
    min_reel_seconds: float = float(_env("MIN_REEL_SECONDS", default="20"))
    target_reel_seconds: float = float(_env("TARGET_REEL_SECONDS", default="25"))
    max_reel_seconds: float = float(_env("MAX_REEL_SECONDS", default="30"))
    words_per_second: float = float(_env("WORDS_PER_SECOND", default="2.4"))

    # Daily automation
    daily_run_enabled: bool = _env("DAILY_RUN_ENABLED", default="false").lower() == "true"
    daily_run_hour: int = int(_env("DAILY_RUN_HOUR", default="8"))
    daily_run_minute: int = int(_env("DAILY_RUN_MINUTE", default="0"))
    daily_run_timezone: str = _env("DAILY_RUN_TIMEZONE", default="UTC")

    rss_feeds: tuple[str, ...] = tuple(
        f.strip()
        for f in _env("RSS_FEEDS", default=DEFAULT_RSS_FEEDS).split(",")
        if f.strip()
    )


settings = Settings()
