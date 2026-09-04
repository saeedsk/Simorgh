"""CLI entry point: reads user input, routes it through the orchestrator to
the emotion and logic sub-agents, and synthesizes their output -- using the
persona's mood on the shared bus -- into one human-like reply.

Every dispatch is also recorded through OutcomeLog (src/orchestrator/
reflection.py), so the feedback loop has real data instead of only being
exercised by tests -- see docs/EVOLUTION.md, "Learning From Mistakes." A
'propose <topic>' command drafts a skill via SkillResearchAgent and runs it
through AuditGate; anything that passes automated checks is logged as
pending, never merged automatically -- 'pending' lists what's awaiting the
creator's actual review. See docs/EVOLUTION.md milestone 10.
"""

from __future__ import annotations

import os
from pathlib import Path

from src.agents.emotion.base import EmotionAgent
from src.agents.interests import InterestTracker
from src.agents.logic.base import LogicAgent
from src.agents.skills.base import SkillsAgent
from src.agents.skills.research import SkillResearchAgent
from src.cognition.budget import Budget, BudgetGuard
from src.cognition.gemini_provider import GeminiProvider
from src.cognition.provider import CognitionRouter, DeterministicFallbackProvider
from src.memory.long_term import JSONFileMemoryStore, MemoryStore
from src.memory.shared_bus import SharedMemoryBus
from src.memory.short_term import ShortTermMemory
from src.orchestrator.audit import REJECTED_KIND, AuditGate
from src.orchestrator.consolidation import run_consolidation
from src.orchestrator.health import HealthMonitor, Severity
from src.orchestrator.reflection import Outcome, OutcomeLog, ReflectionAgent
from src.orchestrator.router import AgentRequest, Router

EXIT_COMMANDS = {"exit", "quit"}
REFLECT_COMMAND = "reflect"
PENDING_COMMAND = "pending"
PROPOSE_PREFIX = "propose "
PENDING_KIND = "pending_approval"
INTEREST_PREFIX = "interest "
INTERESTS_COMMAND = "interests"
CURIOUS_COMMAND = "curious"
SLEEP_COMMAND = "sleep"
HISTORY_COMMAND = "history"
RUN_PREFIX = "run "
BUDGET_COMMAND = "budget"
DEFAULT_MEMORY_PATH = Path.home() / ".simorgh" / "memory.jsonl"

# Gemini 3.8 Flash pricing as of this writing ($/1M tokens) -- verify at
# ai.google.dev/pricing before relying on this for real budgeting; prices
# and model names in this space change often.
GEMINI_PRICE_PER_1M_INPUT = 0.75
GEMINI_PRICE_PER_1M_OUTPUT = 3.75
DEFAULT_DAILY_BUDGET_USD = float(os.environ.get("SIMORGH_LLM_DAILY_BUDGET_USD", "1.0"))
DEFAULT_DAILY_MAX_CALLS = int(os.environ.get("SIMORGH_LLM_DAILY_MAX_CALLS", "50"))


def build_router() -> Router:
    router = Router(SharedMemoryBus())
    router.register(EmotionAgent())
    router.register(LogicAgent())
    router.register(SkillsAgent())
    return router


def build_memory_store(path: Path = DEFAULT_MEMORY_PATH) -> MemoryStore:
    return JSONFileMemoryStore(path)


def build_cognition_router(
    store: MemoryStore,
) -> tuple[CognitionRouter, BudgetGuard | None]:
    """A real Gemini provider, wrapped in a durable BudgetGuard, ahead of
    the free deterministic fallback -- only if GEMINI_API_KEY (or
    GOOGLE_API_KEY) is actually set. With no key configured, this is
    exactly the zero-dependency CognitionRouter it always was; no key is
    required to run Simorgh. Per docs/EVOLUTION.md's Resilience Doctrine,
    a real provider is never registered unguarded. Returns the router and
    the guard (or None, if no key is configured) so a caller can surface
    `guard.status()`.
    """
    gemini = GeminiProvider()
    if not gemini.available():
        return CognitionRouter([DeterministicFallbackProvider()]), None

    guard = BudgetGuard(
        gemini,
        store,
        Budget(
            max_calls=DEFAULT_DAILY_MAX_CALLS,
            max_estimated_cost_usd=DEFAULT_DAILY_BUDGET_USD,
            window_seconds=86400.0,
        ),
        price_per_1m_input=GEMINI_PRICE_PER_1M_INPUT,
        price_per_1m_output=GEMINI_PRICE_PER_1M_OUTPUT,
    )
    return CognitionRouter([guard, DeterministicFallbackProvider()]), guard


def build_outcome_log(store: MemoryStore | None = None) -> OutcomeLog:
    return OutcomeLog(store or build_memory_store())


def synthesize(reaction: str, response: str, bus: SharedMemoryBus) -> str:
    """Combine the emotion agent's reaction and the logic agent's response
    into one reply, checking the persona's live mood on the shared bus to
    decide whether to flag that it's under heavy cognitive load.
    """
    parts = [reaction]
    if bus.read().cognitive_load >= 0.6:
        parts.append("(taking a moment to think this through.)")
    parts.append(response)
    return " ".join(parts)


def handle_turn(
    router: Router,
    text: str,
    outcome_log: OutcomeLog | None = None,
    health_monitor: HealthMonitor | None = None,
) -> str:
    request = AgentRequest(text=text)
    reaction = _dispatch_and_record(router, "emotion", request, outcome_log)
    response = _dispatch_and_record(router, "logic", request, outcome_log)
    reply = synthesize(reaction, response, router.bus)

    if health_monitor is not None:
        critical = [
            issue
            for issue in health_monitor.enforce(router.bus)
            if issue.severity is Severity.CRITICAL
        ]
        if critical:
            reasons = "; ".join(issue.description for issue in critical)
            reply += f" [self-correction: {reasons} -- resetting to a calmer baseline]"

    return reply


def _dispatch_and_record(
    router: Router, name: str, request: AgentRequest, outcome_log: OutcomeLog | None
) -> str:
    try:
        response = router.dispatch(name, request)
    except Exception as exc:  # noqa: BLE001 -- a failing sub-agent must not
        # crash the CLI turn; it becomes a recorded, visible failure instead
        if outcome_log is not None:
            outcome_log.record(
                Outcome(
                    agent=name,
                    request_text=request.text,
                    output="",
                    succeeded=False,
                    note=repr(exc),
                )
            )
        return f"[{name} agent failed: {exc}]"

    if outcome_log is not None:
        outcome_log.record(
            Outcome(
                agent=name,
                request_text=request.text,
                output=response.output,
                succeeded=True,
            )
        )
    return response.output


def run_cli() -> None:
    store = build_memory_store()
    router = build_router()
    outcome_log = OutcomeLog(store)
    reflection_agent = ReflectionAgent(outcome_log)
    audit_gate = AuditGate(memory=store)
    cognition, budget_guard = build_cognition_router(store)
    skill_research = SkillResearchAgent(cognition)
    interests = InterestTracker(store)
    health_monitor = HealthMonitor()
    short_term = ShortTermMemory()
    print(
        "Simorgh -- 'exit'/'quit' to leave, 'reflect' for outcome review, "
        "'propose <topic>' to draft a skill, 'pending' for unmerged proposals, "
        "'interest <topic>'/'interests'/'curious' for world-awareness, "
        "'sleep' for maintenance, 'history' for this session's recent turns, "
        "'run <code>' to execute sandboxed Python, 'budget' for LLM spend status."
    )
    if GeminiProvider().available():
        print(
            f"[cognition: Gemini active, budgeted at ${DEFAULT_DAILY_BUDGET_USD:.2f}/"
            f"{DEFAULT_DAILY_MAX_CALLS} calls per 24h]"
        )
    else:
        print("[cognition: no GEMINI_API_KEY set -- using the free deterministic fallback only]")
    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input:
            continue
        lowered = user_input.lower()
        if lowered in EXIT_COMMANDS:
            break
        if lowered == REFLECT_COMMAND:
            _print_reflection(reflection_agent)
            continue
        if lowered == PENDING_COMMAND:
            _print_pending(store)
            continue
        if lowered.startswith(PROPOSE_PREFIX):
            propose_skill(
                skill_research, audit_gate, store, user_input[len(PROPOSE_PREFIX):].strip()
            )
            continue
        if lowered.startswith(INTEREST_PREFIX):
            note_interest(interests, user_input[len(INTEREST_PREFIX):].strip())
            continue
        if lowered == INTERESTS_COMMAND:
            _print_interests(interests)
            continue
        if lowered == CURIOUS_COMMAND:
            _follow_up(interests)
            continue
        if lowered == SLEEP_COMMAND:
            _run_sleep(store, reflection_agent)
            continue
        if lowered == HISTORY_COMMAND:
            _print_history(short_term)
            continue
        if lowered.startswith(RUN_PREFIX):
            run_skill_code(router, outcome_log, user_input[len(RUN_PREFIX):])
            continue
        if lowered == BUDGET_COMMAND:
            _print_budget(budget_guard)
            continue
        reply = handle_turn(router, user_input, outcome_log, health_monitor)
        short_term.add(user_input, reply)
        print(reply)


def run_skill_code(router: Router, outcome_log: OutcomeLog, code: str) -> str:
    """Execute `code` via the sandboxed skills agent (src/agents/skills/
    base.py -> src/sandboxing/sandbox.py) and return its output. Returns
    the message printed, for testability.
    """
    if not code:
        message = "[usage: run <code>]"
        print(message)
        return message
    output = _dispatch_and_record(router, "skills", AgentRequest(text=code), outcome_log)
    print(output)
    return output


def _print_reflection(reflection_agent: ReflectionAgent) -> None:
    proposals = reflection_agent.reflect()
    if not proposals:
        print("[no concerning patterns in recent outcomes]")
        return
    for proposal in proposals:
        print(f"[proposal] {proposal.rationale}")


def propose_skill(
    skill_research: SkillResearchAgent,
    audit_gate: AuditGate,
    store: MemoryStore,
    topic: str,
) -> str:
    """Draft a skill on `topic`, run it through the audit gate, and -- if it
    passes automated checks -- log it as pending the creator's actual
    review. Nothing is ever merged here; this only ever produces something
    for a human to look at. Returns the message printed, for testability.
    """
    if not topic:
        message = "[usage: propose <topic>]"
        print(message)
        return message

    proposal = skill_research.draft_skill(topic)
    verdict = audit_gate.review(proposal)

    if not verdict.approved_by_automation:
        message = f"[rejected] {'; '.join(verdict.reasons)}"
        print(message)
        return message

    store.remember(
        PENDING_KIND, proposal.subject, code=proposal.code, rationale=proposal.rationale
    )
    message = (
        f"[PENDING YOUR APPROVAL] {proposal.subject} -- {proposal.rationale} "
        "(automated checks passed; nothing merges without your review)"
    )
    print(message)
    return message


def _print_pending(store: MemoryStore) -> None:
    records = store.query(kind=PENDING_KIND)
    if not records:
        print("[no proposals pending approval]")
        return
    for record in records:
        print(f"[pending] {record.content} -- {record.metadata.get('rationale', '')}")


def note_interest(tracker: InterestTracker, topic: str) -> str:
    """Start tracking `topic`. Returns the message printed, for testability."""
    if not topic:
        message = "[usage: interest <topic>]"
        print(message)
        return message
    tracker.note_interest(topic, why="noted by the creator")
    message = f"[noted] now tracking interest in {topic!r}"
    print(message)
    return message


def _print_interests(tracker: InterestTracker) -> None:
    interests = tracker.list_interests()
    if not interests:
        print("[no tracked interests yet -- try 'interest <topic>']")
        return
    for interest in interests:
        status = "never followed up" if interest.last_followed_up is None else "followed up"
        print(f"[interest] {interest.topic} ({status}) -- {interest.why}")


def _follow_up(tracker: InterestTracker) -> None:
    overdue = tracker.least_recently_followed_up()
    if overdue is None:
        print("[nothing to be curious about yet -- try 'interest <topic>' first]")
        return
    items = tracker.follow_up(overdue.topic)
    if not items:
        print(
            f"[curious about {overdue.topic!r}] no updates available "
            "(no real WorldFeed configured yet -- see src/agents/interests.py)"
        )
        return
    for item in items:
        print(f"[{overdue.topic}] {item.title}: {item.summary}")


def _run_sleep(store: MemoryStore, reflection_agent: ReflectionAgent) -> None:
    report = run_consolidation(
        store, reflection_agent, keep_per_kind={"outcome": 200, REJECTED_KIND: 200}
    )
    pruned = ", ".join(f"{kind}: {count}" for kind, count in report.pruned_counts.items())
    print(f"[sleep] pruned -- {pruned or 'nothing to prune'}")
    if not report.proposals:
        print("[sleep] no concerning patterns in recent outcomes")
        return
    for proposal in report.proposals:
        print(f"[sleep proposal] {proposal.rationale}")


def _print_history(short_term: ShortTermMemory) -> None:
    if len(short_term) == 0:
        print("[no turns yet this session]")
        return
    print(short_term.as_context())


def _print_budget(budget_guard: BudgetGuard | None) -> None:
    if budget_guard is None:
        print("[no LLM provider configured -- nothing to budget]")
        return
    status = budget_guard.status()
    print(
        f"[budget] {status['calls_in_window']}/{status['max_calls']} calls, "
        f"${status['spend_in_window_usd']:.4f}/${status['max_estimated_cost_usd']:.2f} "
        "spent in the current 24h window"
    )


if __name__ == "__main__":
    run_cli()
