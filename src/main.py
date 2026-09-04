"""CLI entry point: reads user input, routes it through the orchestrator to
the emotion and logic sub-agents, and synthesizes their output -- using the
persona's mood on the shared bus -- into one human-like reply.

Every dispatch is also recorded through OutcomeLog (src/orchestrator/
reflection.py), so the feedback loop has real data instead of only being
exercised by tests -- see docs/EVOLUTION.md, "Learning From Mistakes." A
'propose <topic>' (or 'improve <topic>') command drafts a skill via
SkillResearchAgent and runs it through AuditGate; per the creator's
explicit, logged policy change (docs/SOUL.md, "Self-Improvement
Philosophy"), anything that passes every check applies immediately --
apply_proposal (src/orchestrator/apply.py) enforces its own independent
scope check (src/agents/skills/ only) regardless. Applied changes land as
normal, uncommitted git changes; nothing here commits or pushes.
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
from src.cognition.claude_code_provider import ClaudeCodeProvider
from src.cognition.gemini_provider import GeminiProvider
from src.cognition.provider import CognitionRouter, DeterministicFallbackProvider
from src.memory.long_term import JSONFileMemoryStore, MemoryStore
from src.memory.shared_bus import SharedMemoryBus
from src.memory.short_term import ShortTermMemory
from src.orchestrator.apply import APPLIED_KIND, ApplyRefused, apply_proposal
from src.orchestrator.audit import REJECTED_KIND, AuditGate
from src.orchestrator.consolidation import run_consolidation
from src.orchestrator.health import HealthMonitor, Severity
from src.orchestrator.reflection import Outcome, OutcomeLog, ReflectionAgent
from src.orchestrator.router import AgentRequest, Router
from src.sandboxing.sandbox import SandboxExecutor, SubprocessSandbox
from src.tools.web_fetch import FetchRefused, WebFetchTool

EXIT_COMMANDS = {"exit", "quit"}
REFLECT_COMMAND = "reflect"
PENDING_COMMAND = "pending"
PROPOSE_PREFIX = "propose "
IMPROVE_PREFIX = "improve "
FETCH_PREFIX = "fetch "
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

# Claude Code CLI is flat-rate (a Pro/Max/Team/Enterprise subscription),
# so the real constraint is call *volume* within Anthropic's own rolling
# quota window, not a dollar figure -- this call cap is a conservative
# safety net, not an attempt to reproduce Anthropic's actual (undocumented
# per-plan) limits. Anthropic's own enforcement still applies underneath
# this and surfaces as a normal ProviderUnavailable (see
# ClaudeCodeProvider) if it's ever hit first.
CLAUDE_CODE_WINDOW_SECONDS = float(
    os.environ.get("SIMORGH_CLAUDE_CODE_WINDOW_SECONDS", str(5 * 3600))
)
DEFAULT_CLAUDE_CODE_MAX_CALLS = int(os.environ.get("SIMORGH_CLAUDE_CODE_MAX_CALLS", "30"))


def build_router(
    cognition: CognitionRouter | None = None,
    short_term: ShortTermMemory | None = None,
    web_fetch: WebFetchTool | None = None,
    sandbox: SandboxExecutor | None = None,
    repo_root: Path | None = None,
) -> Router:
    """All params are optional so existing callers (and every prior test)
    get exactly the old rule-based-only behavior when omitted -- see
    LogicAgent's own fallback logic for why passing a CognitionRouter here
    doesn't change anything unless a real provider actually answers, and
    `web_fetch`/`sandbox` for why LogicAgent only offers FETCH/RUN tools
    when they're actually given.
    """
    router = Router(SharedMemoryBus())
    router.register(EmotionAgent())
    router.register(
        LogicAgent(
            cognition=cognition,
            short_term=short_term,
            web_fetch=web_fetch,
            sandbox=sandbox,
            repo_root=repo_root,
        )
    )
    router.register(SkillsAgent())
    return router


def strip_command_slash(user_input: str) -> str:
    """Accept a leading '/' as optional on any command (the common
    slash-command convention, e.g. Claude Code's own) -- '/reflect' is
    treated exactly like 'reflect' rather than silently falling through
    to plain chat, which is what used to happen.
    """
    if user_input.startswith("/"):
        return user_input[1:].strip()
    return user_input


def extract_propose_topic(user_input: str, lowered: str) -> str | None:
    """Returns the topic if `user_input` starts with 'propose ' or
    'improve ' (case-insensitively via `lowered`), else None. 'improve' is
    accepted as a plain-language alias since that's the natural way to
    ask Sim to change itself.
    """
    for prefix in (PROPOSE_PREFIX, IMPROVE_PREFIX):
        if lowered.startswith(prefix):
            return user_input[len(prefix):].strip()
    return None


def build_memory_store(path: Path = DEFAULT_MEMORY_PATH) -> MemoryStore:
    return JSONFileMemoryStore(path)


def build_cognition_router(
    store: MemoryStore,
) -> tuple[CognitionRouter, dict[str, BudgetGuard]]:
    """Real providers, each wrapped in a durable BudgetGuard, ahead of the
    free deterministic fallback -- each only activated if it's actually
    usable. With nothing configured, this is exactly the zero-dependency
    CognitionRouter it always was; nothing is required to run Simorgh.
    Per docs/EVOLUTION.md's Resilience Doctrine, a real provider is never
    registered unguarded.

    Priority order: Claude Code CLI first (a flat-rate subscription
    already being paid for, per the creator's explicit ask to prefer it
    over metered billing), then Gemini (pay-per-token), then the free
    fallback. Returns the router and a {provider_name: guard} map of
    whichever providers actually got activated, so a caller can surface
    `guard.status()` for each.
    """
    guards: dict[str, BudgetGuard] = {}
    providers: list = []

    claude_code = ClaudeCodeProvider()
    if claude_code.available():
        claude_code_guard = BudgetGuard(
            claude_code,
            store,
            Budget(
                max_calls=DEFAULT_CLAUDE_CODE_MAX_CALLS,
                window_seconds=CLAUDE_CODE_WINDOW_SECONDS,
            ),
        )
        providers.append(claude_code_guard)
        guards["claude_code_cli"] = claude_code_guard

    gemini = GeminiProvider()
    if gemini.available():
        gemini_guard = BudgetGuard(
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
        providers.append(gemini_guard)
        guards["gemini"] = gemini_guard

    providers.append(DeterministicFallbackProvider())
    return CognitionRouter(providers), guards


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
    short_term = ShortTermMemory()
    cognition, budget_guards = build_cognition_router(store)
    web_fetch = WebFetchTool(store)
    sandbox = SubprocessSandbox()
    router = build_router(
        cognition=cognition, short_term=short_term, web_fetch=web_fetch, sandbox=sandbox
    )
    outcome_log = OutcomeLog(store)
    reflection_agent = ReflectionAgent(outcome_log)
    audit_gate = AuditGate(memory=store)
    skill_research = SkillResearchAgent(cognition, audit_gate=audit_gate)
    interests = InterestTracker(store)
    health_monitor = HealthMonitor()
    print(
        "Simorgh -- 'exit'/'quit' to leave, 'reflect' for outcome review, "
        "'propose <topic>' (or 'improve <topic>') to draft, audit, and apply a skill, "
        "'pending' to see what's been applied, 'fetch <url>' for reviewed web access, "
        "'interest <topic>'/'interests'/'curious' for world-awareness, "
        "'sleep' for maintenance, 'history' for this session's recent turns, "
        "'run <code>' to execute sandboxed Python, 'budget' for LLM spend status. "
        "A leading '/' is optional on any command."
    )
    _print_cognition_status(budget_guards)
    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input:
            continue
        user_input = strip_command_slash(user_input)
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
        propose_topic = extract_propose_topic(user_input, lowered)
        if propose_topic is not None:
            propose_skill(skill_research, audit_gate, store, propose_topic)
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
            _print_budget(budget_guards)
            continue
        if lowered.startswith(FETCH_PREFIX):
            fetch_url(web_fetch, user_input[len(FETCH_PREFIX):].strip())
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
    repo_root: Path | None = None,
    max_attempts: int = 3,
) -> str:
    """Draft a skill on `topic`, run it through the audit gate, and -- if it
    passes every check (static denylist, adaptive-immunity memory, a real
    sandboxed run) -- apply it immediately, per the creator's explicit
    decision to auto-merge this narrow class (docs/SOUL.md,
    "Self-Improvement Philosophy"). If a draft is rejected, its reasons are
    fed back to the drafting agent for a corrected attempt, up to
    `max_attempts` total -- bounded self-correction, with every attempt
    still going through the full audit gate, not a shortcut around it.
    apply_proposal enforces its own independent scope check
    (src/agents/skills/ only), so a rejected or off-scope proposal is never
    written regardless of what happens here. Applied changes land as
    normal, uncommitted git changes -- nothing here commits or pushes.
    `repo_root` defaults to the current working directory; tests pass an
    isolated temp directory instead. Returns the message printed, for
    testability.
    """
    if not topic:
        message = "[usage: propose <topic>]"
        print(message)
        return message

    proposal = None
    verdict = None
    prior_reasons: list[str] | None = None
    for attempt in range(1, max_attempts + 1):
        if attempt == 1:
            print(f"[propose] drafting a skill for {topic!r}...")
        else:
            print(f"[propose] attempt {attempt}/{max_attempts}: asking for a corrected draft...")
        proposal = skill_research.draft_skill(topic, prior_reasons=prior_reasons)
        print(
            f"[propose] drafted {proposal.subject} -- running it through the audit "
            "gate (denylist, adaptive-immunity memory, then a real sandboxed run)..."
        )
        verdict = audit_gate.review(proposal)
        if verdict.approved_by_automation:
            break
        print(f"[propose] attempt {attempt} failed: {'; '.join(verdict.reasons)}")
        prior_reasons = verdict.reasons

    if not verdict.approved_by_automation:
        message = f"[rejected after {max_attempts} attempt(s)] {'; '.join(verdict.reasons)}"
        print(message)
        return message

    print("[propose] passed every check -- writing to disk...")
    try:
        target = apply_proposal(proposal, store, repo_root=repo_root)
    except ApplyRefused as exc:
        message = f"[rejected] {exc}"
        print(message)
        return message

    message = (
        f"[APPLIED] {target} -- {proposal.rationale} "
        "(passed every check and was written to disk; review with git diff/status "
        "before committing)"
    )
    print(message)
    return message


def _print_pending(store: MemoryStore) -> None:
    records = store.query(kind=APPLIED_KIND)
    if not records:
        print("[nothing applied yet -- try 'propose <topic>' or 'improve <topic>']")
        return
    for record in records:
        print(f"[applied] {record.content} -- {record.metadata.get('rationale', '')}")


def fetch_url(tool: WebFetchTool, url: str) -> str:
    """Fetch `url` via the reviewed WebFetchTool -- see src/tools/web_fetch.py
    for what's actually enforced (http/https GET only, SSRF protection,
    size/time bounds, rate limiting, logging). Returns the message printed,
    for testability; the printed content is truncated for terminal display
    even though the tool itself may have fetched more.
    """
    if not url:
        message = "[usage: fetch <url>]"
        print(message)
        return message

    print(f"[fetch] validating {url!r} (scheme, DNS resolution, private-address check)...")
    try:
        result = tool.fetch(url)
    except FetchRefused as exc:
        message = f"[refused] {exc}"
        print(message)
        return message

    print(f"[fetch] got HTTP {result.status_code}, {len(result.content)} chars read")
    display = result.content[:1000]
    more_note = " (truncated for display)" if len(result.content) > 1000 or result.truncated else ""
    message = f"[fetched] {url}{more_note}\n{display}"
    print(message)
    return message


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


def _print_budget(budget_guards: dict[str, BudgetGuard]) -> None:
    if not budget_guards:
        print("[no LLM provider configured -- nothing to budget]")
        return
    for name, guard in budget_guards.items():
        status = guard.status()
        max_calls = status["max_calls"] if status["max_calls"] is not None else "∞"
        max_cost = (
            f"${status['max_estimated_cost_usd']:.2f}"
            if status["max_estimated_cost_usd"] is not None
            else "no cap"
        )
        print(
            f"[budget: {name}] {status['calls_in_window']}/{max_calls} calls, "
            f"${status['spend_in_window_usd']:.4f} spent (cap: {max_cost})"
        )


def _print_cognition_status(budget_guards: dict[str, BudgetGuard]) -> None:
    if not budget_guards:
        print("[cognition: no real LLM provider configured -- using the free deterministic fallback only]")
        return
    if "claude_code_cli" in budget_guards:
        print(
            f"[cognition: Claude Code CLI active (subscription billing), budgeted at "
            f"{DEFAULT_CLAUDE_CODE_MAX_CALLS} calls / {CLAUDE_CODE_WINDOW_SECONDS / 3600:.0f}h]"
        )
    if "gemini" in budget_guards:
        print(
            f"[cognition: Gemini active, budgeted at ${DEFAULT_DAILY_BUDGET_USD:.2f}/"
            f"{DEFAULT_DAILY_MAX_CALLS} calls per 24h]"
        )


if __name__ == "__main__":
    run_cli()
