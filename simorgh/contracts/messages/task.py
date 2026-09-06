"""`task.*` and `turn.*` -- task lifecycle (section 4.4). Payload
shapes are expanded in docs/blueprint/subsystems/07-planning.md."""

from __future__ import annotations

from ..fields import Bool, Enum, F, Float, Int, List, Nullable, O, Obj, Str
from ..registry import define
from .. import topics as t

TASK_KIND = Enum("chat", "patch", "skill", "research", "project")
TASK_MODE = Enum("plan", "execute")
TASK_ORIGIN = Enum("human", "curiosity", "reflection", "research", "project")
TASK_RISK = Enum("low", "medium", "high")
SCOPE = Obj(F("paths", List(Str)), F("network", Bool))

TaskCreate = define(t.TASK_CREATE, [
    F("kind", TASK_KIND),
    F("description", Str),
    F("origin", TASK_ORIGIN),
    O("subject", Str),
    O("parent_id", Str),
    O("depends_on", List(Str)),
    O("mode", TASK_MODE),
    O("risk", TASK_RISK),
    O("scope", SCOPE),
], doc="Request form used by Interface commands and sub-agent delegation; Planning dedupes and emits task.created.")
TaskCreateReply = define(t.TASK_CREATE_REPLY, [
    F("task_id", Str),
    O("deduplicated_against", Str),
])
TaskCreated = define(t.TASK_CREATED, [
    F("task_id", Str),
    F("kind", TASK_KIND),
    F("description", Str),
    F("depends_on", List(Str)),
    F("mode", TASK_MODE),
    F("origin", TASK_ORIGIN),
    F("risk", TASK_RISK),
    O("subject", Str),
    O("parent_id", Str),
    O("scope", SCOPE),
])
TaskAvailable = define(t.TASK_AVAILABLE, [
    F("task_id", Str),
    F("kind", TASK_KIND),
    F("lease_seconds", Float),
], doc="Command; consumer group `workers`.")
TaskClaim = define(t.TASK_CLAIM, [F("task_id", Str), F("worker_id", Str)])
TaskClaimReply = define(t.TASK_CLAIM_REPLY, [
    F("granted", Bool),
    O("lease_until", Float),
    O("task", Obj()),
])
TaskListRequest = define(t.TASK_LIST_REQUEST, [
    O("filter", Obj(O("status", Str), O("kind", TASK_KIND), O("parent_id", Str))),
])
TaskListReply = define(t.TASK_LIST_REPLY, [
    F("tasks", List(Obj())),
    F("projects", List(Obj(
        F("project_id", Str), F("rollup", Str), F("done", Int), F("total", Int), F("stalled", Bool),
    ))),
])
TaskWorkNextRequest = define(t.TASK_WORK_NEXT_REQUEST, [])
TaskWorkNextReply = define(t.TASK_WORK_NEXT_REPLY, [O("task_id", Str), O("reason", Str)])
TaskStarted = define(t.TASK_STARTED, [F("task_id", Str), F("worker_id", Str)])
TaskStep = define(t.TASK_STEP, [
    F("task_id", Str),
    F("step_no", Int),
    F("phase", Enum("gather", "act", "verify")),
    F("summary", Str),
    O("tool", Str),
    O("action_id", Str),
    O("ok", Bool),
    O("confidence", Float),
    O("cost_usd", Float),
    O("tokens", Int),
], doc="The trajectory Verification and Reflection read.")
TaskPaused = define(t.TASK_PAUSED, [
    F("task_id", Str),
    F("reason", Str),
    F("resume_from_step", Int),
])
TaskCompleted = define(t.TASK_COMPLETED, [
    F("task_id", Str),
    F("result_summary", Str),
    F("artifacts", List(Str)),
    F("verification_ref", Nullable(Str)),  # required key; null when no review ran (plan-mode)
    O("confidence", Float),
])
TurnCompleted = define(t.TURN_COMPLETED, [
    F("session_id", Str),
    F("task_id", Str),
    F("text", Str),
    F("floor", Bool),
    F("tool_steps", Int),
    O("verification_ref", Str),
    O("confidence", Float),
    O("user_text", Str),
], doc="The chat-turn counterpart of task.completed (Flow 1). "
       "`user_text` is the human's own message for this turn -- optional "
       "so older producers/consumers built against v1 of this catalog "
       "entry still validate; Memory's episodic write (milestone 104) is "
       "the one consumer that actually needs it.")
TaskFailed = define(t.TASK_FAILED, [
    F("task_id", Str),
    F("reason", Str),
    F("terminal", Bool),
    F("attempts", Int),
])
TaskBlocked = define(t.TASK_BLOCKED, [
    F("task_id", Str),
    F("reason", Str),
    O("retry_after", Float),
])
TaskDependencySatisfied = define(t.TASK_DEPENDENCY_SATISFIED, [
    F("task_id", Str),
    F("satisfied_by", Str),
])
