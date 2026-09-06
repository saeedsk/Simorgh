"""Content-addressed blob storage (02-ledger sections 3.4/4.2 and 03
section 7). Large payloads -- file contents, transcripts, tool output --
are never inlined in an event; they are written here and referenced by
`*_ref` fields as `blob:<sha256>`. Content addressing makes refs stable
(the same bytes always get the same ref), dedupes identical content for
free, and makes a ref verifiable on read.

Ref grammar: `blob:<64 hex>`. `blob:sha256:<64 hex>` (an earlier draft
of the spec) is accepted on read so nothing that already wrote it
breaks; new refs always use the governing form.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from .api import BlobNotFound, ValidationError

_REF = re.compile(r"^blob:(?:sha256:)?([0-9a-f]{64})$")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ref_for(data: bytes) -> str:
    return f"blob:{sha256_hex(data)}"


def parse_ref(ref: str) -> str:
    """The hex digest inside a ref, or ValidationError."""
    match = _REF.match(ref or "")
    if not match:
        raise ValidationError(f"malformed blob ref {ref!r}")
    return match.group(1)


def is_ref(value: str) -> bool:
    return bool(_REF.match(value or ""))


class InMemoryBlobStore:
    def __init__(self) -> None:
        self._blobs: dict[str, tuple[bytes, str]] = {}

    def put(self, data: bytes, *, content_type: str) -> str:
        digest = sha256_hex(data)
        self._blobs.setdefault(digest, (bytes(data), content_type))
        return f"blob:{digest}"

    def get(self, ref: str) -> bytes:
        digest = parse_ref(ref)
        try:
            return self._blobs[digest][0]
        except KeyError:
            raise BlobNotFound(ref) from None

    def stat(self) -> dict:
        return {"blobs": len(self._blobs), "blob_bytes": sum(len(d) for d, _ in self._blobs.values())}


class LocalBlobStore:
    """`<root>/<aa>/<sha256>` plus a `.meta` sidecar (content type, size).
    Writes are atomic (tmp -> fsync -> os.replace) so a crash mid-write
    never leaves a partial blob under its final name; a re-put of
    existing content is a no-op."""

    def __init__(self, root: Path, *, fsync: bool = True) -> None:
        self.root = Path(root)
        self._fsync = fsync

    def _path(self, digest: str) -> Path:
        return self.root / digest[:2] / digest

    def put(self, data: bytes, *, content_type: str) -> str:
        digest = sha256_hex(data)
        path = self._path(digest)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            with open(tmp, "wb") as fh:
                fh.write(data)
                fh.flush()
                if self._fsync:
                    os.fsync(fh.fileno())
            os.replace(tmp, path)
            meta = path.with_name(path.name + ".meta")
            meta.write_text(json.dumps({"content_type": content_type, "size": len(data)}), encoding="utf-8")
        return f"blob:{digest}"

    def get(self, ref: str) -> bytes:
        digest = parse_ref(ref)
        path = self._path(digest)
        if not path.exists():
            raise BlobNotFound(ref)
        data = path.read_bytes()
        if sha256_hex(data) != digest:  # bit rot / tampering: a ref is a promise
            raise BlobNotFound(f"{ref}: content does not match its digest")
        return data

    def stat(self) -> dict:
        count = total = 0
        if self.root.exists():
            for path in self.root.rglob("*"):
                if path.is_file() and not path.name.endswith((".meta", ".tmp")):
                    count += 1
                    total += path.stat().st_size
        return {"blobs": count, "blob_bytes": total}


__all__ = ["InMemoryBlobStore", "LocalBlobStore", "is_ref", "parse_ref", "ref_for", "sha256_hex"]
