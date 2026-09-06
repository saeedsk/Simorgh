"""`simorgh.toml [worldmodel]` (spec section 3.5)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    repo_root: Path = Path(".")
    file_index_max_files: int = 5000
    git_refresh_seconds: float = 60.0
    soul_path: Path = Path("docs/SOUL.md")

    @classmethod
    def from_mapping(cls, data: dict | None, *, default_repo_root: Path | None = None) -> "Config":
        data = data or {}
        root = Path(data.get("repo_root", default_repo_root or Path(".")))
        file_index = data.get("file_index") or {}
        git = data.get("git") or {}
        identity = data.get("identity") or {}
        return cls(
            repo_root=root,
            file_index_max_files=int(file_index.get("max_files", 5000)),
            git_refresh_seconds=float(git.get("refresh_seconds", 60.0)),
            soul_path=Path(identity.get("soul_path", "docs/SOUL.md")),
        )

    def resolved_soul_path(self) -> Path:
        """`soul_path` joined against `repo_root` when it's relative --
        the single place this join happens, so it's correct whether the
        config came from `from_mapping` or a direct constructor call
        (e.g. in tests), instead of only working for one of the two."""
        return self.soul_path if self.soul_path.is_absolute() else self.repo_root / self.soul_path
