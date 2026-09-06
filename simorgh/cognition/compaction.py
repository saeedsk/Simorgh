"""The graduated context-compaction pipeline (docs/blueprint/subsystems/
04-cognition.md section 5, "Compaction pipeline"; docs/KnowledgeBase/
harness-01-claude-code-deep-dive.md's five-layer pipeline). Cheap,
non-destructive interventions run before expensive, lossy ones -- never
a single blunt "summarize when full" step. This closes
docs/KnowledgeBase/harness-06-gap-analysis-simorgh.md gap #2 ("No
context-compaction pipeline in any tool loop").

**Layers 1-2** (budget reduction, snip) were built in an earlier
session. **This session adds layers 3-5**:

- Layer 3 (microcompact / reference substitution): repeated identical
  tool results collapse to a one-line reference to the first occurrence;
  whitespace runs are stripped; long previews are shortened further.
- Layer 4 (read-time collapse): a *read-time projection* -- older
  segments render as one-line headlines, the newest stay in full. The
  caller's message list is never mutated; each layer already builds new
  `_Segment`/dict objects rather than editing in place, so this
  constraint holds structurally, not just by convention.
- Layer 5 (auto-compact, last resort): one model call, via an injected
  `summarize` callable (the caller wires this to `Router.complete` with
  `purpose=consolidate`), replaces the collapsed older segments with a
  durable summary; `cognition.compact.pre`/`.done` bracket the call and
  `cognition:summaries:<session_id>` records it (04 section 4).

**Persistent-instruction protection** (roadmap 4.2; docs/KnowledgeBase/
harness-05-subsystems.md's "persistent rules ... are not really
'history,' they're configuration"): any message tagged `protected: true`
or with `role: "system"` is a *segment-level* protection recognized by
every layer below, independent of `assembler.py`'s block-level
protection -- this matters for `cognition.compact.request`, whose
caller-owned message list bypasses the assembler entirely. A protected
segment is never reduced, snipped, deduped, headlined, or folded into a
summary, no matter how much pressure the pipeline is under.

A segment here is one message in the caller-supplied list (an
approximation of the spec's "one user/assistant/tool exchange" -- exact
exchange grouping needs Orchestration's turn structure, not yet
available to Cognition alone at this scope; noted as an open question in
the original layers-1-2 build and still true here).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Awaitable, Callable

from simorgh.contracts import topics
from simorgh.contracts.envelope import Event, Message
from simorgh.contracts.protocols import Bus, Clock, Ledger

from .api import CompactedContext
from .config import Config
from .parser import preview
from .tokens import estimate_tokens

_WS_RUN_RE = re.compile(r"[ \t]{2,}")
_BLANK_LINES_RE = re.compile(r"\n{3,}")
_MICROCOMPACT_PREVIEW_THRESHOLD = 300
_MICROCOMPACT_PREVIEW_LIMIT = 250

_COMPACT_PROMPT = (
    "Summarize the following conversation segments so work can continue "
    "with less context. Preserve: requests made, decisions taken, file "
    "paths touched, and open questions. Drop: chatter and anything "
    "already resolved. Be terse -- this summary replaces the segments "
    "below in the working context.\n\n"
)

Summarizer = Callable[[str], Awaitable[str]]


def _is_protected(message: dict) -> bool:
    return bool(message.get("protected")) or message.get("role") == "system"


@dataclass
class _Segment:
    message: dict
    tokens: int
    protected: bool = False


class Compactor:
    def __init__(
        self, config: Config, ledger: Ledger | None = None, *,
        bus: Bus | None = None, source: str = "cognition", clock: Clock | None = None,
        summarize: Summarizer | None = None,
    ) -> None:
        self._config = config
        self._ledger = ledger
        self._bus = bus
        self._source = source
        self._clock = clock
        self._summarize = summarize

    async def compact(
        self, messages: list[dict], *, limit_tokens: int, allow_summarize: bool = False,
        session_id: str | None = None, purpose: str | None = None,
    ) -> CompactedContext:
        segments = [
            _Segment(m, estimate_tokens(m.get("content", "")), protected=_is_protected(m))
            for m in messages
        ]
        tokens_before = sum(s.tokens for s in segments)
        layers: list[int] = []
        summary_ref: str | None = None

        segments, changed = await self._layer1_budget_reduction(segments)
        if changed:
            layers.append(1)

        total = sum(s.tokens for s in segments)
        if total > limit_tokens * self._config.snip_trigger_fraction:
            segments = self._layer2_snip(segments, limit_tokens)
            layers.append(2)

        total = sum(s.tokens for s in segments)
        if total > limit_tokens * self._config.microcompact_trigger_fraction:
            segments, changed = self._layer3_microcompact(segments)
            if changed:
                layers.append(3)

        pre_collapse = segments
        segments, changed = self._layer4_read_time_collapse(segments)
        if changed:
            layers.append(4)

        total = sum(s.tokens for s in segments)
        if total > limit_tokens and allow_summarize:
            segments, changed, summary_ref = await self._layer5_auto_compact(
                pre_collapse, segments, limit_tokens=limit_tokens, current_tokens=total,
                session_id=session_id, purpose=purpose,
            )
            if changed:
                layers.append(5)

        rendered = "\n\n".join(f"[{s.message.get('role', 'user')}] {s.message.get('content', '')}" for s in segments)
        return CompactedContext(
            text=rendered, layers_applied=tuple(layers),
            tokens_before=tokens_before, tokens_after=sum(s.tokens for s in segments),
            summary_ref=summary_ref,
        )

    # -- layer 1: budget reduction ------------------------------------------------------
    async def _layer1_budget_reduction(self, segments: list[_Segment]) -> tuple[list[_Segment], bool]:
        cap = self._config.tool_result_max_tokens
        changed = False
        result: list[_Segment] = []
        for seg in segments:
            content = seg.message.get("content", "")
            if (
                seg.message.get("role") == "tool" and seg.tokens > cap
                and not seg.message.get("load_bearing") and not seg.protected
            ):
                ref = await self._put_blob(content) if self._ledger is not None else "unavailable"
                # Cap by characters, not just line count -- a long single
                # line (no "\n" at all) must still shrink; `splitlines()`
                # alone leaves it untouched and can even grow the total.
                preview_chars = max(0, cap * 4)
                preview_lines = "\n".join(content.splitlines()[:20])[:preview_chars]
                name = seg.message.get("name", "tool")
                replacement = f"[tool result {name} — {seg.tokens} tokens, ref: {ref}]\n{preview_lines}"
                new_msg = {**seg.message, "content": replacement}
                result.append(_Segment(new_msg, estimate_tokens(replacement)))
                changed = True
            else:
                result.append(seg)
        return result, changed

    # -- layer 2: snip --------------------------------------------------------------------
    def _layer2_snip(self, segments: list[_Segment], limit_tokens: int) -> list[_Segment]:
        keep_last = self._config.snip_keep_last_segments
        target = limit_tokens * self._config.snip_target_fraction
        head, tail = segments[:-keep_last] if keep_last else segments[:], segments[-keep_last:] if keep_last else []
        total = sum(s.tokens for s in segments)
        kept_head: list[_Segment] = []
        for seg in head:
            if total > target and not seg.protected:
                total -= seg.tokens
                continue  # drop it -- oldest non-protected segments go first
            kept_head.append(seg)
        return kept_head + tail

    # -- layer 3: microcompact (reference substitution) ------------------------------------
    def _layer3_microcompact(self, segments: list[_Segment]) -> tuple[list[_Segment], bool]:
        """Collapse repeated identical tool results to one reference;
        strip whitespace runs; shorten previews further -- scoped to
        tool-role segments, the same bloat source layer 1 targets."""
        changed = False
        seen: dict[str, int] = {}
        result: list[_Segment] = []
        for idx, seg in enumerate(segments):
            if seg.protected or seg.message.get("role") != "tool":
                result.append(seg)
                continue
            content = seg.message.get("content", "")
            load_bearing = bool(seg.message.get("load_bearing"))
            if content and content in seen and not load_bearing:
                name = seg.message.get("name", "tool")
                replacement = f"[tool result {name} — duplicate of segment {seen[content]}, ref: identical]"
                new_msg = {**seg.message, "content": replacement}
                result.append(_Segment(new_msg, estimate_tokens(replacement)))
                changed = True
                continue
            if content and content not in seen:
                seen[content] = idx
            if load_bearing:
                result.append(seg)
                continue
            shrunk = _BLANK_LINES_RE.sub("\n\n", content)
            shrunk = _WS_RUN_RE.sub(" ", shrunk)
            if len(shrunk) > _MICROCOMPACT_PREVIEW_THRESHOLD:
                shrunk = preview(shrunk, limit=_MICROCOMPACT_PREVIEW_LIMIT)
            if shrunk != content:
                result.append(_Segment({**seg.message, "content": shrunk}, estimate_tokens(shrunk)))
                changed = True
            else:
                result.append(seg)
        return result, changed

    # -- layer 4: read-time collapse --------------------------------------------------------
    def _layer4_read_time_collapse(self, segments: list[_Segment]) -> tuple[list[_Segment], bool]:
        """A read-time *projection*: builds a new list of new `_Segment`
        objects and never edits `segments` in place, so the caller's
        stored messages are never mutated (04 section 5). Always runs
        (per-spec trigger is "always", not a percentage threshold -- see
        the worked example S1, which collapses turns even at 5.8k/12k
        tokens); only counted in `layers_applied` when it actually
        collapses something."""
        keep_full = self._config.collapse_keep_full_segments
        if keep_full <= 0 or len(segments) <= keep_full:
            return segments, False
        older, newer = segments[:-keep_full], segments[-keep_full:]
        changed = False
        result: list[_Segment] = []
        for i, seg in enumerate(older):
            if seg.protected:
                result.append(seg)
                continue
            content = seg.message.get("content", "")
            role = seg.message.get("role", "user")
            name = seg.message.get("name")
            n_lines = content.count("\n") + 1 if content else 0
            label = f"{role} {name}" if name else role
            headline = f"[step {i}: {label} — {n_lines} lines]"
            result.append(_Segment({**seg.message, "content": headline}, estimate_tokens(headline)))
            changed = True
        return result + newer, changed

    # -- layer 5: auto-compact (model summarization, last resort) --------------------------
    async def _layer5_auto_compact(
        self, pre_collapse: list[_Segment], collapsed: list[_Segment], *,
        limit_tokens: int, current_tokens: int, session_id: str | None, purpose: str | None,
    ) -> tuple[list[_Segment], bool, str | None]:
        if self._summarize is None:
            return collapsed, False, None
        keep_full = self._config.collapse_keep_full_segments
        older = pre_collapse[:-keep_full] if keep_full else pre_collapse
        newer_collapsed = collapsed[-keep_full:] if keep_full else []
        older_elastic = [s for s in older if not s.protected]
        older_protected = [s for s in older if s.protected]
        if not older_elastic:
            return collapsed, False, None

        sid = session_id or "unspecified"
        await self._emit_compact_pre(sid, purpose=purpose, tokens=current_tokens)

        body = "\n\n".join(f"[{s.message.get('role', 'user')}] {s.message.get('content', '')}" for s in older_elastic)
        summary_text = (await self._summarize(_COMPACT_PROMPT + body)).strip()
        summary_content = f"[compacted summary of {len(older_elastic)} earlier steps]\n{summary_text}"
        summary_seg = _Segment({"role": "system", "content": summary_content}, estimate_tokens(summary_content))

        summary_ref = await self._store_summary(sid, summary_text)
        result = older_protected + [summary_seg] + newer_collapsed
        tokens_after = sum(s.tokens for s in result)
        await self._emit_compact_done(
            sid, layers_applied=("1", "2", "3", "4", "5"),
            tokens_before=sum(s.tokens for s in pre_collapse), tokens_after=tokens_after, summary_ref=summary_ref,
        )
        return result, True, summary_ref

    async def _store_summary(self, session_id: str, text: str) -> str | None:
        if self._ledger is None:
            return None
        try:
            ref = await self._ledger.put_blob(text.encode("utf-8"), content_type="text/plain")
        except Exception:  # noqa: BLE001 -- a blob-store failure must not block compaction
            ref = None
        try:
            await self._ledger.append(
                f"cognition:summaries:{session_id}",
                Event(
                    stream=f"cognition:summaries:{session_id}", type="summary.created", ts=self._now(),
                    trace_id="", causation_id=None,
                    payload={"text_ref": ref, "chars": len(text)},
                ),
            )
        except Exception:  # noqa: BLE001 -- durability best-effort; the reply already carries the summary
            pass
        return ref

    async def _emit_compact_pre(self, session_id: str, *, purpose: str | None, tokens: int) -> None:
        if self._bus is None:
            return
        try:
            await self._bus.publish(Message.new(
                topics.COGNITION_COMPACT_PRE, source=self._source, payload={
                    "session_id": session_id, "layer": "5", "purpose": purpose, "tokens": tokens,
                    "reason": "context still over budget after layers 1-4",
                },
            ))
        except Exception:  # noqa: BLE001 -- telemetry must never block compaction itself
            pass

    async def _emit_compact_done(
        self, session_id: str, *, layers_applied: tuple[str, ...], tokens_before: int,
        tokens_after: int, summary_ref: str | None,
    ) -> None:
        if self._bus is None:
            return
        try:
            await self._bus.publish(Message.new(
                topics.COGNITION_COMPACT_DONE, source=self._source, payload={
                    "session_id": session_id, "layer": "5", "layers_applied": list(layers_applied),
                    "tokens_before": tokens_before, "tokens_after": tokens_after, "summary_ref": summary_ref,
                },
            ))
        except Exception:  # noqa: BLE001 -- telemetry must never block compaction itself
            pass

    def _now(self) -> float:
        if self._clock is not None:
            return self._clock.now()
        import time
        return time.time()

    async def _put_blob(self, content: str) -> str:
        try:
            return await self._ledger.put_blob(content.encode("utf-8"), content_type="text/plain")
        except Exception:  # noqa: BLE001 -- a blob-store failure must not block compaction
            return "unavailable"


__all__ = ["Compactor", "Summarizer"]
