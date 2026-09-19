# kernel -- contract

One-line status: layer 0 · 4,140 lines · 20 test files · lock: `kernel` in docs/modules/locks.toml

## Purpose

TODO: 3-6 sentences: what this module owns, what it must never do, the one design decision that shapes it.

## Files

| File | For |
|---|---|
| `simorgh/kernel/__init__.py` | TODO |
| `simorgh/kernel/api.py` | TODO |
| `simorgh/kernel/bootprogress.py` | TODO |
| `simorgh/kernel/cli.py` | TODO |
| `simorgh/kernel/config.py` | TODO |
| `simorgh/kernel/configcheck.py` | TODO |
| `simorgh/kernel/context.py` | TODO |
| `simorgh/kernel/metrics.py` | TODO |
| `simorgh/kernel/migrate_v1.py` | TODO |
| `simorgh/kernel/registry.py` | TODO |
| `simorgh/kernel/scheduler.py` | TODO |
| `simorgh/kernel/secrets.py` | TODO |
| `simorgh/kernel/selfcheck.py` | TODO |
| `simorgh/kernel/service.py` | TODO |
| `simorgh/kernel/state.py` | TODO |
| `simorgh/kernel/supervisor.py` | TODO |
| `simorgh/kernel/vault.py` | TODO |

## Consumes

| Topic | Schema | Where | Does |
|---|---|---|---|
| `action.approved` | `messages/action.py::ActionApproved` | simorgh/kernel/selfcheck.py | TODO |
| `action.denied` | `messages/action.py::ActionDenied` | simorgh/kernel/selfcheck.py | TODO |
| `action.proposed` | `messages/action.py::ActionProposed` | simorgh/kernel/selfcheck.py | TODO |
| `percept.text.received` | `messages/percept.py::PerceptTextReceived` | simorgh/kernel/scheduler.py, simorgh/kernel/service.py | TODO |
| `system.health` | `messages/system.py::SystemHealth` | simorgh/kernel/metrics.py, simorgh/kernel/service.py | TODO |
| `system.metrics` | `messages/system.py::SystemMetrics` | simorgh/kernel/metrics.py, simorgh/kernel/service.py | TODO |
| `system.pause` | `messages/system.py::SystemPause` | simorgh/kernel/selfcheck.py, simorgh/kernel/service.py | TODO |
| `system.restart` | `messages/system.py::SystemRestart` | simorgh/kernel/service.py | TODO |
| `system.resume` | `messages/system.py::SystemResume` | simorgh/kernel/selfcheck.py, simorgh/kernel/service.py | TODO |
| `system.schedule.add` | `messages/system.py::SystemScheduleAdd` | simorgh/kernel/scheduler.py, simorgh/kernel/service.py | TODO |
| `system.schedule.cancel` | `messages/system.py::SystemScheduleCancel` | simorgh/kernel/scheduler.py, simorgh/kernel/service.py | TODO |
| `system.state.changed` | `messages/system.py::SystemStateChanged` | simorgh/kernel/service.py | TODO |
| `system.status.reply` | `messages/system.py::SystemStatusReply` | simorgh/kernel/metrics.py | TODO |
| `system.status.request` | `messages/system.py::SystemStatusRequest` | simorgh/kernel/metrics.py, simorgh/kernel/service.py | TODO |
| `system.stop` | `messages/system.py::SystemStop` | simorgh/kernel/service.py | TODO |

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `action.approved` | `messages/action.py::ActionApproved` | simorgh/kernel/selfcheck.py | TODO |
| `action.denied` | `messages/action.py::ActionDenied` | simorgh/kernel/selfcheck.py | TODO |
| `action.proposed` | `messages/action.py::ActionProposed` | simorgh/kernel/selfcheck.py | TODO |
| `action.result` | `messages/action.py::ActionResult` | simorgh/kernel/selfcheck.py | TODO |
| `percept.time.scheduled` | `messages/percept.py::PerceptTimeScheduled` | simorgh/kernel/scheduler.py, simorgh/kernel/service.py | TODO |
| `system.health` | `messages/system.py::SystemHealth` | simorgh/kernel/service.py | TODO |
| `system.metrics` | `messages/system.py::SystemMetrics` | simorgh/kernel/metrics.py, simorgh/kernel/service.py | TODO |
| `system.pause` | `messages/system.py::SystemPause` | simorgh/kernel/selfcheck.py | TODO |
| `system.resume` | `messages/system.py::SystemResume` | simorgh/kernel/selfcheck.py | TODO |
| `system.schedule.added` | `messages/system.py::SystemScheduleAdded` | simorgh/kernel/scheduler.py, simorgh/kernel/service.py | TODO |
| `system.started` | `messages/system.py::SystemStarted` | simorgh/kernel/service.py | TODO |
| `system.state.changed` | `messages/system.py::SystemStateChanged` | simorgh/kernel/service.py | TODO |
| `system.status.reply` | `messages/system.py::SystemStatusReply` | simorgh/kernel/metrics.py, simorgh/kernel/service.py | TODO |
| `system.stop` | `messages/system.py::SystemStop` | simorgh/kernel/cli.py | TODO |
| `system.tick.idle` | `messages/system.py::SystemTickIdle` | simorgh/kernel/scheduler.py, simorgh/kernel/service.py | TODO |
| `system.tick.second` | `messages/system.py::SystemTickSecond` | simorgh/kernel/scheduler.py, simorgh/kernel/service.py | TODO |
| `system.tick.sleep` | `messages/system.py::SystemTickSleep` | simorgh/kernel/scheduler.py, simorgh/kernel/service.py | TODO |

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `bw:` | simorgh/kernel/vault.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `config:effective` | simorgh/kernel/service.py | simorgh/interface/dispatch.py | see ledger/compaction.py DEFAULT_RETENTION |
| `env:` | simorgh/kernel/vault.py | simorgh/cognition/providers/claude_code.py, simorgh/contracts/settings.py, simorgh/execution/mcp.py, simorgh/execution/security/tools.py, simorgh/execution/tools.py, simorgh/ledger/config.py | see ledger/compaction.py DEFAULT_RETENTION |
| `metrics:history` | simorgh/kernel/metrics.py | simorgh/execution/tools.py, simorgh/interface/config.py, simorgh/interface/httpapi.py, simorgh/ledger/compaction.py | see ledger/compaction.py DEFAULT_RETENTION |
| `ssm:` | simorgh/kernel/vault.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `trace:{trace_id}` | simorgh/kernel/cli.py | simorgh/bus/client.py, simorgh/bus/factory.py, simorgh/bus/service.py, simorgh/bus/trace.py, simorgh/cognition/parser.py, simorgh/ledger/backends/jsonl.py, simorgh/ledger/compaction.py, simorgh/ledger/service.py, simorgh/ledger/streams.py, simorgh/orchestration/context.py | see ledger/compaction.py DEFAULT_RETENTION |
| `v1:<id>` | simorgh/kernel/migrate_v1.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `vault:` | simorgh/kernel/vault.py | simorgh/execution/home/cameras.py, simorgh/execution/home/ring.py, simorgh/execution/home/tools.py, simorgh/execution/media/cast.py, simorgh/execution/pim/accounts.py, simorgh/execution/security/selfcheck.py | see ledger/compaction.py DEFAULT_RETENTION |
| `vault:<cred_id>:<field>` | simorgh/kernel/vault.py | simorgh/execution/home/cameras.py, simorgh/execution/home/ring.py, simorgh/execution/home/tools.py, simorgh/execution/media/cast.py, simorgh/execution/pim/accounts.py, simorgh/execution/security/selfcheck.py | see ledger/compaction.py DEFAULT_RETENTION |

## Config

`[kernel]` in simorgh.toml; dataclass in `simorgh/kernel/config.py`.

| Key | Default | Read in the package |
|---|---|---|

## Public Python surface

TODO: the `Service` class; any `api.py` types other packages import via contracts; module-level singletons (risks).

## Invariants

TODO: the rules that must hold, as testable sentences; include contracts/topics.py policy entries naming this module.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract kernel`.

- `tests/simorgh/kernel/test_bootprogress.py` -- TODO: what it pins
- `tests/simorgh/kernel/test_cli.py` -- TODO: what it pins
- `tests/simorgh/kernel/test_config.py` -- TODO: what it pins
- `tests/simorgh/kernel/test_configcheck.py` -- TODO: what it pins
- `tests/simorgh/kernel/test_context.py` -- TODO: what it pins
- `tests/simorgh/kernel/test_effective_config_record.py` -- TODO: what it pins
- `tests/simorgh/kernel/test_metrics.py` -- TODO: what it pins
- `tests/simorgh/kernel/test_migrate_v1.py` -- TODO: what it pins
- `tests/simorgh/kernel/test_registry.py` -- TODO: what it pins
- `tests/simorgh/kernel/test_scheduler.py` -- TODO: what it pins
- `tests/simorgh/kernel/test_secrets.py` -- TODO: what it pins
- `tests/simorgh/kernel/test_selfcheck.py` -- TODO: what it pins
- `tests/simorgh/kernel/test_service.py` -- TODO: what it pins
- `tests/simorgh/kernel/test_state.py` -- TODO: what it pins
- `tests/simorgh/kernel/test_stop_leaves.py` -- TODO: what it pins
- `tests/simorgh/kernel/test_supervisor.py` -- TODO: what it pins
- `tests/simorgh/kernel/test_supervisor_restarts.py` -- TODO: what it pins
- `tests/simorgh/kernel/test_the_suite_cannot_see_the_operators_env.py` -- TODO: what it pins
- `tests/simorgh/kernel/test_vault.py` -- TODO: what it pins
- `tests/simorgh/kernel/test_vault_cli.py` -- TODO: what it pins

## Known issues (2026-09-18 evaluation)

TODO: catalogue ids from docs/reviews/2026-09-18/architecture-evaluation.md section 13 that name this module.

## Planned changes (roadmap)

TODO: stage numbers from docs/plan/ and what changes here.

## Working on this module

Lock it first (`python tools/modlock.py claim kernel --by <you> --task "..."`), commit the lock, edit only `simorgh/kernel/`, `tests/simorgh/kernel/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py kernel` before committing; commit subject `kernel: <what changed>`.

This package is Guardian-protected: Sim's own tasks cannot edit it. A human-run agent may, with the lock, because a person is accountable for the commit.
