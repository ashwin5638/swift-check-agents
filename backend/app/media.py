"""
Permanent home for rendered reels.

FFmpeg assembles each reel inside a throwaway temp dir, which is the right
place for the ~30 intermediate files a render produces but the wrong place
for the finished artifact: the dashboard has to play it and the social
adapters have to re-read it long after the request that created it. The
final mp4 is therefore copied here and served read-only from /media/reels.
"""

from __future__ import annotations

import shutil
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
MEDIA_ROOT = BACKEND_ROOT / "media" / "reels"
MEDIA_MOUNT = "/media/reels"

MEDIA_ROOT.mkdir(parents=True, exist_ok=True)


def reel_filename(run_id: str) -> str:
    """Run ids are uuids, so this is a guard rather than real sanitising."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in run_id)
    return f"{safe or 'reel'}.mp4"


def store_reel(source: Path, run_id: str) -> tuple[Path, str]:
    """
    Copy a finished render into the served directory.

    Returns the on-disk path (what the social adapters read) and the URL
    the dashboard plays from.
    """
    target = MEDIA_ROOT / reel_filename(run_id)
    shutil.copyfile(source, target)
    return target, f"{MEDIA_MOUNT}/{target.name}"
