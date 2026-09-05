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
import importlib
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

try:
    import readline  # noqa: F401 -- imported for its side effect: input() gains
    # arrow-key editing, backspace/word-editing, and (once history is loaded
    # below) up/down recall. Not available on Windows' stock CPython.
except ImportError:  # pragma: no cover -- platform-dependent
    readline = None

from src.agents.emotion.base import EmotionAgent
from src.agents.interests import DEFAULT_NEWS_TOPICS, InterestTracker, RssWorldFeed
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
from src.orchestrator.autonomy import ActivityClock, AutonomyController
from src.orchestrator.apply import (
    APPLIED_KIND,
    APPLIED_PATCH_KIND,
    SELF_PATCH_SCOPE_PREFIX,
    ApplyRefused,
    apply_proposal,
    apply_source_patch,
)
from src.orchestrator.audit import PROTECTED_SUBJECTS, REJECTED_KIND, AuditGate
from src.orchestrator.consolidation import run_consolidation
from src.orchestrator.console_style import format_code_block, format_diff_block, render_checklist, style
from src.orchestrator.deployment import DeploymentManager
from src.orchestrator.discovery import discover_improvements
from src.orchestrator.git_ops import (
    commit_applied_change,
    current_commit_hash,
    revert_commits_since,
    revert_last_commit,
)
from src.orchestrator.health import HealthMonitor, Severity
from src.orchestrator.reflection import Outcome, OutcomeLog, ReflectionAgent
from src.orchestrator.reminders import parse_duration, schedule_reminder
from src.orchestrator.router import AgentRequest, Router, SubAgent
from src.orchestrator.self_patch import SelfPatchAgent, check_main_py_invariants, relaunch, run_isolated_test_suite
from src.orchestrator.socializing import (
    GrowthHighlight,
    GrowthSocializer,
    NewsHighlight,
    NewsSocializer,
)
from src.orchestrator.tasks import (
    BLOCKED,
    DONE,
    FAILED,
    IN_PROGRESS,
    PATCH_TASK,
    PENDING,
    SKILL_TASK,
    Task,
    TaskStore,
)
from src.orchestrator.verification import verify_task_completion
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
BATCH_PREFIX = "batch "
MAX_BATCH_COUNT = 20
DEFAULT_BATCH_MAX_ATTEMPTS = 2
PLAN_PREFIX = "plan "
DISCOVER_COMMAND = "discover"
TASKS_COMMAND = "tasks"
WORK_COMMAND = "work"
AUTONOMOUS_PREFIX = "autonomous "
DIGEST_COMMAND = "digest"
NEWS_COMMAND = "news"
GROWTH_COMMAND = "growth"
REMIND_PREFIX = "remind "
MAX_TASK_ATTEMPTS = 3
EVOLVE_PREFIX = "evolve "
# Lower than MAX_BATCH_COUNT: each item here is a full propose_self_patch
# (audit gate + this repo's ENTIRE test suite run twice, in an isolated
# copy), not a sandboxed smoke test of one new file -- meaningfully more
# expensive per item, so the ceiling on how many run in one command is
# tighter.
MAX_EVOLVE_COUNT = 10
DEFAULT_EVOLVE_MAX_ATTEMPTS = 2
DEFAULT_MEMORY_PATH = Path.home() / ".simorgh" / "memory.jsonl"
DEFAULT_HISTORY_PATH = Path.home() / ".simorgh" / "cli_history"
# One-shot handoff for ShortTermMemory across exactly one relaunch (see
# ShortTermMemory.save/load_and_clear) -- os.execv wipes the in-memory
# conversation window outright, so this is how a patch/evolve relaunch
# hands the next process something to restore instead of dropping the
# creator's mid-conversation context silently.
DEFAULT_RELAUNCH_CONTEXT_PATH = Path.home() / ".simorgh" / "relaunch_context.json"
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
    "batch",
    "plan",
    "evolve",
    DISCOVER_COMMAND,
    TASKS_COMMAND,
    WORK_COMMAND,
    "autonomous",
    DIGEST_COMMAND,
    NEWS_COMMAND,
    GROWTH_COMMAND,
    "remind",
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
DEFAULT_DAILY_BUDGET_USD = float(os.environ.get("SIMORGH_LLM_DAILY_BUDGET_USD", "2.0"))
# max_calls raised from 50 -> 1500, and the dollar cap from $1.00 ->
# $2.00/day, both at the creator's explicit request. The dollar cap is
# the real limit in practice (a Flash-tier call is a fraction of a
# cent) -- the call-count cap exists as a sanity ceiling, not the
# primary control, so it's set high enough to not be the thing that
# silently kills LLM access first (see docs/EVOLUTION.md, "Sim doesn't
# have LLM access anymore," where the 50-call default was exactly what
# did that).
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
    propose_skill_fn: Callable[[str], str] | None = None,
    propose_patch_fn: Callable[[str, str], str] | None = None,
    propose_batch_fn: Callable[[str, int], str] | None = None,
    plan_fn: Callable[[str, int], str] | None = None,
    propose_evolve_fn: Callable[[str, int], str] | None = None,
    use_skill_fn: Callable[[str], str] | None = None,
    news_fn: Callable[[], str] | None = None,
    growth_fn: Callable[[], str] | None = None,
) -> Router:
    """All params are optional so existing callers (and every prior test)
    get exactly the old rule-based-only behavior when omitted -- see
    LogicAgent's own fallback logic for why passing a CognitionRouter here
    doesn't change anything unless a real provider actually answers, and
    `web_fetch`/`sandbox` for why LogicAgent only offers FETCH/RUN tools
    when they're actually given. `propose_skill_fn`/`propose_patch_fn`/
    `propose_batch_fn`/`plan_fn`/`propose_evolve_fn`, when given, let
    ordinary conversation trigger the real propose/patch/batch/plan/evolve
    pipelines directly -- explicitly authorized by the creator (see
    docs/SOUL.md, "Conversational self-modification"); every downstream
    gate is unchanged, only the trigger source is new. `use_skill_fn`,
    when given, lets a chat reply actually run an already-applied skill
    (the same sandboxed `load_skill_source`/`build_invocation_code` path
    as the typed `use <name>` command) instead of only telling the user
    to type it themselves. `news_fn`/`growth_fn`, when given, let a chat
    reply actually check tracked feeds, or Sim's own most recently
    applied change, and share it right now (`main.py`'s `news_command`/
    `growth_command`, same as the typed `news`/`growth` commands).
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
            propose_skill_fn=propose_skill_fn,
            propose_patch_fn=propose_patch_fn,
            propose_batch_fn=propose_batch_fn,
            plan_fn=plan_fn,
            propose_evolve_fn=propose_evolve_fn,
            use_skill_fn=use_skill_fn,
            news_fn=news_fn,
            growth_fn=growth_fn,
        )
    )
    router.register(SkillsAgent())
    return router


SHELL_PREFIX = "!"
DEFAULT_SHELL_TIMEOUT_SECONDS = 120.0


def _run_shell_passthrough(command: str, timeout: float = DEFAULT_SHELL_TIMEOUT_SECONDS) -> None:
    """Run `command` as a raw shell command, mirroring Claude Code's own
    '!<command>' convention: a line typed straight into this REPL that
    starts with '!' is the human operator's own direct input, run with
    their own shell authority -- the same trust boundary as alt-tabbing
    to a real terminal, not a drafted proposal or an LLM tool call. It
    deliberately bypasses AuditGate/the sandbox entirely for exactly that
    reason, and is unreachable from anywhere except a literal '!'-
    prefixed line here -- LogicAgent's own RUN: tool stays the sandboxed,
    audited path for anything model-drafted. stdout/stderr/stdin are
    inherited directly (not captured) so output streams live and an
    interactive command (e.g. a pager, `$EDITOR`) still works, matching
    what running it in a real shell would do.
    """
    if not command:
        print(style("[usage: !<shell command>]", "dim"))
        return
    try:
        completed = subprocess.run(command, shell=True, cwd=Path.cwd(), timeout=timeout)
    except subprocess.TimeoutExpired:
        print(style(f"⚠️  shell command timed out after {timeout:.0f}s", "red"))
        return
    except OSError as exc:
        print(style(f"⚠️  failed to run shell command: {exc!r}", "red"))
        return
    if completed.returncode != 0:
        print(style(f"(exit {completed.returncode})", "dim"))


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


_COMMANDS_HELP: tuple[tuple[str, str], ...] = (
    ("reflect", "Review recent outcomes for patterns worth addressing."),
    ("propose <topic>", "Draft, audit, and apply a brand-new skill."),
    ("improve <topic>", "Alias for 'propose'."),
    ("patch <path> <description>", "Revise existing source, test it fully, relaunch if it passes."),
    ("batch <count> <theme>", "Brainstorm and apply up to 20 focused skills for a theme."),
    ("plan <count> <goal>", "Brainstorm steps toward a goal and save them as tasks."),
    ("evolve <count> <goal>", "Brainstorm and apply up to 10 REAL patches to core source (not skills)."),
    ("discover", "Scan for improvement areas and save them as tasks."),
    ("tasks", "List the persisted task backlog."),
    ("work", "Run one task from the backlog."),
    ("autonomous [on|off]", "Control the idle-triggered autonomous loop (no arg = status)."),
    ("digest", "Rollup of autonomous activity over the last 24h."),
    ("news", "Share the next interesting item from your tracked feeds."),
    ("growth", "Share the most recent thing you improved about yourself."),
    ("pending [path]", "List applied changes, or diff one (--full for the whole file)."),
    ("skills", "List applied skills you can run by name."),
    ("use <skill name>", "Run an applied skill fresh from disk."),
    ("log [last]", "Show the unified activity/audit trail."),
    ("fetch <url>", "Fetch a web page through the reviewed, SSRF-safe tool."),
    ("interest <topic>", "Start tracking a topic of curiosity."),
    ("interests", "List tracked interests."),
    ("curious", "Follow up on the least-recently-checked interest."),
    ("sleep", "Run maintenance: prune old records, surface patterns."),
    ("history", "Show this session's recent turns."),
    ("run <code>", "Execute Python in the sandbox."),
    ("budget", "Show LLM spend/call status."),
    ("remind <duration> <message>", "Get interrupted with a message later (e.g. 1m, 5m, 2h)."),
    ("!<command>", "Run a raw shell command directly (e.g. '!ls', '!git status')."),
    ("exit / quit", "Leave."),
)


def _print_banner() -> None:
    print(
        style("Simorgh", "magenta", "bold")
        + " -- talk to me directly, or use one of these commands "
        "(a leading '/' is optional on any of them, except '!<command>' "
        "which is its own trigger):\n"
    )
    # Pad the plain label BEFORE styling it -- ANSI escape codes count
    # toward len() but occupy no visual width, so padding a styled string
    # directly would misalign the columns. One line per command --
    # explicit creator preference over the earlier two-line (label +
    # separate "e.g." line) layout.
    width = max(len(name) for name, _ in _COMMANDS_HELP)
    for name, description in _COMMANDS_HELP:
        # '!<command>' is its own trigger character, not a command word
        # that also accepts an optional leading '/' -- '/!ls' isn't a
        # real thing, so this one entry is never slash-prefixed.
        shown = name if name.startswith(SHELL_PREFIX) else f"/{name}"
        label = shown.ljust(width + 1)
        print(f"  {style(label, 'cyan', 'bold')} {description}")
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


def extract_batch_args(user_input: str, lowered: str) -> tuple[int, str] | None:
    """Returns (count, theme) if `user_input` is 'batch <count> <theme>'
    with a valid positive integer count, else None. A missing/malformed
    count or theme returns (0, "") -- same convention as
    extract_patch_args -- so run_cli can show usage rather than silently
    falling through to plain chat.
    """
    if not lowered.startswith(BATCH_PREFIX):
        return None
    rest = user_input[len(BATCH_PREFIX):].strip()
    parts = rest.split(None, 1)
    if len(parts) < 2 or not parts[0].isdigit():
        return (0, "")
    return int(parts[0]), parts[1].strip()


def extract_plan_args(user_input: str, lowered: str) -> tuple[int, str] | None:
    """Same shape and convention as extract_batch_args, for
    'plan <count> <goal>'."""
    if not lowered.startswith(PLAN_PREFIX):
        return None
    rest = user_input[len(PLAN_PREFIX):].strip()
    parts = rest.split(None, 1)
    if len(parts) < 2 or not parts[0].isdigit():
        return (0, "")
    return int(parts[0]), parts[1].strip()


def extract_evolve_args(user_input: str, lowered: str) -> tuple[int, str] | None:
    """Same shape and convention as extract_batch_args, for
    'evolve <count> <goal>'."""
    if not lowered.startswith(EVOLVE_PREFIX):
        return None
    rest = user_input[len(EVOLVE_PREFIX):].strip()
    parts = rest.split(None, 1)
    if len(parts) < 2 or not parts[0].isdigit():
        return (0, "")
    return int(parts[0]), parts[1].strip()


def extract_remind_args(user_input: str, lowered: str) -> tuple[str, str] | None:
    """Returns (duration_text, message) for the explicit
    'remind <duration> <message>' command, else None -- deliberately
    None (not a usage-error pair) for anything else, including plain
    ordinary chat that happens to start with the word "remind" (e.g.
    "remind me to wake up in one minute"). "remind" alone matching
    REMIND_PREFIX isn't enough signal on its own to intercept a whole
    sentence as a command; requiring the very next token to actually
    parse as a duration is what distinguishes the explicit command from
    natural language. Caught live: without this check, "remind me to
    wake up in one minute" was parsed as duration="me", which then
    failed with a confusing "'me' isn't a valid duration" instead of
    ever reaching LogicAgent's own REMIND: tool marker, which is what
    should have understood it. A plain-chat "remind..." now falls
    through correctly; only a genuine 'remind 1m ...'-shaped command is
    intercepted here.
    """
    if not lowered.startswith(REMIND_PREFIX):
        return None
    rest = user_input[len(REMIND_PREFIX):].strip()
    parts = rest.split(None, 1)
    if len(parts) < 2 or parse_duration(parts[0]) is None:
        return None
    return parts[0], parts[1].strip()


def remind_command(duration_text: str, message: str) -> str:
    """Schedule a one-off reminder (src/orchestrator/reminders.py) --
    ephemeral and session-scoped, never persisted or relaunch-surviving.
    Returns the message printed, for testability.
    """
    if not duration_text or not message:
        result = "[usage: remind <duration> <message>] e.g. remind 1m stretch your legs"
        _print_status(result)
        return result
    seconds = parse_duration(duration_text)
    if seconds is None:
        result = f"[remind] {duration_text!r} isn't a valid duration -- try '30s', '5m', or '1h'"
        _print_status(result)
        return result
    schedule_reminder(seconds, message)
    result = f"[remind] scheduled -- will remind you in {duration_text}: {message!r}"
    _print_status(result)
    return result


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
    short_term = ShortTermMemory.load_and_clear(DEFAULT_RELAUNCH_CONTEXT_PATH) or ShortTermMemory()
    activity_log = ActivityLog(store)
    cognition, budget_guards = build_cognition_router(store)
    web_fetch = WebFetchTool(store)
    sandbox = SubprocessSandbox()

    outcome_log = OutcomeLog(store)
    reflection_agent = ReflectionAgent(outcome_log, store=store)
    audit_gate = AuditGate(memory=store)
    skill_research = SkillResearchAgent(cognition, audit_gate=audit_gate, activity_log=activity_log)
    self_patch_agent = SelfPatchAgent(cognition, audit_gate=audit_gate, activity_log=activity_log)
    interests = InterestTracker(store, feed=RssWorldFeed(web_fetch))
    # Seeded exactly once, ever: only when nothing is tracked at all
    # (a brand-new ~/.simorgh/memory.jsonl), so "get news from different
    # fields and domains" produces something real without the creator
    # configuring anything first, but Sim never silently re-adds a
    # default the creator deliberately removed on a later run.
    if not interests.list_interests():
        for feed_url, label in DEFAULT_NEWS_TOPICS:
            interests.note_interest(feed_url, why=f"default {label} feed, seeded on first run")
    news_socializer = NewsSocializer()
    growth_socializer = GrowthSocializer(store)
    health_monitor = HealthMonitor()
    task_store = TaskStore(store)

    # Explicitly authorized by the creator: ordinary conversation can now
    # trigger these pipelines directly (previously only a literally-typed
    # command or the autonomous loop could) -- see docs/SOUL.md,
    # "Conversational self-modification." Every downstream gate (audit
    # gate, isolated test suite, auto-commit-never-push, protected files,
    # network denylist) is completely unchanged; only who is allowed to
    # start the pipeline changed. Closures, not a LogicAgent -> main.py
    # import, to avoid a circular import (main.py already imports
    # LogicAgent).
    #
    # Kept as its own dict, not inlined into build_router() below, for a
    # second reason beyond readability: build_router()'s parameter names
    # mirror LogicAgent's constructor exactly (by design), so this same
    # dict doubles as the hot-swap recipe for a patched LogicAgent
    # (hot_swap_factories below) -- reconstructing a candidate after a
    # self-patch needs the exact same arguments the currently-live
    # instance was built with, not a second, hand-copied list that could
    # drift out of sync with this one.
    logic_agent_kwargs: dict = dict(
        cognition=cognition,
        short_term=short_term,
        web_fetch=web_fetch,
        sandbox=sandbox,
        activity_log=activity_log,
        propose_skill_fn=lambda topic: propose_skill(
            skill_research, audit_gate, store, activity_log, topic
        ),
        propose_patch_fn=lambda path, desc: propose_self_patch(
            self_patch_agent, audit_gate, store, activity_log, path, desc, short_term=short_term,
            deployment_manager=deployment_manager, hot_swap_factories=hot_swap_factories,
        ),
        propose_batch_fn=lambda theme, count: propose_skill_batch(
            cognition, skill_research, audit_gate, store, activity_log, theme, count
        ),
        plan_fn=lambda goal, count: plan_goal(cognition, task_store, goal, count),
        propose_evolve_fn=lambda goal, count: propose_patch_batch(
            cognition, self_patch_agent, audit_gate, store, activity_log, goal, count, short_term=short_term
        ),
        use_skill_fn=lambda name: use_skill(router, outcome_log, activity_log, name),
        news_fn=lambda: news_command(interests, news_socializer, cognition),
        growth_fn=lambda: growth_command(growth_socializer, cognition),
    )
    router = build_router(**logic_agent_kwargs)

    # DeploymentManager (src/orchestrator/deployment.py): wraps the
    # already-built router, taking over version bookkeeping for each
    # slot build_router() just registered directly. This is what makes
    # an in-process hot-swap possible for a self-patch that lands on one
    # of _HOT_SWAP_TARGETS (see _attempt_hot_swap) -- explicitly
    # authorized by the creator; every gate a patch already goes through
    # (audit gate, isolated test suite) is unchanged, only how an
    # already-verified change takes effect can now skip a full relaunch.
    deployment_manager = DeploymentManager(router, memory=store)
    for slot_name in router.agent_names():
        agent = router.get(slot_name)
        if agent is not None:
            deployment_manager.deploy(agent, version_id="initial")

    hot_swap_factories: dict[str, Callable[[type], SubAgent]] = {
        "src/agents/logic/base.py": lambda cls: cls(**logic_agent_kwargs),
        "src/agents/emotion/base.py": lambda cls: cls(),
        "src/agents/skills/base.py": lambda cls: cls(),
    }

    activity_clock = ActivityClock()
    # A one-slot mailbox between perform_action and last_action_succeeded
    # below: AutonomyController.tick() calls both, in that order, so
    # _autonomous_action's outcome_sink writes here and
    # last_action_succeeded reads the same slot back a moment later --
    # this is how the circuit breaker (see src/orchestrator/autonomy.py)
    # learns whether an action actually succeeded, not just that one ran.
    # Reset before every tick: a discovery-only action never writes to
    # it, and a stale value from a PRIOR tick must never be attributed
    # to this one.
    _last_autonomous_outcome: list[bool | None] = [None]

    def _perform_autonomous_action() -> bool:
        _last_autonomous_outcome[0] = None
        return _autonomous_action(
            task_store, reflection_agent, store, skill_research, self_patch_agent,
            audit_gate, activity_log, cognition, short_term=short_term,
            outcome_sink=lambda succeeded: _last_autonomous_outcome.__setitem__(0, succeeded),
            deployment_manager=deployment_manager, hot_swap_factories=hot_swap_factories,
            interests=interests, news_socializer=news_socializer, growth_socializer=growth_socializer,
        )

    autonomy = AutonomyController(
        store,
        activity_clock,
        perform_action=_perform_autonomous_action,
        last_action_succeeded=lambda: _last_autonomous_outcome[0],
    )

    _print_banner()
    _print_cognition_status(budget_guards)
    if len(short_term) > 0:
        print(
            style(
                f"🧠 restored {len(short_term)} turn(s) of conversation context from "
                "before the last relaunch",
                "cyan",
            )
        )
    _print_resume_notice(task_store)
    if autonomy.digest().total > 0:
        _print_autonomous_digest(autonomy)
    print(
        style(
            f"🤖 autonomous self-improvement is ON -- idle "
            f"{autonomy.idle_threshold_seconds:.0f}s triggers it (see 'autonomous status'/"
            "'autonomous off')",
            "dim",
        )
    )
    autonomy.start()
    try:
        _run_cli_loop(
            router, store, short_term, activity_log, outcome_log, reflection_agent,
            audit_gate, skill_research, self_patch_agent, interests, health_monitor,
            web_fetch, budget_guards, cognition, task_store, activity_clock, autonomy,
            deployment_manager=deployment_manager, hot_swap_factories=hot_swap_factories,
            news_socializer=news_socializer, growth_socializer=growth_socializer,
        )
    finally:
        autonomy.stop()
        _save_readline_history()


def _autonomous_action(
    task_store: TaskStore,
    reflection_agent: ReflectionAgent,
    store: MemoryStore,
    skill_research: SkillResearchAgent,
    self_patch_agent: SelfPatchAgent,
    audit_gate: AuditGate,
    activity_log: ActivityLog,
    cognition: CognitionRouter,
    repo_root: Path | None = None,
    short_term: ShortTermMemory | None = None,
    outcome_sink: Callable[[bool | None], None] | None = None,
    deployment_manager: DeploymentManager | None = None,
    hot_swap_factories: dict[str, Callable[[type], SubAgent]] | None = None,
    interests: InterestTracker | None = None,
    news_socializer: NewsSocializer | None = None,
    growth_socializer: GrowthSocializer | None = None,
) -> bool:
    """One autonomous unit of work, called by AutonomyController.tick()
    only once every gate (enabled, idle long enough, past cooldown,
    under the daily cap) already passed.

    Checks first (when given) whether it's time to proactively share a
    growth highlight -- something Sim itself recently improved -- then,
    if not, whether it's time to share a news highlight -- the direct
    mechanism behind "Sim should be able to start the conversation on
    its own, instead of only being reactive," and (per direct feedback)
    the direct answer to "I don't see any evidence of self-improving":
    growth is checked first specifically because that complaint was more
    pointed than "share more news." Each socializer owns its own,
    usually much longer pacing cooldown (see
    src/orchestrator/socializing.py), so most ticks both are no-ops and
    this falls straight through to the logic below; they're checked
    first only so that on a tick where one IS ready, it doesn't have to
    wait behind an arbitrarily long self-improvement backlog.

    Otherwise: discover new improvement areas if the backlog is empty
    ("once detect it became idle start automatically improve itself"),
    otherwise work the next persisted task -- through the exact same
    audited propose/patch/verify/commit pipelines a human-typed command
    uses. Returns True if real work happened, so a no-op tick never
    starts the cooldown -- this is unrelated to whether that work
    actually SUCCEEDED, which is what `outcome_sink` (when given) is
    separately told: True/False for whether the task's own pipeline
    reported [APPLIED], never called for a pure discovery or
    growth/news-sharing tick (none of those are themselves a success or
    failure of anything). AutonomyController's circuit breaker reads
    this signal to notice a systematic failure pattern, not just a
    single bad action.
    """
    if growth_socializer is not None:
        growth_highlight = growth_socializer.maybe_share(cognition)
        if growth_highlight is not None:
            _print_growth_highlight(growth_highlight)
            print(style("> ", "cyan", "bold"), end="", flush=True)
            return True

    if interests is not None and news_socializer is not None:
        highlight = news_socializer.maybe_share(interests, cognition)
        if highlight is not None:
            _print_news_highlight(highlight)
            print(style("> ", "cyan", "bold"), end="", flush=True)
            return True

    if not task_store.unfinished():
        created = discover_improvements(task_store, reflection_agent, store)
        label = "improvement area(s)"
        attempted_creative = False
        if not created:
            # Nothing went wrong recently to react to -- ask Sim to set
            # its own agenda instead of sitting idle with an empty
            # backlog (creator: "be creative, think big and come up with
            # big ideas"). Same audited propose_self_patch pipeline
            # picks these up next tick either way; only how the task got
            # onto the backlog differs.
            provider_sink: dict = {}
            created = discover_creative_improvements(
                cognition, task_store, repo_root=repo_root, provider_sink=provider_sink
            )
            attempted_creative = provider_sink.get("provider_name") != "deterministic_fallback"
            label = "self-directed idea(s)"
        if created:
            print(
                style(
                    f"\n🤖 [autonomous] idle -- discovered {len(created)} {label}",
                    "magenta",
                    "bold",
                )
            )
            for task in created:
                print(f"   + [{task.id}] ({task.discovered_via}) {task.description}")
            print(style("> ", "cyan", "bold"), end="", flush=True)
        # A creative-agenda attempt that produced nothing still spent a
        # real (possibly billed) LLM call, unlike discover_improvements'
        # free, purely local pass -- must still count as "did something"
        # so AutonomyController starts its action_cooldown (default
        # 150s). Without this, a stubborn/unparseable brainstorm would
        # get retried every poll_interval_seconds (default 20s) instead,
        # hammering the provider far faster than this loop is meant to.
        return bool(created) or attempted_creative

    print(style("\n🤖 [autonomous] idle -- picking up the next task...", "magenta", "bold"))
    result = work_on_next_task(
        task_store,
        skill_research,
        self_patch_agent,
        audit_gate,
        store,
        activity_log,
        cognition,
        repo_root=repo_root,
        label="autonomous",
        short_term=short_term,
        deployment_manager=deployment_manager,
        hot_swap_factories=hot_swap_factories,
    )
    if outcome_sink is not None:
        outcome_sink(result.startswith("[APPLIED]"))
    print(style("> ", "cyan", "bold"), end="", flush=True)
    return True


def _print_resume_notice(task_store: TaskStore) -> None:
    unfinished = task_store.unfinished()
    if not unfinished:
        return
    in_progress = [t for t in unfinished if t.status == IN_PROGRESS]
    resumable_note = (
        f" ({len(in_progress)} left mid-work by an earlier process)" if in_progress else ""
    )
    print(
        style(
            f"🗂️  {len(unfinished)} unfinished task(s) in the backlog{resumable_note} -- "
            "'tasks' to see them, 'work' to continue",
            "yellow",
        )
    )


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
    cognition: CognitionRouter,
    task_store: TaskStore,
    activity_clock: ActivityClock,
    autonomy: AutonomyController,
    deployment_manager: DeploymentManager | None = None,
    hot_swap_factories: dict[str, Callable[[type], SubAgent]] | None = None,
    news_socializer: NewsSocializer | None = None,
    growth_socializer: GrowthSocializer | None = None,
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
        activity_clock.touch()
        if not user_input:
            continue
        if user_input.startswith(SHELL_PREFIX):
            _run_shell_passthrough(user_input[len(SHELL_PREFIX):].strip())
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
        if lowered == PENDING_COMMAND or lowered.startswith(PENDING_COMMAND + " "):
            _print_pending(store, user_input[len(PENDING_COMMAND):].strip())
            continue
        propose_topic = extract_propose_topic(user_input, lowered)
        if propose_topic is not None:
            propose_skill(skill_research, audit_gate, store, activity_log, propose_topic)
            continue
        patch_args = extract_patch_args(user_input, lowered)
        if patch_args is not None:
            subject, description = patch_args
            propose_self_patch(
                self_patch_agent, audit_gate, store, activity_log, subject, description,
                short_term=short_term, deployment_manager=deployment_manager,
                hot_swap_factories=hot_swap_factories,
            )
            continue
        batch_args = extract_batch_args(user_input, lowered)
        if batch_args is not None:
            count, theme = batch_args
            propose_skill_batch(cognition, skill_research, audit_gate, store, activity_log, theme, count)
            continue
        plan_args = extract_plan_args(user_input, lowered)
        if plan_args is not None:
            count, goal = plan_args
            plan_goal(cognition, task_store, goal, count)
            continue
        evolve_args = extract_evolve_args(user_input, lowered)
        if evolve_args is not None:
            count, goal = evolve_args
            propose_patch_batch(
                cognition, self_patch_agent, audit_gate, store, activity_log, goal, count,
                short_term=short_term,
            )
            continue
        if lowered == DISCOVER_COMMAND:
            discover_command(task_store, reflection_agent, store)
            continue
        if lowered == TASKS_COMMAND:
            _print_tasks(task_store)
            continue
        if lowered == WORK_COMMAND:
            work_on_next_task(
                task_store, skill_research, self_patch_agent, audit_gate, store,
                activity_log, cognition, short_term=short_term,
                deployment_manager=deployment_manager, hot_swap_factories=hot_swap_factories,
            )
            continue
        if lowered == "autonomous" or lowered.startswith(AUTONOMOUS_PREFIX):
            arg = user_input[len(AUTONOMOUS_PREFIX):].strip().lower() if lowered != "autonomous" else ""
            _handle_autonomous_command(arg, autonomy)
            continue
        if lowered == DIGEST_COMMAND:
            _print_autonomous_digest(autonomy)
            continue
        remind_args = extract_remind_args(user_input, lowered)
        if remind_args is not None:
            duration_text, message = remind_args
            remind_command(duration_text, message)
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
        if lowered == NEWS_COMMAND:
            news_command(interests, news_socializer, cognition)
            continue
        if lowered == GROWTH_COMMAND:
            growth_command(growth_socializer, cognition)
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
        _maybe_volunteer_during_conversation(growth_socializer, news_socializer, interests, cognition)


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
    activity_log: ActivityLog,
    topic: str,
    repo_root: Path | None = None,
    max_attempts: int = 3,
    initial_reasons: list[str] | None = None,
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
    written regardless of what happens here. Applied changes are then
    auto-committed (src/orchestrator/git_ops.py, one commit per change,
    attributed to Simorgh, never `--no-verify`) -- per the creator's
    explicit, separate decision on top of auto-apply. `git push` is never
    run automatically by anything in this codebase; that stays entirely
    the creator's own action. `repo_root` defaults to the current working
    directory; tests pass an isolated temp directory instead. Each
    attempt's audit result is also recorded via `activity_log` (not just
    printed live) -- previously a failed attempt's specific reason was
    gone the moment it scrolled off-screen if nobody was watching the
    terminal; now 'activity'/'activity last' can show it after the fact,
    the same as every other tool-loop step (see activity_log.py).
    `initial_reasons`, when given, seeds the very first attempt's retry
    feedback instead of starting blind -- for a task that's already
    failed in a PRIOR round (see `run_task`, which passes the task's
    own recorded failure note here), so a reconsidered BLOCKED task
    doesn't repeat the identical mistake across rounds with zero memory
    of why the last one failed. Returns the message printed, for
    testability.
    """
    if not topic:
        message = "[usage: propose <topic>]"
        _print_status(message)
        return message

    proposal = None
    verdict = None
    prior_reasons: list[str] | None = initial_reasons
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
        activity_log.record_tool_call(
            "propose_skill", "DRAFT", f"{topic} (attempt {attempt}/{max_attempts})",
            "passed audit gate" if verdict.approved_by_automation else "; ".join(verdict.reasons),
            verdict.approved_by_automation,
        )
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

    commit_result = commit_applied_change(
        repo_root or Path.cwd(),
        proposal.subject,
        _skill_commit_message(proposal.subject, proposal.rationale),
    )
    committed_note = (
        "committed (not pushed)" if commit_result.committed else f"NOT committed: {commit_result.output}"
    )
    message = f"[APPLIED] {target} -- {proposal.rationale} ({committed_note})"
    _print_status(message)
    if commit_result.committed:
        print(style("📦 [git] committed -- push whenever you're ready", "green"))
    else:
        print(style(f"⚠️  [git] {commit_result.output}", "yellow"))
    print(style(f"   → try it now: use {target.stem}", "dim"))
    return message


def _skill_commit_message(subject: str, rationale: str) -> str:
    return (
        f"[sim] Add skill: {subject}\n\n"
        f"{rationale}\n\n"
        "Auto-committed by Simorgh's self-modification pipeline (audited: "
        "denylist, adaptive-immunity memory, sandboxed run). Never pushed "
        "automatically -- see docs/SOUL.md, \"Self-Improvement Philosophy.\""
    )


_BATCH_BRAINSTORM_PROMPT = """List exactly {count} distinct, narrowly-focused skill ideas for the
theme: {theme}

Each one must be small enough to implement as ONE self-contained Python
module with ONE clear capability -- not a framework, not "and also
handles X, Y, Z." If the theme is broad, break it into that many
genuinely separate, specific capabilities rather than one vague one
repeated. Standard library only, no direct network access (skip any idea
that would require it -- that needs the creator to use the separately
reviewed web-fetch tool by hand, not a drafted skill).

Respond with ONLY a numbered list, one short topic per line, nothing
else before or after it:
1. <topic>
2. <topic>
...
{count}. <topic>"""

_NUMBERED_LINE = re.compile(r"^\s*\d+[.):]\s*(.+)$")


def _parse_numbered_list(text: str, expected_count: int) -> list[str]:
    topics = []
    for line in text.splitlines():
        match = _NUMBERED_LINE.match(line)
        if match:
            topic = match.group(1).strip()
            if topic:
                topics.append(topic)
    return topics[:expected_count]


def propose_skill_batch(
    cognition: CognitionRouter,
    skill_research: SkillResearchAgent,
    audit_gate: AuditGate,
    store: MemoryStore,
    activity_log: ActivityLog,
    theme: str,
    count: int,
    repo_root: Path | None = None,
) -> str:
    """The creator's ask made real: 'develop N skills for a theme,' not
    just one. 'propose <topic>' was always a one-shot, one-focused-
    capability-per-call pipeline (the audit gate's drafting prompt
    already says "keep it small, not a framework"), so asking it for
    "100 skills" in one call just produced one overly broad module trying
    to cover everything -- not a bug, but not what was wanted either.

    This runs one additional, bounded LLM call to brainstorm `count`
    distinct sub-topics, then calls propose_skill (unchanged) once per
    topic -- the exact same audited, auto-applied, auto-committed
    pipeline as a single 'propose', reused N times, never a relaxed or
    batched review. `count` is capped at MAX_BATCH_COUNT: each item is a
    handful of real, metered LLM calls, so an unbounded count here would
    be an unbounded bill, not just an unbounded list. Returns a summary
    message, for testability.
    """
    if not 1 <= count <= MAX_BATCH_COUNT or not theme:
        message = f"[usage: batch <count 1-{MAX_BATCH_COUNT}> <theme>]"
        _print_status(message)
        return message

    print(f"🧠 [batch] brainstorming {count} focused sub-topic(s) for {theme!r}...")
    response = cognition.complete(_BATCH_BRAINSTORM_PROMPT.format(theme=theme, count=count))
    if response.provider_name == "deterministic_fallback":
        message = "[batch] no real drafting intelligence available -- try 'propose <topic>' directly instead"
        _print_status(message)
        return message

    topics = _parse_numbered_list(response.text, count)
    if not topics:
        message = "[batch] could not produce a topic list -- try a narrower theme, or 'propose <topic>' directly"
        _print_status(message)
        return message

    print(f"🧠 [batch] got {len(topics)} sub-topic(s):")
    for i, topic in enumerate(topics, 1):
        print(f"   {i}. {topic}")

    # A persistent, reprinted-after-each-step checklist -- the "what's
    # left" view Claude Code's own terminal UI keeps visible during
    # multi-step work, instead of only a scrolling trail of individual
    # step narration with no summary until the very end.
    statuses = ["pending"] * len(topics)
    checklist_title = f"🧵 batch: {theme!r} ({len(topics)} skill(s))"

    applied = 0
    for i, topic in enumerate(topics):
        statuses[i] = "in_progress"
        print(render_checklist(list(zip(topics, statuses)), title=checklist_title))
        result = propose_skill(
            skill_research,
            audit_gate,
            store,
            activity_log,
            topic,
            repo_root=repo_root,
            max_attempts=DEFAULT_BATCH_MAX_ATTEMPTS,
        )
        applied_now = result.startswith("[APPLIED]")
        statuses[i] = "done" if applied_now else "failed"
        applied += applied_now

    print(render_checklist(list(zip(topics, statuses)), title=checklist_title))
    message = f"[batch] {applied}/{len(topics)} skill(s) applied for theme {theme!r} -- see 'skills'"
    _print_status(message)
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
    short_term: ShortTermMemory | None = None,
    deployment_manager: DeploymentManager | None = None,
    hot_swap_factories: dict[str, Callable[[type], SubAgent]] | None = None,
    initial_reasons: list[str] | None = None,
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
    here. A successful patch is then auto-committed (before the relaunch
    below, since os.execv never returns) -- same policy as propose_skill,
    never `git push`. `do_relaunch=False` lets tests exercise the full
    pipeline without actually replacing the test process. `deployment_manager`/
    `hot_swap_factories`, when both given, let a patch to one of
    `_HOT_SWAP_TARGETS` (a file defining a live Router sub-agent) take
    effect via an in-process hot-swap instead of a full relaunch -- see
    `_relaunch_or_rollback`/`_attempt_hot_swap`. Every gate above this
    point (audit gate, isolated test suite, apply, commit) is identical
    either way; only how the already-verified change takes effect
    differs. `initial_reasons`, when given, seeds the very first
    attempt's retry feedback instead of starting blind -- for a task
    that's already failed in a PRIOR round (see `run_task`, which
    passes the task's own recorded failure note here): without this, a
    reconsidered BLOCKED task started every fresh round with zero
    memory of why the last one failed, so the identical mistake could
    repeat indefinitely across rounds even though a single round's own
    internal attempts already retry with feedback. Returns the message
    printed, for testability.
    """
    if not subject or not topic:
        message = "[usage: patch <repo-relative path> <description of the change>]"
        _print_status(message)
        return message

    # Checked here, before ever calling the drafting LLM, not left for
    # apply_source_patch to discover after a whole drafting attempt: a
    # live bug report showed a subject outside this scope (docs/EVOLUTION.md)
    # burning a real drafting attempt -- the model, unable to see enough
    # of a large file (a separate bug, fixed below in draft_patch), spun
    # into a confused, misleading failure ("no real drafting intelligence
    # available", which sounds like an infrastructure problem, not a
    # scope one) instead of getting an instant, honest answer for free.
    if not subject.startswith(SELF_PATCH_SCOPE_PREFIX):
        message = (
            f"[rejected] {subject!r} is outside self-patch's scope "
            f"({SELF_PATCH_SCOPE_PREFIX!r} only) -- self-patch changes Simorgh's own "
            "logic, not its docs, tests, or config. Edit that file directly, or "
            "describe what should change in plain conversation."
        )
        _print_status(message)
        return message

    proposal = None
    verdict = None
    prior_reasons: list[str] | None = initial_reasons
    for attempt in range(1, max_attempts + 1):
        if attempt == 1:
            print(f"🛠️  [patch] drafting a patch to {subject!r}: {topic!r}...")
        else:
            print(f"🛠️  [patch] attempt {attempt}/{max_attempts}: asking for a corrected draft...")
        proposal, draft_failure_reason = self_patch_agent.draft_patch(
            subject, topic, prior_reasons=prior_reasons
        )
        if proposal is None:
            # Two of draft_patch's three failure reasons are genuinely
            # not worth retrying: "deterministic_fallback" (no real LLM
            # answered at all -- the same fixed local template would
            # fail identically every time) and a "refused: ..." target
            # problem (the file itself is the issue, not the draft).
            # The third -- a real provider answered but its response
            # wasn't valid Python -- is exactly the kind of recoverable
            # failure this loop already retries-with-feedback for audit
            # rejections; collapsing it into an immediate stop wasted a
            # real, billed attempt on the very first try, live-caught
            # while an ambitious creative-agenda task (a big, self-
            # directed idea, not a small fix) hit it repeatedly.
            if draft_failure_reason == "deterministic_fallback":
                message = "[patch] no real drafting intelligence available -- nothing applied"
                _print_status(message)
                return message
            if draft_failure_reason is not None and draft_failure_reason.startswith("refused: "):
                message = f"[rejected] {draft_failure_reason}"
                _print_status(message)
                return message
            reason = draft_failure_reason or "the draft was empty"
            print(f"⚠️  [patch] attempt {attempt} failed: {reason}")
            activity_log.record_tool_call(
                "self_patch", "DRAFT", f"{subject}: {topic} (attempt {attempt}/{max_attempts})",
                reason, False,
            )
            prior_reasons = [reason]
            verdict = None
            continue

        if subject.endswith("main.py"):
            invariant_reason = check_main_py_invariants(proposal.code)
            if invariant_reason is not None:
                print(f"⚠️  [patch] attempt {attempt} failed: {invariant_reason}")
                activity_log.record_tool_call(
                    "self_patch", "DRAFT", f"{subject}: {topic} (attempt {attempt}/{max_attempts})",
                    invariant_reason, False,
                )
                prior_reasons = [invariant_reason]
                verdict = None
                continue

        print(
            f"🔎 [patch] drafted a candidate for {subject} -- running it through the audit "
            "gate (denylist, adaptive-immunity memory, then a real sandboxed run)..."
        )
        verdict = audit_gate.review(proposal)
        activity_log.record_tool_call(
            "self_patch", "DRAFT", f"{subject}: {topic} (attempt {attempt}/{max_attempts})",
            "passed audit gate" if verdict.approved_by_automation else "; ".join(verdict.reasons),
            verdict.approved_by_automation,
        )
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
    commit_result = commit_applied_change(
        repo_root or Path.cwd(),
        proposal.subject,
        _patch_commit_message(proposal.subject, proposal.rationale, suite_result.summary),
    )
    committed_note = (
        "committed (not pushed)" if commit_result.committed else f"NOT committed: {commit_result.output}"
    )
    message = (
        f"[APPLIED] {target} -- {proposal.rationale} "
        f"(isolated test suite: {suite_result.test_count} tests passed; {committed_note})"
    )
    _print_status(message)
    if commit_result.committed:
        print(style("📦 [git] committed -- push whenever you're ready", "green"))
    else:
        print(style(f"⚠️  [git] {commit_result.output}", "yellow"))

    if do_relaunch and commit_result.committed:
        # None here means "no override" (the [APPLIED] message above
        # already stands) -- only true for a real relaunch's unreachable
        # success path. A hot-swap success returns its own descriptive
        # message, same as a failure's [REVERTED] one; both override.
        activation_message = _relaunch_or_rollback(
            repo_root,
            target,
            short_term=short_term,
            subject=proposal.subject,
            deployment_manager=deployment_manager,
            hot_swap_factories=hot_swap_factories,
        )
        if activation_message is not None:
            message = activation_message
            _print_status(message)

    return message


# The narrow set of files this self-patching pipeline will try an
# in-process hot-swap for instead of a full relaunch: exactly the
# modules that define one of build_router()'s live Router sub-agents
# (module path, class name). A patch to anything else -- main.py,
# orchestrator internals, anything not on this list -- still always
# relaunches, unchanged. Deliberately does NOT cover
# propose_patch_batch/evolve (a batch may touch several files at once;
# deciding which slot(s) to trial and in what order is a separate
# design question left for later, see docs/EVOLUTION.md).
_HOT_SWAP_TARGETS: dict[str, tuple[str, str]] = {
    "src/agents/logic/base.py": ("src.agents.logic.base", "LogicAgent"),
    "src/agents/emotion/base.py": ("src.agents.emotion.base", "EmotionAgent"),
    "src/agents/skills/base.py": ("src.agents.skills.base", "SkillsAgent"),
}

# A handful of representative, safe canned requests per slot, used only
# to smoke-test that a freshly reloaded, freshly constructed candidate
# actually runs without raising -- the same thing relaunch()'s
# --self-check subprocess verifies for a full relaunch, scoped to just
# this one class instead of the whole process. Not a claim about
# conversational quality (DeploymentManager's default evaluator only
# checks "didn't raise"): there's no oracle to judge that without a real
# LLM, and this project doesn't fake one.
_HOT_SWAP_TRIAL_REQUESTS: dict[str, tuple[str, ...]] = {
    "logic": ("hello", "how are you today?", "what can you help me with?"),
    "emotion": ("I'm really happy about this!", "this is terrible news", "a neutral statement"),
    "skills": ("print('hot-swap trial')",),
}


def _reload_hot_swap_class(module_name: str, class_name: str) -> type | None:
    """The real reload step `_attempt_hot_swap` uses by default --
    injectable there for tests, since this function's whole point is a
    side effect (mutating `sys.modules`) a unit test shouldn't have to
    depend on the real file on disk to exercise. Returns None instead of
    raising if the module won't import, doesn't have `class_name`, or
    `class_name` no longer names a SubAgent subclass after reload.
    """
    try:
        module = importlib.reload(importlib.import_module(module_name))
        cls = getattr(module, class_name, None)
    except Exception:
        return None
    return cls if isinstance(cls, type) and issubclass(cls, SubAgent) else None


def _revert_patch_commit(repo_root: Path | None, target: Path, detail: str) -> str:
    """Shared by the relaunch-failure and hot-swap-trial-failure paths
    below: undo the just-made commit (src/orchestrator/git_ops.py,
    revert_last_commit) rather than leaving a broken commit sitting on
    top of a working history, and report exactly what happened either
    way.
    """
    revert_result = revert_last_commit(repo_root or Path.cwd())
    if revert_result.committed:
        print(style("↩️  [patch] reverted -- the working tree is back to its prior state", "yellow"))
    else:
        print(
            style(
                f"⚠️  [patch] revert also failed ({revert_result.output}) -- "
                "the applied commit is still there; review it by hand",
                "red",
                "bold",
            )
        )
    return f"[REVERTED] {target} passed every mechanical check but {detail}"


def _attempt_hot_swap(
    deployment_manager: DeploymentManager,
    hot_swap_factories: dict[str, Callable[[type], SubAgent]],
    subject: str,
    repo_root: Path | None,
    target: Path,
    reload_class: Callable[[str, str], type | None] = _reload_hot_swap_class,
) -> tuple[bool, str | None]:
    """Try an in-process hot-swap instead of a full relaunch, for a
    patch that landed on one of `_HOT_SWAP_TARGETS`. Returns
    `(attempted, message)`: `attempted=False` means the caller should
    fall through to the normal relaunch path unchanged (this subject
    isn't hot-swap-eligible, the module wouldn't reload cleanly, or
    building a candidate instance raised); `attempted=True` means this
    fully handled the outcome -- `message` is a descriptive
    "[APPLIED] ... hot-swapped ..." string on a successful promotion (so
    the caller reports what actually happened -- unlike a real relaunch,
    a hot-swap success is a normal, reachable return, not something
    replacing the process outright) or a "[REVERTED] ..." string on a
    failed trial, exactly like `_relaunch_or_rollback`'s own contract on
    failure, so the caller
    can treat both the same way.
    """
    target_spec = _HOT_SWAP_TARGETS.get(subject)
    if target_spec is None or subject not in hot_swap_factories:
        return False, None

    module_name, class_name = target_spec
    cls = reload_class(module_name, class_name)
    if cls is None:
        print(
            style(
                f"⚠️  [patch] could not reload {module_name}.{class_name} for a hot-swap "
                "candidate -- falling back to a full relaunch",
                "yellow",
            )
        )
        return False, None

    try:
        candidate = hot_swap_factories[subject](cls)
    except Exception as exc:
        print(
            style(
                f"⚠️  [patch] hot-swap candidate construction failed ({exc!r}) -- "
                "falling back to a full relaunch",
                "yellow",
            )
        )
        return False, None

    slot = candidate.name
    trial_texts = _HOT_SWAP_TRIAL_REQUESTS.get(slot, ("hello",))
    requests = [AgentRequest(text=t) for t in trial_texts]
    print(
        f"🔀 [patch] trialing the patched {slot!r} slot in-process "
        f"({len(requests)} request(s), no restart if it passes)..."
    )
    try:
        promoted, report = deployment_manager.hot_swap(candidate, requests)
    except ValueError as exc:
        # No active version staged for this slot yet (deploy() was never
        # called for it) -- setup issue, not a candidate-quality issue.
        print(
            style(
                f"⚠️  [patch] hot-swap unavailable for {slot!r} ({exc!r}) -- "
                "falling back to a full relaunch",
                "yellow",
            )
        )
        return False, None

    if promoted:
        print(
            style(
                f"🔀 [patch] hot-swapped into the live {slot!r} slot -- "
                "no restart needed, this conversation continues",
                "green",
                "bold",
            )
        )
        return True, (
            f"[APPLIED] {target} -- hot-swapped into the live {slot!r} slot, "
            "no restart needed"
        )

    print(
        style(
            f"🚫 [patch] hot-swap trial failed for {slot!r} "
            f"({report.candidate_success_rate:.0%} vs baseline {report.baseline_success_rate:.0%}) "
            "-- reverting",
            "red",
            "bold",
        )
    )
    return True, _revert_patch_commit(
        repo_root, target, f"failed its in-process hot-swap trial for the {slot!r} slot"
    )


def _relaunch_or_rollback(
    repo_root: Path | None,
    target: Path,
    short_term: ShortTermMemory | None = None,
    subject: str | None = None,
    deployment_manager: DeploymentManager | None = None,
    hot_swap_factories: dict[str, Callable[[type], SubAgent]] | None = None,
) -> str | None:
    """Shared by propose_self_patch (a human-typed `patch`) and the
    autonomous task runner below. If `subject` names a file
    `_HOT_SWAP_TARGETS` recognizes and both `deployment_manager` and
    `hot_swap_factories` are given, tries an in-process hot-swap first
    (see `_attempt_hot_swap`) -- narrower, faster, and doesn't
    interrupt the running process at all. Otherwise (or if hot-swap
    wasn't attempted for any reason) falls through to the original
    relaunch path: relaunch() verifies the new code actually starts
    (see src/orchestrator/self_patch.py) before replacing this process
    with it; on failure, undo the just-made commit
    (src/orchestrator/git_ops.py, revert_last_commit) rather than
    leaving a broken commit sitting on top of a working history. Returns
    a "[REVERTED] ..." message on failure. On success, returns a
    descriptive "[APPLIED] ... hot-swapped ..." message for a hot-swap
    (a real, reachable return -- the caller should use it to replace its
    default message), or None for a real relaunch (the caller's default
    message stands -- this is actually unreachable in production, since
    a real relaunch replaces the process outright and never returns here
    at all).
    """
    if deployment_manager is not None and hot_swap_factories is not None and subject is not None:
        attempted, message = _attempt_hot_swap(
            deployment_manager, hot_swap_factories, subject, repo_root, target
        )
        if attempted:
            return message

    if short_term is not None and len(short_term) > 0:
        short_term.save(DEFAULT_RELAUNCH_CONTEXT_PATH)
    print("🔍 [patch] verifying the new code actually starts before relaunching into it...")
    relaunch_result = relaunch()
    if relaunch_result.succeeded:
        return None
    print(style(f"🚫 [patch] self-check failed: {relaunch_result.detail}", "red", "bold"))
    return _revert_patch_commit(
        repo_root, target, f"failed to start as a live process: {relaunch_result.detail}"
    )


def _patch_commit_message(subject: str, rationale: str, test_summary: str) -> str:
    return (
        f"[sim] Patch {subject}\n\n"
        f"{rationale}\n\n"
        f"Isolated test suite: {test_summary}\n\n"
        "Auto-committed by Simorgh's self-patch pipeline (audited: denylist, "
        "adaptive-immunity memory, sandboxed run, then this repository's "
        "entire test suite run fresh in an isolated copy). Never pushed "
        "automatically -- see docs/SOUL.md, \"Self-patching source code.\""
    )


_EVOLVE_BRAINSTORM_PROMPT = """List exactly {count} distinct, focused architectural improvements to this
Python codebase, toward the goal: {goal}

These are REAL changes to Sim's own core source, not new standalone
skill files -- each one must name a specific file to create or revise
under src/ (never under src/agents/skills/, that's a separate, lighter-
weight pipeline for standalone add-ons) and a one-line description of
the change. Keep each one small and targeted: a genuine, focused
improvement to ONE file, not a rewrite, not several files at once.

Files that already exist in this codebase (prefer revising one of these
when it genuinely fits the goal; naming a new path under src/ is fine
too, for something genuinely new):
{files}

Respond with ONLY a numbered list, one per line, in exactly this format:
1. <repo-relative path under src/> :: <description>
2. <repo-relative path under src/> :: <description>
...
{count}. <repo-relative path under src/> :: <description>
No other text before or after the list."""

_EVOLVE_TARGET_LINE = re.compile(r"^\s*\d+[.):]\s*(\S+)\s*::\s*(.+)$")


def _list_source_files(repo_root: Path, limit: int = 200) -> list[str]:
    """Every tracked .py file under src/, excluding src/agents/skills/
    (that's propose/batch/plan's territory, not evolve's) -- context for
    the brainstorm prompt so it names real files instead of guessing at
    plausible-looking paths that don't exist.
    """
    src = repo_root / "src"
    if not src.is_dir():
        return []
    files = sorted(
        str(p.relative_to(repo_root))
        for p in src.rglob("*.py")
        if "skills" not in p.relative_to(src).parts
    )
    return files[:limit]


def _parse_evolve_targets(text: str, expected_count: int) -> list[tuple[str, str]]:
    pairs = []
    for line in text.splitlines():
        match = _EVOLVE_TARGET_LINE.match(line)
        if not match:
            continue
        path, description = match.group(1).strip(), match.group(2).strip()
        if path.startswith("src/") and "src/agents/skills/" not in path and description:
            pairs.append((path, description))
    return pairs[:expected_count]


_CREATIVE_AGENDA_PROMPT = """You are Sim, deciding your OWN next self-improvement priorities --
nobody gave you a goal this time. Look at your own capabilities and
think ambitiously: not a small bug fix, a genuine idea for how you
could become more capable, more autonomous, more self-aware, or more
useful to work with.

Propose exactly {count} distinct, ambitious architectural improvements
to your own source code. Each one must name a specific file to create
or revise under src/ (never under src/agents/skills/, that's a
separate, lighter-weight pipeline for standalone add-ons) and a
one-line description of the change and why it matters. Keep each one
small and targeted enough to actually implement in one patch -- a real,
focused step toward a big idea, not the whole idea at once.

Files that already exist in this codebase (prefer revising one of
these when it genuinely fits; naming a new path under src/ is fine
too, for something genuinely new):
{files}

Respond with ONLY a numbered list, one per line, in exactly this format:
1. <repo-relative path under src/> :: <description>
2. <repo-relative path under src/> :: <description>
...
{count}. <repo-relative path under src/> :: <description>
No other text before or after the list."""

DEFAULT_CREATIVE_AGENDA_COUNT = 2
_CREATIVE_AGENDA_DEDUPE_MIN_OVERLAP_CHARS = 24


def discover_creative_improvements(
    cognition: CognitionRouter,
    task_store: TaskStore,
    repo_root: Path | None = None,
    count: int = DEFAULT_CREATIVE_AGENDA_COUNT,
    provider_sink: dict | None = None,
) -> list[Task]:
    """The other half of "find gaps AND come up with big ideas":
    discover_improvements (src/orchestrator/discovery.py) only reacts to
    signals that already exist (a recurring failure pattern, a
    takeaway) -- it has nothing to say when nothing has gone wrong yet.
    This is Sim setting its OWN agenda instead of only ever reacting:
    one bounded LLM call, genuinely creative (no goal is given, unlike
    propose_patch_batch/evolve's human-supplied goal), asked to think
    ambitiously about its own architecture and propose real, focused
    next steps. Reuses evolve's exact brainstorm/parse output shape
    (`_parse_evolve_targets`'s `path :: description` format) since only
    the framing differs, not the shape. Deterministic-fallback-safe like
    every other creative/drafting call in this codebase (see
    src/cognition/provider.py's guaranteed-floor pattern): returns
    nothing rather than a fabricated agenda when no real provider
    answers, so an idle tick with no LLM configured is silently a no-op
    here, same as discover_improvements finding nothing. Deduped against
    every existing task description, same substring-containment
    approach discovery.py's `_already_covered` uses, so a repeated tick
    doesn't pile up near-duplicate ambitions. `provider_sink`, if given,
    is updated with {"provider_name": ...} from the response -- lets a
    caller (`_autonomous_action`) tell a genuine, possibly-billed LLM
    attempt apart from a free deterministic-fallback no-op, without this
    function's return type carrying anything beyond the created tasks
    (same sink pattern `_dispatch_and_record`'s `metadata_sink` uses).
    """
    root = repo_root or Path.cwd()
    response = cognition.complete(
        _CREATIVE_AGENDA_PROMPT.format(
            count=count, files="\n".join(_list_source_files(root)) or "(none found)"
        )
    )
    if provider_sink is not None:
        provider_sink["provider_name"] = response.provider_name
    if response.provider_name == "deterministic_fallback":
        return []

    targets = _parse_evolve_targets(response.text, count)
    existing_descriptions = [t.description for t in task_store.all()]
    created: list[Task] = []
    for path, description in targets:
        # A protected-file target (audit.py's PROTECTED_SUBJECTS) can
        # NEVER pass AuditGate.review() no matter how good the draft
        # is -- letting it become a task anyway means every attempt
        # (each one a real, billed LLM call) is guaranteed to fail for
        # the same unfixable reason, and a BLOCKED task keeps getting
        # reconsidered later, repeating the waste. Caught live: a
        # creative-agenda idea targeting self_patch.py (protected) burned
        # three real Gemini calls, got rejected three times, went
        # BLOCKED, then got retried and rejected again on the very next
        # reconsideration pass. Filtered out here, before ever touching
        # the task store, rather than left for the audit gate to keep
        # discovering the same impossibility over and over.
        if any(protected in path for protected in PROTECTED_SUBJECTS):
            print(
                f"[discover] skipping a self-directed idea for {path!r} -- "
                "that file can never be self-patched (protected)"
            )
            continue
        if _creative_agenda_already_covered(description, existing_descriptions):
            continue
        task = task_store.add(
            description, PATCH_TASK, subject=path, discovered_via="creative_agenda"
        )
        created.append(task)
        existing_descriptions.append(description)
    return created


def _creative_agenda_already_covered(candidate: str, existing_descriptions: list[str]) -> bool:
    if len(candidate) < _CREATIVE_AGENDA_DEDUPE_MIN_OVERLAP_CHARS:
        return candidate in existing_descriptions
    return any(candidate in existing or existing in candidate for existing in existing_descriptions)


def propose_patch_batch(
    cognition: CognitionRouter,
    self_patch_agent: SelfPatchAgent,
    audit_gate: AuditGate,
    store: MemoryStore,
    activity_log: ActivityLog,
    goal: str,
    count: int,
    repo_root: Path | None = None,
    do_relaunch: bool = True,
    short_term: ShortTermMemory | None = None,
) -> str:
    """The creator's direct ask, "I want Sim to evolve itself, not just
    add a bunch of new skill files" -- batch/plan only ever call
    propose_skill, which apply_proposal hard-scopes to
    src/agents/skills/ (new, standalone files, sandboxed smoke-tested).
    This is the analogous batch pipeline for REAL patches: one bounded
    LLM call brainstorms `count` (capped at MAX_EVOLVE_COUNT -- lower
    than batch's, since each item here is meaningfully more expensive)
    distinct architectural changes, each naming a real existing-or-new
    file under src/ (never src/agents/skills/), then propose_self_patch
    -- unchanged, same audit gate, same isolated full test suite, same
    auto-commit -- runs once per target.

    Every individual propose_self_patch call here uses do_relaunch=False:
    relaunching after patch #1 would replace this process via os.execv
    before patches #2..N ever ran. Instead this relaunches AT MOST ONCE,
    after the whole batch, and rolls back EVERY commit from this batch
    together (git_ops.revert_commits_since, not just the last one) if
    the combined result fails the post-batch self-check -- a single bad
    patch out of several must not leave the other N-1 stranded in a
    half-reverted state.
    """
    if not 1 <= count <= MAX_EVOLVE_COUNT or not goal:
        message = f"[usage: evolve <count 1-{MAX_EVOLVE_COUNT}> <goal>]"
        _print_status(message)
        return message

    root = repo_root or Path.cwd()
    print(f"🧬 [evolve] brainstorming {count} architectural change(s) toward {goal!r}...")
    response = cognition.complete(
        _EVOLVE_BRAINSTORM_PROMPT.format(
            goal=goal, count=count, files="\n".join(_list_source_files(root)) or "(none found)"
        )
    )
    if response.provider_name == "deterministic_fallback":
        message = "[evolve] no real drafting intelligence available -- try 'patch <path> <description>' directly instead"
        _print_status(message)
        return message

    targets = _parse_evolve_targets(response.text, count)
    if not targets:
        message = "[evolve] could not produce real file targets -- try a narrower goal, or 'patch <path> <description>' directly"
        _print_status(message)
        return message

    print(f"🧬 [evolve] got {len(targets)} target(s):")
    for path, description in targets:
        print(f"   {path} -- {description}")

    base_commit = current_commit_hash(root)
    target_labels = [f"{path}: {description}" for path, description in targets]
    statuses = ["pending"] * len(targets)
    checklist_title = f"🧬 evolve: {goal!r} ({len(targets)} change(s))"

    applied = 0
    for i, (path, description) in enumerate(targets):
        statuses[i] = "in_progress"
        print(render_checklist(list(zip(target_labels, statuses)), title=checklist_title))
        result = propose_self_patch(
            self_patch_agent,
            audit_gate,
            store,
            activity_log,
            path,
            description,
            repo_root=root,
            max_attempts=DEFAULT_EVOLVE_MAX_ATTEMPTS,
            do_relaunch=False,
        )
        applied_now = result.startswith("[APPLIED]")
        statuses[i] = "done" if applied_now else "failed"
        applied += applied_now

    print(render_checklist(list(zip(target_labels, statuses)), title=checklist_title))
    message = f"[evolve] {applied}/{len(targets)} architectural change(s) applied for goal {goal!r}"
    _print_status(message)

    if applied == 0 or not do_relaunch:
        return message

    if short_term is not None and len(short_term) > 0:
        short_term.save(DEFAULT_RELAUNCH_CONTEXT_PATH)
    print("🔍 [evolve] verifying the new code actually starts before relaunching into it...")
    relaunch_result = relaunch()
    if relaunch_result.succeeded:
        return message  # unreachable in production -- a real relaunch never returns

    print(style(f"🚫 [evolve] self-check failed: {relaunch_result.detail}", "red", "bold"))
    if base_commit is not None:
        revert_result = revert_commits_since(root, base_commit)
        if revert_result.committed:
            print(style(f"↩️  [evolve] reverted all {applied} change(s) from this batch", "yellow"))
        else:
            print(
                style(
                    f"⚠️  [evolve] revert also failed ({revert_result.output}) -- "
                    "the applied commits are still there; review them by hand",
                    "red",
                    "bold",
                )
            )
    else:
        print(style("⚠️  [evolve] couldn't determine a base commit to revert to -- review by hand", "red", "bold"))
    message = (
        f"[REVERTED] evolve batch ({applied} change(s)) passed every mechanical check but "
        f"failed to start as a live process: {relaunch_result.detail}"
    )
    _print_status(message)
    return message


def run_task(
    task_store: TaskStore,
    task: Task,
    skill_research: SkillResearchAgent,
    self_patch_agent: SelfPatchAgent,
    audit_gate: AuditGate,
    store: MemoryStore,
    activity_log: ActivityLog,
    cognition: CognitionRouter,
    repo_root: Path | None = None,
) -> tuple[str, bool]:
    """Drive one persisted Task through the unchanged propose_skill/
    propose_self_patch pipelines -- the task queue only decides WHAT to
    work on and tracks WHETHER it succeeded; it is never a second,
    weaker path around the audit gate, the test suite, or auto-commit
    that a human-typed command goes through.

    propose_self_patch is always called with do_relaunch=False here:
    relaunching (and the self-check/rollback it implies) is deliberately
    deferred to the caller, via the second return value, so the task's
    DONE status is safely persisted *before* os.execv ever replaces this
    process -- doing it the other way around would leave a resumed
    process finding the task stuck IN_PROGRESS forever, having actually
    already finished it. Returns (message, needs_relaunch).
    """
    task_store.update_status(task.id, IN_PROGRESS, attempt=True)

    # A task reconsidered after being BLOCKED already carries a real
    # failure reason in its own note (see _reconsider_blocked_tasks) --
    # without seeding it here, every fresh round started blind, with no
    # memory of why the last one failed, so the identical mistake could
    # repeat indefinitely across rounds even though a single round's own
    # internal attempts already retry with feedback. Live-caught: a real
    # self-patch task failed the exact same generic way across multiple
    # reconsideration rounds with zero improvement.
    initial_reasons = [task.note] if task.attempts > 0 and task.note else None

    if task.kind == PATCH_TASK:
        result = propose_self_patch(
            self_patch_agent,
            audit_gate,
            store,
            activity_log,
            task.subject,
            task.description,
            repo_root=repo_root,
            do_relaunch=False,
            initial_reasons=initial_reasons,
        )
    else:
        result = propose_skill(
            skill_research,
            audit_gate,
            store,
            activity_log,
            task.description,
            repo_root=repo_root,
            initial_reasons=initial_reasons,
        )

    if not result.startswith("[APPLIED]"):
        next_status = BLOCKED if task.attempts + 1 >= MAX_TASK_ATTEMPTS else PENDING
        task_store.update_status(task.id, next_status, note=result, attempt=False)
        return result, False

    verification = verify_task_completion(cognition, task, result)
    if not verification.passed:
        task_store.update_status(
            task.id, BLOCKED, note=f"applied but failed review: {verification.explanation}"
        )
        print(style(f"🔬 [verify] looks off-target: {verification.explanation}", "yellow", "bold"))
        return result, False

    task_store.update_status(task.id, DONE, note=result)
    return result, task.kind == PATCH_TASK


MAX_BLOCKED_RETRY_ATTEMPTS = 9  # 3 more rounds of MAX_TASK_ATTEMPTS each


def _next_task(task_store: TaskStore) -> Task | None:
    """Prefer resuming a task an earlier process left IN_PROGRESS
    (interrupted by a crash or relaunch mid-work) over starting a fresh
    PENDING one -- the direct mechanism behind "on restart, find pending
    task and resume." Once there's no fresh work at all, reconsiders
    BLOCKED tasks (see _reconsider_blocked_tasks) rather than leaving
    them stuck forever -- the direct mechanism behind "check if you're
    blocked and automatically unblock yourself."
    """
    unfinished = task_store.unfinished()
    in_progress = [t for t in unfinished if t.status == IN_PROGRESS]
    pending = [t for t in unfinished if t.status == PENDING]
    ordered = in_progress + pending
    if ordered:
        return ordered[0]
    return _reconsider_blocked_tasks(task_store)


def _reconsider_blocked_tasks(task_store: TaskStore) -> Task | None:
    """Gives one BLOCKED task another shot by resetting it to PENDING,
    so the next work_on_next_task() call (a human's 'work', or the
    autonomous loop -- which already checks roughly every cooldown
    period once idle, see src/orchestrator/autonomy.py) picks it up
    fresh. Not every BLOCKED task is truly stuck: some failed because a
    particular draft was wrong, not because the task itself is
    impossible, and a fresh attempt (possibly with different randomness
    in the LLM's response) can succeed where a prior one didn't.

    Bounded, not infinite: once a task's total attempts reach
    MAX_BLOCKED_RETRY_ATTEMPTS, this stops retrying it and marks it
    FAILED instead -- a genuine terminal state, not indefinite limbo,
    for the tasks that really are permanently blocked (e.g. a directive
    violation no rephrasing will pass). Returns the task just reset to
    PENDING, or None if nothing changed.
    """
    for task in task_store.all():
        if task.status != BLOCKED:
            continue
        if task.attempts >= MAX_BLOCKED_RETRY_ATTEMPTS:
            task_store.update_status(
                task.id, FAILED, note=f"gave up after {task.attempts} attempts: {task.note}"
            )
            continue
        task_store.update_status(
            task.id, PENDING, note=f"retrying after being blocked: {task.note}"
        )
        return task_store.get(task.id)
    return None


def work_on_next_task(
    task_store: TaskStore,
    skill_research: SkillResearchAgent,
    self_patch_agent: SelfPatchAgent,
    audit_gate: AuditGate,
    store: MemoryStore,
    activity_log: ActivityLog,
    cognition: CognitionRouter,
    repo_root: Path | None = None,
    label: str = "work",
    short_term: ShortTermMemory | None = None,
    deployment_manager: DeploymentManager | None = None,
    hot_swap_factories: dict[str, Callable[[type], SubAgent]] | None = None,
) -> str:
    """Pick and run exactly one task from the persisted backlog. `label`
    lets the autonomous loop (src/orchestrator/autonomy.py) reuse this
    with an "[autonomous]" prefix instead of "[work]", so a
    self-triggered action is never visually confused with one the
    creator typed -- Directive 8, concretely.
    """
    task = _next_task(task_store)
    if task is None:
        message = f"[{label}] nothing pending -- try 'discover' or 'plan <count> <goal>'"
        _print_status(message)
        return message

    print(style(f"🏗️  [{label}] {task.description}", "cyan", "bold"))
    result, needs_relaunch = run_task(
        task_store,
        task,
        skill_research,
        self_patch_agent,
        audit_gate,
        store,
        activity_log,
        cognition,
        repo_root=repo_root,
    )
    if needs_relaunch:
        target = Path(repo_root or Path.cwd()) / task.subject
        # None means "no override" (unreachable relaunch-success path);
        # a hot-swap success returns its own [APPLIED] message (a real,
        # reachable return, unlike relaunch) and must NOT be treated as
        # a failure -- only a [REVERTED] message means the task failed.
        activation_message = _relaunch_or_rollback(
            repo_root,
            target,
            short_term=short_term,
            subject=task.subject,
            deployment_manager=deployment_manager,
            hot_swap_factories=hot_swap_factories,
        )
        if activation_message is not None:
            result = activation_message
            if activation_message.startswith("[REVERTED]"):
                task_store.update_status(task.id, BLOCKED, note=activation_message)
            else:
                task_store.update_status(task.id, DONE, note=activation_message)
            _print_status(result)
    return result


def discover_command(
    task_store: TaskStore, reflection_agent: ReflectionAgent, store: MemoryStore
) -> str:
    created = discover_improvements(task_store, reflection_agent, store)
    if not created:
        message = "[discover] no new improvement areas found right now"
        _print_status(message)
        return message
    print(style(f"🔭 [discover] found {len(created)} improvement area(s):", "magenta", "bold"))
    for task in created:
        print(f"   + [{task.id}] ({task.discovered_via}) {task.description}")
    message = f"[discover] {len(created)} new task(s) added -- see 'tasks', or 'work' to start"
    _print_status(message)
    return message


def plan_goal(cognition: CognitionRouter, task_store: TaskStore, goal: str, count: int) -> str:
    """Break a broad goal into `count` (max MAX_BATCH_COUNT) concrete,
    focused steps -- reusing the same brainstorm prompt 'batch' uses --
    and persist each as a PENDING Task rather than executing it
    immediately. This is the "plan, break down the required work, save
    them" step; 'work' (or the autonomous loop) actually executes a
    saved task later, through the exact same audited pipelines
    everything else goes through.
    """
    if not 1 <= count <= MAX_BATCH_COUNT or not goal:
        message = f"[usage: plan <count 1-{MAX_BATCH_COUNT}> <goal>]"
        _print_status(message)
        return message

    print(f"🧠 [plan] brainstorming {count} step(s) toward {goal!r}...")
    response = cognition.complete(_BATCH_BRAINSTORM_PROMPT.format(theme=goal, count=count))
    if response.provider_name == "deterministic_fallback":
        message = "[plan] no real drafting intelligence available -- try 'propose <topic>' directly instead"
        _print_status(message)
        return message

    topics = _parse_numbered_list(response.text, count)
    if not topics:
        message = "[plan] could not produce a step list -- try a narrower goal"
        _print_status(message)
        return message

    parent = task_store.add(goal, SKILL_TASK, discovered_via="user")
    for topic in topics:
        task = task_store.add(topic, SKILL_TASK, discovered_via="planner", parent_id=parent.id)
        print(f"   + [{task.id}] {topic}")

    message = (
        f"[plan] saved {len(topics)} step(s) toward {goal!r} -- "
        "'work' to start on them, or 'tasks' to see them all"
    )
    _print_status(message)
    return message


_STATUS_ICONS = {PENDING: "⏳", IN_PROGRESS: "🏗️ ", BLOCKED: "🚫", DONE: "✅", FAILED: "❌"}


def _print_tasks(task_store: TaskStore) -> None:
    tasks = task_store.unfinished()
    print(style(f"🗂️  Task backlog ({len(tasks)} unfinished)", "magenta", "bold"))
    if not tasks:
        print(style("  (nothing pending -- try 'discover' or 'plan <count> <goal>')", "dim"))
        return
    for task in tasks:
        icon = _STATUS_ICONS.get(task.status, "•")
        sub = f" ({task.subject})" if task.subject else ""
        note = f" — {task.note}" if task.note else ""
        print(f"  {icon} [{task.id}] {task.description}{sub}{note}")


def _handle_autonomous_command(arg: str, autonomy: AutonomyController) -> None:
    """`autonomous on`/`off`/`status` -- live control over the idle-
    triggered loop, so it's never a black box: 'status' reports exactly
    which gate (disabled, still active, in cooldown, at the daily cap)
    is currently holding it back, not just a yes/no.
    """
    if arg == "off":
        autonomy.enabled = False
        _print_status("[autonomous] disabled -- Sim will only act when you type a command")
        return
    if arg == "on":
        autonomy.enabled = True
        autonomy.reset_failure_streak()
        _print_status("[autonomous] enabled")
        return
    idle_for = autonomy.idle_seconds()
    print(style("🤖 Autonomous self-improvement", "magenta", "bold"))
    print(f"  enabled: {autonomy.enabled}")
    print(f"  idle for: {idle_for:.0f}s (threshold: {autonomy.idle_threshold_seconds:.0f}s)")
    print(f"  actions today: {autonomy.actions_today()}/{autonomy.max_actions_per_day}")
    if autonomy.consecutive_failures > 0:
        print(
            style(
                f"  consecutive failures: {autonomy.consecutive_failures} "
                f"(pauses itself at {autonomy.max_consecutive_failures})",
                "yellow",
            )
        )
    print(f"  ready to act right now: {autonomy.ready_to_act()}")


def _print_autonomous_digest(autonomy: AutonomyController) -> None:
    """A lightweight rollup of what the autonomous loop actually did
    over the last 24h -- previously the only way to review that was
    reading raw `log`/`tasks` output line by line; nothing summarized
    it. Complements 'autonomous status' (which reports the loop's
    current gating state) rather than duplicating it.
    """
    digest = autonomy.digest()
    print(style("🗞️  Autonomous activity digest (last 24h)", "magenta", "bold"))
    if digest.total == 0:
        print(style("  no autonomous actions in this window", "dim"))
        return
    print(f"  {digest.total} action(s): {digest.succeeded} succeeded, {digest.failed} failed", end="")
    print(f", {digest.unknown} other" if digest.unknown else "")
    if autonomy.consecutive_failures > 0:
        print(
            style(
                f"  current failure streak: {autonomy.consecutive_failures} "
                f"(pauses itself at {autonomy.max_consecutive_failures})",
                "yellow",
            )
        )


def _maybe_volunteer_during_conversation(
    growth_socializer: GrowthSocializer | None,
    news_socializer: NewsSocializer | None,
    interests: InterestTracker | None,
    cognition: CognitionRouter,
) -> None:
    """The other half of the fix for "it just waits for me to tell it
    what to do": AutonomyController's idle-triggered loop only ever gets
    a chance to speak up *between* conversations, since its idle clock
    resets on every typed command -- during an actively chatting session
    it can go the whole time without firing even once. That's the exact
    live-caught complaint this answers (creator: "just waiting for me to
    tell it what to do... I feel I'm in a terminal or shell"). Checked
    once after every ordinary conversational reply (never after a
    recognized command, which already has its own explicit purpose) --
    using the *same* GrowthSocializer/NewsSocializer pacing cooldowns the
    idle loop itself uses, via `maybe_share`, so this is a second trigger
    point for the same rate-limited behavior, not a second, spammier
    budget on top of it. Growth checked before news, same priority as
    `_autonomous_action` -- "evidence of self-improving" was the more
    pointed half of the original complaint.
    """
    if growth_socializer is not None:
        highlight = growth_socializer.maybe_share(cognition)
        if highlight is not None:
            _print_growth_highlight(highlight)
            return
    if interests is not None and news_socializer is not None:
        highlight = news_socializer.maybe_share(interests, cognition)
        if highlight is not None:
            _print_news_highlight(highlight)


def _print_news_highlight(highlight: NewsHighlight) -> None:
    """The shared presentation for a proactively-shared news item --
    used both by the autonomous idle path (unprompted, between prompts,
    the same 'print then redraw >' pattern src/orchestrator/reminders.py
    established) and by the typed 'news' command's own printing.
    """
    print(style(f"\n📰 [Sim] {highlight.blurb}", "magenta", "bold"))
    if highlight.source:
        print(style(f"   (from {highlight.source})", "dim"))


def news_command(
    interests: InterestTracker, news_socializer: NewsSocializer, cognition: CognitionRouter
) -> str:
    """The typed 'news' command: share the next unshared knowledge-base
    item right now, bypassing NewsSocializer's own pacing cooldown --
    an explicit request, the same way typing 'work' bypasses
    AutonomyController's idle-trigger check. Returns the message
    printed, for testability.
    """
    highlight = news_socializer.share_next(interests, cognition)
    if highlight is None:
        message = (
            "[news] nothing new to share right now -- try 'interest <feed url>' "
            "to track more sources, or 'interests' to see what's tracked"
        )
        _print_status(message)
        return message
    _print_news_highlight(highlight)
    return f"[news] {highlight.blurb}"


def _print_growth_highlight(highlight: GrowthHighlight) -> None:
    """The shared presentation for a proactively-shared self-improvement
    highlight -- same pattern as _print_news_highlight, a different
    icon so the two are visually distinguishable at a glance (growth is
    about Sim itself; news is about the outside world).
    """
    print(style(f"\n🌱 [Sim] {highlight.blurb}", "green", "bold"))
    print(style(f"   ({highlight.kind}: {highlight.subject})", "dim"))


def growth_command(growth_socializer: GrowthSocializer, cognition: CognitionRouter) -> str:
    """The typed 'growth' command: share the most recent unshared
    self-improvement right now, bypassing GrowthSocializer's own pacing
    cooldown -- an explicit request, the same way typing 'work' bypasses
    AutonomyController's idle-trigger check. Returns the message
    printed, for testability.
    """
    highlight = growth_socializer.share_next(cognition)
    if highlight is None:
        message = (
            "[growth] nothing applied yet to share -- try 'propose <topic>' or "
            "'patch <path> <description>', or see 'pending' for what's already there"
        )
        _print_status(message)
        return message
    _print_growth_highlight(highlight)
    return f"[growth] {highlight.blurb}"


_PENDING_FULL_SUFFIX = " --full"


def _print_pending(store: MemoryStore, subject: str = "") -> None:
    """Bare 'pending' lists every applied skill/patch (path + rationale).
    'pending <path>' shows what changed for the most recent applied
    change at that path -- previously the only way to review one was
    `git diff`/reading the file by hand; the code was already sitting
    right there in the record the whole time (apply_proposal/
    apply_source_patch both store `code=proposal.code`), just never
    surfaced. When an earlier applied version of the same path exists,
    shows a diff against it (shorter, and matches what actually
    changed -- the point of "minimizing" a big file down to what's
    relevant, the creator's own framing of what Claude Code's UI does
    well); 'pending <path> --full' always shows the complete current
    file instead, and a first-ever version (nothing to diff against)
    always does too, since there's nothing to collapse.
    """
    skills = store.query(kind=APPLIED_KIND)
    patches = store.query(kind=APPLIED_PATCH_KIND)
    if not skills and not patches:
        print(
            "[nothing applied yet -- try 'propose <topic>', 'improve <topic>', or "
            "'patch <path> <description>']"
        )
        return

    if subject:
        show_full = subject.endswith(_PENDING_FULL_SUFFIX)
        if show_full:
            subject = subject[: -len(_PENDING_FULL_SUFFIX)].strip()

        combined = sorted(skills + patches, key=lambda r: r.created_at, reverse=True)
        matches = [r for r in combined if r.content == subject]
        if not matches:
            print(f"[not found] nothing applied at {subject!r} -- see 'pending' for what's tracked")
            return
        record = matches[0]
        kind_label = "skill" if record.kind == APPLIED_KIND else "patch"
        print(style(f"📄 Applied {kind_label}: {subject}", "magenta", "bold"))
        print(f"  rationale: {record.metadata.get('rationale', '')}")
        test_summary = record.metadata.get("test_summary")
        if test_summary:
            print(f"  test suite: {test_summary.splitlines()[0]}")

        previous = matches[1] if len(matches) > 1 else None
        if previous is not None and not show_full:
            diff_lines = list(
                difflib.unified_diff(
                    (previous.metadata.get("code", "") or "").splitlines(keepends=True),
                    (record.metadata.get("code", "") or "").splitlines(keepends=True),
                    fromfile=f"{subject} (previous)",
                    tofile=f"{subject} (current)",
                )
            )
            print(format_diff_block(diff_lines, label=f"{subject} — diff vs previous version"))
            print(style(f"  ('pending {subject} --full' shows the complete current file)", "dim"))
        else:
            print(format_code_block(record.metadata.get("code", ""), label=subject))
        return

    print(style(f"📋 Applied changes ({len(skills) + len(patches)})", "magenta", "bold"))
    for record in skills:
        print(f"  [skill] {record.content} -- {record.metadata.get('rationale', '')}")
    for record in patches:
        print(f"  [patch] {record.content} -- {record.metadata.get('rationale', '')}")
    print(style("  ('pending <path>' shows what changed; add --full for the whole file)", "dim"))


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
        hint = (
            "" if urlparse(overdue.topic).scheme in ("http", "https")
            else " -- 'interest <topic>' an actual RSS/Atom feed URL to get real items back"
        )
        print(f"[curious about {overdue.topic!r}] no updates available{hint}")
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


def self_check() -> int:
    """Smoke-test this process's own code without entering the
    interactive loop: import everything relaunch() needs and construct
    the core objects (router, audit gate, cognition router) the same way
    run_cli() does. Used exclusively as `--self-check`, spawned by
    src/orchestrator/self_patch.py's relaunch() *before* it replaces the
    live process with this code via os.execv -- catches a startup-time
    bug the test suite didn't happen to exercise, at the one point where
    catching it is still possible (once execv runs, there is no "after"
    left to notice a crash in). Returns a process exit code (0 = OK, 1 =
    failed), never raises.
    """
    try:
        store = build_memory_store()
        cognition, _ = build_cognition_router(store)
        build_router(cognition=cognition, repo_root=Path.cwd())
        AuditGate(memory=store)
    except Exception as exc:  # noqa: BLE001 -- this must report any startup
        # failure as a clean exit code, not an uncaught traceback, since
        # relaunch() only inspects the exit code and stderr text.
        print(f"[self-check] FAILED: {exc!r}", file=sys.stderr)
        return 1
    print("[self-check] OK")
    return 0


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        sys.exit(self_check())
    run_cli()
