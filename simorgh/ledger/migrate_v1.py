"""v1 record compatibility (02-ledger section 4.2; 06-migration section
5). v1's `~/.simorgh/memory.jsonl` lines are
`{"id","kind","content","created_at","metadata"}`. `read_v1_records`
maps each to an `Event` on the stream the migration map assigns for its
kind, typed `v1.<kind>`, with `idempotency_key="v1:<id>"` -- so the
Kernel's `migrate-v1` command is a plain replay through `append`, and
running it twice appends nothing the second time.

The route table is the one in `06` section 5; `route_v1` is exposed so
tests can assert every v1 kind lands somewhere sensible.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from simorgh.contracts.envelope import Event

from .streams import is_valid_stream


def _slug(value: object, fallback: str) -> str:
    text = str(value or fallback).lower()
    cleaned = "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in text)
    return cleaned[:60] or fallback


def route_v1(kind: str, metadata: dict) -> str:
    """The v2 stream a v1 record of `kind` belongs on."""
    if kind == "task_event":
        return f"task:{_slug(metadata.get('task_id'), 'unknown')}"
    if kind in ("applied_source_patch", "applied_skill"):
        return "learn:patches" if kind == "applied_source_patch" else "learn:skills"
    if kind == "llm_spend":
        return "cognition:budget"
    if kind in ("interest", "news_seen", "growth_shared"):
        return "curiosity:interests"
    if kind == "research_finding":
        return "memory:semantic"
    if kind in ("autonomous_action", "activity", "tool_call"):
        return "activity"
    if kind == "rejected_proposal":
        return "guardian:rejected"
    return "memory:episodic"


def read_v1_records(path: str | Path) -> Iterator[Event]:
    """Yield one `Event` per well-formed v1 line. A malformed line (a
    crash mid-write, a hand edit) is skipped, not fatal -- mirroring
    v1's own loader -- so a single bad record never blocks a migration."""
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict) or "kind" not in record:
                continue
            kind = str(record.get("kind"))
            metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
            stream = route_v1(kind, metadata)
            if not is_valid_stream(stream):
                stream = "memory:episodic"
            record_id = str(record.get("id") or "")
            payload = {"content": record.get("content"), **metadata}
            yield Event(
                stream=stream,
                type=f"v1.{kind}",
                ts=float(record.get("created_at") or 0.0),
                trace_id=f"v1:{record_id}" if record_id else "v1",
                causation_id=None,
                payload=payload,
                idempotency_key=f"v1:{record_id}" if record_id else None,
            )


__all__ = ["read_v1_records", "route_v1"]
