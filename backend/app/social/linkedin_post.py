"""
LinkedIn posting via the Videos API.

The upload is a three-phase, chunked protocol — not a single PUT:

  1. initializeUpload  declare the file size, get one uploadInstructions
                       entry per 4 MB part
  2. PUT each part      to its own uploadUrl, keeping the ETag response header
  3. finalizeUpload     hand the ETags back in order to get a usable video

Sending the whole file to uploadInstructions[0] is what a naive
implementation does, and LinkedIn answers 413 Payload Too Large, because
each part URL only accepts its own ~4 MB byte range.
"""

import os

import httpx

from app.config import settings

API_ROOT = "https://api.linkedin.com/rest"
HEADERS_BASE = {
    "X-Restli-Protocol-Version": "2.0.0",
}

# LinkedIn breaks the upload into parts of this size. We never hardcode the
# split ourselves — firstByte/lastByte in the response define it — but this is
# the size to expect in the instructions.
PART_SIZE = 4 * 1024 * 1024


def _headers() -> dict:
    return {
        **HEADERS_BASE,
        "LinkedIn-Version": settings.linkedin_api_version,
        "Authorization": f"Bearer {settings.linkedin_access_token}",
    }


def _require_config() -> None:
    if not (settings.linkedin_author_urn and settings.linkedin_access_token):
        raise RuntimeError(
            "LINKEDIN_MEMBER_ID (or LINKEDIN_ORG_URN) / LINKEDIN_ACCESS_TOKEN "
            "not set in backend/.env"
        )


def _initialize_upload(client: httpx.Client, file_size: int) -> dict:
    resp = client.post(
        f"{API_ROOT}/videos?action=initializeUpload",
        headers=_headers(),
        json={
            "initializeUploadRequest": {
                "owner": settings.linkedin_author_urn,
                "fileSizeBytes": file_size,
                "uploadCaptions": False,
                "uploadThumbnail": False,
            }
        },
        timeout=60.0,
    )
    resp.raise_for_status()
    init = resp.json().get("value") or {}
    if not init.get("video") or not init.get("uploadInstructions"):
        raise RuntimeError(f"LinkedIn initializeUpload returned no video/instructions: {init}")
    return init


def _upload_parts(client: httpx.Client, path: str, instructions: list[dict]) -> list[str]:
    """PUT every byte range to its own URL, returning the ETags in order."""
    part_ids: list[str] = []

    with open(path, "rb") as f:
        for index, instruction in enumerate(instructions):
            first = instruction["firstByte"]
            # firstByte and lastByte are both inclusive, hence the + 1.
            last = instruction["lastByte"]
            f.seek(first)
            chunk = f.read(last - first + 1)

            resp = client.put(
                instruction["uploadUrl"],
                content=chunk,
                headers={"Content-Type": "application/octet-stream"},
                timeout=600.0,
            )
            if resp.status_code != 200:
                raise RuntimeError(
                    f"LinkedIn part {index + 1}/{len(instructions)} "
                    f"[{first}-{last}] rejected: {resp.status_code} {resp.text[:200]}"
                )

            etag = resp.headers.get("etag") or resp.headers.get("ETag")
            if not etag:
                raise RuntimeError(
                    f"LinkedIn part {index + 1}/{len(instructions)} returned no ETag"
                )
            # Documented example shows bare ids, not quoted header values.
            part_ids.append(etag.strip().strip('"'))

    return part_ids


def _finalize_upload(client: httpx.Client, video_urn: str, upload_token: str, part_ids: list[str]) -> None:
    resp = client.post(
        f"{API_ROOT}/videos?action=finalizeUpload",
        headers=_headers(),
        json={
            "finalizeUploadRequest": {
                "video": video_urn,
                "uploadToken": upload_token,
                "uploadedPartIds": part_ids,
            }
        },
        timeout=60.0,
    )
    resp.raise_for_status()


def post_reel_to_linkedin(video_path: str, caption: str) -> str:
    _require_config()

    file_size = os.path.getsize(video_path)

    with httpx.Client() as client:
        init = _initialize_upload(client, file_size)
        instructions = init["uploadInstructions"]

        part_ids = _upload_parts(client, video_path, instructions)
        _finalize_upload(client, init["video"], init.get("uploadToken", ""), part_ids)

        post_resp = client.post(
            f"{API_ROOT}/posts",
            headers=_headers(),
            json={
                "author": settings.linkedin_author_urn,
                "commentary": caption,
                "visibility": "PUBLIC",
                "distribution": {"feedDistribution": "MAIN_FEED"},
                "content": {"media": {"id": init["video"]}},
                "lifecycleState": "PUBLISHED",
            },
            timeout=30.0,
        )
        post_resp.raise_for_status()

    post_id = post_resp.headers.get("x-restli-id", init["video"])
    return f"https://www.linkedin.com/feed/update/{post_id}"
