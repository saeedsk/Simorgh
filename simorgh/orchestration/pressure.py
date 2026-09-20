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


def _stub(message: dict, ref: str) -> str:
    content = str(message.get("content") or "")
    if message.get("role") == "tool":
        head = f"of {message.get('name') or 'a tool'}"
    else:
        head = content.split(":", 1)[0].removeprefix("Results ").removeprefix("Result ")
    return (f"{STUB_MARK} {head}, {len(content)} chars; the full text is kept -- "
            f"call {RECALL_TOOL} with {ref} to see it again]")


async def stub_old_results(
    messages: list[dict], *, keep_recent: int, put: Callable[[bytes], Awaitable[str]],
) -> tuple[list[dict], int]:
    """A copy of `messages` with every tool result but the newest
    `keep_recent` replaced by a stub; the originals go to `put` (a ledger
    blob). Returns the new list and how many were stubbed. A result whose
    blob cannot be written is left as it was."""
    positions = [i for i, m in enumerate(messages) if is_result(m)]
    old = positions[:-keep_recent] if keep_recent > 0 else positions
    out = list(messages)
    stubbed = 0
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
        stubbed += 1
    return out, stubbed


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
