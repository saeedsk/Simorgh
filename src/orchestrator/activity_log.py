"""Unified activity log: a queryable, chronological audit trail across
everything Sim does -- conversation, tool use, self-modification, spend,
and rejections -- so the creator (or Claude Code, working on this
codebase) can see exactly what happened and why, not just the final
reply. Directive 8 (Transparency, docs/SOUL.md) made concrete and
queryable, rather than "nothing is silent" left implicit across several
separately-logged MemoryStore kinds.

This module introduces no new storage -- everything already gets written
to the same MemoryStore (~/.simorgh/memory.jsonl by default) by its own
component (OutcomeLog, BudgetGuard, WebFetchTool, AuditGate,
apply_proposal, InterestTracker). ActivityLog adds two record kinds this
project didn't have anywhere before:

- CONVERSATION_KIND: the actual back-and-forth, durably. ShortTermMemory
  already holds recent turns, but only in-process -- gone the moment the
  CLI exits. This is the same content, kept.
- TOOL_CALL_KIND: individual FETCH:/RUN:/READ: steps from LogicAgent's
  and SkillResearchAgent's tool loops. Previously these were only
  print()ed for the person watching the terminal live -- if nobody was
  watching, that trail was gone. Now every step is recorded.

...plus a read-side query/formatting layer (`recent()`, `format_entry()`)
that merges all of the above -- old and new kinds alike -- into one
chronological timeline, since scattered per-kind queries don't answer
"what did Sim actually do" on their own.
"""

from __future__ import annotations

import time

from src.cognition.tool_protocol import preview
from src.memory.long_term import MemoryRecord, MemoryStore
from src.orchestrator.console_style import style

CONVERSATION_KIND = "conversation_turn"
TOOL_CALL_KIND = "tool_call"

# Every kind ActivityLog knows how to pull into a unified timeline, named
# here as the single source of truth rather than each caller guessing
# which kinds matter. Kept in sync by hand with the other modules that
# define these kind names (OutcomeLog.KIND, apply.APPLIED_KIND,
# audit.REJECTED_KIND, budget.SPEND_KIND, web_fetch.FETCH_KIND,
# InterestTracker.KIND) -- there's no cross-module registry, so adding a
# new kind elsewhere means adding it here too if it should show up in
# audit output.
ALL_KINDS = (
    CONVERSATION_KIND,
    TOOL_CALL_KIND,
    "outcome",
    "takeaway",
    "applied_skill",
    "applied_source_patch",
    "rejected_proposal",
    "web_fetch",
    "llm_spend",
    "interest",
)

# Purely cosmetic (see console_style.style): one glyph per record kind so
# a skimmed log reads by shape, not just by parsing text -- the creator's
# ask that reading the log be "a pleasant and easy to do... activity."
# Never load-bearing: format_entry falls back to a plain "•" for any kind
# not listed here, so a new kind never breaks formatting.
_KIND_ICONS = {
    CONVERSATION_KIND: "💬",
    TOOL_CALL_KIND: "🔧",
    "outcome": "🎯",
    "takeaway": "💡",
    "applied_skill": "✨",
    "applied_source_patch": "🛠️ ",
    "rejected_proposal": "🚫",
    "web_fetch": "🌐",
    "llm_spend": "💰",
    "interest": "🔭",
}

# Per-tool glyphs for TOOL_CALL_KIND entries specifically, layered on top
# of the generic 🔧 above so FETCH/RUN/READ/RECALL/DRAFT/TEST_SUITE are
# each visually distinct at a glance.
_TOOL_ICONS = {
    "FETCH": "🌐",
    "RUN": "▶️ ",
    "READ": "📖",
    "RECALL": "🧠",
    "DRAFT": "📝",
    "TEST_SUITE": "🧪",
}

_OK = "✅"
_FAIL = "❌"


class ActivityLog:
    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def record_conversation_turn(self, user_text: str, reply: str) -> None:
        self._store.remember(CONVERSATION_KIND, user_text, reply=reply)

    def record_tool_call(
        self,
        agent: str,
        tool: str,
        request: str,
        result_summary: str,
        succeeded: bool,
    ) -> None:
        self._store.remember(
            TOOL_CALL_KIND,
            f"{tool}: {request}",
            agent=agent,
            tool=tool,
            request=request,
            result_summary=result_summary,
            succeeded=succeeded,
        )

    def recent(
        self, limit: int = 20, kinds: tuple[str, ...] | None = None
    ) -> list[MemoryRecord]:
        """Most recent activity across `kinds` (default: every kind
        ActivityLog knows about), merged and sorted newest-first.
        """
        wanted = kinds or ALL_KINDS
        pool: list[MemoryRecord] = []
        for kind in wanted:
            pool.extend(self._store.query(kind=kind, limit=limit))
        pool.sort(key=lambda r: r.created_at, reverse=True)
        return pool[:limit]

    def since(
        self, timestamp: float, limit: int = 200, kinds: tuple[str, ...] | None = None
    ) -> list[MemoryRecord]:
        """Every activity record at or after `timestamp`, across `kinds`
        (default: every kind ActivityLog knows about), oldest-first --
        chronological narrative order, unlike `recent()`'s newest-first,
        since this is meant to be read as "here's what happened," not a
        dashboard. `limit` bounds how many records are pulled *per kind*
        before filtering, not the size of the final result -- a very
        active window can still return more than `limit` total entries.
        """
        wanted = kinds or ALL_KINDS
        pool: list[MemoryRecord] = []
        for kind in wanted:
            pool.extend(
                r for r in self._store.query(kind=kind, limit=limit) if r.created_at >= timestamp
            )
        pool.sort(key=lambda r: r.created_at)
        return pool

    def since_last_turn(self, limit: int = 200) -> list[MemoryRecord]:
        """Everything recorded from the previous conversation turn
        onward -- i.e. what actually happened (tool calls, outcomes,
        takeaways, any applied change) while Sim was working on the most
        recent prompt. The direct answer to "what happened between my
        last prompt and now": with fewer than two conversation turns
        logged yet, there's no earlier turn to bound "since" by, so this
        falls back to `recent()` (still newest-first in that case, since
        there's no real "since" window to narrate chronologically).
        """
        turns = self._store.query(kind=CONVERSATION_KIND, limit=2)
        if len(turns) < 2:
            return self.recent(limit=limit)
        return self.since(turns[1].created_at, limit=limit)

    @staticmethod
    def format_entry(record: MemoryRecord) -> str:
        ts = style(time.strftime("%H:%M:%S", time.localtime(record.created_at)), "dim")
        icon = _KIND_ICONS.get(record.kind, "•")
        meta = record.metadata

        def status_of(succeeded: object) -> str:
            return style(_OK, "green") if succeeded else style(_FAIL, "red", "bold")

        if record.kind == CONVERSATION_KIND:
            return (
                f"{ts} {icon} {style('you', 'cyan', 'bold')} {record.content!r}\n"
                f"{'':>8} {style('↳ sim', 'magenta', 'bold')} {meta.get('reply', '')!r}"
            )
        if record.kind == TOOL_CALL_KIND:
            tool = str(meta.get("tool"))
            tool_icon = _TOOL_ICONS.get(tool, "🔩")
            # A second safety net, not just the first: callers now
            # truncate before recording (src/cognition/tool_protocol.py,
            # preview()), but an older record written before that fix --
            # or any future caller that forgets -- still renders safely
            # here rather than flooding the terminal.
            request = preview(str(meta.get("request", "")))
            result_summary = preview(str(meta.get("result_summary", "")))
            return (
                f"{ts} {icon} {tool_icon} {style(tool, 'blue', 'bold')} "
                f"({meta.get('agent')}) {status_of(meta.get('succeeded'))} "
                f"{request} → {result_summary}"
            )
        if record.kind == "outcome":
            return (
                f"{ts} {icon} {meta.get('agent')} {status_of(meta.get('succeeded'))} "
                f"{meta.get('request_text', '')!r} → {record.content!r}"
            )
        if record.kind == "takeaway":
            return (
                f"{ts} {icon} {style('takeaway', 'yellow', 'bold')} "
                f"({meta.get('agent')}) {record.content}"
            )
        if record.kind == "applied_skill":
            return (
                f"{ts} {icon} {style('APPLIED · skill', 'green', 'bold')} "
                f"{record.content} — {meta.get('rationale', '')}"
            )
        if record.kind == "applied_source_patch":
            return (
                f"{ts} {icon}{style('APPLIED · self-patch', 'green', 'bold')} "
                f"{record.content} — {meta.get('rationale', '')} "
                f"{style('(' + meta.get('test_summary', '') + ')', 'dim')}"
            )
        if record.kind == "rejected_proposal":
            return (
                f"{ts} {icon} {style('REJECTED', 'red', 'bold')} "
                f"(subject={meta.get('subject')}): {meta.get('reasons')}"
            )
        if record.kind == "web_fetch":
            return (
                f"{ts} {icon} fetch {status_of(meta.get('succeeded'))} "
                f"{record.content} — {meta.get('note', '')}"
            )
        if record.kind == "llm_spend":
            cost = f"${meta.get('cost_usd', 0):.4f}"
            return f"{ts} {icon} {style(record.content, 'orange')} spent {style(cost, 'orange', 'bold')}"
        if record.kind == "interest":
            return f"{ts} {icon} {record.content} — {meta.get('why', '')}"
        return f"{ts} {icon} {record.kind}: {record.content}"
