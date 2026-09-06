# 06 — World Model and Self Model (`simorgh/worldmodel/`)

> Part of the Simorgh v2 blueprint. Governing documents:
> `01-vision-and-principles.md`, `02-system-architecture.md`,
> `03-contracts-and-messaging.md`. This spec refines them; it may not
> contradict them. Contradictions found while writing are listed in §12.

**Layer:** 1 Cognitive core
**Owner (build):** built (Phase 1 Track C)
**Status:** built -- environment facets and the static Self Model shell; the dynamic Self Model content is Phase 3, not this build (see the spec body)
**Depends on (contracts only):** consumes `world.env.query`, `self.summary`, `self.gaps`, `self.observation`, `tool.registered`, `tool.unavailable`, `persona.user_model.updated`, `learn.competence.updated`, `learn.self_patch.applied`, `learn.self_patch.reverted`, `learn.skill.acquired`, `reflect.calibration.updated`, `reflect.patterns.found`, `reflect.health.finding`, `task.created`, `task.completed`, `task.failed`, `project.completed`, `project.failed`, `plan.approved`, `percept.file.changed`, `system.started`, `system.tick.second`
**v1 code that migrates here:** `src/orchestrator/capability_map.py` (`list_capability_areas`, `list_capability_modules`, `pick_diverse_target`'s inventory half), `_list_source_files` from `src/main.py`, `list_applied_skills` inventory use from `src/agents/skills/registry.py`; identity text loading from `src/orchestrator/soul.py`

## 1. Purpose and responsibilities

The World Model is the system's picture of the environment it acts in
and of itself. The **environment model** answers "what is out there":
the real source tree and its capability areas, the tools currently
registered, git state, the files that changed, and what is known about
the user. The **Self Model** answers "what am I, what can I do, how well,
what have I changed, and what am I unsure about" — as a versioned,
queryable, rendered artifact rather than a feeling. Both are
*projections* built from other subsystems' events; this subsystem owns
the projections, the query API, the token-budgeted `self.summary` every
reasoning call embeds, and `self.gaps`, the input Curiosity samples from.
It is the architectural home of self-awareness (`AGI-03` §9, `01` §1).

**Responsibilities (owns):**
- Env facets and `world.env.query`: `capability_map`, `file_index`, `tools`, `git_state`, `user_profile`.
- `world.env.observed` events when a facet materially changes.
- The Self Model stream `self:model`, its JSON schema, versioning, and the `data/self/SELF.md` rendering.
- `self.summary` (budgeted, cached per version) and `self.gaps`.
- Ingesting the events that change the Self Model and emitting `self.model.updated`.

**Explicit non-responsibilities (belongs elsewhere):**
- *Producing* observations about the self (calibration, limitations, drift, health) → Reflection is the writer of record; World Model integrates.
- Competence math and change history *facts* → Learning emits them; World Model records and renders.
- Predictive simulation of code changes → not in v2 (the isolated test suite in Verification is the "what happens if" oracle for code; see §7).
- Deciding what to explore → Curiosity (consumes `self.gaps`).
- Persona identity *text* and emotional state → Persona; the Self Model quotes identity by reference.

**Principles this subsystem is the primary enforcer of:** 4.12 (transparent, file-based self-knowledge), 4.13 (diversity by construction — it supplies the real inventories), 4.4 (self model as a recomputable projection).

## 2. Position in the architecture

Layer 1. Participates in Flows 1 (self summary), 2 (self summary,
env queries, competence update), 4 (change history), 7 (continuity
observation), 8 (limitations from patterns), 9 (`self.gaps`,
`capability_map`). Imports only `simorgh.contracts`, bus/ledger clients,
stdlib, itself. Reading the repository tree and `git` state is done by
*this* subsystem directly because it is read-only observation of its own
host, not an action (analogous to Memory's index); anything that would
modify the tree is Execution's.

## 3. Interfaces

### 3.1 Messages consumed
| Type | Pattern | Semantics | What this subsystem does with it |
|---|---|---|---|
| `world.env.query` | exact | request | Serve a facet |
| `self.summary` | exact | request | Render/cached summary within `budget_tokens` |
| `self.gaps` | exact | request | Weakest competences + least-explored areas |
| `self.observation` | exact | event | Append to `self:model` under the observation's section (from Reflection; also Kernel restart via Reflection) |
| `tool.registered` / `tool.unavailable` | exact | event | Update `tools` facet and Self Model capability inventory |
| `persona.user_model.updated` | exact | event | Update `user_profile` facet |
| `learn.competence.updated` | exact | event | Update competence table |
| `reflect.calibration.updated` | exact | event | Update calibration per task type |
| `learn.self_patch.applied` / `.reverted` / `learn.skill.acquired` | exact | event | Append to change history; refresh capability inventory |
| `reflect.patterns.found` / `reflect.health.finding` | exact | event | Append limitations / stability notes |
| `task.created` / `task.completed` / `task.failed` / `project.*` / `plan.approved` | exact | event | Maintain "current goals/projects" and exploration coverage per area |
| `percept.file.changed` | exact | event | Invalidate `file_index`/`capability_map` cache; `world.env.observed` if a module was added/removed |
| `system.started` / `system.tick.second` | exact | event | Continuity record; every 60 s refresh `git_state` |

### 3.2 Messages produced
| Type | Semantics | Payload summary | Consumers |
|---|---|---|---|
| `world.env.query.reply` | reply | `{ok, facet, data, as_of}` | requester |
| `world.env.observed` | event | `{facet, summary, ref, diff?}` | reflection, interface, curiosity |
| `self.summary.reply` | reply | `{ok, text, version, tokens}` | cognition (assembler), interface |
| `self.gaps.reply` | reply | `{ok, gaps:[{competence, task_type, score, samples}], unexplored_areas:[{area, modules, last_touched, tasks_ever}], version}` | curiosity |
| `self.model.updated` | event | `{version, changed_sections:[...], reason}` | reflection, interface (vitals), curiosity |
| `system.health` | event | degraded if the tree/git cannot be read | kernel |

### 3.3 Request/reply APIs served
- `world.env.query {what: capability_map|file_index|tools|git_state|user_profile, args?}` → reply; ≤ 200 ms (cached; `file_index` rescan ≤ 2 s on cold cache). Failure `error.code: unknown_facet|unavailable`.
- `self.summary {budget_tokens}` → `{text, version, tokens}`; ≤ 20 ms cached, ≤ 200 ms on re-render.
- `self.gaps {k}` → as above; ≤ 50 ms.

### 3.4 Python protocol (`api.py`)

```python
class Facet(Protocol):
    name: str
    async def get(self, args: dict) -> FacetData          # {data, as_of}
    def invalidate(self) -> None

class CapabilityMapFacet(Facet):                         # port of capability_map.py
    def areas(self) -> list[str]                          # top-level src/ dirs with .py, skills excluded
    def modules(self, area: str) -> list[str]             # repo-relative paths
    def coverage(self) -> dict[str, AreaCoverage]         # tasks_ever, last_touched, from task events

@dataclass(frozen=True)
class SelfModel:                                         # the projection; schema in §4
    version: int
    identity: Identity
    capabilities: CapabilityInventory
    competence: dict[str, Competence]                     # task_type → {success_rate, samples, calibration, strategy}
    limitations: list[Limitation]
    change_history: list[Change]
    goals: Goals
    continuity: Continuity
    open_questions: list[OpenQuestion]

class SelfModelProjection:
    def apply(self, event: Event) -> SelfModel | None      # returns new model if changed
    def rebuild(self, events: Iterable[Event]) -> SelfModel

class SelfRenderer:
    def full_markdown(self, m: SelfModel) -> str           # SELF.md
    def summary(self, m: SelfModel, budget_tokens: int) -> str   # ordered sections, truncated by priority

class GapAnalyzer:
    def gaps(self, m: SelfModel, coverage: dict[str, AreaCoverage], k: int) -> Gaps
```

### 3.5 Configuration (`simorgh.toml [worldmodel]`)

| Key | Type | Default | Controls |
|---|---|---|---|
| `repo_root` | path | cwd | Tree scanned for `capability_map`/`file_index` |
| `excluded_area_parts` | list[str] | `["skills"]` | v1 exclusion |
| `file_index.max_files` | int | 5000 | Scan bound |
| `git.refresh_seconds` | float | 60 | `git_state` polling |
| `self.render_path` | path | `<data_dir>/self/SELF.md` | Rendered projection |
| `self.summary_cache_size` | int | 8 | Per (version, budget) |
| `self.summary_section_priority` | list[str] | identity, competence, limitations, goals, capabilities, change_history, continuity, open_questions | Truncation order (last dropped first) |
| `gaps.min_samples` | int | 3 | Competence considered only with ≥ samples |
| `gaps.unexplored_after_seconds` | float | 604800 | Area counts as unexplored if untouched this long |
| `identity.soul_path` | path | `docs/SOUL.md` | Identity source (read-only) |

## 4. Data model and Ledger streams

| Stream | Events | Notes |
|---|---|---|
| `self:model` | `section.updated {section, patch, reason, source_ref}`; `version.bumped {version, changed_sections}`; snapshot every 200 events | The Self Model is exactly the fold of this stream |
| `world:env` | `facet.observed {facet, summary, ref, diff}` | Material changes only |
| `world:coverage` | `area.touched {area, module, task_id, kind}` | Exploration coverage per area (from task events) |

**Self Model JSON schema (v1, abridged but exact in field names):**

```json
{
  "version": 42,
  "updated_at": 1788700000.0,
  "identity": {"name": "Simorgh", "soul_sha256": "…", "directives": ["Safety","Lawfulness","Loyalty","Corrigibility","Restraint","Stability","Growth","Transparency"], "summary": "…one paragraph from SOUL.md Identity…"},
  "capabilities": {
    "tools": [{"name": "read_file", "read_only": true, "provider": "builtin"}],
    "skills": [{"name": "github_skill", "path": "src/agents/skills/github_skill.py", "tests": 4}],
    "providers": [{"name": "claude_code_cli", "available": true}],
    "areas": ["agents","cognition","memory","orchestrator","sandboxing","tools"]
  },
  "competence": {
    "patch": {"success_rate": 0.71, "samples": 58, "calibration": {"stated": 0.80, "empirical": 0.71}, "best_strategy": "search_replace_for_large_files", "trend": "+0.06/30d"},
    "research": {"success_rate": 0.93, "samples": 14, "calibration": null, "best_strategy": null, "trend": "flat"}
  },
  "limitations": [{"id": "lim-17", "text": "Full-file rewrites of modules over ~100 lines rarely produce valid Python", "evidence": ["memory:episodic#4411"], "since": 1788600000.0, "status": "mitigated", "mitigation": "SEARCH/REPLACE edit mode"}],
  "change_history": [{"ts": 1788690000.0, "kind": "self_patch", "subject": "src/cognition/provider.py", "commit": "289ea9d", "summary": "CostTier-aware provider selection", "tests": {"baseline": 820, "patched": 820}}],
  "goals": {"active_projects": [{"project_id": "p9", "goal": "…", "done": 2, "total": 4}], "pending_tasks": 3, "recent_focus_areas": ["cognition","memory"]},
  "continuity": {"started_at": 1788699000.0, "restarts_24h": 3, "last_restart_reason": "self_patch relaunch", "uptime_seconds": 1000},
  "open_questions": [{"id": "oq-4", "text": "Is my review verdict calibrated for research findings?", "raised_by": "reflection", "ts": 1788699500.0}]
}
```

**Example `SELF.md`** (rendered projection; regenerated on every version bump):

```markdown
# Simorgh — Self Model (v42, 2026-09-06 01:12)

## Who I am
Simorgh: a self-improving agent under the creator's authority; directives in order: Safety, Lawfulness, Loyalty, Corrigibility, Restraint, Stability, Growth, Transparency. (SOUL.md sha 3f9a…)

## What I can do
Tools: read_file, list_dir, web_fetch, run_python_sandboxed, apply_source_patch, git_commit (+9). Skills: 23 applied (github_skill, scheduler, …). Providers: claude_code_cli (available), gemini (available), floor.
Areas of my own code: agents, cognition, memory, orchestrator, sandboxing, tools.

## How well I do it
| task type | success | samples | stated→empirical confidence | best strategy | trend |
| patch | 71% | 58 | 80% → 71% (overconfident) | SEARCH/REPLACE for large files | +6%/30d |
| research | 93% | 14 | — | — | flat |

## What I know I'm bad at
- lim-17 (mitigated): full-file rewrites of modules over ~100 lines rarely produce valid Python → SEARCH/REPLACE edit mode.
- lim-21 (open): my review pass sometimes narrates instead of answering; verdict parsing defers, but calibration is unknown.

## What I've changed about myself (last 10)
- 2026-09-05 23:47 self_patch src/cognition/provider.py (289ea9d) — CostTier-aware provider selection; tests 820→820
…

## What I'm working on
Projects: p9 "make memory genuinely self-correcting" (2/4). Pending tasks: 3. Recent focus: cognition, memory.

## Continuity
Started 01:00; 3 restarts in 24 h (last: self_patch relaunch).

## Open questions about myself
- oq-4: Is my review verdict calibrated for research findings? (reflection)
```

Files owned: `<data_dir>/self/SELF.md` (rendered; never the source of
truth). Caches (non-Ledger, justified): facet caches with TTL/invalidation;
summary cache per `(version, budget)`.

## 5. Internal design

```
worldmodel/
  service.py          handlers, lifecycle, git polling
  api.py
  config.py
  facets/
    capability_map.py  v1 port (areas/modules) + coverage join
    file_index.py      tree scan → {path, size, sha256?, mtime}; incremental on percept.file.changed
    tools.py           from tool.registered/unavailable
    git_state.py       `git rev-parse/status/log -5` via to_thread (read-only)
    user_profile.py    from persona.user_model.updated
  selfmodel/
    schema.py          dataclasses + JSON Schema
    projection.py      SelfModelProjection (fold of self:model)
    ingest.py          event → section.updated mapping rules (§5 table)
    render.py          SelfRenderer (SELF.md + budgeted summary)
    gaps.py            GapAnalyzer
```

**Ingestion rules (event → Self Model section):**

| Event | Section | Rule |
|---|---|---|
| `tool.registered/unavailable`, `learn.skill.acquired` | capabilities | replace entry; bump version |
| `learn.competence.updated` | competence[task_type] | set rate/samples; recompute trend from the last 30 d of `section.updated` for that key |
| `reflect.calibration.updated` | competence[task_type].calibration | set stated/empirical; flag `overconfident` if stated−empirical > 0.1 |
| `self.observation{kind:limitation}` | limitations | add or update by fuzzy match (difflib ≥ 0.6) — never duplicate |
| `self.observation{kind:success|failure|change}` | change_history / competence evidence | append (bounded 500; older summarized into a count) |
| `reflect.patterns.found` | limitations (status open) | one entry per pattern with proposal |
| `learn.self_patch.applied/reverted` | change_history; limitations (if `reason` names one → status mitigated) | append |
| `task.*`, `project.*`, `plan.approved` | goals; `world:coverage` | maintain active list; `area.touched` from `subject` |
| `system.started`, `self.observation{kind:restart}` | continuity | restart counters |
| `reflect.health.finding{critical}` | continuity.notes, open_questions | add |

Every applied rule appends `section.updated` and, if any section
changed, `version.bumped`; `self.model.updated` is emitted once per
version (coalesced within 500 ms so a burst of events yields one bump).

**Summary rendering under budget:** sections rendered in priority
order; the table in *competence* is trimmed to the 5 task types with
the most samples; *change_history* to 3 entries; then whole sections
dropped from the tail until under budget; the version and a
`[truncated: …]` marker are always included so Cognition can report
what the model saw.

**Gap analysis** (`self.gaps`): competences with `samples ≥ min_samples`
sorted by `success_rate` ascending, then by `overconfident` flag; areas
from `capability_map` joined with `world:coverage` sorted by
`last_touched` ascending (never-touched first), returning modules so
Curiosity's sampler can pick within an area. This is the *inventory*
half of v1 `pick_diverse_target`; the random *choice* stays in Curiosity.

**Concurrency:** one projection writer task fed from `ledger.tail(self:model)`
so multiple processes converge on the same model; handlers append
events and never mutate the projection directly; facet refreshes run in
`to_thread`. `start()` loads snapshot + tail, renders `SELF.md`;
`stop()` cancels tasks; `health()` reports projection lag and facet
errors.

## 6. Key behaviors — worked scenarios

**S1 — A reasoning call embeds the self summary (Flow 1/2).**
Cognition sends `self.summary{budget_tokens:300}`; cache miss for
(v42, 300); renderer emits identity (1 line), competence (2 rows),
limitations (2), goals (1), drops capabilities/change_history/
continuity/open_questions with `[truncated: capabilities, change_history, continuity, open_questions]`;
reply `{text, version:42, tokens:287}` in 11 ms; cached.

**S2 — A self-patch lands and changes what the system knows about
itself (Flow 4).** `learn.self_patch.applied{subject:"src/memory/long_term.py", commit:"d65fff1", reason:"confidence/decay scoring"}`
→ ingest appends `section.updated{section:"change_history"}`;
`learn.competence.updated{task_type:"patch", success_rate:0.72, samples:59}`
→ `section.updated{competence.patch}`; both within 500 ms →
`version.bumped{43, ["change_history","competence"]}`,
`self.model.updated{version:43, reason:"self_patch applied"}`,
`SELF.md` re-rendered. Interface's vitals shows "changes to self: 18".

**S3 — Curiosity asks where to look (Flow 9).** `self.gaps{k:5}` →
competence `patch` (0.72, overconfident) and `decompose` (0.50, 4
samples) lead; `world:coverage` shows `sandboxing` untouched for 21
days and `tools` never; reply lists both with modules
`["src/sandboxing/sandbox.py"]`, `["src/tools/web_fetch.py"]`.
Curiosity samples `tools` (weight: never-touched > gap), then asks
Cognition for one improvement to `web_fetch.py`.

**S4 — Degradation: repository unreadable, git missing.** On a host
without `git`, `git_state.get()` returns `{available:false}` and the
facet is served as such (no exception); `system.health{degraded,
"git unavailable"}` once. A `world.env.query{what:"file_index"}` when
`repo_root` does not exist replies `ok:false, error.code=unavailable`.
The Self Model still serves from the Ledger; the `areas` capability
list is empty and the summary says so — an honest floor, not a
fabricated inventory. Duplicate `learn.competence.updated` events
(redelivery) apply idempotently because the rule sets, rather than
increments, the values.

## 7. Design considerations and tradeoffs

- **Self-awareness as a projection, not a prompt.** `AGI-03` §9 and
  `AGI-02` §4: robustness to novelty depends on calibrated
  self-knowledge; making the Self Model a fold of real events (from
  Learning, Reflection, Verification) means the system's "I am
  overconfident at patches" is a measured fact, and `01` §2.1's promise
  that generality is a queryable number is kept.
- **World Model without prediction.** `AGI-04` §2 puts prediction at the
  heart of a world model; v2 deliberately scopes the environment model
  to *observation* (tree, tools, git, user) and delegates "what happens
  if I change this code" to Verification's isolated test suite — the
  most reliable predictor available for this domain. A learned
  predictive model is a later subsystem behind `world.env.query`.
- **Inventory here, choice in Curiosity** (principle 4.13): keeping
  the sampler out of this subsystem keeps World Model pure and testable
  and keeps the diversity policy where motivation lives.
- **Budgeted summary with an explicit truncation marker.**
  `harness-01` context principles: the persistent self block is
  protected in Cognition, so it must be small and must say what it
  omitted, or the model will reason on a silently-partial self.
- **Reflection writes, World Model integrates.** One writer of record
  for observations avoids two subsystems arguing about the self
  (`harness-05` §7: derived views recomputable from one record).
- **Alternatives rejected:** storing the Self Model as a mutable JSON
  file (breaks replay and audit; violates 4.4); letting every subsystem
  edit the Self Model (no single source of truth); a learned world
  model in v2 (no data, no evaluation harness yet).

## 8. Safety, degradation, and failure modes

| Condition | Behavior |
|---|---|
| Ledger unavailable | Serve last projection and cached facets (`health` degraded); ingestion buffered ≤ 500 events then dropped with a health event (the source events remain in their own streams and are re-folded on recovery via tail replay) |
| Malformed event | Ignored with a logged warning; projection unchanged |
| Handler crash | Kernel restarts the writer task from last applied seq |
| Restart | Snapshot + tail rebuild; `SELF.md` re-rendered; continuity restart counter via Reflection's `self.observation{restart}` |
| Duplicate events | Rules are set-based/idempotent; change_history dedupes on `(kind, subject, commit)` |
| Oversized inventories | Summary truncation; `file_index` bounded by `max_files` |
| Prompt injection in file names/user profile | Rendered inside labeled blocks; never executed; user profile values are quoted |
| `system.pause/stop` | Read-only service continues answering during pause; stop flushes snapshot and renders `SELF.md` |
| Identity file tampering | `soul_sha256` recorded per version; a change triggers `self.observation`-style note and `world.env.observed{facet:"identity"}` for Reflection/Guardian (Guardian protects `SOUL.md` from the system itself) |

Guaranteed floor: with no repository, no git, and no provider, the Self
Model still folds from the Ledger and serves identity + competence +
limitations.

## 9. Testing strategy

- Contract tests for all produced types; each consumed type with valid/invalid payloads.
- Unit: `capability_map` (port v1 tests: areas, modules, skills exclusion, empty tree), `file_index` (bounds, incremental invalidation), `git_state` (absent git), `tools`/`user_profile` facets; `SelfModelProjection` (each ingestion rule; idempotence; version coalescing; limitation fuzzy-merge); `SelfRenderer` (priority truncation, marker, budget adherence, `SELF.md` golden file); `GapAnalyzer` (ordering, `min_samples`, never-touched first).
- Integration: `test_flow_9_gaps_feed_curiosity` (with a fake curiosity), `test_flow_4_self_patch_updates_self_model`, `test_flow_7_self_model_rebuild_after_restart` (sqlite ledger), `test_self_summary_is_protected_size` (with cognition's assembler).
- Property: `rebuild(events) == fold(apply, events)`; summary tokens ≤ budget for random models; rendering is deterministic per version.
- Mocks: temp repo trees; `FakeClock`; no git subprocess in unit tests (facet interface mocked), one integration test with real `git` skipped if absent.

## 10. Build steps (an agent picks this up here)

Size: **M**. Parallelizable within: (facets) ∥ (selfmodel schema/projection/ingest) ∥ (render/gaps).

1. Skeleton, config, registry, boundary/contracts tests. *Accept:* self-check boots.
2. `facets/capability_map.py` port + tests; `file_index`, `tools`, `git_state`, `user_profile`; `world.env.query` handler. *Accept:* facet tests; S4 unavailable paths.
3. `selfmodel/schema.py` + JSON Schema + validation tests.
4. `projection.py` + `ingest.py` rules + coalesced `version.bumped`/`self.model.updated`. *Accept:* rule tests; property test.
5. `render.py` (SELF.md golden, budgeted summary) + `self.summary` handler with cache. *Accept:* S1 test.
6. `gaps.py` + `world:coverage` from task events + `self.gaps` handler. *Accept:* S3 test.
7. `world.env.observed` on material facet change; `percept.file.changed` invalidation. *Accept:* observed-event tests.
8. Integration scenarios; `src/orchestrator/capability_map.py` adapter; README; EVOLUTION milestone.

## 11. Migration notes

- `capability_map.list_capability_areas/modules` → `facets/capability_map.py` unchanged; `pick_diverse_target` splits: inventory + coverage here, random choice in Curiosity (`13-curiosity.md`).
- `_list_source_files` (main.py) → `file_index` facet (`args:{under:"src", exclude_skills:true}`).
- `list_applied_skills` consumers → `capabilities.skills` via `learn.skill.acquired` + a start-time scan of the skills dir (through Learning's `tool.registered`, not a direct import).
- `soul.py` identity loading → `identity` section (read-only, hashed).
- Behavior change: none for facets; the Self Model is new (v1 had no equivalent beyond the persona prompt and `growth` command).

## 12. Open questions

1. **Contract gap:** `03` §4.10 `self.gaps.reply` lacks `unexplored_areas[].modules/last_touched/tasks_ever` and `version`; `world.env.query` needs `facet`/`as_of` in the reply. *Default:* optional fields.
2. Should World Model read the repo tree directly (this spec) or request it via an Execution read-only tool? *Default:* directly — it is observation of the host, bounded and read-only, and Execution's tools are for *actions* on the action path; revisit if multi-host deployment separates the tree from this process.
3. Change-history bound (500 entries then summarized counts). *Default:* as stated; full history remains in Learning's streams.
4. Limitation fuzzy-merge threshold (0.6 difflib). *Default:* as stated; Reflection may supersede by id.
5. Whether `SELF.md` should be committed to the repository for the creator's visibility. *Default:* no — it lives in the data dir; Interface exposes it via a `self` command.
