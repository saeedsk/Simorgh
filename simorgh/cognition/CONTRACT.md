# cognition -- contract

One-line status: layer 2 · 3,135 lines · 14 test files · lock: `cognition` in docs/modules/locks.toml

## Purpose

TODO: 3-6 sentences: what this module owns, what it must never do, the one design decision that shapes it.

## Files

| File | For |
|---|---|
| `simorgh/cognition/__init__.py` | TODO |
| `simorgh/cognition/api.py` | TODO |
| `simorgh/cognition/assembler.py` | TODO |
| `simorgh/cognition/budget.py` | TODO |
| `simorgh/cognition/compaction.py` | TODO |
| `simorgh/cognition/config.py` | TODO |
| `simorgh/cognition/parser.py` | TODO |
| `simorgh/cognition/providers/__init__.py` | TODO |
| `simorgh/cognition/providers/base.py` | TODO |
| `simorgh/cognition/providers/claude_code.py` | TODO |
| `simorgh/cognition/providers/gemini.py` | TODO |
| `simorgh/cognition/providers/ollama.py` | TODO |
| `simorgh/cognition/providers/together.py` | TODO |
| `simorgh/cognition/router.py` | TODO |
| `simorgh/cognition/service.py` | TODO |
| `simorgh/cognition/tokens.py` | TODO |

## Consumes

| Topic | Schema | Where | Does |
|---|---|---|---|
| `cognition.compact.done` | `messages/cognition.py::CognitionCompactDone` | simorgh/cognition/service.py | TODO |
| `cognition.compact.pre` | `messages/cognition.py::CognitionCompactPre` | simorgh/cognition/service.py | TODO |
| `cognition.compact.reply` | `messages/cognition.py::CognitionCompactReply` | simorgh/cognition/service.py | TODO |
| `cognition.compact.request` | `messages/cognition.py::CognitionCompactRequest` | simorgh/cognition/service.py | TODO |
| `cognition.think` | `messages/cognition.py::CognitionThink` | simorgh/cognition/service.py | TODO |
| `cognition.think.reply` | `messages/cognition.py::CognitionThinkReply` | simorgh/cognition/service.py | TODO |
| `system.started` | `messages/system.py::SystemStarted` | simorgh/cognition/service.py | TODO |
| `system.state.changed` | `messages/system.py::SystemStateChanged` | simorgh/cognition/service.py | TODO |
| `system.tick.second` | `messages/system.py::SystemTickSecond` | simorgh/cognition/service.py | TODO |

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `cognition.compact.done` | `messages/cognition.py::CognitionCompactDone` | simorgh/cognition/compaction.py, simorgh/cognition/service.py | TODO |
| `cognition.compact.pre` | `messages/cognition.py::CognitionCompactPre` | simorgh/cognition/compaction.py, simorgh/cognition/service.py | TODO |
| `cognition.compact.reply` | `messages/cognition.py::CognitionCompactReply` | simorgh/cognition/service.py | TODO |
| `cognition.provider.status` | `messages/cognition.py::CognitionProviderStatus` | simorgh/cognition/service.py | TODO |
| `cognition.think.reply` | `messages/cognition.py::CognitionThinkReply` | simorgh/cognition/service.py | TODO |
| `persona.voice` | `messages/persona.py::PersonaVoice` | simorgh/cognition/assembler.py | TODO |
| `self.summary` | `messages/self_.py::SelfSummary` | simorgh/cognition/assembler.py | TODO |
| `system.health` | `messages/system.py::SystemHealth` | simorgh/cognition/service.py | TODO |
| `system.metrics` | `messages/system.py::SystemMetrics` | simorgh/cognition/service.py | TODO |
| `ui.notice` | `messages/ui.py::UiNotice` | simorgh/cognition/service.py | TODO |
| `world.env.query` | `messages/world.py::WorldEnvQuery` | simorgh/cognition/assembler.py | TODO |

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `cognition:budget:{provider}` | simorgh/cognition/budget.py | simorgh/ledger/compaction.py | see ledger/compaction.py DEFAULT_RETENTION |
| `cognition:calls` | simorgh/cognition/service.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `cognition:summaries:{session_id}` | simorgh/cognition/compaction.py | simorgh/ledger/compaction.py | see ledger/compaction.py DEFAULT_RETENTION |
| `qwen3:4b-instruct` | simorgh/cognition/config.py | - | see ledger/compaction.py DEFAULT_RETENTION |

## Config

`[cognition]` in simorgh.toml; dataclass in `simorgh/cognition/config.py`.

| Key | Default | Read in the package |
|---|---|---|
| `provider_order` | `('together', 'claude_code_cli', 'gemini', 'floor')` | yes |
| `providers` | `field(default_factory=lambda: {'together': ProviderConfig(ma` | yes |
| `purposes` | `field(default_factory=lambda: dict(DEFAULT_PURPOSE_BUDGETS))` | yes |
| `routes` | `field(default_factory=dict)` | yes |
| `tool_result_max_tokens` | `2000` | yes |
| `snip_trigger_fraction` | `0.9` | yes |
| `snip_target_fraction` | `0.85` | yes |
| `snip_keep_last_segments` | `4` | yes |
| `microcompact_trigger_fraction` | `0.95` | yes |
| `collapse_keep_full_segments` | `4` | yes |
| `collapse_trigger_fraction` | `0.45` | yes |
| `availability_poll_seconds` | `30.0` | NO (declared, never read) |
| `assembly_request_timeout` | `2.0` | yes |
| `problems` | `()` | yes |

## Public Python surface

TODO: the `Service` class; any `api.py` types other packages import via contracts; module-level singletons (risks).

## Invariants

TODO: the rules that must hold, as testable sentences; include contracts/topics.py policy entries naming this module.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract cognition`.

- `tests/simorgh/cognition/test_assembler.py` -- TODO: what it pins
- `tests/simorgh/cognition/test_budget.py` -- TODO: what it pins
- `tests/simorgh/cognition/test_compaction.py` -- TODO: what it pins
- `tests/simorgh/cognition/test_config_problems.py` -- TODO: what it pins
- `tests/simorgh/cognition/test_ollama_is_started_when_it_is_needed.py` -- TODO: what it pins
- `tests/simorgh/cognition/test_parser.py` -- TODO: what it pins
- `tests/simorgh/cognition/test_provider_ollama.py` -- TODO: what it pins
- `tests/simorgh/cognition/test_provider_together.py` -- TODO: what it pins
- `tests/simorgh/cognition/test_providers.py` -- TODO: what it pins
- `tests/simorgh/cognition/test_reasoning_room.py` -- TODO: what it pins
- `tests/simorgh/cognition/test_router.py` -- TODO: what it pins
- `tests/simorgh/cognition/test_routes.py` -- TODO: what it pins
- `tests/simorgh/cognition/test_service.py` -- TODO: what it pins
- `tests/simorgh/cognition/test_tidy.py` -- TODO: what it pins

## Known issues (2026-09-18 evaluation)

TODO: catalogue ids from docs/reviews/2026-09-18/architecture-evaluation.md section 13 that name this module.

## Planned changes (roadmap)

TODO: stage numbers from docs/plan/ and what changes here.

## Working on this module

Lock it first (`python tools/modlock.py claim cognition --by <you> --task "..."`), commit the lock, edit only `simorgh/cognition/`, `tests/simorgh/cognition/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py cognition` before committing; commit subject `cognition: <what changed>`.
