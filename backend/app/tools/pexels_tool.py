"""
Pexels lookup tool. Returns the single best matching asset URL for a
query — never the full Pexels JSON payload — to keep agent context lean.
Raises PexelsNotFoundError on a 404/empty result so the Recovery Agent
has a clean, specific error to react to.
"""

import httpx

from app.config import settings

PEXELS_VIDEO_SEARCH = "https://api.pexels.com/videos/search"


class PexelsNotFoundError(Exception):
    pass


def fetch_stock_clip(query: str) -> str:
    """Return a direct MP4 URL for the best matching Pexels video clip."""
    if not settings.pexels_api_key:
        raise RuntimeError("PEXELS_API_KEY is not set. Add it to backend/.env")

    resp = httpx.get(
        PEXELS_VIDEO_SEARCH,
        headers={"Authorization": settings.pexels_api_key},
        params={"query": query, "per_page": 5, "orientation": "portrait"},
        timeout=15.0,
    )
    resp.raise_for_status()

    videos = resp.json().get("videos")
    if not videos:
        raise PexelsNotFoundError(f"Pexels returned 404 for query: '{query}'")

    # Pick the highest-resolution portrait file under a sane size cap.
    best = max(
        (f for v in videos for f in v["video_files"] if f.get("width", 0) <= 1080),
        key=lambda f: f.get("width", 0),
        default=None,
    )
    if best is None:
        raise PexelsNotFoundError(f"Pexels returned no usable portrait file for: '{query}'")

    return best["link"]
