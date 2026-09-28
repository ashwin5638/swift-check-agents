"""
Facebook posting via the Graph API's Page video-upload endpoint.
Requires a Page access token with pages_manage_posts + publish_video.
"""

import httpx

from app.config import settings


def post_reel_to_facebook(video_path: str, caption: str) -> str:
    if not (settings.facebook_page_id and settings.facebook_access_token):
        raise RuntimeError(
            "FACEBOOK_PAGE_ID / FACEBOOK_PAGE_ACCESS_TOKEN not set in backend/.env"
        )

    version = settings.facebook_graph_version
    url = f"https://graph-video.facebook.com/{version}/{settings.facebook_page_id}/videos"

    with open(video_path, "rb") as f:
        resp = httpx.post(
            url,
            data={
                "access_token": settings.facebook_access_token,
                "description": caption,
            },
            files={"source": f},
            timeout=120.0,
        )
    resp.raise_for_status()
    video_id = resp.json()["id"]
    return f"https://www.facebook.com/{settings.facebook_page_id}/videos/{video_id}"
