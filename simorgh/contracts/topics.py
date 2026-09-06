"""The topic catalog: every domain, every message type (as a constant),
subscription-pattern matching, reply naming, and the reserved-topology
table the Kernel enforces. Prose form: docs/blueprint/03-contracts-and-
messaging.md sections 3-4.

`type` doubles as the topic. A message's domain is its first segment.
`CATALOG` is the authoritative list of v1 types; `messages/` must define
exactly this set (tests/simorgh/contracts/test_catalog.py proves it).
"""

from __future__ import annotations

# --- domains (section 3) ---------------------------------------------------
# `turn` and `project` are listed under task.* / plan.* in the prose
# catalog but are their own first segment on the wire, so they are
# domains here; owners: orchestration and planning respectively.
DOMAINS: tuple[str, ...] = (
    "system", "percept", "intent", "plan", "project", "task", "turn", "action",
    "guardian", "tool", "verify", "memory", "world", "self", "learn", "reflect",
    "curiosity", "persona", "ui", "cognition", "research",
)

SUBSYSTEMS: tuple[str, ...] = (
    "bus", "ledger", "kernel", "cognition", "memory", "worldmodel", "planning",
    "execution", "guardian", "verification", "learning", "reflection", "curiosity",
    "persona", "interface", "orchestration",
)

# --- section 4.1 system ---------------------------------------------------
SYSTEM_STARTED = "system.started"
SYSTEM_STATE_CHANGED = "system.state.changed"
SYSTEM_PAUSE = "system.pause"
SYSTEM_RESUME = "system.resume"
SYSTEM_STOP = "system.stop"
SYSTEM_RESTART = "system.restart"
SYSTEM_RELOAD = "system.reload"
SYSTEM_SCHEDULE_ADD = "system.schedule.add"
SYSTEM_SCHEDULE_ADDED = "system.schedule.added"
SYSTEM_SCHEDULE_CANCEL = "system.schedule.cancel"
SYSTEM_TICK_SECOND = "system.tick.second"
SYSTEM_TICK_IDLE = "system.tick.idle"
SYSTEM_TICK_SLEEP = "system.tick.sleep"
SYSTEM_HEALTH = "system.health"
SYSTEM_METRICS = "system.metrics"
SYSTEM_STATUS_REQUEST = "system.status.request"
SYSTEM_STATUS_REPLY = "system.status.reply"
# --- 4.2 percept ----------------------------------------------------------
PERCEPT_TEXT_RECEIVED = "percept.text.received"
PERCEPT_FILE_CHANGED = "percept.file.changed"
PERCEPT_WEB_FETCHED = "percept.web.fetched"
PERCEPT_TIME_SCHEDULED = "percept.time.scheduled"
# --- 4.3 intent -----------------------------------------------------------
INTENT_GOAL_STATED = "intent.goal.stated"
# --- 4.4 task / turn ------------------------------------------------------
TASK_CREATE = "task.create"
TASK_CREATE_REPLY = "task.create.reply"
TASK_CREATED = "task.created"
TASK_AVAILABLE = "task.available"
TASK_CLAIM = "task.claim"
TASK_CLAIM_REPLY = "task.claim.reply"
TASK_LIST_REQUEST = "task.list.request"
TASK_LIST_REPLY = "task.list.reply"
TASK_WORK_NEXT_REQUEST = "task.work_next.request"
TASK_WORK_NEXT_REPLY = "task.work_next.reply"
TASK_STARTED = "task.started"
TASK_STEP = "task.step"
TASK_PAUSED = "task.paused"
TASK_COMPLETED = "task.completed"
TURN_COMPLETED = "turn.completed"
TASK_FAILED = "task.failed"
TASK_BLOCKED = "task.blocked"
TASK_DEPENDENCY_SATISFIED = "task.dependency.satisfied"
# --- 4.5 plan / project ---------------------------------------------------
PLAN_PROPOSED = "plan.proposed"
PLAN_REVIEWED = "plan.reviewed"
PLAN_APPROVED = "plan.approved"
PLAN_REVISED = "plan.revised"
PLAN_REGROUND = "plan.reground"
PLAN_REGROUND_REPLY = "plan.reground.reply"
PROJECT_COMPLETED = "project.completed"
PROJECT_FAILED = "project.failed"
# --- 4.6 action -----------------------------------------------------------
ACTION_PROPOSED = "action.proposed"
ACTION_APPROVED = "action.approved"
ACTION_DENIED = "action.denied"
ACTION_NEEDS_HUMAN = "action.needs_human"
ACTION_RESULT = "action.result"
# --- 4.7 tool -------------------------------------------------------------
TOOL_REGISTERED = "tool.registered"
TOOL_UNAVAILABLE = "tool.unavailable"
TOOL_INVOKED = "tool.invoked"
# --- 4.8 verify -----------------------------------------------------------
VERIFY_REQUESTED = "verify.requested"
VERIFY_RESULT = "verify.result"
# --- 4.9 memory -----------------------------------------------------------
MEMORY_RETRIEVE = "memory.retrieve"
MEMORY_RETRIEVE_REPLY = "memory.retrieve.reply"
MEMORY_STORE = "memory.store"
MEMORY_STORED = "memory.stored"
MEMORY_CONTRADICTION_FLAGGED = "memory.contradiction.flagged"
MEMORY_CONSOLIDATED = "memory.consolidated"
MEMORY_FORGOTTEN = "memory.forgotten"
# --- 4.10 world / self ----------------------------------------------------
WORLD_ENV_QUERY = "world.env.query"
WORLD_ENV_QUERY_REPLY = "world.env.query.reply"
WORLD_ENV_OBSERVED = "world.env.observed"
SELF_SUMMARY = "self.summary"
SELF_SUMMARY_REPLY = "self.summary.reply"
SELF_GAPS = "self.gaps"
SELF_GAPS_REPLY = "self.gaps.reply"
SELF_MODEL_UPDATED = "self.model.updated"
SELF_OBSERVATION = "self.observation"
# --- 4.11 learn -----------------------------------------------------------
LEARN_PIPELINE_RUN = "learn.pipeline.run"
LEARN_PIPELINE_COMPLETED = "learn.pipeline.completed"
LEARN_STRATEGY_SUGGEST = "learn.strategy.suggest"
LEARN_STRATEGY_SUGGEST_REPLY = "learn.strategy.suggest.reply"
LEARN_OUTCOME_RECORDED = "learn.outcome.recorded"
LEARN_COMPETENCE_UPDATED = "learn.competence.updated"
LEARN_SKILL_ACQUIRED = "learn.skill.acquired"
LEARN_SELF_PATCH_APPLIED = "learn.self_patch.applied"
LEARN_SELF_PATCH_REVERTED = "learn.self_patch.reverted"
LEARN_EXPERIMENT_RESULT = "learn.experiment.result"
# --- 4.12 reflect ---------------------------------------------------------
REFLECT_PATTERNS_FOUND = "reflect.patterns.found"
REFLECT_DRIFT_DETECTED = "reflect.drift.detected"
REFLECT_CALIBRATION_UPDATED = "reflect.calibration.updated"
REFLECT_HEALTH_FINDING = "reflect.health.finding"
REFLECT_REVIEW_REQUEST = "reflect.review.request"
REFLECT_REVIEW_REPLY = "reflect.review.reply"
# --- 4.13 curiosity -------------------------------------------------------
CURIOSITY_CANDIDATE = "curiosity.candidate"
CURIOSITY_INTEREST_UPDATED = "curiosity.interest.updated"
CURIOSITY_SHARE_PROPOSED = "curiosity.share.proposed"
CURIOSITY_DISCOVER_REQUEST = "curiosity.discover.request"
CURIOSITY_DISCOVER_REPLY = "curiosity.discover.reply"
CURIOSITY_SHARE_REQUEST = "curiosity.share.request"
CURIOSITY_SHARE_REPLY = "curiosity.share.reply"
CURIOSITY_INTEREST_ADD = "curiosity.interest.add"
CURIOSITY_INTEREST_LIST_REQUEST = "curiosity.interest.list.request"
CURIOSITY_INTEREST_LIST_REPLY = "curiosity.interest.list.reply"
CURIOSITY_INTEREST_FOLLOW_UP_REQUEST = "curiosity.interest.follow_up.request"
CURIOSITY_INTEREST_FOLLOW_UP_REPLY = "curiosity.interest.follow_up.reply"
# --- 4.14 persona ---------------------------------------------------------
PERSONA_STATE_CHANGED = "persona.state.changed"
PERSONA_VOICE = "persona.voice"
PERSONA_VOICE_REPLY = "persona.voice.reply"
PERSONA_USER_MODEL_UPDATED = "persona.user_model.updated"
# --- 4.15 ui / cognition / guardian / research ----------------------------
UI_NOTICE = "ui.notice"
UI_PROMPT = "ui.prompt"
UI_PROMPT_ANSWERED = "ui.prompt.answered"
UI_RENDERED = "ui.rendered"
COGNITION_THINK = "cognition.think"
COGNITION_THINK_REPLY = "cognition.think.reply"
COGNITION_COMPACT_REQUEST = "cognition.compact.request"
COGNITION_COMPACT_REPLY = "cognition.compact.reply"
COGNITION_COMPACT_PRE = "cognition.compact.pre"
COGNITION_COMPACT_DONE = "cognition.compact.done"
COGNITION_PROVIDER_STATUS = "cognition.provider.status"
GUARDIAN_REVIEW = "guardian.review"
GUARDIAN_REVIEW_REPLY = "guardian.review.reply"
GUARDIAN_POSTURE_CHANGED = "guardian.posture.changed"
GUARDIAN_POSTURE_REQUEST = "guardian.posture.request"
GUARDIAN_POSTURE_REPLY = "guardian.posture.reply"
RESEARCH_FINDING_RECORDED = "research.finding.recorded"

CATALOG: tuple[str, ...] = tuple(
    value for name, value in sorted(globals().items())
    if name.isupper() and isinstance(value, str) and "." in value
    and name not in {"DOMAINS", "SUBSYSTEMS"}
)

# --- reserved topology (section 3), data the Kernel enforces --------------
# Only these subsystem names may *subscribe* to the type.
SUBSCRIBE_ONLY_BY: dict[str, frozenset[str]] = {
    ACTION_PROPOSED: frozenset({"guardian"}),
    ACTION_APPROVED: frozenset({"execution"}),
}
# Only these subsystem names may *publish* the type.
PUBLISH_ONLY_BY: dict[str, frozenset[str]] = {
    ACTION_APPROVED: frozenset({"guardian", "kernel"}),
    ACTION_DENIED: frozenset({"guardian", "execution"}),
    SYSTEM_PAUSE: frozenset({"interface", "kernel"}),
    SYSTEM_STOP: frozenset({"interface", "kernel"}),
    SYSTEM_RESUME: frozenset({"interface", "kernel"}),
    SYSTEM_RESTART: frozenset({"interface", "kernel", "execution"}),
    SYSTEM_RELOAD: frozenset({"interface", "kernel", "execution"}),
    SELF_MODEL_UPDATED: frozenset({"worldmodel"}),
    PLAN_PROPOSED: frozenset({"planning"}),
}
# A publisher allowed only for a restricted payload: (type, publisher) -> {field: allowed values}.
PUBLISH_PAYLOAD_CONSTRAINTS: dict[tuple[str, str], dict[str, frozenset[str]]] = {
    (ACTION_DENIED, "execution"): {"layer": frozenset({"token"})},
}
PREEMPT_PRIORITY = 9
PREEMPTING_TYPES: frozenset[str] = frozenset({SYSTEM_PAUSE, SYSTEM_STOP, SYSTEM_RESUME})
WILDCARD_ALL = "#"


def domain_of(type_name: str) -> str:
    return type_name.split(".", 1)[0]


def is_reply(type_name: str) -> bool:
    return type_name.endswith(".reply")


def reply_type_for(type_name: str) -> str:
    """`task.claim` -> `task.claim.reply`; `x.request` -> `x.reply`."""
    if is_reply(type_name):
        return type_name
    if type_name.endswith(".request"):
        return type_name[: -len(".request")] + ".reply"
    return type_name + ".reply"


def source_name(source: str) -> str:
    """`orchestration@w3` -> `orchestration` (the subsystem identity)."""
    return source.split("@", 1)[0]


def matches(pattern: str, type_name: str) -> bool:
    """Subscription patterns: `*` matches exactly one dot-separated
    segment, `#` matches the rest (zero or more segments). `#` alone is
    everything."""
    if pattern == WILDCARD_ALL:
        return True
    p_parts = pattern.split(".")
    t_parts = type_name.split(".")
    i = 0
    for i, part in enumerate(p_parts):
        if part == "#":
            return True
        if i >= len(t_parts):
            return False
        if part != "*" and part != t_parts[i]:
            return False
    return len(t_parts) == len(p_parts)


def may_subscribe(subsystem: str, type_name: str) -> bool:
    allowed = SUBSCRIBE_ONLY_BY.get(type_name)
    return allowed is None or source_name(subsystem) in allowed


def may_publish(subsystem: str, type_name: str, payload: dict | None = None) -> bool:
    name = source_name(subsystem)
    allowed = PUBLISH_ONLY_BY.get(type_name)
    if allowed is not None and name not in allowed:
        return False
    constraint = PUBLISH_PAYLOAD_CONSTRAINTS.get((type_name, name))
    if constraint and payload is not None:
        return all(payload.get(field) in values for field, values in constraint.items())
    return True
