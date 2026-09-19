# Stage 1 -- Telemetry out of the decision log

Status: not started · Depends on: stage 0 items 1-16 · Estimated: 2 weeks · Modules touched: bus, ledger, kernel, contracts, execution, interface, orchestration, cognition

## Outcome

Spans and samples live in SQLite tables with row-level retention; the JSONL decision log holds only decisions. One trace root per turn or task, with children per think, guardian decision, tool call, verification, STT and TTS, so "why was that turn 9 s" is one query. Disk growth is bounded. The Ring dashboard's WebRTC signalling is one approval per session, not one per keepalive. The six tool invocations that bypass Guardian go through the action path. A `deadline` travels in the message envelope.

## Why

Evaluation B2 (88,356 per-message trace streams, 76% single-event), B4/B5 (idle bus cost), B7 (unbound ledger client), P4 (no end-to-end trace for a turn), P6 (no daily-path regression numbers), T4 (85% of Guardian decisions are `ring_live` keepalives), S12 (six direct `tool.run()` sites), B17 (`simorgh status` boots a second Kernel). Unlocks: per-stage p50/p95 in milliseconds for voice and tasks; the attribution every later latency claim needs; a ledger that stays small.

## Before you start

Measure and record in findings: `ls ~/.simorgh/ledger/streams | wc -l` after one day of use; `du -sh ~/.simorgh/ledger`; count of `action:*` streams whose tool is `ring_live`; the wall time of one spoken turn from `voice:turns` (STT, LLM, first audio). Read `simorgh/bus/trace.py`, `simorgh/ledger/backends/sqlite.py` (exists, 275 lines, CAS on `(stream, seq)`), `simorgh/kernel/metrics.py`, `simorgh/interface/dashfeeds.py` (the read side), `simorgh/execution/home/ring.py:698-703`.

## Action items

1. **`telemetry/` package: spans and samples tables.** *Lock `contracts` (new protocol), then `telemetry` (new package; add to `kernel/registry.py` LAYERS layer 0 and `docs/AGENTS.md`).*
   - Files: `simorgh/telemetry/{__init__,service,store,spans,samples,config}.py`; `simorgh/contracts/protocols.py` gains `Telemetry` (`span(name, parent, attrs)` context manager, `sample(series, value, ts)`, `query(trace_id)`).
   - How: one SQLite file at `<data_dir>/telemetry.sqlite`, WAL mode; tables `spans(trace_id, span_id, parent_id, name, start, end, status, attrs_json)` and `samples(series, ts, value_json)`; retention by age per table (spans 14 d, samples 7 d raw then downsampled to 1/min after a day) on the sleep tick; batched writes every 250 ms, no fsync per row. The Kernel injects the implementation into every Context (`kernel/context.py`, beside `bus` and `ledger`).
   - Acceptance: `tests/simorgh/telemetry/test_store.py` (write 10k spans, query one trace, retention removes old rows, downsample keeps 1/min); `tests/simorgh/test_module_boundaries.py` updated for the new package.
   - Rollback: the package is inert until item 3 routes writers to it.
2. **Trace ids threaded per turn and task.** *Lock `orchestration`, `cognition`, `execution`, `interface`, `voice`.* (B2, P4)
   - What: the chat path stops dropping the percept `Message` (`orchestration/service.py:263-283`); `session.py::_think` builds the think request with `trace_id=session.task_id`; the ~15 `Message.new` sites in Cognition and Execution that mint a fresh trace take the incoming message's `trace_id`; Voice roots a spoken turn's trace at `percept.text.received`.
   - Acceptance: a test that one chat turn through `test_cli_end_to_end.py`'s harness produces exactly one trace id across percept, think, action and turn.completed.
3. **Bus tracing writes spans, not ledger streams.** *Lock `bus`, `kernel`.*
   - What: `bus/trace.py::TraceWriter` writes a span per message into the telemetry store (name = topic, parent = causation id) instead of a `trace:<id>` ledger stream; the exclusion list becomes a sampling rate per topic prefix (`ui.notice` 1/50, `persona.state.changed` 1/50, `system.tick.*` 0); `metrics:history`, `curiosity:ticks`, `persona:state` become samples (`kernel/metrics.py::MetricsHistoryWriter`, `curiosity/service.py::_record_tick`, `persona/service.py`).
   - Acceptance: after a booted-Kernel test runs one turn, `ls streams` shows no `trace:` stream and the telemetry store has the turn's spans; `simorgh trace <id>` reads the store.
   - Rollback: `[bus] trace_backend = "ledger"` keeps the old writer for one bless cycle; delete it after.
4. **Per-stage spans on the daily path.** *Lock `voice`, `orchestration`, `guardian`, `execution`, `verification`.* Wrap STT, speaker id, think, guardian decide, tool run, verify, TTS synth and playback in `ctx.telemetry.span(...)`; Guardian records `rule`, `tier`, `posture` as attrs. Acceptance: one spoken turn yields a span tree with those eight names; `/api/traces/<id>` renders it.
5. **A deadline in the envelope.** *Lock `contracts`, `bus`, `cognition`, `execution`.* `Message` gains optional `deadline` (absolute ts); `bus.request` sets it from its timeout; Cognition and Execution read it and shrink their own timeouts to what is left; a breach is a span event. Acceptance: a request with 2 s left never waits 60 s in a tool (`execution/service.py::timeout_for` reads the deadline).
6. **Ring signalling off the approval path.** *Lock `execution`, `interface`.* (T4) One `ring_live offer` proposal per dashboard session mints a session token; keepalive and close are HTTP handlers that verify the token and call the Ring client directly, logged as spans. Acceptance: a dashboard session of 10 minutes produces 1 action stream, not ~30.
7. **The six direct tool runs go through the path.** *Lock `execution`.* (S12) `_autostart_ring_watch`, `_autostart_cam_watch`, `_autostart_tv_show`, the charts autoplay (`execution/service.py:484,517,543,561`) and the camera watcher's list/snapshot (`vision.py:475,515`) publish `action.proposed` with `proposed_by="execution"` and act on the approval like any tool. Acceptance: a booted-Kernel test shows an `action:` stream for the boot-time watch start; PhysicalRule sees them (observe tools abstain).
8. **A ledger client bound to its source.** *Lock `ledger`, `kernel`, `contracts`.* (B7) `LedgerClient` takes `source`; a writer table in `contracts/streamnames.py` says which source may append to which prefix; a violation is refused like a bus policy violation. Acceptance: Reflection appending to `self:model` is refused.
9. **`simorgh status` reads, never boots.** *Lock `kernel`, `interface`.* (B17) The status subcommand calls `/api/status` on the running instance or reads the last `system.state` from the ledger, and appends nothing.
10. **Retire the multi-process substrate behind its interfaces.** *Lock `bus`, `ledger`, `kernel`.* (B8, B14) Move `bus/backends/aws.py`, `ledger/backends/dynamodb.py`, `kernel/worker.py` (WorkerKernel), the identity registry and `contracts/compat.py` under `simorgh/_frozen/` with a README saying why; keep the backend protocol and the `sqlite` backends. Delete their tests from the core gate. Acceptance: boot unchanged; `--tier full` time drops.
11. **Findings entry** with the after-numbers.

## Measurements after

| Number | Before | Target |
|---|---|---|
| Ledger stream files after a day | 44k/day | under 500/day |
| `action:` streams per dashboard hour | ~200 | under 10 |
| One spoken turn: spans with STT/LLM/first-audio in ms | none | present, queryable |
| Tool calls outside the action path | 6 sites | 0 |
| Idle CPU of the process | ~6.6% of a core | under 2% |

## Risks and mitigations

- Consumers of `trace:` streams (dashfeeds, reflection's trajectory reads) must be ported the same fortnight: keep the old writer behind a switch for one bless cycle.
- The deadline field changes provider timeouts: cover with the router tests; a missing deadline means today's behaviour.
- Ring signalling change touches a family-facing page: test on the TV page before removing the old route.

## Definition of done

- [ ] Items 1-10 committed with their tests; `--tier core` green.
- [ ] No `trace:` streams written on a booted Kernel.
- [ ] `docs/findings/` entry with the table above; CONTRACT.md of every touched module updated (new topics, streams, config).
