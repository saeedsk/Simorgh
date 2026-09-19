# contracts -- contract

One-line status: layer shared · 6,497 lines · 23 test files · lock: `contracts` in docs/modules/locks.toml

## Purpose

`simorgh.contracts` is the one package every other package may import: the message envelope and ledger `Event` (`envelope.py`), the topic catalogue and the reserved-topology tables (`topics.py`), one frozen dataclass and one checked-in JSON Schema per message type (`messages/`, `registry.py`, `schema/`), the structural protocols subsystems are written against (`protocols.py`: `Bus`, `Ledger`, `Context`, `Subsystem`, `Provider`, `Tool`), approval and subsystem tokens (`security.py`), and the stream-name grammar (`streamnames.py`). It must stay standard-library only and must never import another `simorgh` package (enforced by `tests/simorgh/test_module_boundaries.py`). It has no `Service`, subscribes to nothing and publishes nothing. The shaping decision: a message type is declared once with `registry.define()` and everything else (dataclass, schema, catalogue entry, validation at publish) is derived from that declaration, so the checked-in schemas are generated, not hand-written. It has also accumulated shared helpers that do IO (settings, places, overheard, console, checkout); those are a known drift from "declarations only" (B20).

## Files

| File | For |
|---|---|
| `simorgh/contracts/__init__.py` | imports `messages` to fill the registry; re-exports envelope and catalogue names |
| `simorgh/contracts/channels.py` | the names of every channel a person reaches Sim by (cli, voice, api, chat, command, telegram, whatsapp) and their display names |
| `simorgh/contracts/checkout.py` | the manifest telling `run_tests` where a containerised checkout's tests run (reads and writes files, runs git) |
| `simorgh/contracts/compat.py` | schema-version translator registry; nothing registers a translator today |
| `simorgh/contracts/connector.py` | `Connector` protocol for account-backed integrations; credential groups and rate budgets |
| `simorgh/contracts/console.py` | appends what Sim printed to `interface/console.log` and trims it (IO) |
| `simorgh/contracts/envelope.py` | `Message`, `Event`, `canonical_json`, `validate` |
| `simorgh/contracts/fields.py` | the field-type language message types are declared in |
| `simorgh/contracts/home/__init__.py` | re-exports the Home Assistant client, dataclasses and `classify_call` |
| `simorgh/contracts/home/api.py` | `Entity`, `ServiceResult` |
| `simorgh/contracts/home/client.py` | stdlib Home Assistant REST client |
| `simorgh/contracts/home/fakes.py` | `FakeHomeAssistant`, a house in memory for tests |
| `simorgh/contracts/home/policy.py` | `classify_call`: the danger class of a service call from its arguments (read by Guardian's `PhysicalRule`) |
| `simorgh/contracts/household.py` | the family roster and child rules |
| `simorgh/contracts/messages/__init__.py` | imports every message module (registration side effect) |
| `simorgh/contracts/messages/action.py` | `action.*` (5 types) |
| `simorgh/contracts/messages/benchmark.py` | `benchmark.*` (12) |
| `simorgh/contracts/messages/cognition.py` | `cognition.*` (7) |
| `simorgh/contracts/messages/curiosity.py` | `curiosity.*` (12) |
| `simorgh/contracts/messages/guardian.py` | `guardian.*` (5) |
| `simorgh/contracts/messages/intent.py` | `intent.goal.stated` |
| `simorgh/contracts/messages/learn.py` | `learn.*` (8) |
| `simorgh/contracts/messages/memory.py` | `memory.*` (9) |
| `simorgh/contracts/messages/percept.py` | `percept.*` (4) |
| `simorgh/contracts/messages/persona.py` | `persona.*` (4) |
| `simorgh/contracts/messages/plan.py` | `plan.*` and `project.*` (8) |
| `simorgh/contracts/messages/reflect.py` | `reflect.*` (8) |
| `simorgh/contracts/messages/research.py` | `research.*` (1) |
| `simorgh/contracts/messages/self_.py` | `self.*` (6) |
| `simorgh/contracts/messages/system.py` | `system.*` (17) |
| `simorgh/contracts/messages/task.py` | `task.*` and `turn.*` (25) |
| `simorgh/contracts/messages/tool.py` | `tool.*` (4) |
| `simorgh/contracts/messages/ui.py` | `ui.*` (11) |
| `simorgh/contracts/messages/verify.py` | `verify.*` (2) |
| `simorgh/contracts/messages/voice.py` | `voice.*` (19) |
| `simorgh/contracts/messages/world.py` | `world.*` (4) |
| `simorgh/contracts/overheard.py` | the store of speech not addressed to Sim, grouped into conversations (file IO under a lock) |
| `simorgh/contracts/places.py` | house name and known networks, read from and written to `simorgh.toml` (IO) |
| `simorgh/contracts/protocols.py` | `Bus`, `Ledger`, `Clock`, `Logger`, `Span`, `Telemetry` (and the no-op `NullTelemetry`/`NULL_TELEMETRY`), `Health`, `Context`, `Subsystem`, `Provider`, `ProviderResponse`, `Tool`, `ToolContext`, `ToolResult` |
| `simorgh/contracts/pytestfailures.py` | a failed-test marker that survives output truncation |
| `simorgh/contracts/registry.py` | `define()`, `MessageSpec`, `get_spec`, `all_specs`, `error_reply_payload`, `ContractError` |
| `simorgh/contracts/schemagen.py` | generates and checks `schema/*.v1.json` from the registry |
| `simorgh/contracts/scratch.py` | `is_scratch(path)`: which paths are scratch |
| `simorgh/contracts/security.py` | HMAC approval tokens, `ReplayGuard`, subsystem identity tokens |
| `simorgh/contracts/settings.py` | settings home, `config_path()`, `persist()` to `simorgh.toml`, secret hand-off files, `conversation_key` |
| `simorgh/contracts/skills.py` | parses `SKILL.md` folders, reviews skill contents, the skills catalogue text |
| `simorgh/contracts/streamnames.py` | the stream-name grammar `[a-z0-9_.:-]{1,128}` |
| `simorgh/contracts/tidy.py` | fixing typos and mishearings in a line before it is answered |
| `simorgh/contracts/timewindow.py` | `"22:00-07:00"` quiet-hours parsing |
| `simorgh/contracts/tone.py` | the `[tone]` tag at the head of a spoken reply: split, strip, names |
| `simorgh/contracts/toolargs.py` | marker-text to tool-argument tables shared by the model path and the CLI `tool` command |
| `simorgh/contracts/topics.py` | `CATALOG`, domains, subsystems, pattern `matches`, reply naming, `SUBSCRIBE_ONLY_BY`, `PUBLISH_ONLY_BY`, `PUBLISH_PAYLOAD_CONSTRAINTS` |
| `simorgh/contracts/validation.py` | a stdlib JSON Schema (draft 2020-12 subset) validator |

## Consumes

Nothing. `contracts` is a library; it has no `Service` and no bus client.

## Produces

Nothing on the bus. It defines all 172 message types (`len(topics.CATALOG) == len(all_specs()) == 172`, checked 2026-09-19) and one schema file per type under `schema/`.

## Ledger streams

None. The package writes no ledger stream (the `corrected:` string in `tidy.py:167` is a model-output prefix, not a stream). It owns the grammar every stream name must satisfy (`streamnames.py`). Several modules write plain files under the settings home instead: `console.py` (`interface/console.log`), `overheard.py`, `places.py` and `settings.py` (`simorgh.toml`), `checkout.py` (the checkout manifest).

## Config

No `[contracts]` section and no config dataclass. `settings.py::config_path()` resolves which `simorgh.toml` other packages should write to, and `settings.persist()`/`places.py` rewrite keys in it.

## Public Python surface

- Envelope: `Message` (`new`, `reply`, `caused`, `with_`, `to_dict/to_json/from_dict/from_json`), `Event`, `canonical_json`, `validate`, `ContractError`, `CATALOG_VERSION`.
- Catalogue: every topic constant in `topics.py`, `CATALOG`, `DOMAINS`, `SUBSYSTEMS`, `matches`, `reply_type_for`, `is_reply`, `may_subscribe`, `may_publish`, `source_name`, `PREEMPT_PRIORITY`, `PREEMPTING_TYPES`.
- Registry: `define`, `get_spec`, `all_specs`, `MessageSpec` (`validate(payload)`, dataclass, schema), `error_reply_payload`.
- Telemetry (stage 1 item 1): `Telemetry` with `span(name, *, trace_id, parent_id=None, attrs=None)` (async context manager yielding a `Span`: `trace_id`, `span_id`, `parent_id`, `name`, `set(key, value)`; status `ok`/`error`/`cancelled`, the exception re-raised; a nested span of the same trace defaults its parent to the enclosing span), `sample(series, value, ts=None)`, `event(name, *, trace_id, span_id, parent_id=None, ts=None, attrs=None)` (a finished point span with a caller-chosen id; a bus message), `async query(trace_id) -> list[dict]`. `NullTelemetry` records nothing; `NULL_TELEMETRY` is the default of `Context.telemetry`, so a hand-built Context needs no store. The implementation is `simorgh/telemetry/`, owned by the Kernel.
- Protocols (structural; subsystems import these, never a concrete Bus or Ledger): `Bus`, `Subscription`, `Ledger`, `Clock`, `Logger`, `Health`, `Context` (fields incl. `telemetry`), `Subsystem`, `Provider`, `ProviderResponse` (has `tool_calls`, never filled by any provider, L1), `Tool`, `ToolContext`, `ToolResult` (`ok` plus free-text `error`, T9).
- Security: `approval_token`, `verify_approval_token`, `canonical_args_sha256`, `ReplayGuard`, `new_run_secret`, `subsystem_token`, `verify_subsystem_token`.
- Module-level mutable singletons (risks): `registry._REGISTRY` (filled by importing `messages`; a type defined twice or late changes validation for the whole process), `compat._TRANSLATORS` (`clear()` exists for tests), `overheard._lock` (a `threading.Lock` around a file), `console._since_check` (a counter mutated on every printed line from the event loop). These are the four module-level singletons of B20.

## Invariants

- `simorgh/contracts/` imports only the standard library and itself.
- Every constant in `topics.py` has exactly one registered spec and one checked-in schema file; `schemagen --check` reports no drift.
- Every request type has a reply type (`x.request` -> `x.reply`, otherwise `x` -> `x.reply`), and every reply type accepts the error shape from `error_reply_payload`.
- Every topic has a publisher and a subscriber in `simorgh/`, or an entry with a reason in `ALLOWED_ONE_SIDED` (29 entries on 2026-09-19); an entry that gains its other side fails the test until it is removed.
- `validate(message)` rejects: an unknown type, a `schema_version` that is not the catalogue's, a payload that fails the type's schema, priority outside 0..9, a `partition_key` not of the form `<kind>:<id>`, a priority-9 message with a `partition_key`, a reply without `correlation_id`, empty `id`/`source`/`trace_id`, a non-positive `ttl_seconds`, NaN or Infinity anywhere in the payload. It reports every problem, not the first.
- `canonical_json` is deterministic: sorted keys, compact separators, UTF-8, no NaN.
- `SUBSCRIBE_ONLY_BY`: only `guardian` may subscribe to `action.proposed`; only `execution` may subscribe to `action.approved`.
- `PUBLISH_ONLY_BY`: `action.approved` by `guardian` or `kernel`; `action.denied` by `guardian` or `execution`; `system.pause`, `system.stop`, `system.resume` by `interface` or `kernel`; `system.restart`, `system.reload` by `interface`, `kernel` or `execution`; `self.model.updated` by `worldmodel`; `plan.proposed` by `planning`.
- `PUBLISH_PAYLOAD_CONSTRAINTS`: `execution` may publish `action.denied` only with `layer: "token"`.
- Identity for these rules is `source_name(source)`: `orchestration@w3` is `orchestration`.
- An approval token verifies only for the same secret, action id, tool, canonical args hash and unexpired `expires_at`; `ReplayGuard` accepts a token once.
- A stream name matches `^[a-z0-9_.:-]{1,128}$`.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract contracts`.

- `tests/simorgh/contracts/test_envelope.py` -- one test per envelope rule in `validate`, canonical JSON, reply/caused construction.
- `tests/simorgh/contracts/test_catalog.py` -- every topic has a spec, a schema file and a domain; every request has a reply; every dataclass round-trips; the reserved-topology tables name real types and subsystems.
- `tests/simorgh/contracts/test_topics.py` -- pattern matching, reply naming, and each `SUBSCRIBE_ONLY_BY`/`PUBLISH_ONLY_BY`/payload-constraint entry.
- `tests/simorgh/contracts/test_topics_have_both_sides.py` -- no one-sided topic outside the allow-list, read from a booted system's subscriptions.
- `tests/simorgh/contracts/test_schemagen.py` -- the checked-in schemas match the registry; rendering is deterministic.
- `tests/simorgh/contracts/test_validation.py` -- the JSON Schema subset the registry relies on.
- `tests/simorgh/contracts/test_security.py` -- approval tokens verify, forgeries and expired or altered tokens fail, replays are refused.
- `tests/simorgh/contracts/test_toolargs.py` -- the shared marker-to-arguments tables the model path and the CLI both use.
- `tests/simorgh/contracts/test_telemetry_protocol.py` -- `NullTelemetry` conforms to `Telemetry`, records nothing, lets a span's exception through; a hand-built `Context` carries `NULL_TELEMETRY`.

## Known issues (2026-09-18 evaluation)

- W7 (medium): 25 topics had one side or none. Fixed 2026-09-18: commit `cd807d4` adds `test_topics_have_both_sides.py` with a reasoned allow-list; commit `b5c2671` makes it read subscriptions from a booted system.
- C1 (critical): `learn.self_patch.applied` (`topics.py:165`) had subscribers and no real publisher. Fixed 2026-09-18 (stage 0 item 9, in orchestration: `_land` publishes it; the schema's `tests` field became optional here).
- B20 (low): five modules do IO (checkout, console, overheard, places, settings) and four of the codebase's module-level mutable singletons live here. Open.
- B7 (medium): stream names are string agreements duplicated across packages; `streamnames.py` holds only the grammar, not the names or a writer table. Open; stage 1 item 8.
- B2 (medium): `Message.new` mints a fresh `trace_id` for every uncaused publish (`envelope.py:98`), which is one trace stream per root. Open; stage 1 item 2.
- L1 / C5 (critical / high): `ProviderResponse.tool_calls` (`protocols.py:151`) exists and no provider fills it. Open; stage 2.
- T2 (high): `tool.registered` carries no description or input schema. Open; stage 2 item 1.
- T9 (low): `ToolResult` has `ok` and free-text `error` (`protocols.py:185-191`); consumers sniff `refused:` text. Open; stage 2 item 8.
- V3 / V10 (medium / low): the percept has `speaker`/`speaker_relation` but only Voice fills them, and no `language` field (`messages/percept.py`). Open; stage 6 item 4.
- B8 / B14 (low): `compat.py` and the subsystem-identity tokens serve multi-process modes that never run. Open; stage 1 item 10.

Found while writing this contract (not in the catalogue): `settings.config_path()` (`settings.py:161-171`) falls back to `~/.simorgh/simorgh.toml` while the Kernel falls back to `$SIMORGH_RUNTIME_DATA_DIR/simorgh.toml` (`kernel/config.py:157`), so with a non-default data dir a writer and the Kernel can pick different files, the B11 shape again.

## Planned changes (roadmap)

- Stage 1 item 1: `protocols.py` gains `Telemetry` (`span`, `sample`, `query`).
- Stage 1 item 5: `Message` gains an optional `deadline` (absolute ts).
- Stage 1 item 8: a writer table in `streamnames.py` says which source may append to which prefix.
- Stage 1 item 10: `compat.py` moves under `simorgh/_frozen/`.
- Stage 2 item 1: `tool.registered` gains `name, description, input_schema, reversibility, read_only, network, cost_class, source, tags` (optional fields in `messages/tool.py`); `test_tool_registered_carries_schema.py`.
- Stage 2 item 8: `ToolResult.error_kind` (`refused | unconfigured | transient | failed`).
- Stage 3 item 2: a `session.delta` topic, bus-only.
- Stage 4 items 1 and 4: `Session`, `Turn`, `Block` contracts, `session.turn.appended/compacted/snapshot` events, `session:<id>` in `streamnames.py`; reader protocols for persona, self and memory.
- Stage 5 item 3: `Fact`, `memory.fact.stored/superseded`, a `facts` field on `memory.retrieve.reply`.
- Stage 6 items 1, 3, 4, 5: `self.estimate.request/reply`; `world.entity.observed`, `world.home.situation_changed`; `contracts/people.py` (`Person`, absorbing `household.py`); `requester{person_id, role, channel, verified}` on proposals.
- Stage 7 items 3 and 5: a typed `Plan` artifact in `messages/plan.py`; `task.waiting`, `task.wake`, `task.answer`.
- Stage 8 item 4: `growth.policy.proposed/adopted/retired`, `growth.lesson.found`.

## Working on this module

Lock it first (`python tools/modlock.py claim contracts --by <you> --task "..."`), commit the lock, edit only `simorgh/contracts/`, `tests/simorgh/contracts/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py contracts` before committing; commit subject `contracts: <what changed>`.

This package is Guardian-protected: Sim's own tasks cannot edit it. A human-run agent may, with the lock, because a person is accountable for the commit.

- Envelope (stage 1 item 5, 2026-09-19): `Message.deadline` (optional absolute epoch time; validated > 0 when set) is when the caller stops waiting. `Message.caused` carries it forward; `reply` does not. `envelope.time_left(message, now)` returns the seconds left (never below 0) or None. Consumers: bus (sets it), cognition, execution.

- `streamnames.WRITERS` (prefix -> subsystems allowed to write) and `writers_for(stream)` (longest prefix; None when unlisted), stage 1 item 8. Two-writer prefixes: `action:` (guardian, execution), `task:` (planning, orchestration), `capabilities` (execution, voice). Kernel-only: `system`, `schedule`, `config:`, `metrics:`.

- `Telemetry.event` takes an optional `end` (a timed span measured by the caller).
