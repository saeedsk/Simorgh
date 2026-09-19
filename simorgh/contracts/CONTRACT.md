# contracts -- contract

One-line status: layer shared · 6,497 lines · 23 test files · lock: `contracts` in docs/modules/locks.toml

## Purpose

TODO: 3-6 sentences: what this module owns, what it must never do, the one design decision that shapes it.

## Files

| File | For |
|---|---|
| `simorgh/contracts/__init__.py` | TODO |
| `simorgh/contracts/channels.py` | TODO |
| `simorgh/contracts/checkout.py` | TODO |
| `simorgh/contracts/compat.py` | TODO |
| `simorgh/contracts/connector.py` | TODO |
| `simorgh/contracts/console.py` | TODO |
| `simorgh/contracts/envelope.py` | TODO |
| `simorgh/contracts/fields.py` | TODO |
| `simorgh/contracts/home/__init__.py` | TODO |
| `simorgh/contracts/home/api.py` | TODO |
| `simorgh/contracts/home/client.py` | TODO |
| `simorgh/contracts/home/fakes.py` | TODO |
| `simorgh/contracts/home/policy.py` | TODO |
| `simorgh/contracts/household.py` | TODO |
| `simorgh/contracts/messages/__init__.py` | TODO |
| `simorgh/contracts/messages/action.py` | TODO |
| `simorgh/contracts/messages/benchmark.py` | TODO |
| `simorgh/contracts/messages/cognition.py` | TODO |
| `simorgh/contracts/messages/curiosity.py` | TODO |
| `simorgh/contracts/messages/guardian.py` | TODO |
| `simorgh/contracts/messages/intent.py` | TODO |
| `simorgh/contracts/messages/learn.py` | TODO |
| `simorgh/contracts/messages/memory.py` | TODO |
| `simorgh/contracts/messages/percept.py` | TODO |
| `simorgh/contracts/messages/persona.py` | TODO |
| `simorgh/contracts/messages/plan.py` | TODO |
| `simorgh/contracts/messages/reflect.py` | TODO |
| `simorgh/contracts/messages/research.py` | TODO |
| `simorgh/contracts/messages/self_.py` | TODO |
| `simorgh/contracts/messages/system.py` | TODO |
| `simorgh/contracts/messages/task.py` | TODO |
| `simorgh/contracts/messages/tool.py` | TODO |
| `simorgh/contracts/messages/ui.py` | TODO |
| `simorgh/contracts/messages/verify.py` | TODO |
| `simorgh/contracts/messages/voice.py` | TODO |
| `simorgh/contracts/messages/world.py` | TODO |
| `simorgh/contracts/overheard.py` | TODO |
| `simorgh/contracts/places.py` | TODO |
| `simorgh/contracts/protocols.py` | TODO |
| `simorgh/contracts/pytestfailures.py` | TODO |
| `simorgh/contracts/registry.py` | TODO |
| `simorgh/contracts/schemagen.py` | TODO |
| `simorgh/contracts/scratch.py` | TODO |
| `simorgh/contracts/security.py` | TODO |
| `simorgh/contracts/settings.py` | TODO |
| `simorgh/contracts/skills.py` | TODO |
| `simorgh/contracts/streamnames.py` | TODO |
| `simorgh/contracts/tidy.py` | TODO |
| `simorgh/contracts/timewindow.py` | TODO |
| `simorgh/contracts/tone.py` | TODO |
| `simorgh/contracts/toolargs.py` | TODO |
| `simorgh/contracts/topics.py` | TODO |
| `simorgh/contracts/validation.py` | TODO |

## Consumes

| Topic | Schema | Where | Does |
|---|---|---|---|

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `corrected:` | simorgh/contracts/tidy.py | simorgh/orchestration/api.py, simorgh/orchestration/session.py | see ledger/compaction.py DEFAULT_RETENTION |

## Config

`[contracts]` in simorgh.toml; dataclass in `simorgh/contracts/config.py`.

| Key | Default | Read in the package |
|---|---|---|

## Public Python surface

TODO: the `Service` class; any `api.py` types other packages import via contracts; module-level singletons (risks).

## Invariants

TODO: the rules that must hold, as testable sentences; include contracts/topics.py policy entries naming this module.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract contracts`.

- `tests/simorgh/contracts/test_bundled_skills.py` -- TODO: what it pins
- `tests/simorgh/contracts/test_catalog.py` -- TODO: what it pins
- `tests/simorgh/contracts/test_channels.py` -- TODO: what it pins
- `tests/simorgh/contracts/test_checkout.py` -- TODO: what it pins
- `tests/simorgh/contracts/test_compat.py` -- TODO: what it pins
- `tests/simorgh/contracts/test_connector.py` -- TODO: what it pins
- `tests/simorgh/contracts/test_console.py` -- TODO: what it pins
- `tests/simorgh/contracts/test_envelope.py` -- TODO: what it pins
- `tests/simorgh/contracts/test_overheard.py` -- TODO: what it pins
- `tests/simorgh/contracts/test_overheard_clock.py` -- TODO: what it pins
- `tests/simorgh/contracts/test_overheard_conversations.py` -- TODO: what it pins
- `tests/simorgh/contracts/test_places.py` -- TODO: what it pins
- `tests/simorgh/contracts/test_schemagen.py` -- TODO: what it pins
- `tests/simorgh/contracts/test_security.py` -- TODO: what it pins
- `tests/simorgh/contracts/test_settings.py` -- TODO: what it pins
- `tests/simorgh/contracts/test_skill_review.py` -- TODO: what it pins
- `tests/simorgh/contracts/test_skills.py` -- TODO: what it pins
- `tests/simorgh/contracts/test_tone.py` -- TODO: what it pins
- `tests/simorgh/contracts/test_tone_preamble.py` -- TODO: what it pins
- `tests/simorgh/contracts/test_toolargs.py` -- TODO: what it pins
- `tests/simorgh/contracts/test_topics.py` -- TODO: what it pins
- `tests/simorgh/contracts/test_topics_have_both_sides.py` -- TODO: what it pins
- `tests/simorgh/contracts/test_validation.py` -- TODO: what it pins

## Known issues (2026-09-18 evaluation)

TODO: catalogue ids from docs/reviews/2026-09-18/architecture-evaluation.md section 13 that name this module.

## Planned changes (roadmap)

TODO: stage numbers from docs/plan/ and what changes here.

## Working on this module

Lock it first (`python tools/modlock.py claim contracts --by <you> --task "..."`), commit the lock, edit only `simorgh/contracts/`, `tests/simorgh/contracts/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py contracts` before committing; commit subject `contracts: <what changed>`.

This package is Guardian-protected: Sim's own tasks cannot edit it. A human-run agent may, with the lock, because a person is accountable for the commit.
