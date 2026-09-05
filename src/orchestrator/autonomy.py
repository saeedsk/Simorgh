"""Idle-triggered autonomous self-improvement -- the one piece of this
project that removes the "a human types the trigger command" boundary
every other capability in Simorgh has kept up to now, explicitly
authorized by the creator (docs/SOUL.md, "Autonomous idle loop") after
being told plainly what that trade-off means: no natural rate limit tied
to how often a human acts, and an LLM-cost profile that runs whenever
nothing else is happening rather than only when asked.

Runs as a daemon thread alongside the interactive CLI loop (src/main.py),
watching how long it's been since the last user input via `ActivityClock`.
Once idle beyond a threshold, `AutonomyController` calls an injected
`perform_action` callback -- it does not itself decide *what* to work on;
that stays main.py's job (discover new work when the queue is empty,
otherwise pick up the next pending/in-progress Task), routed through the
exact same audited propose/patch/verify/commit pipelines a human-typed
command uses. Nothing about *what* it's allowed to do changes; only *what
triggers it* does.

Additionally, during idle cycles, an intrinsic `CuriosityDrive` inspects
episodic memory to identify unresolved knowledge gaps (questions,
uncertainties, missing knowledge) and contradictory beliefs (opposing
claims or negated assertions on identical topics). When found, it
autonomously formulates exploratory research tasks so the agent actively
investigates what it does not know or where its beliefs conflict.

Bounded on top of (never instead of) every existing guard:
- `idle_threshold_seconds`: how long the CLI must sit unused before this
  considers acting at all.
- `action_cooldown_seconds`: a minimum gap between one autonomous action
  and the next, independent of idle time -- no rapid-fire loop.
- `max_actions_per_day`: a hard, durable cap (kind=ACTION_KIND records
  in the same MemoryStore), on top of the BudgetGuard LLM-spend caps
  every real provider is already wrapped in.
- Every action is clearly marked (an unmistakable printed prefix, and
  durably logged) so it is never mistaken for something a human asked
  for -- Directive 8 (Transparency), made concrete for the one capability
  class where confusing the two would matter most.
- `max_consecutive_failures` (a circuit breaker, see the constant's own
  docstring below): if the last `max_consecutive_failures` actions in a
  row all failed, the loop disables itself and prints a loud notice
  instead of quietly grinding through the rest of the daily cap on a
  systematically broken pipeline. Requires `autonomous on` (which resets
  the streak) to resume -- a human checkpoint, not a silent retry.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from src.memory.long_term import MemoryStore
from src.orchestrator.console_style import style


@dataclass(frozen=True)
class ActionDigest:
    total: int
    succeeded: int
    failed: int
    unknown: int
    window_seconds: float


@dataclass(frozen=True)
class KnowledgeGap:
    """An identified gap in understanding, open question, or explicit
    uncertainty discovered in episodic memory.
    """

    topic: str
    description: str
    source_record_ids: tuple[str, ...] = ()
    urgency: float = 1.0


@dataclass(frozen=True)
class ContradictoryBelief:
    """A pair of contradictory statements or conflicting assertions
    discovered across episodic memory on the same topic.
    """

    topic: str
    first_statement: str
    second_statement: str
    source_record_ids: tuple[str, ...] = ()
    confidence_conflict: float = 1.0


@dataclass
class ExploratoryTask:
    """An exploratory research task formulated autonomously by the
    curiosity drive to address a knowledge gap or reconcile contradictory
    beliefs.
    """

    id: str
    title: str
    description: str
    target_topic: str
    rationale: str
    source_type: str  # "knowledge_gap" | "contradictory_belief"
    created_at: float = field(default_factory=time.time)
    status: str = "pending"
    metadata: dict[str, Any] = field(default_factory=dict)


ACTION_KIND = "autonomous_action"
CURIOSITY_TASK_KIND = "curiosity_task"

EPISODIC_KINDS = (
    "episodic",
    "conversation",
    "turn",
    "observation",
    "belief",
    "takeaway",
    "chat",
    "interaction",
    "fact",
)

DEFAULT_IDLE_THRESHOLD_SECONDS = 10.0
DEFAULT_ACTION_COOLDOWN_SECONDS = 3.0
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_MAX_ACTIONS_PER_DAY = 2000
DEFAULT_MAX_CONSECUTIVE_FAILURES = 5

_GAP_INDICATOR_PATTERNS = (
    r"\b(?:don't|do not|doesn't|does not)\s+know\b",
    r"\bnot\s+sure\b",
    r"\bunclear\s+(?:whether|if|how|what|why)\b",
    r"\bunknown\s+(?:whether|if|how|what|why)\b",
    r"\bneed\s+to\s+(?:find\s+out|investigate|determine|learn|research|verify|understand)\b",
    r"\b(?:open\s+question|knowledge\s+gap|missing\s+information|unresolved\s+question)\b",
    r"\b(?:wondering\s+whether|wondering\s+if|wondering\s+how)\b",
    r"\b(?:yet\s+to\s+be\s+determined|have\s+yet\s+to\s+learn)\b",
    r"\bhypothesis:\b",
)

_OPPOSITE_PAIRS = {
    "enabled": "disabled",
    "disabled": "enabled",
    "active": "inactive",
    "inactive": "active",
    "safe": "unsafe",
    "unsafe": "safe",
    "dangerous": "safe",
    "true": "false",
    "false": "true",
    "valid": "invalid",
    "invalid": "valid",
    "possible": "impossible",
    "impossible": "possible",
    "compatible": "incompatible",
    "incompatible": "compatible",
    "succeeds": "fails",
    "fails": "succeeds",
    "success": "failure",
    "failure": "success",
    "always": "never",
    "never": "always",
    "available": "unavailable",
    "unavailable": "available",
    "synchronous": "asynchronous",
    "asynchronous": "synchronous",
    "supported": "unsupported",
    "unsupported": "supported",
}

_STOP_WORDS = {
    "a",
    "an",
    "the",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "with",
    "by",
    "about",
    "that",
    "this",
    "it",
    "from",
    "as",
    "and",
    "or",
    "but",
}


def _tokenize(text: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[A-Za-z0-9_\-]+", text)]


def _content_tokens(text: str) -> set[str]:
    return {w for w in _tokenize(text) if len(w) > 2 and w not in _STOP_WORDS}


class CuriosityDrive:
    """Identifies knowledge gaps and contradictory beliefs across episodic
    memory records, autonomously synthesizing them into structured
    exploratory research tasks.
    """

    def __init__(
        self,
        store: MemoryStore,
        task_store: Any | None = None,
        max_tasks_per_cycle: int = 5,
    ) -> None:
        self._store = store
        self._task_store = task_store
        self.max_tasks_per_cycle = max_tasks_per_cycle
        self._formulated_tasks: dict[str, ExploratoryTask] = {}
        self._seen_signatures: set[str] = set()

    def _fetch_episodic_records(self) -> list[Any]:
        records: list[Any] = []
        try:
            all_records = self._store.query()
        except Exception:
            all_records = []

        if not all_records:
            for k in EPISODIC_KINDS:
                try:
                    all_records.extend(self._store.query(kind=k))
                except Exception:
                    pass

        for record in all_records:
            kind = getattr(record, "kind", "")
            if kind in {ACTION_KIND, CURIOSITY_TASK_KIND}:
                continue
            records.append(record)
        return records

    def _extract_topic(self, sentence: str) -> str:
        match = re.search(
            r"(?:about|regarding|whether|if|how|why|what|on)\s+([A-Za-z0-9_\-\s]{3,40})",
            sentence,
            re.IGNORECASE,
        )
        if match:
            candidate = match.group(1).strip()
            # Stop before terminal punctuation
            candidate = re.split(r"[.?!,;]", candidate)[0].strip()
            if candidate:
                return candidate.lower()

        tokens = [w for w in _tokenize(sentence) if w not in _STOP_WORDS]
        if tokens:
            return " ".join(tokens[:4])
        return "unspecified topic"

    def identify_knowledge_gaps(self, limit: int = 15) -> list[KnowledgeGap]:
        """Scans episodic records for unresolved questions, explicit
        uncertainties, or missing information.
        """
        records = self._fetch_episodic_records()
        gaps: list[KnowledgeGap] = []
        seen_topics: set[str] = set()

        for record in records:
            content = getattr(record, "content", "")
            rec_id = getattr(record, "id", "")
            if not isinstance(content, str):
                continue

            # Split into individual sentences or clauses
            sentences = re.split(r"(?<=[.?!;\n])\s+", content)
            for s in sentences:
                s_clean = s.strip()
                if len(s_clean) < 10:
                    continue

                is_gap = False
                urgency = 1.0

                if s_clean.endswith("?"):
                    is_gap = True
                else:
                    for pat in _GAP_INDICATOR_PATTERNS:
                        if re.search(pat, s_clean, re.IGNORECASE):
                            is_gap = True
                            if "need to" in s_clean.lower() or "critical" in s_clean.lower():
                                urgency = 1.5
                            break

                if is_gap:
                    topic = self._extract_topic(s_clean)
                    if topic in seen_topics:
                        continue
                    seen_topics.add(topic)
                    gaps.append(
                        KnowledgeGap(
                            topic=topic,
                            description=s_clean,
                            source_record_ids=(rec_id,) if rec_id else (),
                            urgency=urgency,
                        )
                    )
                    if len(gaps) >= limit:
                        return gaps

        return gaps

    def identify_contradictory_beliefs(self, limit: int = 15) -> list[ContradictoryBelief]:
        """Scans pairs of episodic records to identify conflicting assertions
        or negated claims regarding the same topic or subject.
        """
        records = self._fetch_episodic_records()
        contradictions: list[ContradictoryBelief] = []
        seen_pairs: set[tuple[str, str]] = set()

        # Extract sentences from each record
        sentence_entries: list[tuple[str, str, set[str]]] = []
        for rec in records:
            rec_id = getattr(rec, "id", "")
            content = getattr(rec, "content", "")
            if not isinstance(content, str):
                continue
            for s in re.split(r"(?<=[.?!;\n])\s+", content):
                s_clean = s.strip()
                tokens = _content_tokens(s_clean)
                if len(tokens) >= 2:
                    sentence_entries.append((rec_id, s_clean, tokens))

        for i in range(len(sentence_entries)):
            for j in range(i + 1, len(sentence_entries)):
                rec_id_a, s_a, tokens_a = sentence_entries[i]
                rec_id_b, s_b, tokens_b = sentence_entries[j]
                if rec_id_a and rec_id_b and rec_id_a == rec_id_b:
                    continue

                shared = tokens_a.intersection(tokens_b)
                if len(shared) < 2:
                    continue

                is_contradiction = False
                lower_a = s_a.lower()
                lower_b = s_b.lower()

                # Case 1: Antonym / opposing term pairs
                for term_a, term_b in _OPPOSITE_PAIRS.items():
                    if term_a in tokens_a and term_b in tokens_b:
                        is_contradiction = True
                        break

                # Case 2: Asymmetric negation on shared predicate
                if not is_contradiction:
                    negation_words = {"not", "cannot", "can't", "never", "no", "fails"}
                    has_neg_a = bool(negation_words.intersection(_tokenize(lower_a)))
                    has_neg_b = bool(negation_words.intersection(_tokenize(lower_b)))
                    if has_neg_a != has_neg_b:
                        is_contradiction = True

                if is_contradiction:
                    pair_key = (min(s_a, s_b), max(s_a, s_b))
                    if pair_key in seen_pairs:
                        continue
                    seen_pairs.add(pair_key)

                    topic = " ".join(sorted(shared)[:4])
                    ids = tuple(sorted(filter(None, [rec_id_a, rec_id_b])))
                    contradictions.append(
                        ContradictoryBelief(
                            topic=topic,
                            first_statement=s_a,
                            second_statement=s_b,
                            source_record_ids=ids,
                            confidence_conflict=1.0,
                        )
                    )
                    if len(contradictions) >= limit:
                        return contradictions

        return contradictions

    def identify_contradictions(self, limit: int = 15) -> list[ContradictoryBelief]:
        """Convenience alias for `identify_contradictory_beliefs`."""
        return self.identify_contradictory_beliefs(limit=limit)

    def formulate_tasks(self, limit: int | None = None) -> list[ExploratoryTask]:
        """Identifies knowledge gaps and contradictory beliefs, creating new
        exploratory research tasks for any unhandled findings.
        """
        max_tasks = limit if limit is not None else self.max_tasks_per_cycle
        new_tasks: list[ExploratoryTask] = []

        gaps = self.identify_knowledge_gaps(limit=max_tasks)
        for gap in gaps:
            if len(new_tasks) >= max_tasks:
                break
            sig = f"gap:{gap.topic}:{gap.description[:40]}"
            if sig in self._seen_signatures:
                continue
            self._seen_signatures.add(sig)

            task_id = "curiosity-gap-" + hashlib.sha256(sig.encode("utf-8")).hexdigest()[:10]
            task = ExploratoryTask(
                id=task_id,
                title=f"Investigate knowledge gap: {gap.topic}",
                description=f"Conduct research to resolve knowledge gap: {gap.description}",
                target_topic=gap.topic,
                rationale=(
                    f"Episodic memory gap detected in records {gap.source_record_ids}: "
                    f"'{gap.description}'"
                ),
                source_type="knowledge_gap",
                metadata={
                    "urgency": gap.urgency,
                    "source_record_ids": list(gap.source_record_ids),
                },
            )
            new_tasks.append(task)
            self._formulated_tasks[task_id] = task

        contradictions = self.identify_contradictory_beliefs(limit=max_tasks)
        for contra in contradictions:
            if len(new_tasks) >= max_tasks:
                break
            sig = f"contra:{contra.topic}:{contra.first_statement[:20]}:{contra.second_statement[:20]}"
            if sig in self._seen_signatures:
                continue
            self._seen_signatures.add(sig)

            task_id = "curiosity-contra-" + hashlib.sha256(sig.encode("utf-8")).hexdigest()[:10]
            task = ExploratoryTask(
                id=task_id,
                title=f"Resolve contradictory beliefs regarding {contra.topic}",
                description=(
                    f"Investigate and reconcile contradictory beliefs on {contra.topic}: "
                    f"'{contra.first_statement}' vs '{contra.second_statement}'"
                ),
                target_topic=contra.topic,
                rationale=(
                    f"Conflicting assertions detected across records {contra.source_record_ids}: "
                    f"'{contra.first_statement}' conflicts with '{contra.second_statement}'"
                ),
                source_type="contradictory_belief",
                metadata={
                    "confidence_conflict": contra.confidence_conflict,
                    "source_record_ids": list(contra.source_record_ids),
                    "first_statement": contra.first_statement,
                    "second_statement": contra.second_statement,
                },
            )
            new_tasks.append(task)
            self._formulated_tasks[task_id] = task

        # Persist formulated tasks in TaskStore and MemoryStore if available
        for t in new_tasks:
            if self._task_store is not None:
                try:
                    self._task_store.add(
                        description=t.description,
                        kind="research",
                        subject=t.target_topic,
                        discovered_via="curiosity",
                    )
                except Exception:
                    pass

            if self._store is not None:
                try:
                    self._store.remember(
                        kind=CURIOSITY_TASK_KIND,
                        content=t.description,
                        title=t.title,
                        target_topic=t.target_topic,
                        source_type=t.source_type,
                        rationale=t.rationale,
                    )
                except Exception:
                    pass

        return new_tasks

    def explore(self, limit: int | None = None) -> list[ExploratoryTask]:
        """Perform one autonomous exploration cycle."""
        return self.formulate_tasks(limit=limit)

    def recent_tasks(self) -> list[ExploratoryTask]:
        return list(self._formulated_tasks.values())


class ActivityClock:
    """Tracks when the interactive loop last did something. The main
    loop calls `touch()` right after each `input()` returns (a user
    submitted something -- the definition of "not idle" here); the
    autonomous loop reads `idle_seconds()` to decide whether to act.
    Thread-safe: a plain float behind a lock is all this needs.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_activity = time.time()

    def touch(self) -> None:
        with self._lock:
            self._last_activity = time.time()

    def idle_seconds(self) -> float:
        with self._lock:
            return time.time() - self._last_activity


class AutonomyController:
    """Owns the enable/disable flag, the idle/cooldown timing, and the
    durable daily action cap. Contains an intrinsic CuriosityDrive that
    identifies knowledge gaps and contradictory beliefs across episodic
    memory during idle cycles.
    """

    def __init__(
        self,
        store: MemoryStore,
        clock: ActivityClock,
        perform_action: Callable[[], bool],
        enabled: bool = True,
        idle_threshold_seconds: float = DEFAULT_IDLE_THRESHOLD_SECONDS,
        action_cooldown_seconds: float = DEFAULT_ACTION_COOLDOWN_SECONDS,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        max_actions_per_day: int = DEFAULT_MAX_ACTIONS_PER_DAY,
        last_action_succeeded: Callable[[], bool | None] | None = None,
        max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES,
        curiosity_drive: CuriosityDrive | None = None,
        task_store: Any | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._perform_action = perform_action
        self.enabled = enabled
        self.idle_threshold_seconds = idle_threshold_seconds
        self.action_cooldown_seconds = action_cooldown_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.max_actions_per_day = max_actions_per_day
        self._last_action_succeeded = last_action_succeeded
        self.max_consecutive_failures = max_consecutive_failures
        self._consecutive_failures = 0
        self._last_action_at = 0.0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.curiosity_drive = curiosity_drive or CuriosityDrive(
            store=store, task_store=task_store
        )
        self.curiosity = self.curiosity_drive

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    def reset_failure_streak(self) -> None:
        """Called when the creator explicitly re-enables the loop after
        a circuit-breaker pause -- a fresh start, not an immediate
        re-trip on the very next failure.
        """
        self._consecutive_failures = 0

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="simorgh-autonomy"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def actions_today(self) -> int:
        cutoff = time.time() - 86400.0
        return sum(
            1
            for r in self._store.query(kind=ACTION_KIND)
            if r.created_at >= cutoff
        )

    def digest(self, window_seconds: float = 86400.0) -> ActionDigest:
        """A lightweight rollup of autonomous activity over the last
        `window_seconds` -- how many actions, how many succeeded/failed
        (per the same `succeeded` signal the circuit breaker uses), and
        how many carried no success/failure signal at all.
        """
        cutoff = time.time() - window_seconds
        records = [
            r
            for r in self._store.query(kind=ACTION_KIND)
            if r.created_at >= cutoff
        ]
        succeeded = sum(1 for r in records if r.metadata.get("succeeded") is True)
        failed = sum(1 for r in records if r.metadata.get("succeeded") is False)
        return ActionDigest(
            total=len(records),
            succeeded=succeeded,
            failed=failed,
            unknown=len(records) - succeeded - failed,
            window_seconds=window_seconds,
        )

    def idle_seconds(self) -> float:
        return self._clock.idle_seconds()

    def ready_to_act(self) -> bool:
        """Whether every gate (enabled, idle long enough, past cooldown,
        under the daily cap) currently allows an action.
        """
        if not self.enabled:
            return False
        if self._clock.idle_seconds() < self.idle_threshold_seconds:
            return False
        if time.time() - self._last_action_at < self.action_cooldown_seconds:
            return False
        if self.actions_today() >= self.max_actions_per_day:
            return False
        return True

    def tick(self) -> bool:
        """One synchronous check-and-maybe-act cycle -- what the
        background loop calls repeatedly, but also directly callable
        (and unit-testable) without any real waiting or threading.
        Returns True only if `perform_action` actually ran and reported
        real work done.
        """
        if not self.ready_to_act():
            return False

        # Autonomous curiosity drive during idle cycles: scan episodic memory
        # to uncover gaps or contradictions and formulate research tasks
        if self.curiosity_drive is not None:
            try:
                self.curiosity_drive.explore()
            except Exception as exc:  # noqa: BLE001
                print(style(f"🔍 [curiosity] exploration error: {exc!r}", "dim"))

        try:
            did_something = self._perform_action()
        except Exception as exc:  # noqa: BLE001
            print(
                style(
                    f"🤖 [autonomous] action raised {exc!r} -- will try again later",
                    "red",
                    "bold",
                )
            )
            return False

        if did_something:
            self._last_action_at = time.time()
            succeeded = None
            if self._last_action_succeeded is not None:
                try:
                    succeeded = self._last_action_succeeded()
                except Exception:  # noqa: BLE001
                    succeeded = None
            self._store.remember(
                ACTION_KIND, "autonomous action taken", succeeded=succeeded
            )
            if succeeded is False:
                self._consecutive_failures += 1
                if self._consecutive_failures >= self.max_consecutive_failures:
                    self.enabled = False
                    print(
                        style(
                            f"🚨 [autonomous] paused itself after {self._consecutive_failures} "
                            "consecutive failed actions -- this looks systematic, not "
                            "incidental. Review recent activity ('log'), then 'autonomous on' "
                            "to resume once the underlying issue is understood.",
                            "red",
                            "bold",
                        )
                    )
            elif succeeded is True:
                self._consecutive_failures = 0
        return did_something

    def _loop(self) -> None:
        while not self._stop.wait(self.poll_interval_seconds):
            self.tick()