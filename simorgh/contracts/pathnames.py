"""What a credentials file looks like by NAME (stage 9 item 1).

Lived in `execution/pathsafety.py` until the product domains moved out of
Execution. Two of them (`knowledge`, `security`) still need the one
question -- does this path segment look like a secret? -- and a domain
must not import the Guardian-protected package to ask it, so the pure
function lives here, where everyone may import from and nothing is
imported in return.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Iterable

_DATA_EXTENSIONS = frozenset({
    "", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".txt", ".env",
})
_SECRET_EXTENSIONS = frozenset({".pem", ".key", ".p12", ".pfx", ".jks", ".keystore"})
_CREDENTIAL_WORDS = ("credential", "secret", "password", "passwd", "token")
_KEY_FILENAMES = frozenset({"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", ".netrc", ".pgpass"})
_CREDENTIAL_DIRECTORIES = frozenset({"secrets", "credentials", ".ssh", ".gnupg", ".aws"})

def _is_dotenv(name: str) -> bool:
    """`.env`, `.env.local`, `prod.env` -- but not `world.env.query.v1.json`,
    which is a schema with the word in the middle of its name."""
    return name == ".env" or name.startswith(".env.") or name.endswith(".env")


def looks_like_credential_path(parts: Iterable[str]) -> bool:
    """True if any path segment looks like a credentials file/dir name.

    Shared by `resolve_safe_path` (so `read_file`/`list_dir` refuse these
    outright) and `search_code`'s own file walk (both the `rg` and
    pure-Python backends) -- without this second use, `search_code`
    could grep the contents of a `.env` or `credentials.json` sitting
    anywhere under `readable_roots` even though `read_file` refuses the
    very same path by name. Found live, 2026-09-08: a `tools/.env` and a
    `tools/credentials.json` were both unreadable via `read_file` but
    their secret contents came back verbatim from `search_code`, via
    ripgrep AND the pure-Python fallback."""
    segments = [str(part).strip().lower() for part in parts if str(part).strip()]
    if not segments:
        return False
    if any(segment in _CREDENTIAL_DIRECTORIES for segment in segments[:-1]):
        return True
    name = segments[-1]
    if name in _KEY_FILENAMES or _is_dotenv(name):
        return True
    suffix = PurePosixPath(name).suffix
    if suffix in _SECRET_EXTENSIONS:
        return True
    if suffix in _DATA_EXTENSIONS and any(word in name for word in _CREDENTIAL_WORDS):
        return True
    return name in _CREDENTIAL_DIRECTORIES


__all__ = ["looks_like_credential_path"]
