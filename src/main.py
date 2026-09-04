"""CLI entry point: reads user input, routes it through the orchestrator to
the emotion and logic sub-agents, and synthesizes their output -- using the
persona's mood on the shared bus -- into one human-like reply.

Every dispatch is also recorded through OutcomeLog (src/orchestrator/
reflection.py), so the feedback loop has real data instead of only being
exercised by tests -- see docs/EVOLUTION.md, "Learning From Mistakes."
Every dispatch is also durably logged through ActivityLog
(src/orchestrator/activity_log.py), forming a unified, chronological
audit trail across conversation, tool use, and self-modification -- see
the 'log' command below.

A 'propose <topic>' (or 'improve <topic>') command drafts a brand-new
skill via SkillResearchAgent and runs it through AuditGate. A
'patch <path> <description>' command drafts a revision to one of Sim's
own EXISTING source files via SelfPatchAgent, and -- if it also survives
a fresh run of this repository's entire test suite in an isolated copy
-- applies it and relaunches the process so the change takes effect (see
src/orchestrator/self_patch.py). Per the creator's explicit, logged
policy change (docs/SOUL.md, "Self-Improvement Philosophy"), anything
that passes every check in either pipeline applies immediately --
apply_proposal/apply_source_patch (src/orchestrator/apply.py) each
enforce their own independent scope check regardless (src/agents/skills/
only for skills; src/ generally, minus protected files, for patches).
Applied changes land as normal, uncommitted git changes; nothing here
commits or pushes.
"""

from __future__ import annotations

import difflib
import os
from pathlib import Path

try:
    import readline  # noqa: F401 -- imported for its side effect: input() gains
    # arrow-key editing, backspace/word-editing, and (once history is loaded
    # below) up/down recall. Not available on Windows' stock CPython.
except ImportError:  # pragma: no cover -- platform-dependent
    readline = None

from src.agents.emotion.base import EmotionAgent
from src.agents.interests import InterestTracker
from src.agents.logic.base import LogicAgent
from src.agents.skills.base import SkillsAgent
from src.agents.skills.registry import build_invocation_code, list_applied_skills, load_skill_source
from src.agents.skills.research import SkillResearchAgent
from src.cognition.budget import Budget, BudgetGuard
from src.cognition.claude_code_provider import ClaudeCodeProvider
from src.cognition.gemini_provider import GeminiProvider
from src.cognition.provider import CognitionRouter, DeterministicFallbackProvider
from src.cognition.tool_protocol import preview
from src.memory.long_term import JSONFileMemoryStore, MemoryStore
from src.memory.shared_bus import SharedMemoryBus
from src.memory.short_term import ShortTermMemory
from src.orchestrator.activity_log import ActivityLog
from src.orchestrator.apply import (
    APPLIED_KIND,
    APPLIED_PATCH_KIND,
    ApplyRefused,
    apply_proposal,
    apply_source_patch,
)
from src.orchestrator.audit import REJECTED_KIND, AuditGate
from src.orchestrator.consolidation import run_consolidation
from src.orchestrator.console_style import style
from src.orchestrator.health import HealthMonitor, Severity
from src.orchestrator.reflection import Outcome, OutcomeLog, ReflectionAgent
from src.orchestrator.router import AgentRequest, Router
from src.orchestrator.self_patch import SelfPatchAgent, check_main_py_invariants, relaunch, run_isolated_test_suite
from src.sandboxing.sandbox import SandboxExecutor, SubprocessSandbox
from src.tools.web_fetch import FetchRefused, WebFetchTool

EXIT_COMMANDS = {"exit", "quit"}
REFLECT_COMMAND = "reflect"
PENDING_COMMAND = "pending"
PROPOSE_PREFIX = "propose "
IMPROVE_PREFIX = "improve "
PATCH_PREFIX = "patch "
FETCH_PREFIX = "fetch "
INTEREST_PREFIX = "interest "
INTERESTS_COMMAND = "interests"
CURIOUS_COMMAND = "curious"
SLEEP_COMMAND = "sleep"
HISTORY_COMMAND = "history"
RUN_PREFIX = "run "
BUDGET_COMMAND = "budget"
LOG_COMMAND = "log"
USE_PREFIX = "use "
SKILLS_COMMAND = "skills"
DEFAULT_MEMORY_PATH = Path.home() / ".simorgh" / "memory.jsonl"
DEFAULT_HISTORY_PATH = Path.home() / ".simorgh" / "cli_history"
HISTORY_LENGTH = 1000

# Command names autocorrect_command below will guess against -- kept as
# bare words (no prefixes/args) since correction only ever touches the
# first token of a line. Deliberately excludes anything that would be
# dangerous to guess wrong; the worst case of a bad guess here is Sim
# misreads a chat message as a command, which is announced, not silent,
# and every command it could guess into is itself already reviewed and
# bounded (see docs/SOUL.md).
_KNOWN_COMMAND_WORDS = (
    REFLECT_COMMAND,
    PENDING_COMMAND,
    "propose",
    "improve",
    "patch",
    "fetch",
    "interest",
    INTERESTS_COMMAND,
    CURIOUS_COMMAND,
    SLEEP_COMMAND,
    HISTORY_COMMAND,
    "run",
    "use",
    SKILLS_COMMAND,
    BUDGET_COMMAND,
    LOG_COMMAND,
    "exit",
    "quit",
)

# Gemini 3.8 Flash pricing as of this writing ($/1M tokens) -- verify at
# ai.google.dev/pricing before relying on this for real budgeting; prices
# and model names in this space change often.
GEMINI_PRICE_PER_1M_INPUT = 0.75
GEMINI_PRICE_PER_1M_OUTPUT = 3.75
DEFAULT_DAILY_BUDGET_USD = float(os.environ.get("SIMORGH_LLM_DAILY_BUDGET_USD", "1.0"))
# Raised from 50 -> 1500 at the creator's explicit request: with the
# $1.00/day dollar cap unchanged, the dollar cap is the real limit in
# practice (a Flash-tier call is a fraction of a cent) -- the call-count
# cap exists as a sanity ceiling, not the primary control, so it's set
# high enough to not be the thing that silently kills LLM access first
# (see docs/EVOLUTION.md, "Sim doesn't have LLM access anymore," where
# the 50-call default was exactly what did that).
DEFAULT_DAILY_MAX_CALLS = int(os.environ.get("SIMORGH_LLM_DAILY_MAX_CALLS", "1500"))

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
    activity_log: ActivityLog | None = None,
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
            activity_log=activity_log,
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


def autocorrect_command(user_input: str, lowered: str) -> tuple[str, str, str | None]:
    """If the first word of `user_input` looks like a near-miss typo of a
    known command (e.g. 'porpose', 'ptach', 'rlefect') -- close but not an
    exact match -- returns (corrected_input, corrected_lowered,
    original_word) so the caller can dispatch on the corrected text while
    still telling the user what was guessed; correction is never silent.
    Returns `(user_input, lowered, None)` unchanged when the first word
    already matches exactly, is too short for "close" to mean anything
    but coincidence, or isn't close enough to any known command --
    ordinary chat is left alone.
    """
    parts = user_input.split(None, 1)
    if not parts:
        return user_input, lowered, None
    first_word = parts[0]
    first_lower = first_word.lower()
    if first_lower in _KNOWN_COMMAND_WORDS or len(first_word) < 4:
        return user_input, lowered, None
    matches = difflib.get_close_matches(first_lower, _KNOWN_COMMAND_WORDS, n=1, cutoff=0.75)
    if not matches:
        return user_input, lowered, None
    rest = parts[1] if len(parts) > 1 else ""
    corrected_input = f"{matches[0]} {rest}".strip() if rest else matches[0]
    return corrected_input, corrected_input.lower(), first_word


def _setup_readline(history_path: Path = DEFAULT_HISTORY_PATH) -> None:
    if readline is None:
        return
    history_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        readline.read_history_file(history_path)
    except (FileNotFoundError, OSError):
        pass
    readline.set_history_length(HISTORY_LENGTH)


def _save_readline_history(history_path: Path = DEFAULT_HISTORY_PATH) -> None:
    if readline is None:
        return
    try:
        readline.write_history_file(history_path)
    except OSError:
        pass


_COMMANDS_HELP: tuple[tuple[str, str, str], ...] = (
    ("reflect", "Review recent outcomes for patterns worth addressing.", "reflect"),
    (
        "propose <topic>",
        "Draft, audit, and apply a brand-new skill.",
        "propose a rocket-thrust calculator",
    ),
    (
        "improve <topic>",
        "Alias for 'propose' -- reads more naturally as a request.",
        "improve error handling",
    ),
    (
        "patch <path> <description>",
        "Revise your own existing source, run this repo's entire test "
        "suite against it in an isolated copy, and relaunch if it passes.",
        "patch src/agents/logic/base.py handle repeated 403s better",
    ),
    ("pending", "List every applied skill and self-patch so far.", "pending"),
    ("skills", "List every applied skill you can actually run by name.", "skills"),
    (
        "use <skill name>",
        "Actually run an applied skill (fresh from disk, no relaunch needed).",
        "use rocketry",
    ),
    (
        "log [last]",
        "Show the unified activity/audit trail; 'last' narrows it to "
        "everything since the previous turn.",
        "log last",
    ),
    ("fetch <url>", "Fetch a web page through the reviewed, SSRF-safe tool.", "fetch https://example.com"),
    ("interest <topic>", "Start tracking a topic of curiosity.", "interest rocketry"),
    ("interests", "List everything currently being tracked.", "interests"),
    ("curious", "Follow up on the least-recently-checked interest.", "curious"),
    ("sleep", "Run maintenance: prune old records, surface patterns.", "sleep"),
    ("history", "Show this session's recent conversation turns.", "history"),
    ("run <code>", "Execute Python in the sandbox.", "run print(2 + 2)"),
    ("budget", "Show LLM spend/call status against the configured caps.", "budget"),
    ("exit / quit", "Leave.", "exit"),
)


def _print_banner() -> None:
    print(
        style("Simorgh", "magenta", "bold")
        + " -- talk to me directly, or use one of these commands "
        "(a leading '/' is optional on any of them):\n"
    )
    # Pad the plain label BEFORE styling it -- ANSI escape codes count
    # toward len() but occupy no visual width, so padding a styled string
    # directly would misalign the columns.
    width = max(len(name) for name, _, _ in _COMMANDS_HELP)
    for name, description, example in _COMMANDS_HELP:
        label = f"/{name}".ljust(width + 1)
        print(f"  {style(label, 'cyan', 'bold')} {description}")
        print(f"  {' ' * (width + 1)} {style('e.g. ' + example, 'dim')}")
    print()


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


def extract_patch_args(user_input: str, lowered: str) -> tuple[str, str] | None:
    """Returns (subject_path, description) if `user_input` is
    'patch <repo-relative path> <description>', else None. A missing
    path or description isn't treated as invalid here -- run_cli prints
    usage for that case so the distinction between "not a patch command"
    and "a malformed one" stays visible to the user.
    """
    if not lowered.startswith(PATCH_PREFIX):
        return None
    rest = user_input[len(PATCH_PREFIX):].strip()
    if not rest or " " not in rest:
        return ("", "")
    path, description = rest.split(" ", 1)
    return path.strip(), description.strip()


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
    activity_log: ActivityLog | None = None,
    reflection_agent: ReflectionAgent | None = None,
    llm_configured: bool = False,
) -> str:
    request = AgentRequest(text=text)
    reaction = _dispatch_and_record(router, "emotion", request, outcome_log, reflection_agent)
    logic_metadata: dict = {}
    response = _dispatch_and_record(
        router, "logic", request, outcome_log, reflection_agent, metadata_sink=logic_metadata
    )
    reply = synthesize(reaction, response, router.bus)

    if llm_configured and logic_metadata.get("source") == "rule_based":
        print(
            style(
                "[notice] LLM access isn't available right now -- that reply used plain "
                "rule-based logic instead. Run 'budget' to see why (a rate/cost cap "
                "reached, or the CLI/API isn't reachable).",
                "orange",
                "bold",
            )
        )

    if health_monitor is not None:
        critical = [
            issue
            for issue in health_monitor.enforce(router.bus)
            if issue.severity is Severity.CRITICAL
        ]
        if critical:
            reasons = "; ".join(issue.description for issue in critical)
            reply += f" [self-correction: {reasons} -- resetting to a calmer baseline]"

    if activity_log is not None:
        activity_log.record_conversation_turn(text, reply)

    return reply


def _dispatch_and_record(
    router: Router,
    name: str,
    request: AgentRequest,
    outcome_log: OutcomeLog | None,
    reflection_agent: ReflectionAgent | None = None,
    metadata_sink: dict | None = None,
) -> str:
    """`metadata_sink`, if given, is updated in place with the successful
    response's metadata -- lets a caller (handle_turn, to check whether a
    reply actually came from an LLM) inspect it without changing this
    function's string-only return type everywhere else it's used.
    """
    try:
        response = router.dispatch(name, request)
    except Exception as exc:  # noqa: BLE001 -- a failing sub-agent must not
        # crash the CLI turn; it becomes a recorded, visible failure instead
        outcome = Outcome(
            agent=name,
            request_text=request.text,
            output="",
            succeeded=False,
            note=repr(exc),
        )
        if outcome_log is not None:
            outcome_log.record(outcome)
        _print_takeaway(reflection_agent, outcome)
        return f"[{name} agent failed: {exc}]"

    outcome = Outcome(
        agent=name,
        request_text=request.text,
        output=response.output,
        succeeded=True,
    )
    if outcome_log is not None:
        outcome_log.record(outcome)
    if metadata_sink is not None:
        metadata_sink.update(response.metadata)
    return response.output


def _print_status(message: str) -> None:
    """Icon/color a final status line for the live terminal narration --
    purely cosmetic, the same way ActivityLog.format_entry decorates the
    durable log. Never touches the string itself: callers still return
    and test the plain `message`, this only decorates what's shown on
    screen.
    """
    lowered = message.lower()
    if lowered.startswith("[applied"):
        print(style(f"✨ {message}", "green", "bold"))
    elif lowered.startswith("[rejected"):
        print(style(f"🚫 {message}", "red", "bold"))
    elif lowered.startswith("[usage"):
        print(style(message, "dim"))
    else:
        print(message)


def _print_takeaway(reflection_agent: ReflectionAgent | None, outcome: Outcome) -> None:
    """The creator's ask that Sim evaluate 'how it can do that task
    better next time' for every situation, not only in aggregate -- see
    ReflectionAgent.reflect_on_outcome. Only fires for a failed/corrected
    outcome; a turn that went fine has nothing to take away.
    """
    if reflection_agent is None:
        return
    proposal = reflection_agent.reflect_on_outcome(outcome)
    if proposal is not None:
        print(style(f"[takeaway] {proposal.rationale}", "yellow"))


def run_cli() -> None:
    _setup_readline()
    store = build_memory_store()
    short_term = ShortTermMemory()
    activity_log = ActivityLog(store)
    cognition, budget_guards = build_cognition_router(store)
    web_fetch = WebFetchTool(store)
    sandbox = SubprocessSandbox()
    router = build_router(
        cognition=cognition,
        short_term=short_term,
        web_fetch=web_fetch,
        sandbox=sandbox,
        activity_log=activity_log,
    )
    outcome_log = OutcomeLog(store)
    reflection_agent = ReflectionAgent(outcome_log, store=store)
    audit_gate = AuditGate(memory=store)
    skill_research = SkillResearchAgent(cognition, audit_gate=audit_gate, activity_log=activity_log)
    self_patch_agent = SelfPatchAgent(cognition, audit_gate=audit_gate, activity_log=activity_log)
    interests = InterestTracker(store)
    health_monitor = HealthMonitor()
    _print_banner()
    _print_cognition_status(budget_guards)
    try:
        _run_cli_loop(
            router, store, short_term, activity_log, outcome_log, reflection_agent,
            audit_gate, skill_research, self_patch_agent, interests, health_monitor,
            web_fetch, budget_guards,
        )
    finally:
        _save_readline_history()


def _run_cli_loop(
    router: Router,
    store: MemoryStore,
    short_term: ShortTermMemory,
    activity_log: ActivityLog,
    outcome_log: OutcomeLog,
    reflection_agent: ReflectionAgent,
    audit_gate: AuditGate,
    skill_research: SkillResearchAgent,
    self_patch_agent: SelfPatchAgent,
    interests: InterestTracker,
    health_monitor: HealthMonitor,
    web_fetch: WebFetchTool,
    budget_guards: dict[str, BudgetGuard],
) -> None:
    """The interactive read-eval-print loop, extracted out of run_cli so
    run_cli can guarantee readline history is saved on the way out
    (try/finally) regardless of how this loop ends -- 'exit'/'quit',
    EOF, or Ctrl-C.
    """
    while True:
        try:
            user_input = input(style("> ", "cyan", "bold")).strip()
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
        corrected_input, corrected_lowered, original_word = autocorrect_command(user_input, lowered)
        if original_word is not None:
            print(style(f"[guessing {original_word!r} -> {corrected_input.split()[0]!r}]", "dim"))
            user_input, lowered = corrected_input, corrected_lowered
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
        patch_args = extract_patch_args(user_input, lowered)
        if patch_args is not None:
            subject, description = patch_args
            propose_self_patch(self_patch_agent, audit_gate, store, activity_log, subject, description)
            continue
        if lowered == LOG_COMMAND or lowered.startswith(LOG_COMMAND + " "):
            _print_activity_log(activity_log, user_input[len(LOG_COMMAND):].strip())
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
        if lowered == SKILLS_COMMAND:
            _print_skills_list()
            continue
        if lowered.startswith(USE_PREFIX):
            use_skill(router, outcome_log, activity_log, user_input[len(USE_PREFIX):].strip())
            continue
        if lowered == BUDGET_COMMAND:
            _print_budget(budget_guards)
            continue
        if lowered.startswith(FETCH_PREFIX):
            fetch_url(web_fetch, user_input[len(FETCH_PREFIX):].strip())
            continue
        reply = handle_turn(
            router,
            user_input,
            outcome_log,
            health_monitor,
            activity_log,
            reflection_agent,
            llm_configured=bool(budget_guards),
        )
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


def use_skill(
    router: Router,
    outcome_log: OutcomeLog,
    activity_log: ActivityLog | None,
    name: str,
    repo_root: Path | None = None,
) -> str:
    """Actually run an applied skill by name -- the closing half of
    propose/improve (drafts and deploys a skill to disk, but never ran
    it) and self-patch (revises and relaunches Sim's *own already-loaded*
    logic, which a new skill file isn't). A skill was never imported into
    the running process to begin with, so nothing here needs a relaunch:
    `load_skill_source` re-reads the file fresh from disk on every call,
    so a skill just applied (or overwritten by a later 'propose' on the
    same topic) is usable immediately. Runs through the same sandbox as
    'run <code>' (src/agents/skills/registry.py's build_invocation_code),
    never a live in-process import. Returns the message printed, for
    testability.
    """
    root = repo_root or Path.cwd()
    if not name:
        message = "[usage: use <skill name> -- see 'skills' for the list]"
        _print_status(message)
        return message

    source = load_skill_source(root, name)
    if source is None:
        message = f"[not found] no applied skill named {name!r} -- see 'skills' for the list"
        _print_status(message)
        return message

    output = _dispatch_and_record(
        router, "skills", AgentRequest(text=build_invocation_code(source)), outcome_log
    )
    print(output)
    if activity_log is not None:
        first_line = output.splitlines()[0] if output.strip() else "(no output)"
        activity_log.record_tool_call("cli", "USE", name, preview(first_line), True)
    return output


def _print_skills_list(repo_root: Path | None = None) -> None:
    names = list_applied_skills(repo_root or Path.cwd())
    print(style(f"🧰 Applied skills ({len(names)})", "magenta", "bold"))
    if not names:
        print(style("  (none yet -- try 'propose <topic>' or 'improve <topic>')", "dim"))
        return
    for name in names:
        print(f"  • {name}  —  {style('use ' + name, 'cyan')}")


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
        _print_status(message)
        return message

    proposal = None
    verdict = None
    prior_reasons: list[str] | None = None
    for attempt in range(1, max_attempts + 1):
        if attempt == 1:
            print(f"🧪 [propose] drafting a skill for {topic!r}...")
        else:
            print(f"🧪 [propose] attempt {attempt}/{max_attempts}: asking for a corrected draft...")
        proposal = skill_research.draft_skill(topic, prior_reasons=prior_reasons)
        print(
            f"🔎 [propose] drafted {proposal.subject} -- running it through the audit "
            "gate (denylist, adaptive-immunity memory, then a real sandboxed run)..."
        )
        verdict = audit_gate.review(proposal)
        if verdict.approved_by_automation:
            break
        print(f"⚠️  [propose] attempt {attempt} failed: {'; '.join(verdict.reasons)}")
        prior_reasons = verdict.reasons

    if not verdict.approved_by_automation:
        message = f"[rejected after {max_attempts} attempt(s)] {'; '.join(verdict.reasons)}"
        _print_status(message)
        return message

    print("✅ [propose] passed every check -- writing to disk...")
    try:
        target = apply_proposal(proposal, store, repo_root=repo_root)
    except ApplyRefused as exc:
        message = f"[rejected] {exc}"
        _print_status(message)
        return message

    message = (
        f"[APPLIED] {target} -- {proposal.rationale} "
        "(passed every check and was written to disk; review with git diff/status "
        "before committing)"
    )
    _print_status(message)
    print(style(f"   → try it now: use {target.stem}", "dim"))
    return message


def propose_self_patch(
    self_patch_agent: SelfPatchAgent,
    audit_gate: AuditGate,
    store: MemoryStore,
    activity_log: ActivityLog,
    subject: str,
    topic: str,
    repo_root: Path | None = None,
    max_attempts: int = 3,
    do_relaunch: bool = True,
) -> str:
    """Draft a revision to an EXISTING source file at `subject`, run it
    through the same audit gate a drafted skill goes through, and -- if
    it also survives a fresh run of this repository's entire test suite
    in an isolated copy -- apply it and relaunch so the change actually
    takes effect (src/orchestrator/self_patch.py). Same auto-apply
    posture and bounded self-correction as propose_skill above, with one
    extra, stronger gate: the whole test suite, not just a sandboxed
    smoke run of the changed file alone. apply_source_patch enforces its
    own independent scope check, so a rejected, off-scope, or
    test-failing proposal is never written regardless of what happens
    here. `do_relaunch=False` lets tests exercise the full pipeline
    without actually replacing the test process. Returns the message
    printed, for testability.
    """
    if not subject or not topic:
        message = "[usage: patch <repo-relative path> <description of the change>]"
        _print_status(message)
        return message

    proposal = None
    verdict = None
    prior_reasons: list[str] | None = None
    for attempt in range(1, max_attempts + 1):
        if attempt == 1:
            print(f"🛠️  [patch] drafting a patch to {subject!r}: {topic!r}...")
        else:
            print(f"🛠️  [patch] attempt {attempt}/{max_attempts}: asking for a corrected draft...")
        proposal = self_patch_agent.draft_patch(subject, topic, prior_reasons=prior_reasons)
        if proposal is None:
            message = "[patch] no real drafting intelligence available -- nothing applied"
            _print_status(message)
            return message

        if subject.endswith("main.py"):
            invariant_reason = check_main_py_invariants(proposal.code)
            if invariant_reason is not None:
                print(f"⚠️  [patch] attempt {attempt} failed: {invariant_reason}")
                prior_reasons = [invariant_reason]
                verdict = None
                continue

        print(
            f"🔎 [patch] drafted a candidate for {subject} -- running it through the audit "
            "gate (denylist, adaptive-immunity memory, then a real sandboxed run)..."
        )
        verdict = audit_gate.review(proposal)
        if verdict.approved_by_automation:
            break
        print(f"⚠️  [patch] attempt {attempt} failed: {'; '.join(verdict.reasons)}")
        prior_reasons = verdict.reasons

    if verdict is None or not verdict.approved_by_automation:
        if verdict is not None:
            reasons = "; ".join(verdict.reasons)
        elif prior_reasons:
            reasons = "; ".join(prior_reasons)
        else:
            reasons = "no candidate passed review"
        message = f"[rejected after {max_attempts} attempt(s)] {reasons}"
        _print_status(message)
        return message

    print(
        "🧪 [patch] passed the audit gate -- running the full test suite in an "
        "isolated copy (this can take a while)..."
    )
    suite_result = run_isolated_test_suite(repo_root or Path.cwd(), subject, proposal.code)
    if not suite_result.passed:
        message = f"[rejected] isolated test suite did not pass: {suite_result.summary}"
        _print_status(message)
        activity_log.record_tool_call(
            "self_patch", "TEST_SUITE", f"{subject}: {topic}", suite_result.summary, False
        )
        return message

    print(
        f"✅ [patch] test suite passed ({suite_result.test_count} tests, was "
        f"{suite_result.baseline_test_count}) -- writing to disk..."
    )
    try:
        target = apply_source_patch(proposal, store, suite_result.summary, repo_root=repo_root)
    except ApplyRefused as exc:
        message = f"[rejected] {exc}"
        _print_status(message)
        return message

    activity_log.record_tool_call(
        "self_patch", "TEST_SUITE", f"{subject}: {topic}", suite_result.summary, True
    )
    message = (
        f"[APPLIED] {target} -- {proposal.rationale} "
        f"(isolated test suite: {suite_result.test_count} tests passed; review with "
        "git diff/status before committing)"
    )
    _print_status(message)

    if do_relaunch:
        print("🔁 [patch] relaunching now so the new code takes effect...")
        relaunch()

    return message


def _print_pending(store: MemoryStore) -> None:
    skills = store.query(kind=APPLIED_KIND)
    patches = store.query(kind=APPLIED_PATCH_KIND)
    if not skills and not patches:
        print(
            "[nothing applied yet -- try 'propose <topic>', 'improve <topic>', or "
            "'patch <path> <description>']"
        )
        return
    for record in skills:
        print(f"[applied: skill] {record.content} -- {record.metadata.get('rationale', '')}")
    for record in patches:
        print(f"[applied: patch] {record.content} -- {record.metadata.get('rationale', '')}")


def _print_activity_log(activity_log: ActivityLog, arg: str = "", limit: int = 20) -> None:
    """`arg == 'last'` (or 'recent') narrows the trail to everything
    since the previous conversation turn (see
    ActivityLog.since_last_turn) -- the direct "what happened between my
    last prompt and now" view; anything else shows the ordinary
    newest-first recent trail across every kind.
    """
    narrowed = arg.lower() in ("last", "recent")
    entries = activity_log.since_last_turn(limit=limit) if narrowed else activity_log.recent(limit=limit)
    title = "since your last prompt" if narrowed else f"last {len(entries)}"
    print(style(f"📜 Activity log — {title}", "magenta", "bold"))
    print(style("─" * 60, "dim"))
    if not entries:
        print(style("  (nothing recorded yet)", "dim"))
        return
    for entry in entries:
        print(ActivityLog.format_entry(entry))
    print(style("─" * 60, "dim"))


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
        store,
        reflection_agent,
        keep_per_kind={
            "outcome": 200,
            REJECTED_KIND: 200,
            "conversation_turn": 500,
            "tool_call": 500,
            "takeaway": 200,
        },
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
