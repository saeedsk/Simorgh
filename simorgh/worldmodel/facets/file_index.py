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

    def __init__(self, repo_root: Path, *, max_files: int = 5000) -> None:
        self._repo_root = repo_root
        self._max_files = max_files
        self._cache: dict | None = None

    def invalidate(self) -> None:
        self._cache = None

    async def get(self, args: dict) -> dict:
        args = args or {}
        path = args.get("path")
        if path:
            return self._preview(path, args.get("max_chars", 2000))
        if self._cache is None:
            self._cache = self._scan(args.get("under", "simorgh"), args.get("exclude_skills", True))
        return self._cache

    def _scan(self, under: str, exclude_skills: bool) -> dict:
        root = self._repo_root / under
        if not root.is_dir():
            return {"files": [], "truncated": False, "under": under}
        files = []
        for p in sorted(root.rglob("*.py")):
            rel = p.relative_to(self._repo_root)
            if exclude_skills and "skills" in rel.parts:
                continue
            if len(files) >= self._max_files:
                return {"files": files, "truncated": True, "under": under}
            try:
                stat = p.stat()
                files.append({"path": str(rel), "size": stat.st_size, "mtime": stat.st_mtime})
            except OSError:
                continue
        return {"files": files, "truncated": False, "under": under}

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
