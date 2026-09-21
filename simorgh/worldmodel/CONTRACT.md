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
| `simorgh/worldmodel/facets/home.py` | `home` facet: the entity table, presence beliefs with decay, situation facts, `now_block` (stage 6 item 3) |
| `simorgh/worldmodel/facets/people.py` | `people` facet: the People store (`people.json`), resolution by identity or name, link/unlink/set_role, and since stage 10 grant/revoke/add_interest/remove_interest |
| `simorgh/worldmodel/facets/wellbeing.py` | `wellbeing` facet: a per-person baseline of cheap turn features, a Beta posterior over low-side turns with a half-life, states `unknown/usual/low/high`, `now_block(person=)`, `wellbeing.json`; keeps nothing about anybody `may_check_in` refuses (stage 10 item 2) |
| `simorgh/worldmodel/facets/registry_facets.py` | `tools` facet (from `tool.*`) and `user_profile` facet (from Persona) |
| `simorgh/worldmodel/selfmodel.py` | `SelfModel` dataclass, pure mutators, summary and markdown rendering, `compute_gaps` |
| `simorgh/worldmodel/service.py` | the bus subsystem: facet queries, Self Model folding, loader-rollback ingestion |

## Consumes

Authority: `Service.consumes` in `service.py:45-53`.

| Topic | Schema | Where | Does |
|---|---|---|---|
| `world.env.query` | `messages/world.py::WorldEnvQuery` | simorgh/worldmodel/service.py | answers one facet by `what` (`capability_map`, `file_index`, `git_state`, `tools`, `user_profile`, `home`, `people`, `wellbeing`) |
| `action.result` | `messages/action.py::ActionResult` | service.py `_on_action_result` | what SIM changed in the house: a successful `home_call`/`home_undo`'s `changed` entities, each with the state it is in now (`metadata["after"]`). Only entities the house reports as actually changed -- Home Assistant answers 200 for an unplugged bulb, and "the call succeeded" is not "the house did something". Until 2026-09-20 every source of the entity table was somebody else telling Sim what happened, so Sim turned the kitchen light on and then did not know it was on. Since 2026-09-20 EVERY result, whatever the tool and whether it worked, also folds into `SelfModel.tool_stats` (`selfmodel.observe_tool`): runs, oks, `p_ok`, and p50/p95 over the last `TOOL_SAMPLES` durations. That is the one thing Sim can learn about itself from ordinary use at no cost, and it was being discarded on the first line of this handler because the handler was written for the house |
| `self.summary` | `messages/self_.py::SelfSummary` | simorgh/worldmodel/service.py | rescans areas, replies a token-bounded summary (Cognition's assembler prepends it to prompts) |
| `self.gaps` | `messages/self_.py::SelfGaps` | simorgh/worldmodel/service.py | rescans areas, replies the k least-known task types and unmeasured areas |
| `tool.registered` | `messages/tool.py::ToolRegistered` | simorgh/worldmodel/service.py | adds to the tools facet; after `system.started`, syncs `capabilities["tools"]` |
| `tool.unavailable` | `messages/tool.py::ToolUnavailable` | simorgh/worldmodel/service.py | marks a tool unavailable with its reason |
| `tool.probed` | `messages/tool.py::ToolProbed` | simorgh/worldmodel/service.py | a passing probe marks its tools available again |
| `persona.user_model.updated` | `messages/persona.py::PersonaUserModelUpdated` | simorgh/worldmodel/service.py | updates the user_profile facet |
| `learn.competence.updated` | `messages/learn.py::LearnCompetenceUpdated` | simorgh/worldmodel/service.py | sets success rate, samples, calibration for a task type |
| `reflect.calibration.updated` | `messages/reflect.py::ReflectCalibrationUpdated` | simorgh/worldmodel/service.py | merges stated vs empirical confidence into the same competence entry |
| (no topic) | `selfmodel.observe_tool` / `slow_or_unreliable` | folded from `action.result` | per-tool `runs`, `ok`, `p_ok`, `p50_ms`, `p95_ms` in `SelfModel.tool_stats` -- deliberately not `capabilities["tools"]`, which is the registry and is rescanned at every boot. The summary renders only the tools worth planning around -- under 80% or a p95 over 10 s, and only after 5 runs, because the interesting failure of a number like this is a tool that failed once on its first call and reads as 0% forever. A plain rate, not a Beta posterior: a tool has thousands of samples where a task type has tens, which is why the cheap number is enough here and is not there |
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
| `world.people.update` | `messages/world.py::WorldPeopleUpdate` | simorgh/worldmodel/service.py | link a handle to a person, unlink one, set a role (stage 6 item 4); grant or revoke a permission, add or remove an interest (stage 10 item 1). The only write in this subsystem; tier 3 on the way in, so a person has already confirmed it. A `grant` of a name that is not in `contracts.people.PERMISSIONS` is a `refused` reply |
| `turn.completed` | `messages/task.py::TurnCompleted` | simorgh/worldmodel/service.py `_on_turn_completed` | one wellbeing trial per turn for a speaker `may_check_in` admits: `user_text` (word count), the reply's tone tag (`contracts/tone.py::split_tone`; `warm`/`sorry` read as soft), and for `channel: voice` the last `voice.transcript`'s `seconds` for that speaker within 120 s (speech rate). A turn with no `speaker` is nobody's and is dropped (stage 10 item 2) |

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `world.env.query.reply` | `messages/world.py::WorldEnvQueryReply` | simorgh/worldmodel/service.py | reply to every query: `ok`, `facet`, `as_of` plus the facet's data, or an `unknown_facet`/`unavailable` error |
| `world.people.update.reply` | `messages/world.py::WorldPeopleUpdateReply` | simorgh/worldmodel/service.py | reply to every `world.people.update`: the person as written, or a `refused` error naming what was wrong |
| `self.summary.reply` | `messages/self_.py::SelfSummaryReply` | simorgh/worldmodel/service.py | reply to every `self.summary`: `text`, `version`, `tokens` |
| `self.gaps.reply` | `messages/self_.py::SelfGapsReply` | simorgh/worldmodel/service.py | reply to every `self.gaps`: `gaps`, `unexplored_areas`, `version` |
| `self.model.updated` | `messages/self_.py::SelfModelUpdated` | simorgh/worldmodel/service.py | once per version bump, with the changed section and reason (no subscriber; allow-listed as an announcement) |
| `world.wellbeing.changed` | `messages/world.py::WorldWellbeingChanged` | simorgh/worldmodel/service.py `_announce_wellbeing` | when a tracked person's state flips (`unknown/usual/low/high`), with the posterior mean of the low-side rate and the fresh evidence it rests on; never their words; only for an adult who said yes. Consumer: initiative (stage 10 item 3) |

The generated draft also listed `world.env.observed` and `system.health`; this package publishes neither.

## Ledger streams

None. World Model neither reads nor writes the Ledger. Its durable outputs are `<data_dir>/self/SELF.md` (re-rendered on every version), the `.last_rollback_ingested` stamp in the loader-notes directory, `<data_dir>/people.json` (the People store) and `<data_dir>/wellbeing.json` (per-person baselines and a bounded window of `(when, z)` trials; never words). This is evaluation C6; the wellbeing file is the same stopgap shape as `people.json` until a ledger fold.

## Config

`[worldmodel]` in simorgh.toml; dataclass in `simorgh/worldmodel/config.py`.

| Key | Default | Read in the package |
|---|---|---|
| `self:changes` | every applied change to what Sim knows about ITSELF -- `{rule, args, section, reason}` for the five replayable rules (`competence`, `limitation`, `change`, `mitigate`, `skill`) -- written by `_record` and folded back at boot by `_replay_self`. Capabilities and goals are NOT here: they are re-derived at every start, and replaying them could resurrect a tool that has since gone (stage 6 item 1, 2026-09-20) |
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
- The `wellbeing` facet stores nothing about anybody `contracts.people.may_check_in` refuses (a child, a guest, an unknown voice, an adult who has not said yes): `observe` returns False before any record exists, `now_block(person=)` renders nothing for them, and revoking `wellbeing_checkins` deletes the person's record (`forget`). Nothing is asserted from silence: no turns, a baseline under `BASELINE_MIN` (12) turns, no turn in `FRESH_S` (24 h) or under `MIN_EVIDENCE` (3) turns' worth of fresh weight is `unknown`, never `usual` and never `low`. `world.wellbeing.changed` is published only on a flip and never carries a person's words.
- A loader rollback note becomes exactly one limitation, whatever the number of boots.
- No SUBSCRIBE_ONLY_BY or PUBLISH_PAYLOAD_CONSTRAINTS entry names worldmodel.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract worldmodel`.

- `tests/simorgh/worldmodel/test_service.py` -- the bus surface: facet queries and honest errors, summary and gaps replies, tool inventory, `SELF.md` on disk, areas rescan.
- `tests/simorgh/worldmodel/test_selfmodel.py` -- each pure mutator's merge, dedupe and bounding rules.
- `tests/simorgh/worldmodel/test_file_index_facet.py` -- the file index answers the path asked and refreshes on its window.
- `tests/simorgh/worldmodel/test_capability_map.py` -- the capability areas and modules listed from `simorgh/`.
- `tests/simorgh/worldmodel/test_substrate.py` -- `cognition.provider.status` reaches the Self Model and its rendering.
- `tests/simorgh/worldmodel/test_wellbeing_facet.py` and `test_wellbeing_over_the_bus.py` -- the wellbeing facet: nothing from silence, the baseline forms before anything is scored, twelve usual turns then five short ones read `low` and the same five over two days do not, a quiet person is not low for being quiet, a long change becomes the new usual, flips are reported once, one person's line is never another's, a child's turns leave no record, a revoke deletes, a flip on the bus carries no words (stage 10 item 2).
- `tests/simorgh/worldmodel/test_people_store.py` and `test_people_consent.py` -- the People store: one person across channels, `unknown` by default; a grant lands on the record and on disk, survives a restart, is refused for a name that is not a permission, and a guest with the flag is still refused by the role gate (stage 10 item 1).

## Known issues (2026-09-18 evaluation)

- C6 -- the Self Model is volatile: built static at every start, mutated in memory only, never folded from a stream; Reflection's calibration findings and applied patches vanish at the next boot. Open; stage 6 item 1. One visible consequence: `continuity.restarts` is a per-process counter starting at 0 (`service.py:63, 384`), so it reads 1 after every boot.
- C1 -- `learn.self_patch.applied` had no publisher on the real landing path. **Fixed 2026-09-18** (`1e486f1`: `_land` publishes it). Part of the same finding, `compute_gaps` returned two empty lists and `capabilities["tools"]` was never written: **fixed 2026-09-18** (`62318d3`).
- W7 -- `learn.self_patch.reverted` is subscribed here and published by nothing since the PatchPipeline was retired; `self.model.updated` has no subscriber. Allow-listed with reasons (`b5c2671`); the loader's rollback should publish the former (stage 8).
- S6/T1/T10 -- the tools facet stores the proposer-independent `read_only`/`reversibility` from `tool.registered`, but Guardian does not read it; see guardian's contract.

## Planned changes (roadmap)

- Stage 2 item 1: `ToolsFacet` keeps the tool's JSON schema from `tool.registered` (lock `worldmodel` with `contracts`, `execution`).
- Stage 6 item 1, in part, 2026-09-20: the history half of the Self Model IS a fold. Every applied change to competence, limitations, change history and skills is written to `self:changes` by `_record` and folded back at boot by `_replay_self`, so what Sim learnt about itself survives a restart -- before this it woke up every morning having forgotten what it had found it was bad at. Capabilities and goals stay derived (rescanned at boot), because a fold is for what happened and a rescan is for what is. Still open in item 1: Beta posteriors per (task type, strategy) with exponential forgetting, expected calibration error, per-tool p(ok) and latency quantiles from `action.result`, per-provider quality from `verify.result`, and snapshots every N events (the stream is short enough to replay whole today).
- Stage 6 item 3, in part, 2026-09-19: the `home` facet folds `world.camera.event`, `ui.tv.state` and placed `voice.transcript` speakers into an entity table plus a presence belief per (person, area) that halves every 20 minutes; situation facts are pure rules over it, and `world.home.situation_changed` is published when one flips. Nothing is asserted from silence: an entity is `stale` once it is older than its OWN learned window -- three times the median gap between its state CHANGES, floored at 5 minutes and capped at 24 hours (`Entity.typical_change_s`, `stale_after_s`, 2026-09-21), falling back to a flat two hours with fewer than three changes recorded. A door sensor and a thermostat do not go stale at the same speed, and the flat two hours was wrong in both directions. What is learnt is the gap between changes, not between observations: polling a light every ten seconds must not make it look like it changes every ten seconds. The window is on the entity's dict as `stale_after_s`, because reading `stale: false` without knowing what is behind it is why one number went unquestioned. An entity unobserved that long and left out of the prompt block, a person no evidence places is `unknown`, and `nobody_home` is `None` rather than `true` when there is no evidence either way. A presence belief also records whether the evidence was a *verified* identification (a speaker match at confidence >= 0.6, not a lean) -- `saw_person(..., verified=)`, `HomeFacet.verified`, and `verified` in the `world.env.query` reply for a person. Guardian's `PresenceRule` reads it before letting a voice approve anything that reaches outside the house (stage 6 item 5): belief and verification answer different questions, and a television can be mistaken for the creator at 0.5. It is the latest evidence's answer, not a high-water mark. Folding `action.result` of the home tools landed 2026-09-20 (see the row above). Still open: calendar reads, `percept.home.state_changed`, and the per-area transcript ring.
- Stage 6 item 4, in part, 2026-09-19: the `people` facet is the one answer to who somebody is -- a `Person` per household member with their identities (`voice:`, `telegram:`, `whatsapp:`, `cli:`, `ha:`, `email:`), a role (owner/adult/child/guest/unknown) and one memory namespace across every channel. Seeded from `contracts/household.py`, kept as `people.json` in the data dir, resolved by identity; an identity nobody has linked is `None` and `unknown`, never a new person. Still open: resolution at each channel edge, the `people_*` tools, and folding in the speaker book, the allow-lists and `persona/user_model.py`.
- Stage 6 item 4: the People store (`contracts/people.py`) lives here.
- Stage 7 item 9: standing intents evaluated against `world.home.situation_changed` (lock `planning`, `worldmodel`).

## Working on this module

Lock it first (`python tools/modlock.py claim worldmodel --by <you> --task "..."`), commit the lock, edit only `simorgh/worldmodel/`, `tests/simorgh/worldmodel/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py worldmodel` before committing; commit subject `worldmodel: <what changed>`.

- ToolsFacet keeps each tool's `description` and `input_schema` from `tool.registered` (stage 2 item 1).

- Stage 10 item 1, 2026-09-20: the `people` facet keeps what a person said yes to (`grant`/`revoke` of `contracts.people.PERMISSIONS`) and what they care about (`add_interest`/`remove_interest`), through the same `world.people.update` write and the same tier; `consented(name, permission)` answers the grant half and `contracts.people.may_check_in` the whole gate. `world.env.query{what: "people", args: {name}}` answers by name. A fresh install grants nothing. The store never infers a permission from a turn.

- Stage 10 item 2, 2026-09-20: the `wellbeing` facet (`facets/wellbeing.py`). Per person and per feature (`words` = log1p of the turn's word count, `rate` = words per second when spoken, `soft` = whether Sim's reply tone was `warm` or `sorry`) an exponentially-weighted baseline (`Moments`, horizon 100 turns, trusted after `BASELINE_MIN` = 12); each turn after that is a composite z against the baseline (signed so fewer words, slower speech and a softer reply all point down, clipped to ±3, spread floored per feature); a turn at or beyond `Z_EDGE` = 1 is a low-side (or high-side) trial. The state is `Beta(1 + Σ w·low, 1 + Σ w·not-low)` over the kept trials with `w = 0.5 ** (age / HALF_LIFE_S)` (6 h): `low` when the mean ≥ `LOW_AT` (0.5) and the summed weight ≥ `MIN_EVIDENCE` (3), `high` mirrored, `usual` otherwise, `unknown` before the baseline, after `FRESH_S` (24 h) of silence, or under the evidence bar. The baseline learns from a turn after scoring it, so a long change becomes the new usual. `estimate(person)` returns `{state, tracked, low, high, spread, evidence, samples, baseline_turns, last_seen_s, why}`; `now_block(person=)` one line with numbers and no words; `changes()` flips only; `forget(person)` for a revoke. `world.env.query{what: "wellbeing", args: {person}}` returns the estimate plus `note`; without `person`, every tracked person. Consent is a callable the service supplies (`may_check_in(people.by_name(name))`), asked on every observation. Still open: the ledger fold, energy/pitch as further features on the same machinery, a latency feature (needs the turn's timestamps), seeding baselines from an archived ledger.
