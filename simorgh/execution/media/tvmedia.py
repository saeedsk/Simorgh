"""A YouTube video as a plain file for the TV's own player.

The creator, 2026-09-13: "the video showing on tv dash is blank white,
and when it's running I don't hear the voice on tv." The dashboard
framed YouTube with YouTube's embedded player, and inside a Cast
receiver that player draws nothing and says nothing -- YouTube keeps
its player off Cast devices, which is why full-screen mode (YouTube's
own receiver app) works and a framed video does not.

So the video is fetched on the laptop with yt-dlp -- an open-source
downloader; YouTube's terms frown on it, and the person is told the
file is for the TV in this house -- as 720p H.264 with AAC sound, and
served from `workspace/tv/media/` by Sim's HTTP API. The page plays
that file in a `<video>` element, with sound. A song takes about five
seconds to arrive (33 MB, measured); the page shows the thumbnail and
"fetching" until it does. The cache keeps the newest few gigabytes.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

DEFAULT_DIR = Path("workspace") / "tv" / "media"
CACHE_CAP_BYTES = 3 * 1024 ** 3
#: what the Bravia's Cast browser decodes without thinking: H.264 in mp4
FORMAT = "bv*[height<={h}][ext=mp4][vcodec^=avc1]+ba[ext=m4a]/b[height<={h}][ext=mp4]/b[ext=mp4]/b"


def default_dir() -> Path:
    return (Path.cwd() / DEFAULT_DIR).resolve()


def fetch(video_id: str, cache_dir: Path | str | None = None, *, max_height: int = 720, timeout_s: float = 180.0,
          runner=subprocess.run, which=shutil.which) -> tuple[Path | None, str]:
    """`<cache_dir>/<video_id>.mp4`, fetched if not already there.
    Returns (path, "") or (None, why): yt-dlp missing, the download
    refused, the clock run out."""
    if not video_id or not all(c.isalnum() or c in "-_" for c in video_id):
        return None, f"not a YouTube video id: {video_id!r}"
    root = Path(cache_dir) if cache_dir is not None else default_dir()
    target = root / f"{video_id}.mp4"
    if target.is_file() and target.stat().st_size > 0:
        target.touch()
        return target, ""
    tool = which("yt-dlp")
    if not tool:
        return None, ("yt-dlp is not installed, so a YouTube video cannot be framed on the TV; `brew install yt-dlp` "
                      "(full screen through YouTube's own receiver still works)")
    root.mkdir(parents=True, exist_ok=True)
    partial = root / f"{video_id}.part.mp4"
    cmd = [tool, "--no-playlist", "--quiet", "--no-warnings", "-f", FORMAT.format(h=int(max_height)),
           "--merge-output-format", "mp4", "--postprocessor-args", "ffmpeg:-movflags +faststart",
           "-o", str(partial), f"https://www.youtube.com/watch?v={video_id}"]
    try:
        done = runner(cmd, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        partial.unlink(missing_ok=True)
        return None, f"the download took more than {timeout_s:.0f}s"
    except OSError as exc:
        return None, f"could not run yt-dlp: {exc}"
    if done.returncode != 0 or not partial.is_file():
        partial.unlink(missing_ok=True)
        tail = ((done.stderr or done.stdout or "").strip().splitlines() or ["yt-dlp gave no reason"])[-1]
        return None, f"YouTube would not give the video: {tail[:200]}"
    partial.replace(target)
    prune(root)
    return target, ""


def prune(root: Path, cap_bytes: int = CACHE_CAP_BYTES) -> int:
    """Delete the oldest files until the folder is under `cap_bytes`;
    returns how many went."""
    files = sorted((p for p in root.glob("*.mp4") if p.is_file()), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in files)
    gone = 0
    for path in files:
        if total <= cap_bytes:
            break
        total -= path.stat().st_size
        path.unlink(missing_ok=True)
        gone += 1
    return gone


__all__ = ["CACHE_CAP_BYTES", "DEFAULT_DIR", "FORMAT", "default_dir", "fetch", "prune"]
