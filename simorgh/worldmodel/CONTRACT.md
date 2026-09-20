# worldmodel -- contract

One-line status: layer 2 · 1,282 lines · 6 test files · lock: `worldmodel` in docs/modules/locks.toml

## Purpose

World Model owns two read models: the environment facets (the code areas under `simorgh/`, a bounded file index, `git` state, the tool registry as announced, the user profile as Persona announces it), answered on `world.env.query`; and the Self Model (identity hashed from `docs/SOUL.md`, capabilities, competence and calibration, limitations, change history, goals, continuity), answered on `self.summary` and `self.gaps` and rendered to `<data_dir>/self/SELF.md`. It is the only publisher of `self.model.updated`. It observes; it must never act (no `action.proposed`, no writes outside `SELF.md` and one loader-note stamp) and never fabricate an entry: a facet that fails answers an error reply, and an empty facet is empty. The shaping decision is that every Self Model change is a pure mutator `(SelfModel, event) -> SelfModel` applied through one `_apply` (`service.py:424-446`), which bumps the version only when the model actually changed. Its weakness is the other half of that decision: the model is folded in memory only, rebuilt static at every boot, and not yet a fold of a durable stream (`selfmodel.py:16-23`).

## Files

| File | For |
|---|---|
| `simorgh/worldmodel/__init__.py` | empty package marker (the Kernel imports `service.Service` directly) |
| `simorgh/worldmodel/api.py` | the `Facet` protocol (`name`, `get(args)`, `invalidate()`) |
| `simorgh/worldmodel/config.py` | `[worldmodel]` dataclass and its nested-key parser |
| `simorgh/worldmodel/facets/__init__.py` | empty package marker |
| `simorgh/worldmodel/facets/capability_map.py` | `capability_map` facet: the areas and modules under `simorgh/`, uncached |
| `simorgh/worldmodel/facets/file_index.py` | `file_index` facet: bounded tree scan with optional per-path preview, 30 s cache |
| `simorgh/worldmodel/facets/git_state.py` | `git_state` facet: read-only `git` subprocess observation |
| `simorgh/worldmodel/facets/registry_facets.py` | `tools` facet (from `tool.*`) and `user_profile` facet (from Persona) |
| `simorgh/worldmodel/selfmodel.py` | `SelfModel` dataclass, pure mutators, summary and markdown rendering, `compute_gaps` |
| `simorgh/worldmodel/service.py` | the bus subsystem: facet queries, Self Model folding, loader-rollback ingestion |

## Consumes

Authority: `Service.consumes` in `service.py:45-53`.

| Topic | Schema | Where | Does |
|---|---|---|---|
| `world.env.query` | `messages/world.py::WorldEnvQuery` | simorgh/worldmodel/service.py | answers one facet by `what` (`capability_map`, `file_index`, `git_state`, `tools`, `user_profile`) |
| `self.summary` | `messages/self_.py::SelfSummary` | simorgh/worldmodel/service.py | rescans areas, replies a token-bounded summary (Cognition's assembler prepends it to prompts) |
| `self.gaps` | `messages/self_.py::SelfGaps` | simorgh/worldmodel/service.py | rescans areas, replies the k least-known task types and unmeasured areas |
| `tool.registered` | `messages/tool.py::ToolRegistered` | simorgh/worldmodel/service.py | adds to the tools facet; after `system.started`, syncs `capabilities["tools"]` |
| `tool.unavailable` | `messages/tool.py::ToolUnavailable` | simorgh/worldmodel/service.py | marks a tool unavailable with its reason |
| `tool.probed` | `messages/tool.py::ToolProbed` | simorgh/worldmodel/service.py | a passing probe marks its tools available again |
| `persona.user_model.updated` | `messages/persona.py::PersonaUserModelUpdated` | simorgh/worldmodel/service.py | updates the user_profile facet |
| `learn.competence.updated` | `messages/learn.py::LearnCompetenceUpdated` | simorgh/worldmodel/service.py | sets success rate, samples, calibration for a task type |
| `reflect.calibration.updated` | `messages/reflect.py::ReflectCalibrationUpdated` | simorgh/worldmodel/service.py | merges stated vs empirical confidence into the same competence entry |
| `self.observation` | `messages/self_.py::SelfObservation` | simorgh/worldmodel/service.py | `kind=limitation` only: adds or fuzzy-merges a limitation |
| `learn.self_patch.applied` | `messages/learn.py::LearnSelfPatchApplied` | simorgh/worldmodel/service.py | appends a change-history entry and mitigates limitations naming the subject |
| `learn.self_patch.reverted` | `messages/learn.py::LearnSelfPatchReverted` | simorgh/worldmodel/service.py | appends a revert entry (nothing publishes it today; allow-listed) |
| `learn.skill.acquired` | `messages/learn.py::LearnSkillAcquired` | simorgh/worldmodel/service.py | adds the skill and a change entry |
| `system.started` | `messages/system.py::SystemStarted` | simorgh/worldmodel/service.py | marks boot done, syncs the tool list once, bumps continuity |
| `cognition.provider.status` | `messages/cognition.py::CognitionProviderStatus` | simorgh/worldmodel/service.py | records which providers exist and which is selected (in place, no version bump) |
| `task.created` | `messages/task.py::TaskCreated` | simorgh/worldmodel/service.py | adds a pending goal (and an active project for `kind=project`) |
| `task.completed` | `messages/task.py::TaskCompleted` | simorgh/worldmodel/service.py | closes the goal as completed |
| `task.failed` | `messages/task.py::TaskFailed` | simorgh/worldmodel/service.py | closes the goal as failed |
| `task.blocked` | `messages/task.py::TaskBlocked` | simorgh/worldmodel/service.py | marks the goal blocked (still outstanding) |

Also read at boot: `SIMORGH_LOADER_NOTES/last_rollback.json`, turned into a limitation once per rollback (`service.py:133-172`).
| `world.people.update` | `messages/world.py::WorldPeopleUpdate` | simorgh/worldmodel/service.py | link a handle to a person, unlink one, or set a role (stage 6 item 4). The only write in this subsystem; tier 3 on the way in, so a person has already confirmed it |

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `world.env.query.reply` | `messages/world.py::WorldEnvQueryReply` | simorgh/worldmodel/service.py | reply to every query: `ok`, `facet`, `as_of` plus the facet's data, or an `unknown_facet`/`unavailable` error |
| `world.people.update.reply` | `messages/world.py::WorldPeopleUpdateReply` | simorgh/worldmodel/service.py | reply to every `world.people.update`: the person as written, or a `refused` error naming what was wrong |
| `self.summary.reply` | `messages/self_.py::SelfSummaryReply` | simorgh/worldmodel/service.py | reply to every `self.summary`: `text`, `version`, `tokens` |
| `self.gaps.reply` | `messages/self_.py::SelfGapsReply` | simorgh/worldmodel/service.py | reply to every `self.gaps`: `gaps`, `unexplored_areas`, `version` |
| `self.model.updated` | `messages/self_.py::SelfModelUpdated` | simorgh/worldmodel/service.py | once per version bump, with the changed section and reason (no subscriber; allow-listed as an announcement) |

The generated draft also listed `world.env.observed` and `system.health`; this package publishes neither.

## Ledger streams

None. World Model neither reads nor writes the Ledger. Its only durable outputs are `<data_dir>/self/SELF.md` (re-rendered on every version) and the `.last_rollback_ingested` stamp in the loader-notes directory. This is evaluation C6.

## Config

`[worldmodel]` in simorgh.toml; dataclass in `simorgh/worldmodel/config.py`.

| Key | Default | Read in the package |
|---|---|---|
| `repo_root` | `Path('.')` | yes |
| `file_index_max_files` | `5000` | yes |
| `file_index_refresh_seconds` | `30.0` | yes |
| `git_refresh_seconds` | `60.0` | NO (declared, never read) |
| `soul_path` | `Path('docs/SOUL.md')` | yes (via `resolved_soul_path()`, `service.py:100`) |

The TOML shape is nested, not the field names: `from_mapping` reads `repo_root`, `[worldmodel.file_index] max_files, refresh_seconds`, `[worldmodel.git] refresh_seconds` and `[worldmodel.identity] soul_path` (`config.py:24-36`). `GitStateFacet` has no cache, so `git_refresh_seconds` has nothing to bound.

## Public Python surface

- `simorgh.worldmodel.service.Service` (name `worldmodel`, `VERSION = "0.1.0"`): constructed by `kernel/registry.py:144` with no arguments.
- `simorgh.worldmodel.config.Config`: imported by `kernel/configcheck.py:226`.
- Nothing else is imported from outside; other packages reach the Self Model and facets only over the bus. `SelfModel` is not in `simorgh/contracts`.
- No module-level mutable state. Per-instance state lost at restart: the whole `SelfModel`, the tools and user-profile facets, `_restarts`.

## Invariants

- Only `worldmodel` may publish `self.model.updated` (`contracts/topics.py` PUBLISH_ONLY_BY).
- `self.model.updated` is published exactly once per version bump, and the version bumps only when a mutator returned a different model; a no-op (duplicate limitation, unchanged areas or tools) changes neither version nor `SELF.md`.
- Every `world.env.query` gets a reply; an unknown facet or a facet exception is an error reply with `facet` and `as_of`, never a crash or silence.
- `self.summary` and `self.gaps` rescan the capability areas first, so the summary and `capability_map` agree; an empty scan never wipes known areas.
- `capabilities["tools"]` is the sorted set of registered tools not currently unavailable; it is written once at `system.started` and on every change after, never per tool during boot.
- `compute_gaps` ranks by `success_rate - 1/sqrt(samples+1)` ascending; types with no samples are not gaps; areas with no measured `type:area` are `unexplored`.
- Identity is loaded and hashed from the SOUL file; World Model never writes it.
- A loader rollback note becomes exactly one limitation, whatever the number of boots.
- No SUBSCRIBE_ONLY_BY or PUBLISH_PAYLOAD_CONSTRAINTS entry names worldmodel.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract worldmodel`.

- `tests/simorgh/worldmodel/test_service.py` -- the bus surface: facet queries and honest errors, summary and gaps replies, tool inventory, `SELF.md` on disk, areas rescan.
- `tests/simorgh/worldmodel/test_selfmodel.py` -- each pure mutator's merge, dedupe and bounding rules.
- `tests/simorgh/worldmodel/test_file_index_facet.py` -- the file index answers the path asked and refreshes on its window.
- `tests/simorgh/worldmodel/test_capability_map.py` -- the capability areas and modules listed from `simorgh/`.
- `tests/simorgh/worldmodel/test_substrate.py` -- `cognition.provider.status` reaches the Self Model and its rendering.

## Known issues (2026-09-18 evaluation)

- C6 -- the Self Model is volatile: built static at every start, mutated in memory only, never folded from a stream; Reflection's calibration findings and applied patches vanish at the next boot. Open; stage 6 item 1. One visible consequence: `continuity.restarts` is a per-process counter starting at 0 (`service.py:63, 384`), so it reads 1 after every boot.
- C1 -- `learn.self_patch.applied` had no publisher on the real landing path. **Fixed 2026-09-18** (`1e486f1`: `_land` publishes it). Part of the same finding, `compute_gaps` returned two empty lists and `capabilities["tools"]` was never written: **fixed 2026-09-18** (`62318d3`).
- W7 -- `learn.self_patch.reverted` is subscribed here and published by nothing since the PatchPipeline was retired; `self.model.updated` has no subscriber. Allow-listed with reasons (`b5c2671`); the loader's rollback should publish the former (stage 8).
- S6/T1/T10 -- the tools facet stores the proposer-independent `read_only`/`reversibility` from `tool.registered`, but Guardian does not read it; see guardian's contract.

## Planned changes (roadmap)

- Stage 2 item 1: `ToolsFacet` keeps the tool's JSON schema from `tool.registered` (lock `worldmodel` with `contracts`, `execution`).
- Stage 6 item 1: `self:model` becomes a fold rebuilt at boot from `learn:outcomes`, `self:changes`, `tool.registered` replay and `system.started`, with Beta posteriors per task type, calibration, per-tool reliability, and snapshots; the Self Model survives a restart.
- Stage 6 item 3, in part, 2026-09-19: the `home` facet folds `world.camera.event`, `ui.tv.state` and placed `voice.transcript` speakers into an entity table plus a presence belief per (person, area) that halves every 20 minutes; situation facts are pure rules over it, and `world.home.situation_changed` is published when one flips. Nothing is asserted from silence: an entity unobserved for two hours is `stale` and left out of the prompt block, a person no evidence places is `unknown`, and `nobody_home` is `None` rather than `true` when there is no evidence either way. A presence belief also records whether the evidence was a *verified* identification (a speaker match at confidence >= 0.6, not a lean) -- `saw_person(..., verified=)`, `HomeFacet.verified`, and `verified` in the `world.env.query` reply for a person. Guardian's `PresenceRule` reads it before letting a voice approve anything that reaches outside the house (stage 6 item 5): belief and verification answer different questions, and a television can be mistaken for the creator at 0.5. It is the latest evidence's answer, not a high-water mark. Still open: folding `action.result` of home tools and calendar reads, `percept.home.state_changed`, learned change rates, and the per-area transcript ring.
- Stage 6 item 4, in part, 2026-09-19: the `people` facet is the one answer to who somebody is -- a `Person` per household member with their identities (`voice:`, `telegram:`, `whatsapp:`, `cli:`, `ha:`, `email:`), a role (owner/adult/child/guest/unknown) and one memory namespace across every channel. Seeded from `contracts/household.py`, kept as `people.json` in the data dir, resolved by identity; an identity nobody has linked is `None` and `unknown`, never a new person. Still open: resolution at each channel edge, the `people_*` tools, and folding in the speaker book, the allow-lists and `persona/user_model.py`.
- Stage 6 item 4: the People store (`contracts/people.py`) lives here.
- Stage 7 item 9: standing intents evaluated against `world.home.situation_changed` (lock `planning`, `worldmodel`).

## Working on this module

Lock it first (`python tools/modlock.py claim worldmodel --by <you> --task "..."`), commit the lock, edit only `simorgh/worldmodel/`, `tests/simorgh/worldmodel/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py worldmodel` before committing; commit subject `worldmodel: <what changed>`.

- ToolsFacet keeps each tool's `description` and `input_schema` from `tool.registered` (stage 2 item 1).
