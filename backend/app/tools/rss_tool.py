"""
fetch_trending_headlines()

This is the hard boundary that keeps raw XML out of any LLM context
window. Everything here is plain, deterministic code: fetch, parse,
normalize, dedupe, truncate. The agent only ever sees the return value
of this function — an array of ~15 short strings.
"""

from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher

import feedparser
import httpx

from app.config import settings
from app.state import Headline

MAX_HEADLINES = 15
SIMILARITY_THRESHOLD = 0.82  # collapse near-duplicate headlines across feeds


def _clean(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    title = re.sub(r"^\[[^\]]+\]\s*", "", title)  # strip leading [Tags]
    return title


def _is_duplicate(candidate: str, seen: list[str]) -> bool:
    for s in seen:
        if SequenceMatcher(None, candidate.lower(), s.lower()).ratio() > SIMILARITY_THRESHOLD:
            return True
    return False


def fetch_trending_headlines() -> list[Headline]:
    """
    Fetch + parse every configured RSS feed, dedupe near-identical
    stories across sources, and return at most MAX_HEADLINES short
    {id, title, source} records. Never returns raw XML/HTML.
    """
    collected: list[Headline] = []
    seen_titles: list[str] = []

    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        for url in settings.rss_feeds:
            try:
                resp = client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; NewsAgent/1.0)"})
                resp.raise_for_status()
            except httpx.HTTPError:
                continue  # a single dead feed should never kill research

            parsed = feedparser.parse(resp.content)
            source = parsed.feed.get("title", url)

            for entry in parsed.entries[:10]:
                title = _clean(entry.get("title", ""))
                if not title or _is_duplicate(title, seen_titles):
                    continue
                seen_titles.append(title)
                story_id = hashlib.sha1(title.encode()).hexdigest()[:10]
                collected.append({"id": story_id, "title": title, "source": source})

                if len(collected) >= MAX_HEADLINES:
                    return collected

    return collected
