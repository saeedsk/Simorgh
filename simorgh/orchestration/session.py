"""The session state machine (16 section 5): CLAIMED -> GATHER -> THINK ->
(final -> VERIFY -> COMPLETED | tool_calls -> PROPOSE -> GATHER) with a
bounded evaluator-optimizer revision loop. One action is proposed per
step and awaited before the next THINK, except that up to
`[orchestration] parallel_read_tools` read-only calls from one reply
run together.

Optional, each behind its own `[orchestration]` switch: re-grounding
every `reground_every_steps` (`progress.py`), clean revisions, helper
tasks through the `delegate` tool (`delegation`, bounded by
`max_depth`), and strong-tier escalation (`escalate_from_attempt`).
Not built: Plan Mode artifact assembly and steer injection.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
import os
import re
import subprocess
import time
import uuid

from simorgh.contracts import topics

from . import pressure as pressure_mod

@dataclass(frozen=True)
class _CheckpointProposal:
    """The two fields `guardian.tiers.tier_of` reads, so the session can
    ask how far an action reached without building a real Proposal."""

    tool: str
    args: dict
    reversibility: str = ""

    def __post_init__(self) -> None:
        if not self.reversibility:
            from .tools import _TOOL_POLICY

            object.__setattr__(self, "reversibility", _TOOL_POLICY.get(self.tool, ("irreversible", False))[0])


def _args_hash(args: dict) -> str:
    import hashlib
    import json as _json

    return hashlib.sha256(_json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()[:16]


#: Agentic recall (stage 5 item 6): session-local, effect-free, so it never
#: reaches Guardian. Offered by the agents that list it.
MEMORY_SEARCH = "memory_search"

#: Stop and come back later (stage 7 item 5), holding no worker while
#: waiting. `WAIT: 10m` or `WAIT: until world.home.situation_changed`.
WAIT = "wait"

#: Tools the session answers itself: no Execution tool exists for them and
#: Guardian never sees them, because none of them has an effect. An agent
#: file may list `memory_search`; `delegate`, `use_skill` and
#: `recall_result` are added when the session has something to use them on.
SESSION_LOCAL = frozenset({MEMORY_SEARCH, WAIT, "delegate", "task", "use_skill", pressure_mod.RECALL_TOOL})
from . import progress as progress_note
from . import stophook
from .stophook import (  # noqa: F401 -- re-exported: tests and callers import them from here
    claimed_to_commit, claimed_to_note_a_pronunciation, claimed_tv_act, promised_behaviour, wanted_tv_act,
)
from simorgh.contracts.pytestfailures import hoist_marker
from simorgh.contracts.scratch import SCRATCH_PREFIX, is_scratch  # noqa: F401 -- re-export
from simorgh.contracts.envelope import Event, Message

from . import scaffolds
from .api import Outcome, Session, Step
from .context import DEFAULT_TIMEOUT_S, Assembler
from .claims import unsupported_claims
from .tools import is_read_only, known_tools, marker_hint, offered_tools, to_action_payload

# What a Guardian refusal looks like on a step, in one place. The step's
# `denied` flag is set from it, and Verification reads the flag rather
# than this string, so the prefix may change without the checks noticing.
DENIED_PREFIX = "denied: "
#: The outcome kind `_propose_and_await` gives a Guardian `action.denied`.
#: The other kinds are `action.result.error_kind` (refused | unconfigured
#: | transient | failed), or "" for a result that was ok.
DENIED_KIND = "denied"


class Detail(str):
    """A step's detail text that also carries its outcome kind, so a
    reader never has to work the kind out of the words (stage 2 item 8).
    It is still a `str` everywhere it goes -- a Step's summary, the
    Ledger -- and the kind rides only as far as this process."""

    kind: str

    def __new__(cls, text: str, kind: str = "") -> "Detail":
        made = super().__new__(cls, text)
        made.kind = kind
        return made


def was_denied(detail: str) -> bool:
    """Whether the Guardian refused this call before it ran. Read from
    the outcome kind; a plain string with no kind (a step read back from
    an older record) falls back to the text prefix this module writes."""
    kind = getattr(detail, "kind", None)
    if kind is not None:
        return kind == DENIED_KIND
    return (detail or "").startswith(DENIED_PREFIX)

ACTION_TIMEOUT_S = 30.0
# The reason an attempt gives when it spends its whole step budget with
# a tool call still pending. Planning matches it by prefix to re-offer
# the task soon (`planning/service.py::CONTINUATION_REASON`, same text;
# the packages may not import each other).
CONTINUATION_REASON = "step budget exhausted"
#: An attempt that spent its tokens, dollars or time (stage 4 item 6).
BUDGET_REASON = "budget exhausted"
#: what the model is told when its lookups have used a chat turn's budget
WRAP_UP_TEXT = ("Your lookups are over -- no more tools this turn. Answer the person now, in one or two "
                "sentences, from what you found; say plainly what you could not check.")
VERIFICATION_REASON = "verification failed"
# The task's branch could not be put on main: a rebase conflict, a red
# whole-suite gate, or a live checkout in the way. The worktree stays,
# and the next attempt starts from it with the reason in hand.
LANDING_REASON = "landing failed"
# Task kinds whose product is a change to the repository, and so work
# in their own worktree (execution/worktree.py) when one can be opened.
WORKTREE_KINDS = frozenset({"patch", "skill"})
CANCELLED_REASON = "the task was cancelled"

# `workspace/` is the one directory that is both readable and writable
# and never committed (execution/config.py::workspace_dir). The rule
# itself lives in `contracts/scratch.py`: Verification needs the same
# fact to decide whether a change is worth a suite run, and Execution's
# config is not importable from either (tests/simorgh/test_module_
# boundaries.py). Re-exported here because this is where callers and
# tests already look for it.


def record_side_effects(session, effects) -> None:
    """Route a tool's reported `side_effects` into the session's sets.

    A free function rather than an inline loop so it can be tested for
    what it actually does -- the sets it fills decide whether cleanup
    deletes a file and whether a finished task is blocked, which is too
    much consequence to leave only reachable through a full session.
    """
    for effect in effects:
        kind, _, path = str(effect).partition(":")
        if not path:
            continue
        if kind == "worktree_land":
            session.landed_commit = path
            continue
        if kind in ("file_write", "file_create"):
            session.wrote.add(path)
            # Scratch is written, never "uncommitted". A file under
            # `workspace/` is gitignored by design, so there is no
            # commit to make and no change for anybody to review --
            # but treating it like source would (a) block the task
            # with "finished with uncommitted changes" over a scratch
            # note, and (b) have cleanup DELETE it on a failed
            # attempt, which defeats the entire point of a workspace
            # that persists. It still joins `wrote`, so the
            # verification checks that read files can see it.
            if is_scratch(path):
                continue
            session.uncommitted.add(path)
            if kind == "file_create":
                # A file this session brought into existence. If it is
                # never committed, cleanup removes it outright:
                # `git_discard` rightly refuses an untracked path, which
                # used to leave every abandoned new file behind as a
                # dirty tree (watched trials, 2026-09-07).
                session.created.add(path)
        elif kind in ("git_commit", "git_discard"):
            session.uncommitted.discard(path)
            session.created.discard(path)


# An attempt that says it finished while its edit is still uncommitted.
UNCOMMITTED_REASON = "finished with uncommitted changes"
FABRICATED_REASON = "the answer claims work the step log does not show"
# Ledger-only record type: which uncommitted edits an exhausted attempt
# left in the tree for the next one.
EDITS_KEPT = topics.TASK_EDITS_KEPT
# Tools that *end* an attempt's work rather than extend it, so the last
# step may still run one when there is an uncommitted edit waiting.
FINISHING_TOOLS = ("git_commit", "git_discard")
# Tools that leave something DURABLE behind, which the next attempt
# inherits (`resume.py` carries uncommitted edits forward). On the last
# step these are worth running for the same reason a finishing tool is:
# the alternative is throwing the model's most expensive output away.
#
# Measured by an observer 2026-09-08, on a task with a 2-step budget
# over 8 attempts: SEVEN complete whole-file patches were drafted and
# silently discarded, one per attempt, because each arrived on the last
# step. Attempts 2 through 8 were byte-identical and nothing in the step
# log, the ledger or the CLI ever mentioned a discarded patch. The task
# could never have finished, and the reason was invisible.
DURABLE_TOOLS = ("apply_source_patch", "apply_skill")
# How much of each step's `summary` (== `detail`, up to `_DETAIL_CHARS`
# == 2000, see `_bound_for_model`'s neighbour below) survives into the
# verification subject's step list. Kept equal to `_DETAIL_CHARS` so
# this cut loses nothing that a previous cut did not already remove.
# Patch/skill diffs run longer and are worth more room.
_VERIFY_SUMMARY_CHARS = 2000
_VERIFY_PATCH_SUMMARY_CHARS = 4000


def _trim_evidence(text: str, limit: int) -> str:
    """Cut `text` to `limit` chars for the verification reviewer without
    slicing through a word or number. A bare `text[:limit]` turned
    "temperature 0.7" into "temperature 0." -- indistinguishable from a
    source that genuinely only said "0." -- and a reviewer read the
    truncated tail as the actual fact, rejecting an answer whose full,
    correct number came from a later step (two observers, 2026-09-08).
    Back up to the last whitespace and say the text was cut, so an
    incomplete quote reads as incomplete instead of as a contradiction.
    """
    if len(text) <= limit:
        return text
    cut = text[:limit]
    last_space = cut.rfind(" ")
    if last_space > limit * 0.5:
        cut = cut[:last_space]
    return cut + " ...[cut]"


# Shapes a reply takes when it is narrating tool calls rather than
# making them. `[tool_call X]` was our own transcript stand-in; the
# others are what a model invents around it.
_ECHO_SHAPES = (
    (re.compile(r"\[tool_call\s", re.I), "narrates tool calls in brackets instead of making them"),
    (re.compile(r"\[result message\]", re.I), "invents tool results"),
    (re.compile(r"^\s*\[result\]", re.I | re.M), "invents tool results"),
)


def _transcript_echo(text: str) -> str:
    """Why this reply is a fabrication, or "" if it is a real answer."""
    for pattern, why in _ECHO_SHAPES:
        if pattern.search(text or ""):
            return why
    return ""


_MARKER_LINE = re.compile(r"^\s*[A-Z][A-Z0-9_]{2,}:\s", re.M)


def _marker_shaped(text: str) -> bool:
    """Whether a reply is (or opens with) a tool marker line -- `READ_FILE: ...`."""
    return bool(_MARKER_LINE.search(text or ""))


def invented_markers(text: str, offered: tuple[str, ...]) -> list[str]:
    """Marker-shaped lines naming tools that are not on offer -- the
    model inventing a capability. Live 2026-09-13: "Play animation" got
    "PLAY_ANIMATION: wave" and "Waving at you, Saeed -- right side of
    the screen", spoken; there is no such tool and no such wave."""
    have = {t.upper() for t in offered}
    out = []
    for line in (text or "").splitlines():
        match = _MARKER_LINE.match(line + " ")
        if match:
            name = line.strip().split(":", 1)[0].strip()
            if name.upper() not in have and name.upper() not in ("QUIET", "FINAL ANSWER", "NOTE", "TODO"):
                out.append(name)
    return out


def without_markers(text: str, names: list[str]) -> str:
    drop = {n.upper() for n in names}
    kept = [line for line in (text or "").splitlines()
            if not (_MARKER_LINE.match(line + " ") and line.strip().split(":", 1)[0].strip().upper() in drop)]
    return "\n".join(kept).strip()


def unhonoured_marker(text: str, offered: tuple[str, ...]) -> str:
    """A tool the model asked for in the middle of a sentence, or "".

    A marker must own its line -- a mention inside a sentence stays
    prose, or any reply discussing a tool would run it
    (`cognition/parser.py::parse_marker`). That rule is right and stays.
    What was missing is anyone saying so: a reply like "I'll read all
    five docs. Starting with the first two. READ_FILE: docs/x.md" was
    filed as a final answer, failed verification for describing work it
    had not done, and spent one of the task's few attempts -- three
    times in seven seconds, in a run an observer watched on 2026-09-10.
    One corrective step costs a step; the silent version costs an
    attempt."""
    from simorgh.contracts.tone import strip_tone

    body = strip_tone(text or "")     # "[bright] CAST_SHOW: home" starts its line (2026-09-13)
    for tool in offered:
        prefix = f"{tool.upper()}:"
        position = body.upper().find(prefix)
        if position <= 0:
            continue        # absent, or at the very start where it IS honoured
        line_start = body.rfind("\n", 0, position) + 1
        if body[line_start:position].strip():
            return tool
    return ""
# An attempt below this number may leave its edits for the next; the
# one at it discards. Planning gives up after nine blocks, so the chain
# always ends with a clean-up before that.
KEEP_EDITS_UNTIL_ATTEMPT = 6
# How long to wait for a given tool, when 30s is not the right answer.
#
# Live-caught 2026-09-07, watching a real patch task: `run_tests`
# reported "no response (timed out)" twice, and the session -- doing
# exactly what its scaffold says, not committing on a failing suite --
# left the edit applied and uncommitted. Execution allows a test run
# `test_timeout_s` (300s) and every tool `default_timeout_s` (60s),
# while this caller gave *everything* 5 seconds. A test suite cannot
# finish in 5s, so `run_tests` could never once have succeeded, and
# Sim could never verify its own work.
#
# Kept a little above Execution's own limits so the tool's timeout is
# what fires, with its real error, rather than this one guessing. When
# `test_timeout_s` went 120 -> 300 this stayed at 180, so a suite that
# ran long under load (a repeat trial with a full pytest in the next
# process, 2026-09-07) timed out *here* first: the session moved on
# while the tests were still running, and the task sat in_progress.
_ACTION_TIMEOUTS: dict[str, float] = {
    "run_tests": 330.0,
    # Landing runs the whole suite as its gate; `RunTestsTool` allows
    # 300s for that, and the tool's own bound adds a minute.
    "worktree_land": 400.0,
    "worktree_open": 60.0,
    "worktree_close": 60.0,
    "run_python_sandboxed": 45.0,
    "run_js_sandboxed": 45.0,
    "web_fetch": 45.0,
    "render_page": 30.0,
    "browse_page": 60.0,
    "run_container": 330.0,
    "search_listings": 45.0,
    "find_package": 30.0,
    "install_package": 330.0,
    "run_script": 200.0,
    "notify": 25.0,
    # A calendar or mailbox is a network round trip to somebody else's
    # server, and a mailbox with thousands of messages is a slow SEARCH.
    # `sec_self` walks the workspace looking for credential-shaped
    # strings, which on a large tree is seconds, not milliseconds.
    # A service call waits for the house to settle before re-reading.
    # An energy report pulls hours of history out of HA's recorder.
    "energy_status": 45.0,
    "energy_report": 90.0,
    "energy_tariff": 20.0,
    "media_now": 30.0,
    "media_control": 45.0,
    "media_play": 45.0,
    "home_find": 30.0,
    "home_state": 30.0,
    "home_describe": 30.0,
    "home_call": 45.0,
    "home_undo": 45.0,
    "sec_self": 120.0,
    "sec_posture": 20.0,
    "sec_findings": 20.0,
    "sec_show": 20.0,
    "sec_accept": 20.0,
    "cal_list": 45.0,
    "mail_search": 60.0,
    "mail_read": 45.0,
    "remind": 15.0,
    "kb_search": 30.0,
    "kb_ask": 30.0,
    "kb_open": 20.0,
    "kb_status": 20.0,
    # A first scan of a documents folder parses and embeds every file in
    # it. Minutes, not seconds -- and it runs off the event loop.
    "kb_sources": 900.0,
    "run_remote": 330.0,
    "geocode": 15.0,
    "apply_source_patch": 60.0,
    "replace_in_file": 60.0,
    "start_task": 20.0,
    "apply_skill": 60.0,
}
# Found by a watched trial, 2026-09-07, and the third stale 5-second
# timeout in this file. Verification at LIGHT rigor makes two sequential
# provider round trips (generate a checklist, then evaluate it) plus the
# mechanical checks, so 5s could never cover it: in 2 of 2 runs the real
# verdict landed 14ms to 3s *after* the session had already given up and
# accepted the task with `verification_ref=None`. Money spent on the
# review, verdict discarded -- and the `blocked` path for a failing
# verdict was unreachable, so verification could never stop a bad patch.
# Matches `learning/config.py::verify_timeout_seconds`.
VERIFY_TIMEOUT_S = 300.0


# How often a cancel-aware wait re-checks `cancel_check` while a real
# `action.result` is still outstanding. Live-measured, 2026-09-08: a
# `TASK_CANCEL` arriving 0.3s into a 3s `web_fetch` used to sit unnoticed
# for the whole remaining 2.7s (up to a tool's full `_ACTION_TIMEOUTS`
# ceiling -- 330s for `run_tests`, 45s for `web_fetch`/
# `run_python_sandboxed` -- since `_EventWaiter.wait` only ever looked at
# the bus, never at the cancel flag, while it awaited a single
# `asyncio.wait_for`). This bounds that to one poll interval.
_CANCEL_POLL_INTERVAL_S = 0.2


# Guardian denies an unanswered prompt after `human_prompt_timeout_s`
# (1800 s by default), so a task waiting on a person always hears back.
_HUMAN_ANSWER_WAIT_S = 1860.0


#: The most calls one native reply may run; the rest are reported as not run.
MAX_NATIVE_CALLS = 8


class _EventWaiter:
    """Waits for the first event of any of `types` whose payload[`key`]
    equals `value` -- the action.proposed -> {result|denied|needs_human}
    and verify.requested -> verify.result correlations, neither of which
    rides the bus's reply_to inbox (they're events, not request/reply;
    03 section 1's own table).
    """

    def __init__(self, bus) -> None:
        self._bus = bus

    async def wait(
        self, types: tuple[str, ...], *, key: str, value: str, timeout: float,
        cancel_check=None, poll_interval: float = _CANCEL_POLL_INTERVAL_S,
        through: tuple[str, ...] = (), through_timeout: float = 0.0,
    ) -> Message | None:
        """`through`: events that do not end the wait but say it will be
        long -- `action.needs_human` in a task, where the answer is the
        person's. Seeing one stretches the deadline to `through_timeout`.
        One subscription covers both phases, so an answer that arrives
        the instant after the question cannot fall between two waits."""
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        loop = asyncio.get_running_loop()
        deadline = [loop.time() + timeout]

        async def _on(message: Message) -> None:
            if message.payload.get(key) != value or fut.done():
                return
            if message.type in through:
                deadline[0] = max(deadline[0], loop.time() + through_timeout)
                return
            fut.set_result(message)

        subs = [await self._bus.subscribe(t, _on) for t in (*types, *through)]
        try:
            if through:
                while True:
                    left = deadline[0] - loop.time()
                    if left <= 0:
                        return None
                    try:
                        return await asyncio.wait_for(asyncio.shield(fut), timeout=min(poll_interval, left))
                    except asyncio.TimeoutError:
                        if cancel_check is not None and cancel_check():
                            return None
            if cancel_check is None:
                return await asyncio.wait_for(fut, timeout=timeout)
            # `asyncio.shield` keeps a per-poll `wait_for` timeout from
            # cancelling the underlying future itself, so the next poll
            # can keep waiting on the very same delivery rather than
            # missing it. Only used when the caller can prove there is
            # nothing at stake in giving up early (a read-only tool has
            # no side effect for cleanup to lose).
            remaining = timeout
            while remaining > 0:
                step = min(poll_interval, remaining)
                try:
                    return await asyncio.wait_for(asyncio.shield(fut), timeout=step)
                except asyncio.TimeoutError:
                    remaining -= step
                    if cancel_check():
                        return None
            return None
        except asyncio.TimeoutError:
            return None
        finally:
            for s in subs:
                await s.unsubscribe()


def _git_head() -> str:
    """The current commit, or "" when there is no repo to ask.

    Deliberately silent on failure: a session must never fail to start
    because git is missing, and every reader of `base_ref` treats "" as
    "cannot attribute", which is the same conservative behaviour these
    checks had before the field existed.
    """
    try:
        done = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                              text=True, timeout=10, cwd=os.getcwd())
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


# "Sima, are you there?" -- whisper hearing the name (live 2026-09-15).
_NAMES_SIM = re.compile(r"\b(?:sim|sima|simorgh|sam|seem|seam|seym|syme)\b", re.IGNORECASE)


# The file each live-tree write tool changes, by its argument.
_CHAT_WRITE_TARGET = {"replace_in_file": "path", "apply_source_patch": "subject"}


def chat_outside_workspace_refusal(session: Session, tool: str, args: dict) -> str:
    """Why a chat turn may not write this file, or "" when it may.

    Chat can write files, by the creator's choice (2026-09-09: a deck, a
    game, a document -- in `workspace/`). It could also write anywhere
    else: on 2026-09-19 a typo ("?/tas") became a chat turn that saw a
    queued patch task in `list_tasks` and did that task itself, editing
    `simorgh/growth/estimate/` in the live checkout Sim runs from, with no
    worktree, no tests before landing and no verification; three tests
    broke. A change to anything outside `workspace/` is a task's job.
    """
    if getattr(session.profile, "scaffold", "") != "chat" or tool not in _CHAT_WRITE_TARGET:
        return ""
    target = str(args.get(_CHAT_WRITE_TARGET[tool]) or "")
    if is_scratch(target):
        return ""
    return (f"refused: a chat turn writes only under workspace/, and {target or 'this file'} is outside it. "
            "To change it, start a task with start_task: a task works in its own worktree, runs the tests and "
            "is verified before its change lands. Do not edit it from chat.")


def unplaced_voice_refusal(session: Session, tool: str) -> str:
    """Why a spoken turn may not run `tool`, or "" when it may.

    Live 2026-09-14: a TV advert, heard as "Delete promotions and spam
    emails." from a voice Sim could not place, became a queued task to
    delete mail -- one "go ahead" from the TV away from running -- and an
    NFL advert queued a 50-step build. A voice the house does not know,
    that did not say Sim's name, may talk to Sim but may not start work or
    change anything. Typed turns and known voices are unaffected.

    Reversible actions count too (live 2026-09-15): "We are on the queue."
    from a voice Sim could not place became `dash_view` on the TV, refused
    only because the view it invented did not exist. Only read-only tools
    run for such a voice.
    """
    if getattr(session, "channel", "") != "voice" or getattr(session, "speaker", ""):
        return ""
    if tool != "start_task" and is_read_only(tool):
        return ""
    if _NAMES_SIM.search(session.user_text or ""):
        return ""
    return (f"refused: {tool} was asked for by a voice Sim does not recognise, without saying Sim's name -- "
            "it may be the TV or someone in the background. Do not do it; say briefly that whoever wants it "
            "should ask again starting with \"Sim\".")


def _epoch(clock) -> float:
    """Seconds since the epoch from whatever shape of clock this is.

    Interface passes `ctx.clock.now` -- the bound method -- while other
    callers pass the clock object itself, and tests pass a plain
    function. Assuming one shape broke 52 tests with
    `AttributeError: 'function' object has no attribute 'now'`; a prompt
    stamp is never worth a raised turn, so anything unreadable is 0.0
    and the date is simply left out.
    """
    if clock is None:
        return 0.0
    try:
        if callable(clock):
            return float(clock())
        now = getattr(clock, "now", None)
        return float(now()) if callable(now) else 0.0
    except Exception:  # noqa: BLE001 -- a stamp must not cost a turn
        return 0.0


class SessionRunner:
    def __init__(
        self, bus, ledger, *, clock=None, worker_id: str = "w1", is_paused=None, is_cancelled=None,
        think_timeout_s: float = 5.0, action_timeout_s: float = ACTION_TIMEOUT_S,
        verify_timeout_s: float = VERIFY_TIMEOUT_S, assemble_timeout_s: float = DEFAULT_TIMEOUT_S,
        worktrees: bool = False, reground_every_steps: int = 0, keep_recent_steps: int = 2,
        escalate_below_posterior: float = 0.0, escalate_min_samples: int = 8,
        clean_revisions: bool = False, delegation: bool = False, max_depth: int = 3, max_children: int = 4,
        delegate_max_steps: int = 12, escalate_from_attempt: int = 0, parallel_read_tools: int = 1,
        skills_enabled: bool = False, skills_catalog_max_chars: int = 3000, skills_roots: tuple[str, ...] = (),
        skills_channels: tuple[str, ...] = ("", "cli", "http"), telemetry=None,
        bridge_on_slow_turns: bool = False, bridge_timeout_s: float = 2.0,
    ) -> None:
        # Counts each Stop-hook rule that fires (`stophook.py`); a no-op
        # stand-in when the runner is built without one (tests, harnesses).
        from simorgh.contracts.protocols import NULL_TELEMETRY

        self._telemetry = telemetry or NULL_TELEMETRY
        #: What each tool has recently cost, in milliseconds, newest
        #: last (stage 3 item 5). Kept here rather than asked of
        #: Telemetry because it is read on the way OUT of a turn, where
        #: a query is exactly the latency it is trying to cover.
        self._tool_ms: dict[str, list[float]] = {}
        # A one-line bridge before a slow turn (stage 3 item 7).
        self._bridge_on = bool(bridge_on_slow_turns)
        self._bridge_timeout_s = float(bridge_timeout_s)
        #: Sessions that have already had one, so a ten-step patch task
        #: says "I'll look at that" once rather than at every step.
        self._bridged: set[str] = set()
        #: The sessions running right now, by task id, so something that
        #: happens in the house can reach the agent working in it
        #: (stage 6 item 7).
        self._open: dict[str, Session] = {}
        #: Helper sessions running for a parent task (stage 7 item 1), so
        #: `max_children_concurrent` is a real cap and not a number in a doc.
        self._children: dict[str, list] = {}
        # Agent Skills: the catalog rides in `task_rules` and `use_skill` returns
        # one skill's instructions. Off by default -- every THINK pays for the
        # catalog (docs/plans/agent-skills-design.md section 5.2).
        self._skills_enabled = bool(skills_enabled)
        self._skills_catalog_max_chars = max(0, int(skills_catalog_max_chars))
        self._skills_roots = tuple(skills_roots or ())
        # Which channels are charged for the catalog at all (config.py's
        # `skills_channels`). A voice turn pays nothing rather than a little.
        self._skills_channels = tuple(skills_channels or ())
        self._skill_cache: tuple[list, list] | None = None
        # Independent read-only calls in one reply run together, up to this
        # many per step (change H). 1 is off: one tool call per reply.
        self._parallel_reads = max(1, int(parallel_read_tools))
        # Escalation (design section 7): from this attempt on, or after a
        # helper came back without an answer, a THINK asks Cognition for the
        # strong tier. 0 is off.
        self._escalate_from_attempt = max(0, int(escalate_from_attempt))
        self._escalate_below = max(0.0, float(escalate_below_posterior))
        self._escalate_min_samples = max(1, int(escalate_min_samples))
        # Helper tasks (design section 5): `delegate` runs a read-only research
        # session in-process with a fresh context and returns only its report.
        self._delegation = bool(delegation)
        self._max_depth = max(0, int(max_depth))
        self._max_children = max(1, int(max_children))
        self._delegate_max_steps = max(3, int(delegate_max_steps))
        # A revision after a rejected answer starts from the note and the
        # last few steps, not the whole transcript (design section 4).
        self._clean_revisions = bool(clean_revisions)
        self._bus = bus
        # Re-grounding (orchestration/progress.py): every N steps the model
        # writes a progress note and the transcript is replaced by it. 0 is
        # off -- the default until its benchmark arm wins.
        self._reground_every = max(0, int(reground_every_steps or 0))
        self._keep_recent_steps = max(0, int(keep_recent_steps))
        # Off here, on in production (`[orchestration] worktrees`, the
        # default): a harness that stands in for Execution would
        # otherwise be asked to fake three more tools in every flow.
        self._worktrees = worktrees
        self._ledger = ledger
        self._clock = clock
        self._worker_id = worker_id
        self._assembler = Assembler(bus, clock=clock, timeout_s=assemble_timeout_s, ledger=ledger)
        self._waiter = _EventWaiter(bus)
        # Each session's messages, durably, as `session:<id>` (stage 4 item 2).
        from .transcript import TranscriptWriter

        self._transcripts = TranscriptWriter(ledger, clock)
        self._is_paused = is_paused or (lambda: False)
        self._is_cancelled = is_cancelled or (lambda task_id: False)
        self._think_timeout_s = think_timeout_s
        self._action_timeout_s = action_timeout_s
        self._verify_timeout_s = verify_timeout_s

    #: How many recent durations per tool are kept for the p95.
    TOOL_MS_KEEP = 20

    def recent_p95_ms(self, tool: str) -> int:
        """This tool's recent 95th-percentile duration, or -1 (stage 3 item 5).

        -1 means "nothing is known about it yet", which a consumer must
        not read as fast: the first `web_fetch` after a boot is as slow
        as every other one, and guessing zero would be the one time a
        filler is most needed and least likely to fire.
        """
        samples = sorted(self._tool_ms.get(tool) or ())
        if not samples:
            return -1
        index = min(len(samples) - 1, int(round(0.95 * (len(samples) - 1))))
        return int(samples[index])

    def _note_tool_ms(self, tool: str, ms: float) -> None:
        """Remember what a call cost, keeping only the recent ones: a
        tool that was slow a thousand calls ago is not slow now."""
        kept = self._tool_ms.setdefault(tool, [])
        kept.append(max(0.0, ms))
        del kept[:-self.TOOL_MS_KEEP]


    async def run(self, session: Session, *, user_text: str = "") -> Outcome:
        """Run the session, and never leave a change behind that nobody
        committed.

        Live-caught 2026-09-07 by a trial designed to fail: asked to make
        a change that breaks the suite, Sim applied it, ran the tests, saw
        red, and correctly refused to commit -- and then left the modified
        file sitting in the working tree. Its instructions do say to put
        the tree back, and it had `git_discard` to do it with, but it
        spent its remaining steps investigating the failure instead.

        Which is a reasonable thing for it to do. "Never leave a broken
        change in the tree" is a property the system should hold, not a
        request the model has to remember, so the cleanup happens here
        whichever way the session ended.
        """
        if self._uses_worktree(session) and not session.worktree:
            await self._open_worktree(session)
        if not session.base_ref:
            # Captured here, before the first step, and only here: both
            # `Session` construction sites in `worker.py` and every
            # resumed session pass through this one entry point. What it
            # is for: `full_suite_ran` cannot tell a failure this change
            # caused from one that was already red without a tree to
            # compare against, and this commit is that tree.
            session.base_ref = _git_head()
        self._open[session.task_id] = session
        if not session.estimate and session.profile.scaffold != "chat":
            # Asked once, before the first step (stage 6 item 2): what Sim's
            # own record says about this kind of work decides whether it
            # starts on the strong tier.
            session.estimate = await self._estimate(session.kind)
        # One line before a slow turn, so the person is not watching
        # nothing happen (stage 3 item 7). Off by default; never the
        # answer, and never recorded as the turn's text -- it is not
        # put on `session.messages` and does not reach `Outcome`.
        try:
            await self._bridge(session, user_text)
        except Exception:  # noqa: BLE001 -- a courtesy is never worth failing a turn for
            pass
        try:
            outcome = await self._run(session, user_text=user_text)
        finally:
            self._open.pop(session.task_id, None)
            await self._persist_transcript(session)
        if outcome.kind == "completed":
            # `_transcript_echo` catches a fabrication written in our own
            # bracket syntax. Plain prose walked straight past it: "I've
            # added the docstring and committed the change as a3f19c2",
            # with no git_commit step in the log at all (observer,
            # 2026-09-08). Compare the claim against what ran.
            claims = unsupported_claims(
                outcome.result_summary or "", session.steps, offered_tools(session.profile.tools),
                # A retry's step log is not the whole story: the work it
                # is finishing happened in an earlier attempt, whose
                # steps are not in `session.steps`. Caught by the trial
                # suite 2026-09-08 -- a session applied its patch in
                # attempt 1, committed it in attempt 2, and was told
                # "says it changed a file, and no edit was applied".
                complete_log=session.attempt <= 1 and not session.carried,
            )
            if claims:
                step = Step(session.next_step_no(), "act",
                            "rejected an unsupported answer: " + "; ".join(claims), ok=False)
                session.record(step)
                await self._record_step(session, step)
                outcome = Outcome(
                    "blocked", reason=f"{FABRICATED_REASON}: {'; '.join(claims)}",
                    result_summary=outcome.result_summary, verification_ref=outcome.verification_ref,
                )
        if session.uncommitted and outcome.kind == "completed":
            # "Done" with an edit still uncommitted is wrong by
            # construction, and it became MORE wrong once an attempt
            # could inherit an edit: the model saw its change already in
            # the tree, read that as already committed, and answered with
            # a fabricated commit hash. The task was recorded COMPLETED
            # and `_discard_uncommitted` then deleted the correct, tested
            # patch (observer, 2026-09-08). Silent loss plus a false
            # success is worse than a visible failure, so this is not a
            # completion -- it is an unfinished attempt, and the next one
            # inherits the edit and can commit it.
            step = Step(
                session.next_step_no(), "act",
                f"answered as finished with {len(session.uncommitted)} uncommitted edit(s): "
                + ", ".join(sorted(session.uncommitted)),
                ok=False,
            )
            session.record(step)
            await self._record_step(session, step)
            outcome = Outcome(
                "blocked", reason=f"{UNCOMMITTED_REASON}: {', '.join(sorted(session.uncommitted))}",
                result_summary=outcome.result_summary, verification_ref=outcome.verification_ref,
            )
        if session.worktree:
            if outcome.kind == "completed":
                # Verified, committed on its own branch: now the part that
                # touches main. A refusal here is an unfinished attempt,
                # not a failure -- the worktree stays and the next attempt
                # inherits the reason.
                outcome = await self._land(session, outcome)
            if session.worktree and outcome.kind != "paused" and not self._continues(session, outcome):
                await self._close_worktree(session)
        if session.uncommitted and outcome.kind != "paused":
            if self._continues(session, outcome):
                await self._keep_uncommitted(session)
            else:
                await self._discard_uncommitted(session)
        return outcome

    # -- the task's own worktree ---------------------------------------------------------------

    def _uses_worktree(self, session: Session) -> bool:
        if not self._worktrees or session.kind not in WORKTREE_KINDS or session.mode != "execute":
            return False
        # Only when Execution has announced the tool. `known_tools()` is
        # empty in a harness with no Execution (then the switch alone
        # decides); once anything has registered, an Execution that
        # never offered `worktree_open` -- worktrees off, a repository
        # nobody named -- is not asked for one, which would only cost a
        # Guardian round trip to hear "unknown tool".
        known = known_tools()
        return not known or "worktree_open" in known

    async def _open_worktree(self, session: Session) -> None:
        """Ask Execution for this task's worktree. The tool's first two
        output lines are the path and the commit it stands at (the
        same commit on a retry that resumes an earlier attempt's tree).
        When there is no such tool -- worktrees off, no git, a harness
        -- the session edits the live tree as before, and the step says
        so rather than pretending."""
        call = {"tool": "worktree_open", "args": {}}
        ok, summary, detail = await self._propose_and_await(session, call, session.next_step_no())
        lines = [line.strip() for line in (summary or "").splitlines() if line.strip()]
        if ok and lines and os.path.isabs(lines[0]) and os.path.isdir(lines[0]):
            session.worktree = lines[0]
            if len(lines) > 1 and not session.base_ref:
                session.base_ref = lines[1]
            how = lines[2] if len(lines) > 2 else "opened"
            step = Step(session.next_step_no(), "gather",
                        f"working in this task's own worktree ({how}): {lines[0]}",
                        tool="worktree_open", ok=True)
        else:
            step = Step(session.next_step_no(), "gather",
                        f"working in the live tree; no worktree: {detail}"[:400],
                        tool="worktree_open", ok=False, denied=was_denied(detail))
        session.record(step)
        await self._record_step(session, step)

    async def _land(self, session: Session, outcome: Outcome) -> Outcome:
        call = {"tool": "worktree_land", "args": {}}
        ok, summary, detail = await self._propose_and_await(session, call, session.next_step_no())
        step = Step(session.next_step_no(), "act",
                    (f"landed on main: {detail}" if ok else f"landing failed: {detail}")[:2000],
                    tool="worktree_land", ok=ok, denied=was_denied(detail))
        session.record(step)
        await self._record_step(session, step)
        if ok:
            # The manager removed the worktree as part of landing.
            session.worktree = ""
            # Tell Learning, the Self Model, Reflection, Curiosity and
            # Planning that Sim changed its own code. Four of them had
            # subscribed to this topic since Phase 0 and nothing on the
            # real landing path ever published it: the self-improvement
            # loop was open (2026-09-18 evaluation, C1).
            await self._publish(session, topics.LEARN_SELF_PATCH_APPLIED, {
                "subject": session.subject or ", ".join(sorted(session.wrote)[:8]) or session.profile.name,
                "commit": session.landed_commit,
                "reason": f"landed by a {session.profile.name} task ({session.task_id})",
            })
            first = next((line.strip() for line in (summary or "").splitlines() if line.strip()), "landed")
            return Outcome(
                "completed", result_summary=f"{outcome.result_summary}\n\n[{first}]".strip(),
                verification_ref=outcome.verification_ref, floor=outcome.floor, confidence=outcome.confidence,
            )
        reason = " ".join((summary or detail or "no reason given").split())[:1200]
        return Outcome("blocked", reason=f"{LANDING_REASON}: {reason}",
                       result_summary=outcome.result_summary, verification_ref=outcome.verification_ref)

    async def _close_worktree(self, session: Session) -> None:
        """Remove a worktree whose task is over: failed, or blocked
        for a reason no retry will pick up. Whatever it held that was
        not landed goes with it -- the same "never leave a change
        behind" cleanup `_discard_uncommitted` does on the live tree."""
        call = {"tool": "worktree_close", "args": {}}
        ok, summary, _detail = await self._propose_and_await(session, call, session.next_step_no())
        step = Step(session.next_step_no(), "act",
                    f"closed the worktree: {summary}" if ok else f"could not close the worktree: {summary}",
                    tool="worktree_close", ok=ok)
        session.record(step)
        await self._record_step(session, step)
        session.worktree = ""
        session.uncommitted.clear()
        session.created.clear()

    @staticmethod
    def _continues(session: Session, outcome: Outcome) -> bool:
        """Whether this attempt's uncommitted edits stay in the tree for
        the next one. Only when the attempt ran out of steps mid-work
        (Planning re-offers such a task within seconds, see
        `resume.py`) and only for the first few attempts: watched trial,
        2026-09-07 -- with the edit discarded every time, each attempt
        re-applied the same patch and none ever reached the commit. The
        last allowed attempt discards as before, so the "never leave a
        broken change" property still holds for the chain as a whole."""
        if session.attempt >= KEEP_EDITS_UNTIL_ATTEMPT or outcome.kind != "blocked":
            return False
        reason = outcome.reason or ""
        # Two ways an attempt is unfinished rather than wrong: it ran out
        # of steps, or verification objected. Discarding on the second
        # threw away a correct, tested patch that only lacked a commit
        # (watched trial, 2026-09-08) -- the next attempt inherits the
        # edit and the objection, and can finish the job.
        return reason.startswith((CONTINUATION_REASON, VERIFICATION_REASON, UNCOMMITTED_REASON, LANDING_REASON))

    async def _keep_uncommitted(self, session: Session) -> None:
        kept = sorted(session.uncommitted)
        created = sorted(p for p in session.created if p in session.uncommitted)
        step = Step(
            session.next_step_no(), "act",
            f"kept {len(kept)} uncommitted edit(s) in the tree for the next attempt: {', '.join(kept)}",
            ok=True,
        )
        session.record(step)
        await self._record_step(session, step)
        # Ledger only: the next attempt reads this back (`resume.py`) to
        # inherit the paths, so *its* end cleans them up if it does not
        # commit. Nothing on the bus needs it.
        await self._append(session, EDITS_KEPT, {"task_id": session.task_id, "paths": kept, "created": created})

    async def _discard_uncommitted(self, session: Session) -> None:
        left = sorted(session.uncommitted)
        for path in left:
            call = {"tool": "git_discard", "args": {"path": path, "created": path in session.created}}
            ok, summary, _detail = await self._propose_and_await(session, call, session.next_step_no())
            step = Step(
                session.next_step_no(), "act",
                f"put {path} back: {summary}" if ok else f"could not put {path} back: {summary}",
                tool="git_discard", ok=ok,
            )
            session.record(step)
            await self._record_step(session, step)
        session.uncommitted.clear()

    async def _run(self, session: Session, *, user_text: str = "") -> Outcome:
        await self._append(session, topics.TASK_STARTED, {"task_id": session.task_id, "worker_id": self._worker_id})
        await self._publish(session, topics.TASK_STARTED, {"task_id": session.task_id, "worker_id": self._worker_id})

        pending_user_text = user_text
        started = time.monotonic()
        while True:
            if self._paused():
                return await self._pause(session)
            spent = session.budget.over(tokens=session.spent_tokens, usd=session.spent_usd,
                                        wall_s=time.monotonic() - started)
            if spent:
                # Stage 4 item 6. Not CONTINUATION_REASON: a retry with a fresh
                # allowance would spend past the budget that just ended.
                step = Step(session.next_step_no(), "act", f"{BUDGET_REASON}: {spent}", ok=False)
                session.record(step)
                await self._record_step(session, step)
                return Outcome("blocked", reason=f"{BUDGET_REASON}: {spent}")
            # Cooperative, and checked between steps rather than during
            # one: a cancel must not tear down a provider call or leave a
            # half-applied edit behind. The cleanup in `run` runs either
            # way, so an uncommitted change is still discarded.
            if self._is_cancelled(session.task_id) or (session.parent_id and self._is_cancelled(session.parent_id)):
                return Outcome("failed", reason=CANCELLED_REASON)

            if (session.profile.scaffold != "chat" and session.messages and not session.budget.is_last_step
                    and progress_note.due(session.budget.steps_used, session.reground_at, self._reground_every)):
                await self._reground(session)
            if session.replan:
                # Twice off course, or stuck: this attempt ends and the
                # subtree is re-planned rather than spending the rest of
                # the budget going further the wrong way (stage 7 item 6).
                return Outcome("blocked", reason=f"needs re-planning -- {session.replan}")
            if session.messages and session.context_pressure >= pressure_mod.STUB_AT:
                await self._relieve(session)

            step_no = session.next_step_no()
            is_last = session.budget.is_last_step
            # Live-caught (the creator: "not informative ... what do you
            # mean thinking"): every narration event before this one fired
            # *after* `_think()` already had its reply -- during the real
            # wait (the slow part, seconds to well over a minute for a
            # real model call) nothing was published at all. This is a
            # bus-only heads-up (no Ledger append, no `session.record()`
            # -- it isn't a completed step, just an announcement of intent)
            # so a live narrator has something concrete to say *while*
            # waiting, not just after.
            await self._publish(session, topics.TASK_STEP, {
                "task_id": session.task_id, "step_no": step_no, "phase": "gather",
                "summary": f"asking the model (purpose={'chat' if session.profile.name == 'chat' else 'draft'})",
            })
            think_reply = await self._think(session, pending_user_text, last_step=is_last)
            pending_user_text = ""

            if think_reply is None and session.last_think_error == "context_too_large" \
                    and session.profile.scaffold != "chat" and session.messages:
                # A long transcript the model cannot take: write the note,
                # replace the transcript with it, and ask again -- once.
                session.last_think_error = ""
                if await self._reground(session, forced=True):
                    think_reply = await self._think(session, "", last_step=is_last)
            if think_reply is None:  # provider unavailable / timeout -- honest floor
                if session.profile.name == "chat":
                    return Outcome("completed", result_summary="", floor=True)
                if session.last_think_error == "context_too_large":
                    return Outcome("blocked", reason="context too large for the model, even after re-grounding")
                return Outcome("blocked", reason="no real provider")

            session.budget.steps_used += 1
            tool_calls = think_reply.payload.get("tool_calls") or []
            floor = think_reply.payload.get("floor", False)

            if tool_calls and is_last and tool_calls[0].get("tool") in DURABLE_TOOLS:
                # Run it, then end the attempt as a continuation. The
                # edit stays in the tree and the next attempt starts
                # from a file that is already written instead of
                # redrafting it from nothing.
                call = tool_calls[0]
                ok, summary, detail = await self._propose_and_await(session, call, step_no)
                step = Step(step_no, "act", detail, tool=call.get("tool"), ok=ok, denied=was_denied(detail))
                session.record(step)
                await self._record_step(session, step)
                if session.profile.scaffold == "chat":
                    # A chat has no next attempt: the person asked for the
                    # edit and gets told what was done, not "step budget
                    # exhausted" (observer, 2026-09-13).
                    answer = await self._wrap_up(session)
                    if answer:
                        return Outcome("completed", result_summary=answer)
                return Outcome(
                    "blocked",
                    reason=f"{CONTINUATION_REASON}; the edit is applied and waiting to be committed",
                )

            if tool_calls and is_last and tool_calls[0].get("tool") in FINISHING_TOOLS and session.uncommitted:
                # The last step may still *finish*: refusing a git_commit
                # here threw away the whole attempt's work and reported
                # "step budget exhausted" over an applied, tested change
                # (watched trial, 2026-09-07). A finishing tool ends the
                # work rather than extending it, so it costs no further
                # step -- the model answers straight after.
                call = tool_calls[0]
                ok, summary, detail = await self._propose_and_await(session, call, step_no)
                step = Step(step_no, "act", detail, tool=call.get("tool"), ok=ok, denied=was_denied(detail))
                session.record(step)
                await self._record_step(session, step)
                if ok:
                    # A successful finishing action leaves nothing for
                    # cleanup to undo. The `file_write`/`git_commit` side
                    # effects normally say so; clearing here as well means
                    # a tool that reports success without them can never
                    # have its own commit discarded a moment later.
                    session.uncommitted.clear()
                    session.created.clear()
                text = f"{'Committed' if ok else 'Could not commit'} the change: {summary}"
                session.messages.append({"role": "assistant", "content": text})
                if not session.profile.verify:
                    return Outcome("completed", result_summary=text, floor=False)
                return await self._verify_then_finish(session, text, floor=False)

            if tool_calls and not is_last and all(c.get("id") for c in tool_calls):
                # A native provider's typed calls (stage 2 items 5-6): every
                # call in the reply runs -- reads together, changes in order,
                # stopping at the first that fails -- and the turn is kept
                # typed: the assistant's calls, then one tool result per id.
                calls = tool_calls[:MAX_NATIVE_CALLS]
                summaries = await self._run_native_calls(session, calls, step_no)
                session.messages.append({
                    "role": "assistant", "content": think_reply.payload.get("text") or "",
                    "tool_calls": [{"id": c["id"], "tool": c.get("tool"), "args": c.get("args") or {}} for c in calls],
                })
                for call, summary in zip(calls, summaries):
                    session.messages.append({"role": "tool", "tool_call_id": call["id"],
                                             "name": call.get("tool"), "content": summary})
                dropped = len(tool_calls) - len(calls)
                session.messages.append({"role": "user", "content": (
                    (f"{dropped} further call(s) were not run: at most {MAX_NATIVE_CALLS} per reply. " if dropped else "")
                    + "If the task is now finished, reply with your final answer in plain text. "
                      "Otherwise take the next step.")})
                if self._paused():
                    return await self._pause(session)
                continue

            if tool_calls and not is_last:
                call = tool_calls[0]  # one action per step (section 7)
                # ...unless it and the calls straight after it are all
                # read-only: those run together as one step (change H).
                batch = self._read_batch(tool_calls)
                if len(batch) > 1:
                    summary = await self._run_batch(session, batch, step_no)
                else:
                    if call.get("tool") in ("delegate", "task"):
                        ok, summary, detail = await self._delegate(session, call)
                    elif call.get("tool") == "use_skill":
                        ok, summary, detail = await self._use_skill(session, call)
                    elif call.get("tool") == pressure_mod.RECALL_TOOL:
                        ok, summary, detail = await self._recall_result(call)
                    elif call.get("tool") == MEMORY_SEARCH:
                        ok, summary, detail = await self._memory_search(session, call)
                    else:
                        ok, summary, detail = await self._propose_and_await(session, call, step_no)
                    # `detail` (narration/Ledger, generously bounded) vs `summary`
                    # (the model's own next-turn context, tightly bounded) are
                    # deliberately different lengths -- see `_propose_and_await`.
                    step = Step(step_no, "act", detail, tool=call.get("tool"), ok=ok, denied=was_denied(detail))
                    session.record(step)
                    await self._record_step(session, step)
                    if session.waiting:
                        # The task is parked (stage 7 item 5). Ending the
                        # attempt here is what frees the worker; Planning
                        # wakes the task when its moment or its event comes.
                        return Outcome("paused", reason=summary)
                # Two turns, not one. This used to append a single
                # *assistant* message reading "[tool_call read_file] ->
                # <the file>", so the model was asked to continue a
                # conversation whose last turn was its own, with the tool
                # output attributed to itself rather than returned to it.
                #
                # Live-caught 2026-09-07, monitoring whether Sim ever
                # edits its own source: it never has -- 246 tool runs,
                # every one read-only, zero `apply_source_patch`. Asked to
                # add a docstring, it searched, read the exact file, and
                # then answered "It looks like your message came through
                # as just a step marker with no actual content." It was
                # looking for a turn addressed to it and finding a
                # fragment it thought it had written, so it lost the
                # thread and wrote prose instead of applying anything.
                #
                # The request stays the assistant's; the result comes back
                # as a turn addressed to it, which is the shape every
                # tool-using model is trained on.
                tool_name = call.get("tool")
                # The model's OWN words, not a synthetic `[tool_call X]`
                # stand-in. Live-caught 2026-09-08: given that stand-in
                # to imitate, the model produced a "final answer" reading
                # `[tool_call run_tests]\n[result message]: passed 12
                # [tool_call git_commit] ... Committed as 5a1c3f2` -- no
                # such run, no such commit. It was recorded as success,
                # and `_discard_uncommitted` then deleted the correct
                # skill it really had written. We taught it the format.
                session.messages.append({
                    "role": "assistant",
                    "content": think_reply.payload.get("text") or f"{tool_name.upper()}:",
                })
                # "Continue the task." here was read literally: after a
                # successful git_commit the model re-read the file, ran the
                # tests again, re-applied the same content, and burned the
                # whole step budget without ever answering (watched trial,
                # 2026-09-07). Say what finishing looks like every time.
                dropped = max(len(tool_calls) - 1, int(call.get("dropped_markers") or 0)) - (len(batch) - 1)
                dropped_note = (
                    f"\n\nYour reply also contained {dropped} further tool marker"
                    f"{'s' if dropped != 1 else ''}, which were NOT run: {self._dropped_rule()} "
                    "Ask for the next one now if you still need it."
                ) if dropped else ""
                head = f"Results of {len(batch)} lookups, run together" if len(batch) > 1 else f"Result of {tool_name}"
                session.messages.append({
                    "role": "user",
                    "content": (
                        f"{head}:\n{summary}{dropped_note}\n\n"
                        "If the task is now finished, reply with your final answer in plain text, "
                        "with no tool marker. Otherwise take the next step."
                    ),
                })
                if self._paused():
                    return await self._pause(session)
                continue

            text = think_reply.payload.get("text", "")
            if tool_calls and is_last and session.profile.scaffold == "chat":
                # A person asked a question and the model spent every step
                # looking things up. "Step budget exhausted" is not an
                # answer -- it was spoken aloud to the creator, 2026-09-13,
                # about a failed test -- so one more call, with no tools,
                # says what was found.
                answer = await self._wrap_up(session)
                if answer:
                    step = Step(step_no, "act", "answered from what was found; the lookups had used the budget", ok=True)
                    session.record(step)
                    await self._record_step(session, step)
                    return Outcome("completed", result_summary=answer)
            if tool_calls and is_last:
                # The budget ran out while the model was still asking for
                # a tool. That is not a finished task, and recording it as
                # `completed` -- with the raw tool marker as the answer --
                # taught Learning that doing nothing is a win, and showed
                # the human "READ_FILE: simorgh/cognition/parser.py" as a
                # result. Found by two watched trials 2026-09-07.
                step = Step(step_no, "act", "step budget exhausted with work still pending", ok=False)
                session.record(step)
                await self._record_step(session, step)
                return Outcome("blocked", reason=f"{CONTINUATION_REASON} before the task was finished")
            stray = unhonoured_marker(text, offered_tools(session.profile.tools))
            if stray and not is_last and not session.marker_corrected:
                # Once per session: if it does it again, that is an
                # answer about a tool and not a request for one.
                session.marker_corrected = True
                step = Step(step_no, "act", f"a {stray} marker mid-sentence was not run", ok=False)
                session.record(step)
                await self._record_step(session, step)
                session.messages.append({"role": "assistant", "content": text})
                session.messages.append({"role": "user", "content": (
                    f"Nothing ran: your {stray.upper()}: marker had text before it on the same "
                    f"line, and a marker is only a tool call when it starts its own line. Write it "
                    f"again on a line of its own if you still want it -- or, if you are finished, "
                    f"give your final answer with no marker in it at all."
                )})
                continue
            echo = _transcript_echo(text)
            if echo and not is_last:
                # It claimed results it never got. Do not record that as
                # an answer -- say so and let it act for real.
                step = Step(step_no, "act", f"rejected a fabricated answer: {echo}", ok=False)
                session.record(step)
                await self._record_step(session, step)
                session.messages.append({"role": "assistant", "content": text})
                session.messages.append({"role": "user", "content": (
                    f"That reply {echo}. Nothing in it actually ran. Do not describe tool calls or "
                    "their results in prose: write one real marker line, or give your final answer "
                    "using only what the results above actually said."
                )})
                continue

            invented = invented_markers(text, offered_tools(session.profile.tools))
            if invented and not is_last and not session.invented_corrected:
                session.invented_corrected = True
                step = Step(step_no, "act", f"rejected a marker for a tool that does not exist: {invented[0]}", ok=False)
                session.record(step)
                await self._record_step(session, step)
                session.messages.append({"role": "assistant", "content": text})
                session.messages.append({"role": "user", "content": (
                    f"There is no tool called {invented[0]}. Your tools are the ones listed above and no others; "
                    "do not write a marker for anything else, and do not describe doing what no tool did. Answer "
                    "with what you can actually do, or say plainly that you cannot."
                )})
                continue
            if invented:
                text = without_markers(text, invented)
            # One Stop hook (stage 4 item 8): the first claim no tool backs
            # bounces the reply once, whichever rule caught it.
            bounce = stophook.check(text, session) if not is_last and not session.claim_corrected else None
            if bounce is not None:
                session.claim_corrected = True
                self._telemetry.event("orchestration.stop_hook", trace_id=session.trace or session.task_id,
                                      span_id=uuid.uuid4().hex, ts=_epoch(self._clock) or None,
                                      attrs={"rule": bounce.rule, "scaffold": session.profile.scaffold})
                step = Step(step_no, "act", bounce.step, ok=False)
                session.record(step)
                await self._record_step(session, step)
                session.messages.append({"role": "assistant", "content": text})
                session.messages.append({"role": "user", "content": bounce.reply})
                continue

            step = Step(step_no, "gather" if step_no == 1 else "act", "final answer", ok=True)
            session.record(step)
            await self._record_step(session, step)
            session.messages.append({"role": "assistant", "content": text})

            if not session.profile.verify:
                return Outcome("completed", result_summary=text, floor=floor)

            return await self._verify_then_finish(session, text, floor=floor)

    # -- phases -----------------------------------------------------------------------------

    async def _wrap_up(self, session: Session) -> str:
        """One model call with no tools: the answer from what the steps
        so far found. "" when the model has nothing (or no provider)."""
        from dataclasses import replace

        saved = session.profile
        session.profile = replace(saved, tools=())
        session.extra_rules = WRAP_UP_TEXT
        try:
            reply = await self._think(session, WRAP_UP_TEXT, last_step=True, no_tools=True)
        finally:
            session.profile = saved
            session.extra_rules = ""
        if reply is None or reply.payload.get("floor"):
            return ""
        text = str(reply.payload.get("text") or "").strip()
        if not text or reply.payload.get("tool_calls") or _marker_shaped(text):
            return ""   # a marker on its own line is a tool request, not an answer (observer, 2026-09-13)
        return text

    async def _persist_transcript(self, session: Session) -> None:
        if session.profile.scaffold == "chat":
            # A chat turn's record is its conversation's session stream
            # (worker `_remember_exchange`, stage 4 item 3); a stream per
            # typed line would be one more file per line.
            return
        try:
            await self._transcripts.persist(session.task_id, session.messages)
        except Exception as exc:  # noqa: BLE001 -- a transcript that could not be written must not stop the work
            self._log_transcript_failure(session, exc)

    @staticmethod
    def _log_transcript_failure(session: Session, exc: Exception) -> None:
        import logging

        logging.getLogger("simorgh.orchestration").warning(
            "session transcript not written for %s: %r", session.task_id, exc)

    #: Scaffolds whose turns are slow enough to be worth bridging.
    SLOW_SCAFFOLDS = ("patch", "research")

    async def _bridge(self, session: Session, user_text: str) -> str:
        """One line, before a slow turn, so the person knows Sim started.

        Streamed as `session.delta` and returned for the caller to
        record as *said*, never as the turn's text: the answer is what
        the real reply says, and a bridge that could end up in the
        transcript would be a turn Sim answered without thinking.

        Cheap by construction -- 24 tokens, no tools, two seconds --
        and skipped entirely on anything that is not slow.
        """
        if not self._bridge_on or session.profile.scaffold not in self.SLOW_SCAFFOLDS:
            return ""
        if session.task_id in self._bridged:
            return ""
        self._bridged.add(session.task_id)
        ask = ("In one short sentence, say what you are about to go and do. "
               "No preamble, no promises about the result, under 12 words.\n\n"
               f"The request: {user_text[:400]}")
        req = Message.new(
            topics.COGNITION_THINK, source=self._bus.source, trace_id=session.trace,
            payload={"purpose": "chat", "messages": [{"role": "user", "content": ask}],
                     "tools": [], "budget": {"max_tokens": 24, "max_cost_usd": 0.01},
                     # A bridge is a courtesy. If only the floor is left,
                     # the turn says nothing rather than saying something
                     # canned in Sim's voice.
                     "require_real_provider": True,
                     "stream": True, "stream_to": session.task_id},
        )
        try:
            reply = await self._bus.request(req, timeout=self._bridge_timeout_s)
        except Exception:  # noqa: BLE001 -- a bridge is never worth failing a turn for
            return ""
        text = str((reply.payload or {}).get("text") or "").strip()
        return text[:200]

    async def _think(self, session: Session, user_text: str, *, last_step: bool, no_tools: bool = False) -> Message | None:
        # Everything up to this call is durable before the model is asked.
        await self._persist_transcript(session)
        steps_left = session.budget.steps_left
        # `offered_tools(())` means "every registered tool" (skills arrive
        # that way); the wrap-up call wants none at all.
        offered = () if no_tools else offered_tools(session.profile.tools)
        if (offered and self._delegation and session.depth < self._max_depth
                and session.profile.scaffold in ("patch", "research") and "delegate" not in offered):
            offered = tuple(offered) + ("delegate",)
        catalog = self._catalog(session) if offered and not no_tools else ""
        if offered and session.profile.scaffold in ("patch", "research", "plan") and WAIT not in offered:
            # Long work may have to wait for the world (stage 7 item 5).
            offered = tuple(offered) + (WAIT,)
        if catalog and "use_skill" not in offered:
            offered = tuple(offered) + ("use_skill",)
        if offered and any(str(m.get("content") or "").startswith(pressure_mod.STUB_MARK) for m in session.messages):
            offered = tuple(offered) + (pressure_mod.RECALL_TOOL,)
        messages = await self._assembler.assemble(session, session.profile.scaffold, user_text=user_text)
        # Per-turn material goes to the latest user turn, so the system
        # prefix stays byte-identical from turn to turn (stage 4 item 4).
        messages = scaffolds.with_turn_note(messages, scaffolds.when_line(_epoch(self._clock)))
        is_chat = session.profile.name == "chat"
        req = Message.new(
            topics.COGNITION_THINK, source=self._bus.source,
            payload={
                "purpose": "chat" if is_chat else "draft",
                "messages": messages, "tools": list(offered),
                # A reply the person is waiting for is streamed as it is
                # written (`session.delta`, stage 3 item 2), to the id the
                # Interface and Voice already key the turn by.
                **({"stream": True, "stream_to": session.task_id} if session.profile.scaffold == "chat" else {}),
                # `Profile.scaffold` reached `assemble()` and was dropped;
                # Cognition's protected `task_rules` block (04 section 5.4)
                # was implemented and never filled by anyone. So a patch
                # session was told what it *could* call and never what
                # finishing means -- live 2026-09-07, a run applied its
                # edit and stopped without committing it. See scaffolds.py.
                "task_rules": scaffolds.render(
                    # A chat turn's text is its own latest user turn, already
                    # in `messages`; in the system prompt it changed the
                    # prefix on every turn.
                    session.profile, subject=session.subject,
                    task=None if session.profile.scaffold == "chat" else session.user_text,
                    unavailable=scaffolds.unavailable_note(offered), channel=session.channel,
                    speaker=session.speaker, speaker_relation=session.speaker_relation, room=session.room,
                    speaker_doubt=session.speaker_doubt,
                    speaker_before=getattr(session, "speaker_before", ""),
                    offered=() if no_tools else offered,
                    skills=catalog,
                ) + (f"\n\n{session.extra_rules}" if getattr(session, "extra_rules", "") else ""),
                # Live-caught: this request never actually asked Cognition
                # to parse tool calls -- `expected` was never set, so
                # `cognition/service.py::_expected_spec` always fell
                # through to `{"kind": "final"}` and every model reply was
                # treated as a plain answer, no matter what it wrote. The
                # GATHER -> THINK -> (tool_calls -> PROPOSE | final ->
                # VERIFY) loop this module's own docstring describes was
                # real code with no way to ever reach its tool_calls
                # branch from a real chat turn. `expected: "tool_calls"`
                # only when this profile actually has tools to offer --
                # an empty list would ask Cognition to scan for zero
                # markers, indistinguishable from asking for `final`
                # except for the wasted round-trip.
                "expected": "tool_calls" if offered else "text",
                # Live-caught: the general "here's the marker syntax"
                # instruction (cognition/service.py) never told the model
                # a tool's own argument *shape* -- a model asked to use
                # propose_mcp_server invented a JSON format with a made-up
                # field instead of the real key:value one. Only tools with
                # real internal structure need an entry (orchestration/
                # tools.py::_MARKER_ARG_HINT); most don't.
                "tool_hints": {t: h for t in offered if (h := marker_hint(t))},
                "budget": {"max_tokens": session.profile.max_output_tokens, "max_cost_usd": 0.5},
                "require_real_provider": False, "last_step": last_step,
                # So the model can wind down rather than hit a wall.
                "steps_left": steps_left,
                **self._parallel_offer(offered),
                # Live-caught (v2 live trial, 2026-09-06): a chat turn
                # whose assembled memory-retrieval block happens to be
                # large (large migrated records, a broad query) could
                # exceed budget even after layers 1-4 -- `allow_summarize`
                # (04-cognition.md section 5's own layer 5, "last resort")
                # exists precisely for this and was simply never opted
                # into here. Scoped to chat only, never draft -- summarizing
                # a patch/skill draft's own code context could silently
                # lose the exact content a real code change needs.
                "allow_summarize": is_chat,
                **self._tier(session),
            },
            trace_id=session.trace, clock=self._clock,
        )
        reply = await self._bus.request_or_error(req, timeout=self._think_timeout_s)
        # Every think is billed, and `cognition.think.reply` says what it
        # cost. Accumulating here is what puts a real number on
        # `task.step` and, downstream, on a benchmark run.
        session.spent_usd += float(reply.payload.get("cost_usd") or 0.0)
        session.spent_tokens += int(reply.payload.get("tokens") or 0)
        # Which model actually answered. Cognition has always said so in
        # the reply and nothing carried it any further, so a benchmark
        # run could not check its own headline: the creator's GAIA run
        # on 2026-09-20 was labelled with one model while six provider
        # changes went past in the log, Gemini and the floor among them.
        session.last_provider = str(reply.payload.get("provider") or "")
        if reply.payload.get("ok") is False:
            # Live-caught (v2 live trial, 2026-09-06): this used to just
            # return None, and every caller collapsed that into a silent,
            # empty `Outcome(floor=True, result_summary="")` -- no error
            # code anywhere, not on the Ledger, not in the HTTP response,
            # not even printed (the real process's stdout is buffered when
            # not a tty). Diagnosing a real intermittent failure this way
            # took far longer than it should have. A `task.step` record
            # with `ok=False` costs nothing and makes the actual Cognition
            # error code/detail visible on this task's own Ledger stream
            # (queryable via `/api/logs?stream=task:<id>`) instead of
            # vanishing -- callers still get `None` and are unaffected.
            error = reply.payload.get("error") or {}
            # `phase` is `gather|act|verify` in the contract (TaskStep); the
            # failed think happened while gathering the answer, so "gather"
            # -- a first version wrote "think", which only the schema-blind
            # Ledger path accepted (post-cutover review caught it).
            step_payload = {
                "task_id": session.task_id, "step_no": session.next_step_no(),
                "phase": "gather", "ok": False,
                "summary": f"cognition error: {error.get('code', 'unknown')} -- {error.get('detail', '')}",
            }
            await self._append(session, topics.TASK_STEP, step_payload)
            # Published too (not just appended) so a live surface -- the
            # REPL's narration, the dashboard feed -- sees the failure as
            # it happens, not only in the Ledger afterwards.
            await self._publish(session, topics.TASK_STEP, step_payload)
            session.last_think_error = str(error.get("code") or "")
            return None
        session.last_think_error = ""
        session.context_pressure = pressure_mod.pressure(reply.payload)
        return reply

    def _skills(self) -> list:
        """Every valid skill under the configured roots, read once per runner.

        A broken skill is not a crash and not silence: `discover_skills`
        returns it with a reason, and the reason is logged the first time."""
        if not self._skills_enabled or not self._skills_roots:
            return []
        if self._skill_cache is None:
            from pathlib import Path

            from simorgh.contracts.skills import discover_skills

            roots = [(Path(root).expanduser().name or "skills", Path(root).expanduser())
                     for root in self._skills_roots]
            cards, invalid = discover_skills(roots)
            self._skill_cache = (cards, invalid)
            for bad in invalid:
                self._log_invalid_skill(bad)
        return list(self._skill_cache[0])

    def _log_invalid_skill(self, bad) -> None:
        print(f"[skills] ignored {bad.path}: {bad.reason}")

    def _catalog(self, session: Session) -> str:
        """The `- name: description` lines for this session's profile.

        Nothing at all on a channel that is not listed. A voice turn and a
        typed one both run the profile named "chat" (`profiles.for_percept`
        returns VOICE_CHAT or CHAT, and both are named "chat"), so the
        profile cannot tell them apart -- but the Session carries the
        channel it came in on, and that can.
        """
        if getattr(session, "channel", "") not in self._skills_channels:
            return ""
        from simorgh.contracts.skills import catalog_text

        cards = self._skills()
        if not cards:
            return ""
        return catalog_text(cards, profile=session.profile.name, max_chars=self._skills_catalog_max_chars)

    async def _use_skill(self, session: Session, call: dict) -> tuple[bool, str, str]:
        """`USE_SKILL: <name>` -- the skill's own instructions, as a result.

        Nothing outside this process is touched, so it never goes to Guardian
        (like `delegate`). An unknown name says which names are real rather
        than failing blankly."""
        from simorgh.contracts.skills import load_body

        wanted = " ".join(str((call.get("args") or {}).get("argument") or "").split()).strip().lower()
        cards = {card.name: card for card in self._skills()}
        card = cards.get(wanted)
        if card is None:
            known = ", ".join(sorted(cards)) or "none are loaded"
            text = f"no skill called {wanted!r}. The skills you have: {known}"
            return False, text, text
        try:
            body = load_body(card)
        except OSError as exc:
            text = f"{card.name}: its SKILL.md could not be read ({exc})"
            return False, text, text
        header = (f"Skill {card.name} ({card.source}, files under {card.path}). Follow it for this task. "
                  f"Read the files it mentions with read_file; run any script it ships with run_script, "
                  f"never by pasting its contents somewhere else:")
        return True, f"{header}\n\n{body}", f"loaded the skill {card.name}"

    def _parallel_offer(self, offered) -> dict:
        """Which offered tools may run together, when that is switched on."""
        reads = [tool for tool in offered if tool not in ("delegate", "task") and is_read_only(tool)]
        if self._parallel_reads < 2 or len(reads) < 2:
            return {}
        return {"parallel_tools": reads, "max_parallel_tools": self._parallel_reads}

    def _read_batch(self, tool_calls: list) -> list:
        """The calls this step runs: the first, plus the read-only calls
        straight after it when the first is read-only too, up to
        `parallel_read_tools`. Anything that can change something still
        runs alone, and nothing after it runs in the same step."""
        batch = [tool_calls[0]]
        if self._parallel_reads < 2 or not self._batchable(batch[0]):
            return batch
        for extra in tool_calls[1:]:
            if len(batch) >= self._parallel_reads or not self._batchable(extra):
                break
            batch.append(extra)
        return batch

    @staticmethod
    def _batchable(call: dict) -> bool:
        tool = str(call.get("tool") or "")
        return tool not in ("delegate", "task") and is_read_only(tool)

    def _dropped_rule(self) -> str:
        if self._parallel_reads > 1:
            return (f"only read-only lookups run together, up to {self._parallel_reads}, "
                    "and nothing after a tool that changes something.")
        return "one tool call per message."

    async def _run_native_calls(self, session: Session, calls: list, step_no: int) -> list[str]:
        """Every call of one native reply, results in the calls' order.
        Read-only calls run together, `parallel_read_tools` at a time;
        anything that can change something runs alone, in order, and the
        first that fails stops the rest of the changes (a later write may
        depend on it). Each call is its own recorded step."""
        results: dict[int, tuple[bool, str, str]] = {}
        reads = [i for i, c in enumerate(calls) if self._batchable(c)]
        cap = max(1, self._parallel_reads)
        for start in range(0, len(reads), cap):
            chunk = reads[start:start + cap]
            done = await asyncio.gather(*(self._run_one(session, calls[i], step_no + i) for i in chunk))
            results.update(zip(chunk, done))
        stopped = False
        for i, call in enumerate(calls):
            if i in results:
                continue
            if stopped:
                text = f"{call.get('tool')}: not run -- an earlier change in this reply failed"
                results[i] = (False, text, text)
                continue
            results[i] = await self._run_one(session, call, step_no + i)
            stopped = not results[i][0]
        for i, call in enumerate(calls):
            ok, _summary, detail = results[i]
            step = Step(step_no + i, "act", detail, tool=call.get("tool"), ok=ok, denied=was_denied(detail))
            session.record(step)
            await self._record_step(session, step)
        return [results[i][1] for i in range(len(calls))]

    async def _run_one(self, session: Session, call: dict, step_no: int) -> tuple[bool, str, str]:
        if call.get("tool") in ("delegate", "task"):
            return await self._delegate(session, call)
        if call.get("tool") == "use_skill":
            return await self._use_skill(session, call)
        if call.get("tool") == pressure_mod.RECALL_TOOL:
            return await self._recall_result(call)
        if call.get("tool") == MEMORY_SEARCH:
            return await self._memory_search(session, call)
        if call.get("tool") == WAIT:
            return await self._wait(session, call)
        return await self._propose_and_await(session, call, step_no)

    async def _run_batch(self, session: Session, batch: list, step_no: int) -> str:
        """Run independent read-only calls at once. Each is proposed to
        Guardian on its own and recorded as its own step; the model gets
        one numbered block with every result."""
        results = await asyncio.gather(*(
            self._propose_and_await(session, call, step_no + i) for i, call in enumerate(batch)
        ))
        blocks = []
        for i, (call, (ok, summary, detail)) in enumerate(zip(batch, results)):
            step = Step(step_no + i, "act", detail, tool=call.get("tool"), ok=ok, denied=was_denied(detail))
            session.record(step)
            await self._record_step(session, step)
            argument = " ".join(str((call.get("args") or {}).get("argument") or "").split())[:120]
            blocks.append(f"[{i + 1}] {str(call.get('tool') or '').upper()}: {argument}\n{summary}")
        return "\n\n".join(blocks)

    async def _delegate(self, session: Session, call: dict) -> tuple[bool, str, str]:
        """Run a helper: a read-only research session with a fresh context and
        its own small budget, in this process (so a single Worker cannot
        deadlock waiting on its own child). Only its report comes back; its
        steps live on its own `task:<id>` stream. (Design section 5.)"""
        from dataclasses import replace as _replace

        from . import profiles as _profiles
        from .api import Budget as _Budget

        args = call.get("args") or {}
        if isinstance(args, dict) and set(args) == {"argument"}:
            # A marker from a real model arrives as one raw string. Guardian's
            # `to_action_payload` is where other tools get it split, and a
            # delegate is never proposed -- so split it here the same way:
            # the job on line one, optional JSON after.
            from .tools import _json_rest

            head, _, rest = str(args["argument"]).partition("\n")
            args = {"job": head.strip(), **_json_rest(rest, "spec")}
        job = " ".join(str(args.get("job") or args.get("goal") or args.get("brief") or "").split())
        if not job:
            text = "delegate: refused -- say on the first line what the helper should do"
            return False, text, text
        # Which agent the helper is (stage 7 item 1). `research` unless the
        # caller names one that exists; an unknown name is said rather than
        # silently swapped, or a typo becomes a different kind of helper.
        from . import profiles as _agents

        wanted = str(args.get("agent") or "").strip().lower()
        if wanted and wanted not in _agents.AGENTS:
            text = (f"delegate: refused -- no agent called {wanted!r}; "
                    f"the agents are {', '.join(sorted(_agents.AGENTS))}")
            return False, text, text
        running = len([t for t in self._children.get(session.task_id, ()) if not t.done()])
        if running >= self._max_children:
            text = (f"delegate: refused -- {running} helper(s) already running for this task; "
                    f"{self._max_children} at once is the cap")
            return False, text, text
        if session.depth >= self._max_depth:
            text = f"delegate: refused -- helpers may not go deeper than {self._max_depth}"
            return False, text, text
        try:
            steps = int(args.get("steps") or 0)
        except (TypeError, ValueError):
            steps = 0
        steps = max(3, min(self._delegate_max_steps, steps or self._delegate_max_steps))
        n = sum(1 for s in session.steps if s.tool in ("delegate", "task")) + 1
        child_id = f"{session.task_id}-h{n}"
        goal = (session.progress.split("\n", 1)[0] if session.progress
                else " ".join(session.user_text.split())[:500]) or "(not stated; the job below is the whole brief)"
        brief = (
            f"You are a helper on a larger task. Its goal: {goal}\n\n"
            f"Your one job: {job}\n\n"
            # No `WORD:` lines: a capitalised word and a colon reads as a tool
            # marker, and a report of "ANSWER: 2009" was bounced as an invented
            # tool (test_delegate, 2026-09-15).
            "Do only this job, in as few steps as you can. Then reply with a short plain-text report: "
            "first the answer in one or two sentences, then the facts behind it as '- ' bullets with "
            "exact paths, names and numbers, including any tests you ran and whether they passed."
        )
        agent = _agents.AGENTS[wanted] if wanted else _profiles.RESEARCH
        child = Session(
            task_id=child_id, kind=agent.scaffold if wanted else "research", mode="execute",
            profile=_replace(agent, verify=False, max_steps=steps),
            budget=_Budget(max_steps=steps), worker_id=session.worker_id, user_text=brief,
            depth=session.depth + 1, parent_id=session.task_id,
        )
        running_task = asyncio.ensure_future(self.run(child, user_text=brief))
        self._children.setdefault(session.task_id, []).append(running_task)
        try:
            outcome = await running_task
        finally:
            siblings = self._children.get(session.task_id) or []
            if running_task in siblings:
                siblings.remove(running_task)
        session.spent_usd += child.spent_usd
        session.spent_tokens += child.spent_tokens
        body = (outcome.result_summary or outcome.reason or "(no report)").strip()
        if len(body) > 1500:
            body = body[:1499] + "\u2026"
        ok = outcome.kind == "completed" and bool((outcome.result_summary or "").strip())
        text = f"Helper {child_id} ({outcome.kind}, {child.budget.steps_used} steps): {body}"
        return ok, text, text[:self._DETAIL_CHARS]

    async def _checkpoint(self, session: Session, call: dict, summary: str) -> None:
        """Record an irreversible action that succeeded (stage 7 item 7).

        A crash between the commit and the step record used to leave a
        resumed session no way to tell that the commit had happened, so it
        could make it twice. The checkpoint is on the session's own stream,
        keyed by the tool and a hash of its arguments, and
        `resume.done_actions` reads it back.
        """
        from simorgh.contracts.session import CHECKPOINT, stream_name
        from simorgh.contracts.tiers import tier_of

        tool = str(call.get("tool") or "")
        if not tool or self._ledger is None:
            return
        # Not the Guardian tier: that asks how far an action reaches, and
        # `git_commit` is "reversible" there because a revert exists. The
        # question here is different -- would doing it twice be visible? --
        # so every tool that changes something is checkpointed, and only a
        # read may be repeated freely.
        proposal = _CheckpointProposal(tool, call.get("args") or {})
        tier, _why = tier_of(proposal)
        if proposal.reversibility == "read_only":
            return
        stream = stream_name(session.task_id)
        try:
            await self._ledger.append(stream, Event(
                stream=stream, type=CHECKPOINT, ts=_epoch(self._clock), trace_id=session.trace or "",
                causation_id=None,
                payload={"tool": tool, "args_sha256": _args_hash(call.get("args") or {}),
                         "summary": summary[:500], "tier": tier}))
        except Exception as exc:  # noqa: BLE001 -- a missing checkpoint is a repeat, not a crash
            self._log_transcript_failure(session, exc)

    def note_environment(self, fact: str, value: bool, *, people: dict | None = None) -> int:
        """Tell every open task session that the house changed (stage 6
        item 7); how many were told.

        A task runs for minutes and the house does not hold still for it.
        The turn is appended as an ordinary user message, so the model may
        act on it at its next step -- under the same gate as everything
        else it does. A chat turn is one exchange long and is left alone:
        an environment line arriving mid-answer is noise, not news.
        """
        where = ", ".join(f"{who} in the {area}" for who, area in (people or {}).items())
        told = 0
        for session in list(self._open.values()):
            if session.profile.scaffold == "chat" or not session.messages:
                continue
            session.messages.append({"role": "user", "content": (
                f"While you work, something changed in the house: {fact.replace('_', ' ')} is now "
                f"{'true' if value else 'false'}" + (f" ({where})" if where else "") +
                ". Act on it only if it affects the task you are doing; otherwise carry on."
            )})
            told += 1
        return told

    async def _estimate(self, task_type: str) -> dict:
        """What Sim believes about its own competence here (stage 6 item
        2), or {} when Learning does not answer in time."""
        if not task_type or self._escalate_below <= 0.0:
            return {}
        req = Message.new(topics.SELF_ESTIMATE_REQUEST, source=self._bus.source,
                          payload={"task_type": task_type}, clock=self._clock)
        try:
            reply = await asyncio.wait_for(self._bus.request(req, timeout=0.25), timeout=0.3)
        except Exception:  # noqa: BLE001 -- no estimate is not an escalation
            return {}
        return dict(reply.payload or {})

    def _tier(self, session: Session) -> dict:
        """`{"tier": "strong", "tier_reason": ...}` when this THINK should use
        the strong tier, else {}. Cognition falls back to the default order
        when no strong route is configured, so asking costs nothing."""
        if not self._escalate_from_attempt or session.profile.scaffold == "chat":
            return {}
        if session.attempt >= self._escalate_from_attempt:
            return {"tier": "strong", "tier_reason": f"attempt {session.attempt}"}
        estimate = getattr(session, "estimate", None) or {}
        mean, samples = float(estimate.get("mean") or 0.0), int(estimate.get("samples") or 0)
        if samples >= self._escalate_min_samples and mean < self._escalate_below:
            # Sim's own record at this kind of work, not a guess about the
            # model: below the bar and resting on enough outcomes to mean
            # something, this asks for the stronger tier from the start.
            return {"tier": "strong", "tier_reason": f"{session.kind} succeeds {mean:.0%} over {samples}"}
        last = session.steps[-1] if session.steps else None
        if last is not None and last.tool == "delegate" and last.ok is False:
            return {"tier": "strong", "tier_reason": "a helper came back without an answer"}
        return {}

    async def _relieve(self, session: Session) -> None:
        """Compaction by token pressure (orchestration/pressure.py): stub
        the older tool results; when that finds nothing to stub and the
        pressure is past `NOTE_AT`, write the progress note instead."""
        measured = session.context_pressure
        # Acted on once per measurement; the next reply measures again.
        session.context_pressure = 0.0
        stubbed = 0
        if self._ledger is not None:
            async def put(data: bytes) -> str:
                return await self._ledger.put_blob(data, content_type="text/plain")
            session.messages, stubbed = await pressure_mod.stub_old_results(
                session.messages, keep_recent=max(1, self._keep_recent_steps), put=put)
        if stubbed:
            step = Step(session.next_step_no(), "gather",
                        f"context at {measured:.0%}: {stubbed} older tool result(s) set aside "
                        f"(recall_result brings one back)", ok=True)
            session.record(step)
            await self._record_step(session, step)
            return
        if measured >= pressure_mod.NOTE_AT and session.profile.scaffold != "chat" and not session.budget.is_last_step:
            await self._reground(session, forced=True)

    async def _wait(self, session: Session, call: dict) -> tuple[bool, str, str]:
        """`wait 10m` or `wait until <topic>` -- stop, and come back when
        there is something to come back for (stage 7 item 5).

        A task that waits by sleeping holds a worker and a model context
        for as long as it waits, so ten minutes of waiting is ten minutes
        nothing else runs. This publishes `task.waiting` instead: Planning
        parks the task, the lease goes, and the wake puts it back on the
        queue with everything it had.
        """
        from simorgh.contracts.durations import parse_duration

        args = call.get("args") or {}
        raw = " ".join(str(args.get("argument") or args.get("for") or args.get("until") or "").split())
        if session.profile.scaffold == "chat":
            text = "wait: a chat turn is answered now; start a task if the answer has to come later"
            return False, text, text
        event, seconds = "", None
        body = raw[len("until"):].strip() if raw.lower().startswith("until") else raw
        if "." in body and " " not in body:
            event = body
        else:
            seconds = parse_duration(body)
        if not event and not seconds:
            text = "wait: say how long (`wait 10m`) or what to wait for (`wait until world.home.situation_changed`)"
            return False, text, text
        payload = {"task_id": session.task_id, "why": f"the session asked to wait for {body}"}
        if seconds:
            payload["until"] = _epoch(self._clock) + seconds
        if event:
            payload["event"] = event
        await self._publish(session, topics.TASK_WAITING, payload)
        session.waiting = True
        text = (f"waiting for {body}; the task is parked and will come back when it is due. "
                "Say nothing further this turn.")
        return True, text, text

    async def _memory_search(self, session: Session, call: dict) -> tuple[bool, str, str]:
        """`memory_search <what>` -- ask Memory, in the middle of a turn.

        Recall already runs once per turn before the model speaks; this is
        for the second question the first answer raises ("when did she say
        that?"), which used to be unanswerable without waiting for the next
        turn. Effect-free, so it never goes to Guardian (like `delegate`),
        and a person's memories stay theirs: a spoken turn searches with the
        speaker's tag, exactly as the turn's own recall does.
        """
        args = call.get("args") or {}
        query = " ".join(str(args.get("argument") or args.get("query") or "").split())
        if not query:
            text = "memory_search needs something to look for"
            return False, text, text
        kinds = [k for k in str(args.get("kinds") or "").replace(",", " ").split() if k] or ["episodic", "semantic"]
        payload = {"query": query, "kinds": kinds, "k": int(args.get("k") or 8)}
        speaker = str(getattr(session, "speaker", "") or "")
        if speaker:
            payload["filters"] = {"tags": [f"person:{speaker}"]}
        reply = await self._assembler.retrieve(payload, trace_id=session.trace)
        if reply is None:
            text = "memory could not be reached just now"
            return False, text, text
        items = list(reply.payload.get("items") or [])
        facts = list(reply.payload.get("facts") or [])
        lines = [f"- {f.get('subject','')} {f.get('predicate','')} {f.get('object','')}"
                 + (f" (was {f['was']})" if f.get("was") else "") for f in facts]
        lines += [f"- {str(i.get('content') or '')[:400]}" for i in items]
        if not lines:
            text = f"nothing remembered about {query!r}"
            return True, text, text
        body = "\n".join(lines[:12])
        return True, f"What you remember about {query!r}:\n{body}", f"searched memory for {query!r}: {len(lines)} line(s)"

    async def _recall_result(self, call: dict) -> tuple[bool, str, str]:
        """`recall_result <ref>`: a tool result set aside under pressure,
        back in full. Local to the session, so it never goes to Guardian."""
        ref = pressure_mod.recall_ref(call.get("args") or {})
        if not ref or self._ledger is None:
            text = "recall_result needs the ref from a stubbed result"
            return False, text, text
        try:
            data = await self._ledger.get_blob(ref)
        except Exception as exc:  # noqa: BLE001 -- an unknown ref is the model's mistake, said plainly
            text = f"no stored result under {ref!r} ({type(exc).__name__})"
            return False, text, text
        return True, data.decode("utf-8", errors="replace"), f"recalled a stored result ({len(data)} bytes)"

    async def _reground(self, session: Session, *, forced: bool = False) -> bool:
        """Write the progress note and replace the transcript with it.

        True when the transcript was replaced. A failed or unusable note
        leaves the transcript exactly as it was -- a re-ground may lose
        nothing -- and is tried again at the next interval.
        (docs/plans/long-run-context-design.md section 3.)"""
        since = session.messages
        prompt = progress_note.reground_prompt(session.user_text, session.progress, since,
                                               steps_left=session.budget.steps_left)
        req = Message.new(
            topics.COGNITION_THINK, source=self._bus.source,
            payload={
                "purpose": "reground", "messages": [{"role": "user", "content": prompt}], "tools": [],
                "expected": "text", "budget": {"max_tokens": 1500, "max_cost_usd": 0.1},
                "require_real_provider": True, "last_step": False, "steps_left": session.budget.steps_left,
            },
            trace_id=session.trace, clock=self._clock,
        )
        reply = await self._bus.request_or_error(req, timeout=self._think_timeout_s)
        session.spent_usd += float(reply.payload.get("cost_usd") or 0.0)
        session.spent_tokens += int(reply.payload.get("tokens") or 0)
        note = None
        if reply.payload.get("ok") is not False and not reply.payload.get("floor"):
            note = progress_note.parse_note(str(reply.payload.get("text") or ""))
        # Counted from now either way, so a failing note-writer is not asked every step.
        session.reground_at = session.budget.steps_used
        if note is None:
            error = (reply.payload.get("error") or {}).get("code") or "no usable note"
            step = Step(session.next_step_no(), "gather", f"reground skipped ({error}); the transcript is kept", ok=False)
            session.record(step)
            await self._record_step(session, step)
            return False
        before = len(session.messages)
        session.progress = note.render()
        session.messages = progress_note.compacted(session.messages, note, keep_recent_steps=self._keep_recent_steps)
        await self._append(session, topics.TASK_PROGRESS, {
            "task_id": session.task_id, "note": session.progress, "step_no": session.budget.steps_used,
            "attempt": session.attempt,
        })
        step = Step(session.next_step_no(), "gather",
                    f"reground{' (context too large)' if forced else ''}: {before} messages -> {len(session.messages)}; "
                    f"next: {note.next}", ok=True)
        session.record(step)
        await self._record_step(session, step)
        await self._checkpoint_critic(session, note)
        return True

    async def _checkpoint_critic(self, session: Session, note) -> None:
        """Ask whether this is still going to work (stage 7 item 6).

        A long task does not fail by returning something wrong; it
        wanders, and nothing notices until the budget is gone. The critic
        scores the trajectory against the acceptance criteria at every
        progress note, on the cheap tier. Two `drifting` verdicts in a
        row end the attempt for re-planning -- one is a bad patch, two in
        a row is a direction.
        """
        acceptance = [line[len("done when:"):].strip() for line in (session.acceptance or [])]
        req = Message.new(topics.VERIFY_CHECKPOINT_REQUEST, source=self._bus.source, payload={
            "task_id": session.task_id, "goal": session.user_text[:500],
            "acceptance": session.acceptance or [], "trajectory": note.render()[:3000],
        }, trace_id=session.trace, clock=self._clock)
        try:
            reply = await self._bus.request(req, timeout=self._think_timeout_s)
        except Exception:  # noqa: BLE001 -- no critic is not a verdict
            return
        verdict = str(reply.payload.get("verdict") or "insufficient_evidence")
        session.drifting = session.drifting + 1 if verdict == "drifting" else 0
        if verdict in ("on_track", "insufficient_evidence"):
            return
        unmet = ", ".join(reply.payload.get("unmet") or []) or str(reply.payload.get("why") or "")
        step = Step(session.next_step_no(), "verify", f"checkpoint: {verdict}" + (f" ({unmet})" if unmet else ""),
                    ok=verdict != "blocked")
        session.record(step)
        await self._record_step(session, step)
        if verdict == "blocked" or session.drifting >= 2:
            session.replan = f"{verdict}: {unmet}" if unmet else verdict
        elif reply.payload.get("next"):
            session.messages.append({"role": "user", "content": (
                f"A check of your progress says this is drifting ({unmet or 'no criterion met yet'}). "
                f"The next thing to do is: {reply.payload['next']}")})

    # Live-caught (the creator: "I'd like ... code diffs ... similar UI
    # experience as claude code cli" -- 07-post-cutover-review.md §3.11):
    # a real diff (`execution/tools.py::_write_scoped_file`) now travels
    # through `output`/`stdout_preview`, but the old 200-char cap here
    # existed for the *model's own next-turn context* (`session.messages`
    # -- keeping tool output small is deliberate, this session's own
    # context_too_large work), not for what a human watching narration
    # gets to see. Returns both: `summary` (200 chars, unchanged, goes to
    # the model) and `detail` (2000 chars, goes only to the published
    # `task.step` -- the Ledger, the CLI narration, the dashboard feed --
    # never back into the model's own context).
    _DETAIL_CHARS = 2000
    # What the *model* is shown of a tool result.
    #
    # This was 200 characters. Live-caught 2026-09-07, tracing why
    # Sim had never once edited its own source across 246 tool runs:
    # asked to add a docstring to a 5,457-character file, it read the
    # file, was handed the first 200 characters of it, and read it
    # again -- eight times in a row, replying with nothing but
    # "READ_FILE: simorgh/interface/vitals.py" each time. It could not
    # patch a file it had never been allowed to see, and `list_dir` of
    # the repo root came back so clipped that it concluded it was
    # working in "an empty temp directory".
    #
    # 8000 characters is about 2000 tokens, which is exactly the size
    # Cognition already budgets per tool result
    # (`cognition/config.py::tool_result_max_tokens`) and compacts
    # from layer 1 onward. Bounding it to a fiftieth of that here,
    # before compaction ever saw it, was not caution -- it removed
    # the only channel the model had for looking at anything.
    _MODEL_RESULT_CHARS = 8000

    @classmethod
    def _bound_for_model(cls, text: str) -> str:
        # A silent cut taught the model that the file *ended* there
        # (observer round, 2026-09-07: it rewrote a module from the
        # first 8000 chars and lost the rest). Say it was cut, say how
        # long the whole thing is, and say how to get the remainder.
        if len(text) <= cls._MODEL_RESULT_CHARS:
            return text
        return (
            text[: cls._MODEL_RESULT_CHARS]
            + f"\n...[cut at {cls._MODEL_RESULT_CHARS} of {len(text)} chars;"
            " for a file, READ_FILE: path:START-END returns just those lines]"
        )

    async def _propose_and_await(self, session: Session, call: dict, step_no: int) -> tuple[bool, str, str]:
        if call.get("error"):
            # A native call whose arguments were not a JSON object (stage 2):
            # nothing to propose; the model is told and can send it again.
            text = f"{call.get('tool')}: {call['error']} -- send the call again with its arguments as a JSON object"
            return False, text, text
        refused = unplaced_voice_refusal(session, str(call.get("tool") or ""))
        if refused:
            return False, refused, Detail(refused, "refused")
        action_id = uuid.uuid4().hex[:12]
        payload = to_action_payload(
            action_id=action_id, task_id=session.task_id, call=call,
            rationale=f"step {step_no} of {session.profile.name} session",
            proposed_by=self._bus.source, kind=session.kind,
            # Who Sim is talking to (stage 6 item 5). A typed turn carries
            # no speaker and is the owner's console; a spoken one names the
            # person Voice placed, and an unplaced voice stays unnamed.
            requester=str(getattr(session, "speaker", "") or ""),
            requester_channel=str(getattr(session, "channel", "") or ""),
        )
        already = session.done_actions.get((str(call.get("tool") or ""), _args_hash(payload.get("args") or {})))
        if already is not None:
            # This exact call already succeeded before the crash that
            # ended the last attempt (stage 7 item 7). Doing it again is
            # a second commit, a second message, a second purchase.
            text = f"{call.get('tool')} was already done before this attempt was interrupted: {already}"
            return True, text, Detail(text, "")
        refused = chat_outside_workspace_refusal(session, str(call.get("tool") or ""), payload.get("args") or {})
        if refused:
            return False, refused, Detail(refused, "refused")
        # How long this session waits for the result, on the wire (stage 1
        # item 5): the approval carries it to Execution, which never runs
        # the tool past it. A person's later yes is caused by their answer,
        # not by this proposal, so it is not cut short by it.
        wait_s = _ACTION_TIMEOUTS.get(str(call.get("tool") or ""), self._action_timeout_s)
        now = _epoch(self._clock)
        msg = Message.new(
            topics.ACTION_PROPOSED, source=self._bus.source,
            payload=payload, partition_key=f"task:{session.task_id}",
            trace_id=session.trace, clock=self._clock, deadline=(now + wait_s) if now else None,
        )
        await self._bus.publish(msg)
        tool_name = call.get("tool")
        # Say a tool has STARTED, so anything covering the wait can
        # start covering it now (stage 3 item 5). `tool.invoked` fires
        # when the call finishes, which is too late to be useful to
        # somebody standing in the kitchen.
        await self._bus.publish(Message.new(
            topics.TOOL_STARTED, source=self._bus.source, trace_id=session.trace,
            payload={"name": str(tool_name or ""), "action_id": action_id,
                     "recent_p95_ms": self.recent_p95_ms(str(tool_name or "")),
                     "session_id": session.task_id, "channel": session.channel},
        ))
        started_at = time.monotonic()
        # A read-only tool (`web_fetch`, `run_python_sandboxed`, ...)
        # never reports a `file_write`/`file_create` side effect, so
        # `session.uncommitted` has nothing at stake in giving up on it
        # early -- unlike `apply_source_patch`/`git_commit`, where the
        # side effect only becomes known (and trackable for cleanup)
        # once the real `action.result` arrives, so those must still
        # ride out the full timeout. Without this, a cancel arriving
        # mid-call sat unnoticed for the tool's whole remaining timeout
        # (up to 330s for `run_tests`, 45s for `web_fetch`) even though
        # `_run`'s own loop is ready to act on it the instant this
        # returns (live-measured, 2026-09-08).
        cancel_check = (lambda: self._is_cancelled(session.task_id)) if is_read_only(tool_name) else None
        # A task waits for the person's answer; a chat turn does not (the
        # person is right there, and a yes given later still runs it).
        # Before 2026-09-19 a task recorded "needs human" as a failed step
        # and moved on; the stand-in person's yes then ran apply_skill
        # after the session had ended, and the landing was refused over
        # the file it wrote (the write-a-skill trial).
        waits_for_person = session.profile.scaffold != "chat"
        result = await self._waiter.wait(
            (topics.ACTION_RESULT, topics.ACTION_DENIED)
            + (() if waits_for_person else (topics.ACTION_NEEDS_HUMAN,)),
            key="action_id", value=action_id,
            timeout=_ACTION_TIMEOUTS.get(tool_name, self._action_timeout_s),
            cancel_check=cancel_check,
            through=(topics.ACTION_NEEDS_HUMAN,) if waits_for_person else (),
            through_timeout=_HUMAN_ANSWER_WAIT_S + _ACTION_TIMEOUTS.get(tool_name, self._action_timeout_s),
        )
        self._note_tool_ms(str(tool_name or ""), (time.monotonic() - started_at) * 1000.0)
        if result is None:
            if cancel_check is not None and cancel_check():
                text = f"{tool_name}: cancelled while waiting for a response"
            else:
                text = f"{tool_name}: no response (timed out)"
            return False, text, Detail(text, "transient")
        if result.type == topics.ACTION_RESULT:
            ok = result.payload.get("ok", False)
            if ok:
                record_side_effects(session, result.payload.get("side_effects") or ())
            full = result.payload.get("stdout_preview", "")
            error = result.payload.get("error") or ""
            if not ok:
                # A failing tool puts its reason in `error`, not in
                # `stdout_preview`, and only the preview was ever read --
                # so a refusal reached the model as an *empty* result. It
                # was told "that failed" and nothing else.
                #
                # Live-caught 2026-09-07: `apply_source_patch` was refused
                # and the step recorded an empty summary, leaving the
                # model to guess. The same silence sat behind every failed
                # `run_tests` and `git_commit` in the earlier trials.
                full = f"{error}\n\n{full}".strip() if full else error
            if call.get("tool") == "run_tests":
                # The one fact verification's `FullSuiteRanCheck` needs
                # and nothing else records: what TARGET this call ran.
                # Two real trials committed a change that broke the
                # suite by narrowing `run_tests` to one passing file --
                # "run the tests, and run them again if they fail"
                # (scaffolds.py) is satisfied literally by a target that
                # was never going to fail (2026-09-08). Prefixed onto
                # `full`, which is what `_put_verify_subject` forwards as
                # this step's `summary`, so the check can see it without
                # a new field threaded through `Step`/the ledger schema.
                #
                # Read from `payload["args"]`, NOT `call["args"]`. Every
                # real marker call arrives as `call["args"] ==
                # {"argument": "<raw text>"}` -- `to_action_payload`
                # remaps that to the tool's real schema key (`target`)
                # in a fresh dict it returns, never mutating `call`
                # itself. Reading `call.get("args", {}).get("target")`
                # therefore always found nothing and always fell back to
                # the literal `"tests"` default, for every real call, no
                # matter what was actually run -- an observer proved the
                # check accepted a 34-test slice as proof the whole
                # 3080-test suite had passed, defeating the entire fix
                # for the one calling convention every real trial uses
                # (2026-09-08).
                target = (payload.get("args") or {}).get("target") or "tests"
                # And WHICH tests failed, hoisted past the stderr tail
                # `_publish_result` puts in front of the output. Both
                # facts have to survive the 2000-char cut below, and on a
                # live trial the failure list cleared it by 465 of 2000
                # characters -- a slightly noisier stderr and
                # `full_suite_ran` would have been blind again, with no
                # sign that anything had been lost.
                full = f"[ran target={target!r}]\n{hoist_marker(full)}"
            # The kind as Execution sent it; a result with none (an older
            # producer) is "failed" -- never guessed from its words.
            kind = "" if ok else str(result.payload.get("error_kind") or "failed")
            if ok:
                await self._checkpoint(session, call, full)
            return ok, self._bound_for_model(full), Detail(full[: self._DETAIL_CHARS], kind)
        if result.type == topics.ACTION_DENIED:
            reasons = "; ".join(result.payload.get("reasons", [])) or result.payload.get("layer", "denied")
            text = f"{DENIED_PREFIX}{reasons}"
            return False, text, Detail(text, DENIED_KIND)
        text = f"needs human: {result.payload.get('question', '')}"
        return False, text, Detail(text, "refused")

    async def _verify_then_finish(self, session: Session, text: str, *, floor: bool) -> Outcome:
        while True:
            # `_run`'s main loop checks `_is_cancelled` between every
            # step; this loop never did, and it can run for a long time
            # -- each pass is a real verify round-trip plus, on a fail,
            # a real re-think call. An observer measured the cost
            # directly: a preemption cancel arrived while a session was
            # mid-revision and the handover took 56 seconds instead of
            # the sub-second norm, because the worker only hands over
            # "at the next step boundary" and this loop has none
            # (2026-09-08). Checked at the top of every pass, so a
            # cancel is honoured between verification rounds exactly
            # the way it is honoured between ordinary steps.
            if self._is_cancelled(session.task_id):
                return Outcome("failed", reason=CANCELLED_REASON, result_summary=text)
            # A fresh verification_id per attempt (not just per session): a
            # real Verification service treats a *repeated* id on
            # `verify:<id>` as a redelivery and replays the recorded verdict
            # instead of re-running checks (10 section 8, "duplicate
            # request") -- reusing one id across revisions would silently
            # replay the first (failing) verdict forever and never see the
            # revised text (harness-06 gap #5: iterative verification).
            verification_id = uuid.uuid4().hex[:12]
            subject_ref = await self._put_verify_subject(session, text)
            msg = Message.new(
                topics.VERIFY_REQUESTED, source=self._bus.source,
                payload={
                    "verification_id": verification_id, "task_id": session.task_id,
                    "kind": "task", "subject_ref": subject_ref,
                },
                partition_key=f"task:{session.task_id}", trace_id=session.trace, clock=self._clock,
            )
            await self._bus.publish(msg)
            result = await self._waiter.wait(
                (topics.VERIFY_RESULT,), key="verification_id", value=verification_id, timeout=self._verify_timeout_s,
            )
            if result is None:
                # No verdict in time. Accept rather than block forever, but
                # say so: "verification never answered" used to be
                # indistinguishable from "verification passed".
                step = Step(session.next_step_no(), "act",
                            f"verification did not answer within {self._verify_timeout_s:.0f}s; accepted unverified",
                            ok=False)
                session.record(step)
                await self._record_step(session, step)
                return Outcome("completed", result_summary=text, floor=floor, verification_ref=None)

            verdict = result.payload.get("verdict")
            if verdict in ("pass", "insufficient_evidence"):
                return Outcome("completed", result_summary=text, floor=floor, verification_ref=verification_id)

            # The objection, on the record. A failed verdict used to leave
            # nothing on the task's own stream or on screen: the trial saw
            # "blocked: verification failed after max revisions" after a
            # search, a patch, a green suite and a commit, and nobody could
            # say what the reviewer had objected to (2026-09-07).
            feedback = result.payload.get("feedback", {}).get("items", [])
            note = "; ".join(
                f"{f.get('what')}" + (f" -- {f.get('why')}" if f.get('why') else "")
                + (f" (fix: {f.get('suggested_fix')})" if f.get('suggested_fix') else "")
                for f in feedback
            ) or "revise and try again"
            step = Step(session.next_step_no(), "verify", f"verification {verdict}: {note}", ok=False)
            session.record(step)
            await self._record_step(session, step)

            if session.budget.revisions_used >= session.profile.max_revisions:
                # The answer travels with the refusal. Otherwise nobody
                # downstream can tell whether verification rejected
                # something wrong or something right.
                return Outcome("blocked", reason=f"{VERIFICATION_REASON} after max revisions",
                               result_summary=text, verification_ref=verification_id)

            session.budget.revisions_used += 1
            if self._clean_revisions:
                # The objection, the note and the last few steps -- not every
                # failed attempt and tool dump that led to the rejected answer.
                kept = session.messages[-(2 * self._keep_recent_steps):] if self._keep_recent_steps else []
                while kept and kept[0].get("role") != "assistant":
                    kept = kept[1:]
                head = [{"role": "user", "content": f"{progress_note.NOTE_HEADER}\n\n{session.progress}"}] \
                    if session.progress else []
                session.messages = head + list(kept)
            session.messages.append({"role": "user", "content": f"Verification feedback: {note}"})
            think_reply = await self._think(session, "", last_step=session.budget.is_last_step)
            if think_reply is None:
                return Outcome("blocked", reason="no real provider during revision", verification_ref=verification_id)
            # A revision reply's tool calls used to be dropped on the
            # floor. Verification would say "this was never committed",
            # the model would answer `GIT_COMMIT: <path>`, nothing would
            # run, and it re-issued the same call saying "the previous
            # commit attempt did not register" -- then the whole correct,
            # tested patch was discarded (watched trial, 2026-09-08).
            # Acting on the fix the reviewer just asked for is the point
            # of having a revision loop at all.
            for call in (think_reply.payload.get("tool_calls") or ())[:1]:
                ok, summary, detail = await self._propose_and_await(session, call, session.next_step_no())
                step = Step(session.next_step_no(), "act", detail, tool=call.get("tool"), ok=ok, denied=was_denied(detail))
                session.record(step)
                await self._record_step(session, step)
                if ok and call.get("tool") in FINISHING_TOOLS:
                    session.uncommitted.clear()
                    session.created.clear()
                session.messages.append({"role": "assistant", "content": think_reply.payload.get("text") or ""})
                session.messages.append({"role": "user", "content": (
                    f"Result of {call.get('tool')}:\n{summary}\n\nNow give your final answer."
                )})
                think_reply = await self._think(session, "", last_step=session.budget.is_last_step)
                if think_reply is None:
                    return Outcome("blocked", reason="no real provider during revision",
                                   verification_ref=verification_id)
            text = think_reply.payload.get("text", text)
            session.messages.append({"role": "assistant", "content": text})

    async def _put_verify_subject(self, session: Session, text: str) -> str:
        """`verify.requested.subject_ref` is a blob ref, not raw text --
        Verification's `_resolve_subject` reads it with `ledger.get_blob`
        and expects a JSON object with `description`/`result` (the shape
        every other producer, e.g. `learning/pipeline.py`'s
        `candidate_ref`, already sends). Sending truncated raw text there
        silently resolves to an empty subject and the semantic checklist
        loses its signal.
        """
        # The steps travel too. The reviewer used to see only the task
        # and the final answer, generate questions about the change, and
        # answer them from the answer's *prose* -- so a correct patch with
        # a green suite and a commit failed on "does the new code have a
        # test?" it was never asked to write, and a research answer failed
        # on whatever its two paragraphs did not happen to mention
        # (watched trials, 2026-09-07). Now it sees what was actually done.
        #
        # The cut used to be a bare `[:300]` -- far below the 2000 chars
        # `step.summary` (`detail`, above) actually carries. A PDF read
        # whose relevant number landed at char 340 came through as
        # "...sampling 21 CoT trajectories... temperature 0." -- a real
        # quote from a LATER step already had the full "temperature
        # 0.7", but the truncated EARLIER step read like the source
        # itself only supported "0.", and the reviewer failed a correct
        # answer as unsupported/contradicted (two independent observers,
        # 2026-09-08). Cut at a generous width that matches what was
        # already captured in `detail`, and never mid-word: a hard slice
        # invents a fact ("0.") that was never actually said.
        steps = [
            {
                "tool": step.tool, "ok": step.ok, "phase": step.phase, "denied": step.denied,
                "summary": _trim_evidence(
                    step.summary or "",
                    _VERIFY_PATCH_SUMMARY_CHARS if step.tool in ("apply_source_patch", "apply_skill")
                    else _VERIFY_SUMMARY_CHARS,
                ),
            }
            for step in session.steps
        ]
        # Same signal `unsupported_claims` uses below as `complete_log`:
        # a retry's own `session.steps` is only what THIS attempt did,
        # not the whole session's history -- an earlier attempt may have
        # applied the patch and run out of steps, and this attempt's log
        # can legitimately show no write tool at all. Mechanical checks
        # that judge "did a write tool run in the whole session" need to
        # know when they are looking at a partial log, the same way
        # `unsupported_claims` already does.
        complete_log = session.attempt <= 1 and not session.carried
        # The paths this session actually wrote, so a mechanical check can
        # open the real file instead of inferring it from a step summary.
        # Added 2026-09-09 for the non-Python checks (js_syntax, render,
        # trailing_narration): every one of them has to read the artifact
        # to say anything true about it, and the request carried only
        # prose. `subject` travels too -- a patch task names its file up
        # front, and a session that was blocked before its write still
        # tells the checks what it was aiming at.
        written = sorted(session.wrote)
        payload = json.dumps({
            "description": session.user_text, "result": text[:2000], "kind": session.kind, "steps": steps,
            "complete_log": complete_log, "subject": session.subject or "", "written_paths": written,
            "base_ref": session.base_ref,
            # Where the written files are: the task's worktree, or ""
            # for the live tree (`verification/checks/_files.py`).
            "repo_root": session.worktree,
        }).encode("utf-8")
        return await self._ledger.put_blob(payload, content_type="application/json")

    # -- pause/resume -------------------------------------------------------------------------

    def _paused(self) -> bool:
        return self._is_paused()

    async def _pause(self, session: Session) -> Outcome:
        resume_from = len(session.steps)
        await self._append(session, topics.TASK_PAUSED, {
            "task_id": session.task_id, "reason": "system paused", "resume_from_step": resume_from,
        })
        await self._publish(session, topics.TASK_PAUSED, {
            "task_id": session.task_id, "reason": "system paused", "resume_from_step": resume_from,
        })
        return Outcome("paused", reason="system paused")

    # -- ledger + bus plumbing -----------------------------------------------------------------

    async def _record_step(self, session: Session, step: Step) -> None:
        # The spend since the previous step, so a task's steps SUM to the
        # task's cost instead of each repeating the running total.
        already = sum(s.cost_usd for s in session.steps if s is not step)
        step.cost_usd = max(0.0, round(session.spent_usd - already, 6))
        step.tokens = max(0, session.spent_tokens
                          - sum(s.tokens for s in session.steps if s is not step))
        payload = {
            "task_id": session.task_id, "step_no": step.no, "phase": step.phase, "summary": step.summary,
        }
        if step.tool is not None:
            payload["tool"] = step.tool
        if step.ok is not None:
            payload["ok"] = step.ok
        if step.cost_usd:
            payload["cost_usd"] = step.cost_usd
        if step.tokens:
            payload["tokens"] = step.tokens
        # Only on a step a think paid for: attaching the last provider
        # to a pure tool step would say a model served something it did
        # not.
        provider = step.provider or (session.last_provider if step.cost_usd else "")
        if provider:
            payload["provider"] = provider
        await self._append(session, topics.TASK_STEP, payload)
        await self._publish(session, topics.TASK_STEP, payload)

    async def _append(self, session: Session, type_: str, payload: dict) -> None:
        msg = Message.new(type_, source=self._bus.source, payload=payload,
                          partition_key=f"task:{session.task_id}",
                          trace_id=session.trace, clock=self._clock)
        await self._ledger.append(f"task:{session.task_id}", Event.from_message(msg, f"task:{session.task_id}"))

    async def _publish(self, session: Session, type_: str, payload: dict) -> None:
        msg = Message.new(type_, source=self._bus.source, payload=payload,
                          partition_key=f"task:{session.task_id}",
                          trace_id=session.trace, clock=self._clock)
        await self._bus.publish(msg)
