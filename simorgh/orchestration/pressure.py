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

Masking by age (stage 17 item 7, `[orchestration] mask_after_steps`, 0 =
off): a tool result that many steps old is set aside the same way at any
pressure, and its stub carries a one-line gist made by code
(`mask_old_results`, `gist`).
"""

from __future__ import annotations

import hashlib
import re
from typing import Awaitable, Callable, Iterable

STUB_AT = 0.70
NOTE_AT = 0.85
# Tool results this short cost less than their stub is worth.
MIN_STUB_CHARS = 400
STUB_MARK = "[stubbed result"
RECALL_TOOL = "recall_result"
_RESULT_HEADS = ("Result of ", "Results of ")


def pressure(reply_payload: dict, previous: float = 0.0) -> float:
    """tokens_before / tokens_limit from a think reply.

    When the reply carries no usable compaction data (an older Cognition,
    an error or missing-compaction reply) the last known pressure
    (`previous`) is carried forward instead of dropping to 0.0, so one
    errored think does not make the session skip a due layer-A/B
    compaction. A reply that genuinely reports pressure still overwrites
    it, including a real 0.0 from an empty context.
    """
    compaction = reply_payload.get("compaction")
    if not isinstance(compaction, dict) or "tokens_before" not in compaction \
            or "tokens_limit" not in compaction:
        return previous
    try:
        before = float(compaction["tokens_before"] or 0)
        limit = float(compaction["tokens_limit"] or 0)
    except (TypeError, ValueError):
        return previous
    return before / limit if limit > 0 else previous


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


#: The longest gist a masked stub carries, in characters.
GIST_CHARS = 120
GIST_MARK = "gist:"
# What the session appends after a marker-dialect result's body; never
# part of what the result said.
_TRAILERS = ("\n\nIf the task is now finished", "\n\nYour reply also contained")
_LIST_ITEM = re.compile(r"^(?:[-*•]\s|\d+[.)]\s|\[\d+\]\s)")


def digest(content: str) -> str:
    """A result's identity for `Session.failed_results`: the session marks
    a failed result by the digest of the text it appended."""
    return hashlib.sha256(str(content).encode("utf-8")).hexdigest()[:24]


def _body(message: dict) -> str:
    """What a result said: a native result's content, or a marker-dialect
    result's text without its "Result of X:" head and the session's own
    closing instructions."""
    content = str(message.get("content") or "")
    if message.get("role") == "tool":
        return content
    head, sep, rest = content.partition(":\n")
    body = rest if sep and head.startswith(_RESULT_HEADS) else content
    for trailer in _TRAILERS:
        body = body.split(trailer, 1)[0]
    return body


def _tabular(lines: list[str]) -> bool:
    if len(lines) < 3:
        return False
    if sum(1 for line in lines if "|" in line) >= 0.8 * len(lines):
        return True
    for sep, least in (("\t", 1), (",", 2)):
        counts = {line.count(sep) for line in lines}
        if len(counts) == 1 and counts.pop() >= least:
            return True
    return False


def gist(message: dict) -> str:
    """One line saying what a result was, made by code and never by a model:
    "N rows: <first>" for tabular output, "N lines: <first>" for a list,
    otherwise its first non-empty line; at most `GIST_CHARS`."""
    raw = _body(message).splitlines()
    tabs = [line for line in raw if line.strip()]
    lines = [" ".join(line.split()) for line in tabs]
    if not lines:
        return "(empty)"
    first = lines[0]
    if _tabular(tabs):
        text = f"{len(lines)} rows: {first}"
    elif len(lines) >= 3 and sum(1 for line in lines if _LIST_ITEM.match(line)) >= 0.8 * len(lines):
        text = f"{len(lines)} lines: {first}"
    else:
        text = first
    return text if len(text) <= GIST_CHARS else text[: GIST_CHARS - 3].rstrip() + "..."


def _tool_of(message: dict) -> str:
    return _head(message).removeprefix("of ").strip() or "a tool"


async def mask_old_results(
    messages: list[dict], *, after_steps: int, put: Callable[[bytes], Awaitable[str]],
    failed: Iterable[str] = (),
) -> tuple[list[dict], list[tuple[str, str]]]:
    """A copy of `messages` with every tool result at least `after_steps`
    steps old replaced by its stub and a gist (stage 17 item 7); the
    originals go to `put`, as in `stub_old_results`, and `recall_result`
    brings any of them back in full. `after_steps <= 0` changes nothing.

    A step is one assistant message: a result's age is how many
    assistant messages follow it. Never masked, whatever their age:
    - the latest result;
    - the results of the pending step -- every result after the newest
      assistant message that precedes the latest result (a parallel batch
      is one step; its `tool_call_id`s are what that step's calls name);
    - an error the model has not yet answered: a result whose `digest` is
      in `failed`, until a later step has a result of the same tool (a
      retry) or a result that did not fail;
    - a result shorter than `MIN_STUB_CHARS`, and one whose blob cannot
      be written.
    Deterministic: the same history and the same `put` give the same
    bytes, and a stub is never masked again, so a masked message reads
    the same on every later turn.
    """
    if after_steps <= 0:
        return list(messages), []
    failed = frozenset(failed)
    positions = [i for i, m in enumerate(messages) if is_result(m)]
    if not positions:
        return list(messages), []
    assistants = [i for i, m in enumerate(messages) if m.get("role") == "assistant"]
    latest = positions[-1]
    opener = max((a for a in assistants if a < latest), default=-1)
    pending = {i for i in positions if i > opener}

    def age(i: int) -> int:
        return sum(1 for a in assistants if a > i)

    def step_of(i: int) -> int:
        return sum(1 for a in assistants if a < i)

    def answered(i: int) -> bool:
        tool, step = _tool_of(messages[i]), step_of(i)
        return any(step_of(j) > step and (_tool_of(messages[j]) == tool
                                          or digest(str(messages[j].get("content") or "")) not in failed)
                   for j in positions if j > i)

    out = list(messages)
    made: list[tuple[str, str]] = []
    for i in positions:
        message = messages[i]
        content = str(message.get("content") or "")
        if i in pending or age(i) < after_steps or len(content) < MIN_STUB_CHARS:
            continue
        if digest(content) in failed and not answered(i):
            continue
        try:
            ref = await put(content.encode("utf-8"))
        except Exception:  # noqa: BLE001 -- a failed blob keeps the result, never loses it
            continue
        out[i] = {**message, "content": f"{_stub(message, ref)} {GIST_MARK} {gist(message)}"}
        made.append((ref, _tool_of(message)))
    return out, made


def recall_ref(args: dict) -> str:
    """The ref a `recall_result` call names, whatever key the model used."""
    for key in ("ref", "argument", "id", "reference", "blob_ref", "result_id"):
        value = args.get(key)
        if value:
            return " ".join(str(value).split())
    values = [v for v in args.values() if isinstance(v, str) and v.strip()]
    return values[0].strip() if values else ""


__all__ = ["GIST_CHARS", "GIST_MARK", "MIN_STUB_CHARS", "digest", "gist", "mask_old_results", "NOTE_AT", "RECALL_TOOL", "STUB_AT", "STUB_MARK", "is_result", "pressure",
           "recall_ref", "stub_old_results"]
