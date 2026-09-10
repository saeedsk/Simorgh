"""Consolidation on `system.tick.sleep` (docs/blueprint/subsystems/05-
memory.md section 4): flag contradictions, prune each durable kind, and
-- if a real Cognition is reachable -- ask for a distilled semantic
summary of the window's episodic activity (`cognition.think`,
`purpose=consolidate`). Degrades honestly: no real provider answering is
a `floor:true` reply, never a fabricated distillation (principle 4.5)."""

from __future__ import annotations

from dataclasses import dataclass, field

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Bus

from .store import MemoryEngine


#: What consolidation asks Cognition for, and the reason this constant
#: exists at all.
#:
#: The request used to carry ONE message -- the episodic window pasted
#: in as `role: "user"` with nothing said about what to do with it.
#: `purpose="consolidate"` only picks a budget (`cognition/config.py`),
#: so nothing anywhere told the model this was a transcript to summarise
#: rather than a question to answer. It answered it. Live-caught by an
#: observer on 2026-09-10, in a 22-turn CLI conversation whose window
#: happened to end on home-lab talk: the first consolidation pass stored
#:
#:   "Good question -- and it's one of the most important decisions for
#:    a home lab, because remote access is the most common thing people
#:    get wrong. ... **1. Tailscale (easiest, and what I'd suggest
#:    first)** ..."
#:
#: as `memory:semantic:1`, tagged `consolidation`. Recall then handed
#: that back as a *memory*, and Sim reported it as history. Asked "Did I
#: ever ask you about remote access or Tailscale? Be precise", it
#: answered "Yes -- precisely once ... That's the only exchange we've had
#: on the topic." The human had never said either word.
#:
#: This is the honesty rule (docs: "a tool must never succeed while
#: saying nothing true") failing at the worst possible place: a
#: fabrication written into durable memory is indistinguishable from a
#: real one forever after. The module docstring's promise -- "never a
#: fabricated distillation" -- was only ever enforced for the *floor*
#: path; a real provider was free to invent whatever it liked because
#: nobody asked it not to.
DISTILL_INSTRUCTION = (
    "You are consolidating memory. The text below is a transcript of past exchanges, "
    "NOT a question addressed to you. Do not answer it, do not advise, do not continue "
    "the conversation. Write only a short factual summary of what was actually said and "
    "what was actually learned, in the third person. Every statement must be traceable to "
    "the transcript -- add nothing, recommend nothing, and never write anything that would "
    "read as the human having said something they did not. If there is nothing worth "
    "recording, reply with exactly: NOTHING"
)

#: Prepended to the window itself, so the framing survives a provider or
#: an assembler that drops or reorders system messages.
DISTILL_PREFIX = "Transcript to summarise (do not answer it):\n\n"

#: The distillation's own opt-out. A model with nothing to record used to
#: have no way to say so and padded instead.
NOTHING = "NOTHING"


@dataclass(frozen=True)
class ConsolidationReport:
    contradictions: list[tuple[str, str, str]]
    pruned: dict[str, int] = field(default_factory=dict)
    distilled: bool = False


async def run_consolidation(
    engine: MemoryEngine, *, bus: Bus, source: str, keep_per_kind: dict[str, int],
    since: float | None = None, cognition_timeout: float = 30.0,
) -> ConsolidationReport:
    flagged = await engine.flag_contradictions(kind="semantic")
    pruned = {kind: await engine.prune(kind=kind, keep=keep) for kind, keep in keep_per_kind.items()}

    distilled = False
    filters = {"since": since} if since is not None else None
    episodic_items, _ = await engine.retrieve(query="", kinds=["episodic"], k=20, filters=filters)
    if episodic_items:
        window = "\n".join(i.content for i in episodic_items)
        request = Message.new(topics.COGNITION_THINK, source=source, payload={
            "purpose": "consolidate",
            "messages": [
                {"role": "system", "content": DISTILL_INSTRUCTION},
                {"role": "user", "content": DISTILL_PREFIX + window},
            ],
            "budget": {"max_tokens": 2_000, "max_cost_usd": 0.1},
            "require_real_provider": False,
        })
        try:
            reply = await bus.request(request, timeout=cognition_timeout)
        except Exception:  # noqa: BLE001 -- cognition unreachable: skip distillation this cycle, never fabricate one
            reply = None
        if reply is not None and reply.payload.get("ok") is not False and not reply.payload.get("floor", True):
            text = str(reply.payload.get("text", "")).strip()
            # `NOTHING` is a real answer, and storing it would be the same
            # class of mistake as storing the essay: filling durable
            # memory with something that was never said.
            if text and text.upper().strip(".!") != NOTHING:
                await engine.store(
                    kind="semantic", content=text,
                    # A reader of this record -- recall, a later
                    # consolidation, a human -- must be able to tell a
                    # distillation from a thing that happened. It could
                    # not before: `memory:semantic:1` looked exactly like
                    # a remembered exchange.
                    tags=["consolidation", "distilled"], source_ref="", confidence=None,
                )
                distilled = True

    return ConsolidationReport(contradictions=flagged, pruned=pruned, distilled=distilled)


__all__ = ["DISTILL_INSTRUCTION", "DISTILL_PREFIX", "NOTHING",
           "ConsolidationReport", "run_consolidation"]
