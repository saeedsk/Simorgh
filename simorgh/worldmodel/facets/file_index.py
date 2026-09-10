"""`file_index` facet -- a bounded scan of the repository tree with an
optional per-path content preview (03 section 4.10's amendment). Ports
v1's `_list_source_files` (main.py) generalized beyond `src/` and given
a real preview instead of just a name list, since 06-worldmodel.md
section 12 Q2 keeps this read directly (observation of the host, not an
action) rather than through an Execution tool.

Its default `under` stayed at v1's own `src/` -- retired but not
deleted -- rather than `simorgh/`, the live v2 tree, which the sibling
`capability_map.py` facet had the identical bug in for the same reason
(2026-09-08). It matters here too: Curiosity's own real call
(`simorgh/curiosity/service.py`) passes `args={}`, taking this default
every time, so its self-directed exploration was reading the wrong
tree's file list. No model-callable tool exposes this facet directly
(an observer confirmed Sim answers "where do you live" questions by
grepping instead), so the wrong default was invisible from the outside.
"""

from __future__ import annotations

import time
from pathlib import Path


class FileIndexFacet:
    name = "file_index"

    def __init__(self, repo_root: Path, *, max_files: int = 5000,
                 refresh_seconds: float = 30.0, clock=None) -> None:
        self._repo_root = repo_root
        self._max_files = max_files
        self._refresh_seconds = max(0.0, float(refresh_seconds))
        self._clock = clock or time.monotonic
        # Keyed by what was ASKED FOR, and stamped with when it was
        # scanned. One unkeyed slot meant the first call ever made
        # answered every later one: asking for `src` returned the 308
        # files of `simorgh`, labelled `"under": "simorgh"` -- a
        # confidently wrong answer, not a refusal (observer,
        # 2026-09-10). And nothing anywhere calls `invalidate()`, so
        # that one snapshot was the answer for the life of the process,
        # while `capability_map` beside it has no cache at all and sees
        # the tree as it is. Curiosity reads this listing to decide what
        # to explore, off a boot snapshot.
        self._cache: dict[tuple[str, bool], tuple[float, dict]] = {}

    def invalidate(self) -> None:
        self._cache.clear()

    async def get(self, args: dict) -> dict:
        args = args or {}
        path = args.get("path")
        if path:
            return self._preview(path, args.get("max_chars", 2000))
        key = (str(args.get("under", "simorgh")), bool(args.get("exclude_skills", True)))
        now = self._clock()
        cached = self._cache.get(key)
        if cached is not None and (now - cached[0]) < self._refresh_seconds:
            return cached[1]
        scanned = self._scan(*key)
        self._cache[key] = (now, scanned)
        return scanned

    def _scan(self, under: str, exclude_skills: bool) -> dict:
        # `scanned_at` travels with the listing: the envelope's `as_of`
        # is when the question was asked, which says nothing about how
        # old the answer is.
        stamped = {"scanned_at": self._clock()}
        root = self._repo_root / under
        if not root.is_dir():
            return {"files": [], "truncated": False, "under": under, **stamped}
        files = []
        for p in sorted(root.rglob("*.py")):
            rel = p.relative_to(self._repo_root)
            if exclude_skills and "skills" in rel.parts:
                continue
            if len(files) >= self._max_files:
                return {"files": files, "truncated": True, "under": under, **stamped}
            try:
                stat = p.stat()
                files.append({"path": str(rel), "size": stat.st_size, "mtime": stat.st_mtime})
            except OSError:
                continue
        return {"files": files, "truncated": False, "under": under, **stamped}

    def _preview(self, raw_path: str, max_chars: int) -> dict:
        try:
            target = (self._repo_root / raw_path).resolve()
            target.relative_to(self._repo_root.resolve())  # refuse traversal outside the repo
        except (ValueError, OSError):
            return {"path": raw_path, "available": False, "reason": "invalid path"}
        if not target.is_file():
            return {"path": raw_path, "available": False, "reason": "not a file"}
        try:
            text = target.read_text(errors="replace")
        except OSError as exc:
            return {"path": raw_path, "available": False, "reason": str(exc)}
        truncated = len(text) > max_chars
        return {
            "path": raw_path, "available": True, "content": text[:max_chars],
            "truncated": truncated, "total_chars": len(text),
        }
