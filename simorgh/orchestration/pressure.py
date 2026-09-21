"""Compaction by token pressure (stage 4 item 5).

Cognition reports, on every think reply, how many tokens the caller's
messages came to (`compaction.tokens_before`) and how much room the
purpose left them (`compaction.tokens_limit`). Their ratio is the
session's context pressure, and it decides what happens before the next
think:

- Layer A, at `STUB_AT` (70%): tool results older than the last few are
  moved out of the transcript into a ledger blob and replaced by a
  one-line stub naming the tool, the size and a ref. The model gets any
  of them back with the `recall_result` built-in. Nothing is lost and no
  model call is spent.
- Layer B, at `NOTE_AT` (85%): the existing progress note
  (`progress.py`) replaces everything but the last few steps. It costs
  one model call and is lossy, so it runs only when layer A was not
  enough.

Cognition's own read-time compaction (`cognition/compaction.py`) still
runs on every call; this is the session keeping its transcript small
enough that it rarely has to.
"""

from __future__ import annotations

from typing import Awaitable, Callable

STUB_AT = 0.70
NOTE_AT = 0.85
# Tool results this short cost less than their stub is worth.
MIN_STUB_CHARS = 400
STUB_MARK = "[stubbed result"
RECALL_TOOL = "recall_result"
_RESULT_HEADS = ("Result of ", "Results of ")


def pressure(reply_payload: dict) -> float:
    """tokens_before / tokens_limit from a think reply; 0.0 when either is
    missing (an older Cognition, an error reply)."""
    compaction = reply_payload.get("compaction") or {}
    try:
        before = float(compaction.get("tokens_before") or 0)
        limit = float(compaction.get("tokens_limit") or 0)
    except (TypeError, ValueError):
        return 0.0
    return before / limit if limit > 0 else 0.0


def is_result(message: dict) -> bool:
    """A tool result in either dialect: a native `tool` turn, or the marker
    dialect's user turn that starts "Result of ..."."""
    content = message.get("content")
    if not isinstance(content, str) or content.startswith(STUB_MARK):
        return False
    if message.get("role") == "tool":
        return True
    return message.get("role") == "user" and content.startswith(_RESULT_HEADS)


def _head(message: dict) -> str:
    """What this result was OF, as the stub and the recall hint name it.

    A native tool result carries `name`; a marker-dialect one is a
    user message whose text opens "Result of read_file:", and that
    prefix is the only place the tool is written down. Both paths
    need it -- the trials that showed why this matters all ran in the
    marker dialect, where `name` is absent (2026-09-20).
    """
    if message.get("role") == "tool":
        return f"of {message.get('name') or 'a tool'}"
    content = str(message.get("content") or "")
    return content.split(":", 1)[0].removeprefix("Results ").removeprefix("Result ")


def _stub(message: dict, ref: str) -> str:
    content = str(message.get("content") or "")
    return (f"{STUB_MARK} {_head(message)}, {len(content)} chars; the full text is kept -- "
            f"call {RECALL_TOOL} with {ref} to see it again]")


async def stub_old_results(
    messages: list[dict], *, keep_recent: int, put: Callable[[bytes], Awaitable[str]],
) -> tuple[list[dict], list[tuple[str, str]]]:
    """A copy of `messages` with every tool result but the newest
    `keep_recent` replaced by a stub; the originals go to `put` (a ledger
    blob). Returns the new list and `(ref, tool)` for each one set aside.
    A result whose blob cannot be written is left as it was.

    The refs come back because knowing a result exists is not the same
    as being able to name it. A trial on 2026-09-20 read a 638-line
    file six times, had those reads set aside at 93% of the window,
    and then wrote a `replace_in_file` SEARCH block from a read it
    could no longer see -- `recall_result` would have brought it back
    for nothing, and the refusal pointed at a full re-read instead.
    """
    positions = [i for i, m in enumerate(messages) if is_result(m)]
    old = positions[:-keep_recent] if keep_recent > 0 else positions
    out = list(messages)
    made: list[tuple[str, str]] = []
    for i in old:
        message = messages[i]
        content = str(message.get("content") or "")
        if len(content) < MIN_STUB_CHARS:
            continue
        try:
            ref = await put(content.encode("utf-8"))
        except Exception:  # noqa: BLE001 -- a failed blob keeps the result, never loses it
            continue
        out[i] = {**message, "content": _stub(message, ref)}
        made.append((ref, _head(message).removeprefix("of ").strip() or "a tool"))
    return out, made


def recall_ref(args: dict) -> str:
    """The ref a `recall_result` call names, whatever key the model used."""
    for key in ("ref", "argument", "id", "reference", "blob_ref", "result_id"):
        value = args.get(key)
        if value:
            return " ".join(str(value).split())
    values = [v for v in args.values() if isinstance(v, str) and v.strip()]
    return values[0].strip() if values else ""


__all__ = ["MIN_STUB_CHARS", "NOTE_AT", "RECALL_TOOL", "STUB_AT", "STUB_MARK", "is_result", "pressure",
           "recall_ref", "stub_old_results"]
