"""`system.*` -- kernel lifecycle, ticks, pause/stop/resume, schedules,
health, metrics, status (docs/blueprint/03 section 4.1)."""

from __future__ import annotations

from ..fields import Any_, Bool, Enum, F, Float, Int, List, O, Obj, Str
from ..registry import define
from .. import topics as t

SystemStarted = define(t.SYSTEM_STARTED, [
    F("mode", Enum("single", "local-multi", "aws")),
    F("subsystems", List(Str)),  # "name@version"
    F("data_dir", Str),
])
SystemStateChanged = define(t.SYSTEM_STATE_CHANGED, [
    F("state", Enum("running", "paused", "stopping", "stopped")),
    O("reason", Str),
])
_CONTROL = [
    F("reason", Str),
    F("requested_by", Str),
    O("scope", Enum("all", "autonomous")),
]
SystemPause = define(t.SYSTEM_PAUSE, _CONTROL, doc="Priority 9. scope=autonomous pauses only self-initiated work.")
SystemResume = define(t.SYSTEM_RESUME, _CONTROL, doc="Priority 9.")
SystemStop = define(t.SYSTEM_STOP, _CONTROL, doc="Priority 9. Drain, then stop.")
SystemRestart = define(t.SYSTEM_RESTART, [
    F("reason", Str),
    F("self_check_passed", Bool),
    O("commit", Str),
])
SystemReload = define(t.SYSTEM_RELOAD, [
    F("subsystem", Str),
    F("trial", Bool),
])
_SCHEDULE = [
    F("schedule_id", Str),
    O("at", Float),
    O("every_seconds", Float),
    F("label", Str),
    O("payload", Obj()),
]
SystemScheduleAdd = define(t.SYSTEM_SCHEDULE_ADD, _SCHEDULE, doc="Exactly one of `at` / `every_seconds` (validated by the Kernel).")
SystemScheduleAdded = define(t.SYSTEM_SCHEDULE_ADDED, _SCHEDULE)
SystemScheduleCancel = define(t.SYSTEM_SCHEDULE_CANCEL, [F("schedule_id", Str)])
SystemTickSecond = define(t.SYSTEM_TICK_SECOND, [F("n", Int)])
SystemTickIdle = define(t.SYSTEM_TICK_IDLE, [F("idle_seconds", Float)])
SystemTickSleep = define(t.SYSTEM_TICK_SLEEP, [F("window_seconds", Float)])
SystemHealth = define(t.SYSTEM_HEALTH, [
    F("subsystem", Str),
    F("status", Enum("ok", "degraded", "down")),
    O("detail", Str),
])
SystemMetrics = define(t.SYSTEM_METRICS, [
    F("subsystem", Str),
    F("counters", Obj(additional=Int)),
    F("gauges", Obj(additional=Any_)),
])
SystemStatusRequest = define(t.SYSTEM_STATUS_REQUEST, [])
SystemStatusReply = define(t.SYSTEM_STATUS_REPLY, [
    F("state", Enum("running", "paused", "stopping", "stopped")),
    F("mode", Str),
    F("run_id", Str),
    F("subsystems", List(Obj(F("name", Str), F("version", Str), F("status", Str)))),
    F("uptime_seconds", Float),
    O("metrics", Obj()),
], doc="The snapshot; open to extra facets (additionalProperties true).")
