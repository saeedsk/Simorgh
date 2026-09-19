# interface -- contract

One-line status: layer 5 · 10,788 lines · 31 test files · lock: `interface` in docs/modules/locks.toml

## Purpose

TODO: 3-6 sentences: what this module owns, what it must never do, the one design decision that shapes it.

## Files

| File | For |
|---|---|
| `simorgh/interface/__init__.py` | TODO |
| `simorgh/interface/activity.py` | TODO |
| `simorgh/interface/api.py` | TODO |
| `simorgh/interface/benchmarkchart.py` | TODO |
| `simorgh/interface/benchmarkview.py` | TODO |
| `simorgh/interface/config.py` | TODO |
| `simorgh/interface/dashfeeds.py` | TODO |
| `simorgh/interface/dispatch.py` | TODO |
| `simorgh/interface/httpapi.py` | TODO |
| `simorgh/interface/live_status.py` | TODO |
| `simorgh/interface/panel.py` | TODO |
| `simorgh/interface/parser.py` | TODO |
| `simorgh/interface/render.py` | TODO |
| `simorgh/interface/service.py` | TODO |
| `simorgh/interface/splash_art.py` | TODO |
| `simorgh/interface/telegram.py` | TODO |
| `simorgh/interface/tui.py` | TODO |
| `simorgh/interface/vitals.py` | TODO |
| `simorgh/interface/voiceview.py` | TODO |
| `simorgh/interface/whatsapp.py` | TODO |

## Consumes

| Topic | Schema | Where | Does |
|---|---|---|---|
| `action.denied` | `messages/action.py::ActionDenied` | simorgh/interface/dispatch.py, simorgh/interface/httpapi.py, simorgh/interface/service.py | TODO |
| `action.needs_human` | `messages/action.py::ActionNeedsHuman` | simorgh/interface/service.py | TODO |
| `action.proposed` | `messages/action.py::ActionProposed` | simorgh/interface/dispatch.py | TODO |
| `action.result` | `messages/action.py::ActionResult` | simorgh/interface/dispatch.py, simorgh/interface/httpapi.py | TODO |
| `benchmark.progress` | `messages/benchmark.py::BenchmarkProgress` | simorgh/interface/service.py | TODO |
| `cognition.provider.status` | `messages/cognition.py::CognitionProviderStatus` | simorgh/interface/service.py | TODO |
| `guardian.posture.changed` | `messages/guardian.py::GuardianPostureChanged` | simorgh/interface/service.py | TODO |
| `percept.text.received` | `messages/percept.py::PerceptTextReceived` | simorgh/interface/httpapi.py | TODO |
| `percept.time.scheduled` | `messages/percept.py::PerceptTimeScheduled` | simorgh/interface/service.py | TODO |
| `persona.state.changed` | `messages/persona.py::PersonaStateChanged` | simorgh/interface/service.py | TODO |
| `system.health` | `messages/system.py::SystemHealth` | simorgh/interface/service.py | TODO |
| `system.metrics` | `messages/system.py::SystemMetrics` | simorgh/interface/service.py | TODO |
| `system.state.changed` | `messages/system.py::SystemStateChanged` | simorgh/interface/service.py | TODO |
| `task.blocked` | `messages/task.py::TaskBlocked` | simorgh/interface/httpapi.py, simorgh/interface/service.py | TODO |
| `task.cleared` | `messages/task.py::TaskCleared` | simorgh/interface/service.py | TODO |
| `task.completed` | `messages/task.py::TaskCompleted` | simorgh/interface/httpapi.py, simorgh/interface/service.py | TODO |
| `task.created` | `messages/task.py::TaskCreated` | simorgh/interface/service.py | TODO |
| `task.failed` | `messages/task.py::TaskFailed` | simorgh/interface/httpapi.py, simorgh/interface/service.py | TODO |
| `task.started` | `messages/task.py::TaskStarted` | simorgh/interface/httpapi.py, simorgh/interface/service.py | TODO |
| `task.step` | `messages/task.py::TaskStep` | simorgh/interface/httpapi.py, simorgh/interface/service.py | TODO |
| `turn.completed` | `messages/task.py::TurnCompleted` | simorgh/interface/httpapi.py, simorgh/interface/service.py, simorgh/interface/telegram.py, simorgh/interface/whatsapp.py | TODO |
| `ui.command.request` | `messages/ui.py::UiCommandRequest` | simorgh/interface/service.py | TODO |
| `ui.dash.key` | `messages/ui.py::UiDashKey` | simorgh/interface/httpapi.py | TODO |
| `ui.dash.state` | `messages/ui.py::DashState` | simorgh/interface/httpapi.py | TODO |
| `ui.notice` | `messages/ui.py::UiNotice` | simorgh/interface/service.py | TODO |
| `ui.prompt` | `messages/ui.py::UiPrompt` | simorgh/interface/service.py | TODO |
| `ui.tv.speech` | `messages/ui.py::TvSpeech` | simorgh/interface/httpapi.py | TODO |
| `ui.tv.state` | `messages/ui.py::TvState` | simorgh/interface/httpapi.py | TODO |
| `voice.listening` | `messages/voice.py::VoiceListening` | simorgh/interface/service.py | TODO |
| `voice.spoken` | `messages/voice.py::VoiceSpoken` | simorgh/interface/service.py | TODO |
| `voice.transcript` | `messages/voice.py::VoiceTranscript` | simorgh/interface/service.py | TODO |

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `action.proposed` | `messages/action.py::ActionProposed` | simorgh/interface/dispatch.py | TODO |
| `benchmark.history.request` | `messages/benchmark.py::BenchmarkHistoryRequest` | simorgh/interface/dispatch.py, simorgh/interface/httpapi.py, simorgh/interface/service.py | TODO |
| `benchmark.load.request` | `messages/benchmark.py::BenchmarkLoadRequest` | simorgh/interface/dispatch.py, simorgh/interface/service.py | TODO |
| `benchmark.progress` | `messages/benchmark.py::BenchmarkProgress` | simorgh/interface/service.py | TODO |
| `benchmark.run.request` | `messages/benchmark.py::BenchmarkRunRequest` | simorgh/interface/dispatch.py, simorgh/interface/service.py | TODO |
| `benchmark.stop.request` | `messages/benchmark.py::BenchmarkStopRequest` | simorgh/interface/dispatch.py, simorgh/interface/service.py | TODO |
| `benchmark.suites.request` | `messages/benchmark.py::BenchmarkSuitesRequest` | simorgh/interface/dispatch.py, simorgh/interface/service.py | TODO |
| `curiosity.interest.add` | `messages/curiosity.py::CuriosityInterestAdd` | simorgh/interface/dispatch.py | TODO |
| `curiosity.interest.list.request` | `messages/curiosity.py::CuriosityInterestListRequest` | simorgh/interface/dispatch.py | TODO |
| `guardian.posture.request` | `messages/guardian.py::GuardianPostureRequest` | simorgh/interface/service.py | TODO |
| `intent.goal.stated` | `messages/intent.py::IntentGoalStated` | simorgh/interface/service.py | TODO |
| `percept.text.received` | `messages/percept.py::PerceptTextReceived` | simorgh/interface/httpapi.py, simorgh/interface/service.py, simorgh/interface/telegram.py, simorgh/interface/whatsapp.py | TODO |
| `percept.time.scheduled` | `messages/percept.py::PerceptTimeScheduled` | simorgh/interface/service.py | TODO |
| `system.health` | `messages/system.py::SystemHealth` | simorgh/interface/service.py | TODO |
| `system.pause` | `messages/system.py::SystemPause` | simorgh/interface/dispatch.py, simorgh/interface/service.py | TODO |
| `system.restart` | `messages/system.py::SystemRestart` | simorgh/interface/dispatch.py, simorgh/interface/service.py | TODO |
| `system.resume` | `messages/system.py::SystemResume` | simorgh/interface/dispatch.py, simorgh/interface/service.py | TODO |
| `system.schedule.add` | `messages/system.py::SystemScheduleAdd` | simorgh/interface/dispatch.py | TODO |
| `system.schedule.cancel` | `messages/system.py::SystemScheduleCancel` | simorgh/interface/dispatch.py | TODO |
| `system.status.request` | `messages/system.py::SystemStatusRequest` | simorgh/interface/dispatch.py, simorgh/interface/httpapi.py | TODO |
| `system.stop` | `messages/system.py::SystemStop` | simorgh/interface/dispatch.py, simorgh/interface/service.py | TODO |
| `system.tick.idle` | `messages/system.py::SystemTickIdle` | simorgh/interface/dispatch.py | TODO |
| `task.cancel` | `messages/task.py::TaskCancel` | simorgh/interface/dispatch.py | TODO |
| `task.clear.request` | `messages/task.py::TaskClearRequest` | simorgh/interface/dispatch.py | TODO |
| `task.create` | `messages/task.py::TaskCreate` | simorgh/interface/dispatch.py | TODO |
| `task.list.request` | `messages/task.py::TaskListRequest` | simorgh/interface/dispatch.py, simorgh/interface/service.py | TODO |
| `task.work_next.request` | `messages/task.py::TaskWorkNextRequest` | simorgh/interface/dispatch.py | TODO |
| `ui.command.reply` | `messages/ui.py::UiCommandReply` | simorgh/interface/service.py | TODO |
| `ui.dash.state` | `messages/ui.py::DashState` | simorgh/interface/httpapi.py | TODO |
| `ui.hook.received` | `messages/ui.py::UiHookReceived` | simorgh/interface/httpapi.py | TODO |
| `ui.prompt.answered` | `messages/ui.py::UiPromptAnswered` | simorgh/interface/service.py | TODO |
| `voice.bench.request` | `messages/voice.py::VoiceBenchRequest` | simorgh/interface/dispatch.py | TODO |
| `voice.control.request` | `messages/voice.py::VoiceControlRequest` | simorgh/interface/dispatch.py | TODO |
| `voice.devices.request` | `messages/voice.py::VoiceDevicesRequest` | simorgh/interface/dispatch.py | TODO |
| `voice.listen.request` | `messages/voice.py::VoiceListenRequest` | simorgh/interface/dispatch.py | TODO |
| `voice.models.request` | `messages/voice.py::VoiceModelsRequest` | simorgh/interface/dispatch.py | TODO |
| `voice.speak.request` | `messages/voice.py::VoiceSpeakRequest` | simorgh/interface/dispatch.py | TODO |
| `voice.status.request` | `messages/voice.py::VoiceStatusRequest` | simorgh/interface/dispatch.py | TODO |
| `voice.voices.request` | `messages/voice.py::VoiceVoicesRequest` | simorgh/interface/dispatch.py | TODO |
| `world.env.query` | `messages/world.py::WorldEnvQuery` | simorgh/interface/dispatch.py | TODO |

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `budget:` | simorgh/interface/render.py | simorgh/cognition/budget.py, simorgh/cognition/router.py, simorgh/execution/config.py, simorgh/execution/pim/connectors/caldav.py, simorgh/execution/pim/connectors/imap.py, simorgh/guardian/service.py, simorgh/ledger/compaction.py, simorgh/orchestration/api.py | see ledger/compaction.py DEFAULT_RETENTION |
| `caldav:` | simorgh/interface/dispatch.py | simorgh/execution/domainstatus.py, simorgh/execution/pim/connectors/caldav.py, simorgh/execution/pim/connectors/fakes.py, simorgh/kernel/cli.py, simorgh/kernel/secrets.py | see ledger/compaction.py DEFAULT_RETENTION |
| `class:exiting` | simorgh/interface/tui.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `class:sim.breath.{shade}` | simorgh/interface/panel.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `class:sim.command` | simorgh/interface/tui.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `class:sim.flag` | simorgh/interface/tui.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `class:sim.footer` | simorgh/interface/panel.py, simorgh/interface/tui.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `class:sim.live` | simorgh/interface/panel.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `class:sim.path` | simorgh/interface/tui.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `class:sim.prompt` | simorgh/interface/tui.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `class:sim.rule` | simorgh/interface/tui.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `class:sim.status` | simorgh/interface/panel.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `class:sim.string` | simorgh/interface/tui.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `cli:{session_id}` | simorgh/interface/dispatch.py | simorgh/voice/config.py, simorgh/voice/stt/whisper_cli.py | see ledger/compaction.py DEFAULT_RETENTION |
| `config:effective` | simorgh/interface/dispatch.py | simorgh/kernel/service.py | see ledger/compaction.py DEFAULT_RETENTION |
| `connector:` | simorgh/interface/dispatch.py | simorgh/contracts/connector.py, simorgh/execution/capabilities.py, simorgh/voice/planner.py, simorgh/voice/session.py | see ledger/compaction.py DEFAULT_RETENTION |
| `execution:tools` | simorgh/interface/dispatch.py | simorgh/execution/service.py, simorgh/ledger/compaction.py, simorgh/orchestration/service.py | see ledger/compaction.py DEFAULT_RETENTION |
| `hearing:` | simorgh/interface/service.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `im:image` | simorgh/interface/dashfeeds.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `im:name` | simorgh/interface/dashfeeds.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `imap:` | simorgh/interface/dispatch.py | simorgh/execution/domainstatus.py, simorgh/execution/pim/api.py, simorgh/execution/pim/connectors/imap.py, simorgh/kernel/cli.py, simorgh/kernel/registry.py, simorgh/kernel/secrets.py | see ledger/compaction.py DEFAULT_RETENTION |
| `interface:{session_id}` | simorgh/interface/dispatch.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `mcp:proposals` | simorgh/interface/dispatch.py | simorgh/execution/tools.py | see ledger/compaction.py DEFAULT_RETENTION |
| `metrics:history` | simorgh/interface/config.py, simorgh/interface/httpapi.py | simorgh/execution/tools.py, simorgh/kernel/metrics.py, simorgh/ledger/compaction.py | see ledger/compaction.py DEFAULT_RETENTION |
| `reflection:alerts` | simorgh/interface/dispatch.py | simorgh/reflection/service.py | see ledger/compaction.py DEFAULT_RETENTION |
| `skills:installs` | simorgh/interface/dispatch.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `task:{client_session_id}` | simorgh/interface/httpapi.py | simorgh/benchmark/runner.py, simorgh/benchmark/service.py, simorgh/bus/backends/aws.py, simorgh/bus/backends/memory.py, simorgh/bus/trace.py, simorgh/contracts/toolargs.py, simorgh/execution/home/ring.py, simorgh/execution/service.py, simorgh/execution/tools.py, simorgh/execution/worktree.py, simorgh/kernel/api.py, simorgh/kernel/metrics.py, simorgh/kernel/supervisor.py, simorgh/learning/outcomes.py, simorgh/ledger/client.py, simorgh/ledger/compaction.py, simorgh/ledger/migrate_v1.py, simorgh/ledger/streams.py, simorgh/orchestration/context.py, simorgh/orchestration/profiles.py, simorgh/orchestration/progress.py, simorgh/orchestration/resume.py, simorgh/orchestration/scaffolds.py, simorgh/orchestration/service.py, simorgh/orchestration/session.py, simorgh/orchestration/tools.py, simorgh/orchestration/worker.py, simorgh/planning/api.py, simorgh/planning/dag.py, simorgh/planning/intake.py, simorgh/planning/scheduler.py, simorgh/planning/service.py, simorgh/planning/store.py, simorgh/reflection/service.py, simorgh/verification/checklist.py, simorgh/verification/checks/fullsuiteran.py, simorgh/verification/service.py, simorgh/verification/trajectory.py, simorgh/voice/service.py, simorgh/voice/session.py | see ledger/compaction.py DEFAULT_RETENTION |

## Config

`[interface]` in simorgh.toml; dataclass in `simorgh/interface/config.py`.

| Key | Default | Read in the package |
|---|---|---|
| `history_path` | `None` | NO (declared, never read) |
| `history_length` | `1000` | yes |
| `color` | `'auto'` | yes |
| `unicode` | `'auto'` | yes |
| `narrate` | `True` | yes |
| `narrate_autonomous` | `True` | yes |
| `tidy_input` | `True` | yes |
| `narrate_steps` | `True` | yes |
| `narrate_heartbeat_s` | `10.0` | yes |
| `time_marker_minutes` | `15.0` | yes |
| `show_speaker_score` | `True` | yes |
| `boot_wait_s` | `20.0` | yes |
| `rich_prompt` | `True` | yes |
| `live_status` | `'auto'` | yes |
| `prompt_timeout_s` | `120.0` | NO (declared, never read) |
| `vitals_idle_reprint_s` | `3.0` | NO (declared, never read) |
| `vitals_interval_s` | `15.0` | NO (declared, never read) |
| `notice_queue_max` | `200` | NO (declared, never read) |
| `shell_timeout_s` | `120.0` | NO (declared, never read) |
| `chat_reply_timeout_s` | `420.0` | yes |
| `http_host` | `'127.0.0.1'` | yes |
| `http_port` | `8765` | yes |
| `http_status_timeout_s` | `3.0` | yes |
| `http_chat_timeout_s` | `130.0` | yes |
| `api_max_body_bytes` | `1000000` | yes |
| `telegram_allowed` | `()` | yes |
| `telegram_poll_s` | `25.0` | yes |
| `whatsapp_allowed` | `()` | yes |
| `whatsapp_api_version` | `'v21.0'` | yes |
| `history_stream` | `'metrics:history'` | yes |
| `history_default_minutes` | `10.0` | yes |
| `history_max_points` | `500` | yes |
| `logs_default_limit` | `100` | yes |
| `logs_max_limit` | `500` | yes |
| `dash_feeds` | `True` | yes |
| `dash_place` | `'San Jose, CA'` | yes |
| `dash_latitude` | `37.34` | yes |
| `dash_longitude` | `-121.89` | yes |
| `dash_watchlist` | `()` | yes |
| `dash_majors` | `()` | yes |
| `dash_cameras_live` | `True` | yes |

## Public Python surface

TODO: the `Service` class; any `api.py` types other packages import via contracts; module-level singletons (risks).

## Invariants

TODO: the rules that must hold, as testable sentences; include contracts/topics.py policy entries naming this module.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract interface`.

- `tests/simorgh/interface/test_activity.py` -- TODO: what it pins
- `tests/simorgh/interface/test_an_approval_shows_what_it_grants.py` -- TODO: what it pins
- `tests/simorgh/interface/test_benchmarkchart.py` -- TODO: what it pins
- `tests/simorgh/interface/test_capabilities_command.py` -- TODO: what it pins
- `tests/simorgh/interface/test_cartoon_splash.py` -- TODO: what it pins
- `tests/simorgh/interface/test_command_request.py` -- TODO: what it pins
- `tests/simorgh/interface/test_command_table.py` -- TODO: what it pins
- `tests/simorgh/interface/test_dashfeeds.py` -- TODO: what it pins
- `tests/simorgh/interface/test_dispatch.py` -- TODO: what it pins
- `tests/simorgh/interface/test_domains_panel.py` -- TODO: what it pins
- `tests/simorgh/interface/test_httpapi.py` -- TODO: what it pins
- `tests/simorgh/interface/test_httpapi_token_boundary.py` -- TODO: what it pins
- `tests/simorgh/interface/test_line_widths.py` -- TODO: what it pins
- `tests/simorgh/interface/test_live_status.py` -- TODO: what it pins
- `tests/simorgh/interface/test_panel.py` -- TODO: what it pins
- `tests/simorgh/interface/test_parser.py` -- TODO: what it pins
- `tests/simorgh/interface/test_render.py` -- TODO: what it pins
- `tests/simorgh/interface/test_schedule_command.py` -- TODO: what it pins
- `tests/simorgh/interface/test_service.py` -- TODO: what it pins
- `tests/simorgh/interface/test_skills_command.py` -- TODO: what it pins
- `tests/simorgh/interface/test_speaker_score_on_screen.py` -- TODO: what it pins
- `tests/simorgh/interface/test_status_panel.py` -- TODO: what it pins
- `tests/simorgh/interface/test_telegram_channel.py` -- TODO: what it pins
- `tests/simorgh/interface/test_the_approval_still_hid_what_it_grants.py` -- TODO: what it pins
- `tests/simorgh/interface/test_the_sentence_builds_in_place.py` -- TODO: what it pins
- `tests/simorgh/interface/test_time_marker.py` -- TODO: what it pins
- `tests/simorgh/interface/test_tool_command.py` -- TODO: what it pins
- `tests/simorgh/interface/test_tui.py` -- TODO: what it pins
- `tests/simorgh/interface/test_visibility_commands.py` -- TODO: what it pins
- `tests/simorgh/interface/test_vitals.py` -- TODO: what it pins
- `tests/simorgh/interface/test_whatsapp_channel.py` -- TODO: what it pins

## Known issues (2026-09-18 evaluation)

TODO: catalogue ids from docs/reviews/2026-09-18/architecture-evaluation.md section 13 that name this module.

## Planned changes (roadmap)

TODO: stage numbers from docs/plan/ and what changes here.

## Working on this module

Lock it first (`python tools/modlock.py claim interface --by <you> --task "..."`), commit the lock, edit only `simorgh/interface/`, `tests/simorgh/interface/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py interface` before committing; commit subject `interface: <what changed>`.
