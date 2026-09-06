"""The graduated context-compaction pipeline (docs/blueprint/subsystems/
04-cognition.md section 5, "Compaction pipeline"; docs/KnowledgeBase/
harness-01.md's five-layer pipeline). Cheap, non-destructive
interventions run before expensive, lossy ones -- never a single blunt
"summarize when full" step.

**Scope this build session: layers 1-2 only** (budget reduction of
oversized tool results, and snip of the oldest conversation segments).
Layers 3-5 (microcompact, the read-time-collapse projection, and
model-generated auto-compact via `cognition.compact.pre/.done`) are
explicitly Phase 4 work -- see this package's README "What's not built
yet." The pipeline shape below is written so adding a layer is one more
method in sequence, not a redesign: each layer receives the previous
layer's `messages` and returns `(messages, layer_id_or_None)`.

A segment here is one message in the caller-supplied list (an
approximation of the spec's "one user/assistant/tool exchange" -- exact
exchange grouping needs Orchestration's turn structure, not yet
available to Cognition alone at this scope; noted as an open question).
"""

from __future__ import annotations

from dataclasses import dataclass

from simorgh.contracts.protocols import Ledger

from .api import CompactedContext
from .config import Config
from .tokens import estimate_tokens


@dataclass
class _Segment:
    message: dict
    tokens: int


class Compactor:
    def __init__(self, config: Config, ledger: Ledger | None = None) -> None:
        self._config = config
        self._ledger = ledger

    async def compact(self, messages: list[dict], *, limit_tokens: int, allow_summarize: bool = False) -> CompactedContext:
        segments = [_Segment(m, estimate_tokens(m.get("content", ""))) for m in messages]
        tokens_before = sum(s.tokens for s in segments)
        layers: list[int] = []

        segments, changed = await self._layer1_budget_reduction(segments)
        if changed:
            layers.append(1)

        total = sum(s.tokens for s in segments)
        if total > limit_tokens * self._config.snip_trigger_fraction:
            segments = self._layer2_snip(segments, limit_tokens)
            layers.append(2)

        rendered = "\n\n".join(f"[{s.message.get('role', 'user')}] {s.message.get('content', '')}" for s in segments)
        return CompactedContext(
            text=rendered, layers_applied=tuple(layers),
            tokens_before=tokens_before, tokens_after=sum(s.tokens for s in segments),
        )

    async def _layer1_budget_reduction(self, segments: list[_Segment]) -> tuple[list[_Segment], bool]:
        cap = self._config.tool_result_max_tokens
        changed = False
        result: list[_Segment] = []
        for seg in segments:
            content = seg.message.get("content", "")
            if seg.message.get("role") == "tool" and seg.tokens > cap and not seg.message.get("load_bearing"):
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

    def _layer2_snip(self, segments: list[_Segment], limit_tokens: int) -> list[_Segment]:
        keep_last = self._config.snip_keep_last_segments
        target = limit_tokens * self._config.snip_target_fraction
        head, tail = segments[:-keep_last] if keep_last else segments[:], segments[-keep_last:] if keep_last else []
        total = sum(s.tokens for s in segments)
        i = 0
        while total > target and i < len(head):
            total -= head[i].tokens
            i += 1
        return head[i:] + tail

    async def _put_blob(self, content: str) -> str:
        try:
            return await self._ledger.put_blob(content.encode("utf-8"), content_type="text/plain")
        except Exception:  # noqa: BLE001 -- a blob-store failure must not block compaction
            return "unavailable"


__all__ = ["Compactor"]
