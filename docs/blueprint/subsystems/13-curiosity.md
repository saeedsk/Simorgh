# 13 — Curiosity (`simorgh/curiosity/`)

> Part of the Simorgh v2 blueprint. Governing documents:
> `01-vision-and-principles.md` (principles), `02-system-architecture.md`
> (position and flows), `03-contracts-and-messaging.md` (envelope, topics,
> delivery semantics, protocols). A spec may refine those documents; it
> may not contradict them. If you find a contradiction, fix the governing
> document and note it in `00-README.md`'s changelog.

**Layer:** 3 Growth
**Owner (build):** unassigned
**Status:** draft
**Depends on (contracts only):** `system.tick.idle`, `system.tick.sleep`, `system.state.changed`, `task.created`, `task.completed`, `task.failed`, `task.blocked`, `project.completed`, `project.failed`, `learn.competence.updated`, `learn.self_patch.applied`, `learn.skill.acquired`, `reflect.calibration.updated`, `cognition.provider.status`, `persona.state.changed`, `action.result`, `action.denied`, `percept.text.received` (interest commands, via Interface), `self.gaps` (request), `world.env.query` (request), `cognition.think` (request)
**v1 code that migrates here:** `src/main.py` (`discover_creative_improvements`, `discover_creative_project`, `_creative_agenda_already_covered`, `_parse_targeted_idea`, `_CREATIVE_AGENDA_PROMPT`, `_PROJECT_AGENDA_PROMPT`, `DEFAULT_CREATIVE_PROJECT_CHANCE`, `note_interest`, `news_command`, `growth_command`, `_maybe_volunteer_during_conversation`), `src/orchestrator/capability_map.py` (`pick_diverse_target` policy; the listings themselves move to World Model), `src/agents/interests.py` (`InterestTracker`, `RssWorldFeed`, `DEFAULT_NEWS_TOPICS`), `src/orchestrator/socializing.py` (`GrowthSocializer`, `NewsSocializer`, cooldowns)

## 1. Purpose and responsibilities

Curiosity is why Simorgh does anything when nobody asked. It is the
subsystem for intrinsic motivation (AGI-02 §3 "self-directed goal
generation"; AGI-03 §10) — the drives that turn an empty backlog into a
next thing worth doing: a competence gap the Self Model exposes, an area
of the codebase nothing has touched in a while, an interest the creator
seeded, or plain boredom after a long idle. Its defining discipline is
**diversity by construction** (principle 4.13): Curiosity chooses *where
to look* by structured sampling over real inventories, and only then
asks a model to propose *one* idea for that place. The model is never
asked "what should I improve?" in the open, because the live-caught
answer to that question was a dozen paraphrases of the same idea.

**Responsibilities (owns):**
- The drives and their weights: competence gaps, novelty/staleness, interests, boredom; modulated by mood and by budget pressure.
- Diversified target selection and the single-target idea prompt → `curiosity.candidate` (PATCH or RESEARCH).
- Rare, bounded project proposals → `intent.goal.stated{origin: curiosity}`.
- Interests: tracking topics, following up feeds (via `web_fetch` proposals), `curiosity.interest.updated`.
- Proactive sharing decisions (growth and news, with cooldowns) → `curiosity.share.proposed`; Persona decides *how* to say it.
- The explore/exploit balance: how much of idle time is spent exploring versus letting Planning work an existing backlog.

**Explicit non-responsibilities (belongs elsewhere):**
- Deduplicating candidates against the backlog — **Planning** (07) owns the fuzzy-similarity check on `task.created`; Curiosity keeps only a short local memory to avoid resending the same candidate within a session.
- Listing the codebase's areas/modules, competence gaps — **World Model** (06); Curiosity queries them.
- Running any task, including research — **Orchestration** (16).
- Fetching a feed — **Execution** (`web_fetch` tool) after Guardian approval.
- Rendering or timing the *delivery* of a share — **Persona** (14) and **Interface** (15).
- Deciding whether the backlog is "empty enough" to explore is *shared*: Planning publishes task lifecycle events; Curiosity maintains its own projection of unfinished counts from them.

**Principles this subsystem is the primary enforcer of** (from `01` §4): 4.13 (diversity by construction), 4.5 (a floor tick proposes nothing rather than a templated idea), 4.6 (explores within a budget; backs off under provider pressure).

## 2. Position in the architecture

Layer 3. Participates in Flow 1 (volunteering a share after a turn), Flow 2 (the source of tasks when the backlog is empty), Flow 3 (rare project proposals), Flow 8 (interest decay, drive recomputation), Flow 9 (owner). Imports only `simorgh.contracts`, bus/ledger clients, stdlib.

## 3. Interfaces

### 3.1 Messages consumed

| Type | Pattern | Semantics | What this subsystem does with it |
|---|---|---|---|
| `system.tick.idle` | event | schedule | If the backlog projection is empty and not paused: run one exploration tick (§5.3); else update boredom |
| `system.tick.sleep` | event | schedule | Decay interest scores; recompute area staleness from Ledger; snapshot drives |
| `system.state.changed` | event | lifecycle | `paused`/`stopping`: no ticks, no proposals |
| `task.created` / `task.completed` / `task.failed` / `task.blocked` | event | fact | Backlog projection; area staleness (a completed patch in area A refreshes A); `task.created{origin: curiosity}` echo confirms a candidate was accepted (dedupe outcome) |
| `project.completed` / `project.failed` | event | fact | Clears the "active project" flag that gates project proposals |
| `learn.competence.updated` / `reflect.calibration.updated` | event | fact | Cache gaps locally (the authoritative list still comes from `self.gaps`) |
| `learn.self_patch.applied` / `learn.skill.acquired` | event | fact | Growth-highlight buffer for sharing |
| `cognition.provider.status` | event | fact | Budget pressure → exploration rate scaling (§5.6) |
| `persona.state.changed` | event | fact | Mood modulation: high arousal + positive valence raises exploration temperature slightly; low valence favors consolidation-type (research) candidates over patches |
| `action.result` / `action.denied` | event | fact | Results of `web_fetch` proposals for interests |
| `percept.text.received` | event | input | Only the routed interest commands (`interest <topic>`, `interests`, `curious`, `news`, `growth`) — Interface routes them by publishing with `channel: command` and `command: interest…`; Curiosity ignores plain chat |

### 3.2 Messages produced

| Type | Semantics | Payload summary | Consumers |
|---|---|---|---|
| `curiosity.candidate` | event | `{kind: patch\|research, subject?, description, area, why_this_area, novelty_score, drive: gap\|staleness\|interest\|boredom, provider}` | planning |
| `intent.goal.stated` | event | `{goal, origin: curiosity, priority, wants_project: true, constraints?}` | planning |
| `curiosity.interest.updated` | event | `{topic, last_followed_up, items_found, score}` | interface, memory, worldmodel |
| `curiosity.share.proposed` | event | `{kind: growth\|news, content_ref, summary, cooldown_key}` | persona |
| `action.proposed` | event → guardian | `tool=web_fetch{url}`, `reversibility=read_only`, `scope.network=true` | guardian |
| `memory.store` | command | `{kind: semantic, content: <news item>, tags: [news, <topic>]}` | memory |
| `self.gaps` / `world.env.query` / `cognition.think` | requests | see §5.3 | worldmodel, cognition |

### 3.3 Request/reply APIs served
None. (The `curious`/`news`/`growth` commands are one-shot triggers that produce the same events an idle tick would.)

### 3.4 Python protocol (`api.py`)

```python
@dataclass(frozen=True)
class Drive:
    name: str                 # gap | staleness | interest | boredom
    weight: float             # config
    def score(self, ctx: DriveContext) -> dict[str, float]: ...   # area/target → score in [0,1]

class TargetSampler(Protocol):                     # port of pick_diverse_target
    def pick(self, areas: list[Area], gaps: list[Gap], recent_subjects: list[str], *, rng: random.Random,
             temperature: float) -> Target | None: ...

class IdeaProposer(Protocol):
    async def propose(self, target: Target, content_preview: str, think: ThinkFn) -> Idea | None: ...
    # Idea = {kind: patch|research, description}; NEVER a path — the target is the subject (port _parse_targeted_idea)

class ProjectProposer(Protocol):
    async def propose(self, files: list[str], think: ThinkFn) -> str | None: ...   # a GOAL line or None

class InterestTracker(Protocol):                   # port of agents/interests.py
    def note(self, topic: str) -> Interest: ...
    def least_recently_followed(self) -> Interest | None: ...
    def record_follow_up(self, topic: str, items: list[NewsItem]) -> None: ...
    def decay(self, now: float) -> None: ...

class ShareScheduler(Protocol):                    # port of socializing.py
    def maybe_share(self, kind: str, now: float) -> ShareDecision | None: ...   # cooldowns per kind
```

### 3.5 Configuration

| Key (`[curiosity]`) | Type | Default | Controls |
|---|---|---|---|
| `candidates_per_tick` | int | 2 | v1 `DEFAULT_CREATIVE_AGENDA_COUNT` |
| `recent_subjects` | int | 30 | Subjects avoided by the sampler (v1 `_CREATIVE_AGENDA_RECENT_SUBJECTS`) |
| `drive.gap` / `drive.staleness` / `drive.interest` / `drive.boredom` | float | 0.45 / 0.30 / 0.15 / 0.10 | Drive weights (sum 1.0; the sampler renormalizes) |
| `temperature` | float | 0.7 | Softmax temperature over area scores; 0 → greedy, high → uniform |
| `project_chance` | float | 0.2 | v1 `DEFAULT_CREATIVE_PROJECT_CHANCE`; applied only with no active project |
| `boredom_after_seconds` | float | 1800 | Idle with empty backlog before boredom drive reaches 1.0 |
| `budget.backoff_below_remaining` | float | 0.2 | Fraction of any provider's window remaining below which exploration rate halves |
| `budget.stop_below_remaining` | float | 0.05 | Below this, no candidates (research-only ticks still allowed if a free provider exists) |
| `interest.follow_up_cooldown_seconds` | float | 3600 | Per topic |
| `interest.max_items_per_follow_up` | int | 5 | |
| `interest.default_topics` | list | v1 `DEFAULT_NEWS_TOPICS` | Seeded on first run |
| `share.growth_cooldown_seconds` | float | 900 | v1 `GrowthSocializer` |
| `share.news_cooldown_seconds` | float | 1800 | v1 `NewsSocializer` |
| `mood.arousal_temperature_gain` | float | 0.2 | How much high arousal raises `temperature` |

## 4. Data model and Ledger streams

| Stream | Event types | Payload |
|---|---|---|
| `curiosity:ticks` | `tick` | `{ts, backlog: n, drives: {area: {gap, staleness, interest, boredom, total}}, picked: [target], proposed: [candidate_id], skipped_reason?}` — the audit trail that proves diversity |
| `curiosity:candidates` | `proposed`, `accepted`, `deduped` | `{candidate_id, kind, subject, description, area, drive}`; `accepted/deduped` come from `task.created` echoes |
| `curiosity:interests` | `noted`, `followed_up`, `decayed` | `{topic, score, last_followed_up, items}` |
| `curiosity:shares` | `proposed`, `suppressed` | `{kind, content_ref, cooldown_key, reason?}` |
| `curiosity:projects` | `proposed`, `skipped` | `{goal, reason?}` |

Projections: `BacklogCounter` (from `task.*`), `AreaStaleness` (last touched ts per area, from `task.completed{subject}` and `learn.self_patch.applied`), `InterestTable`, `ShareCooldowns`, `RecentCandidates` (ring of last `recent_subjects` subjects + descriptions), `ActiveProject` flag. All rebuildable from the streams above plus `task.*` history; only the RNG state is not persisted (seeded from config for tests).

## 5. Internal design

```
service.py
  ├── BacklogCounter / AreaStaleness / ActiveProject   (projections from task.*, project.*)
  ├── DriveEngine      { gap, staleness, interest, boredom } → per-area scores, mood- and budget-modulated
  ├── TargetSampler    two-stage: area by softmax(drive scores, temperature) → module uniform among fresh ones
  ├── IdeaProposer     one narrow think per target; parser accepts only PATCH|RESEARCH :: description
  ├── ProjectProposer  rare; GOAL :: … parser
  ├── InterestService  note / follow-up (web_fetch proposals) / decay
  └── ShareScheduler   growth/news cooldowns → curiosity.share.proposed
```

Concurrency: one exploration tick at a time (`asyncio.Lock`); a tick
that is still awaiting Cognition when the next `system.tick.idle`
arrives is not re-entered (the tick is skipped and recorded). Interest
follow-ups run as independent bounded tasks. `start()` rebuilds
projections and seeds default interests if the interest stream is empty;
`stop()` cancels in-flight ticks (recorded `skipped_reason: shutdown`).

### 5.1 Drives (per area, all in [0,1])
- **gap**: from `self.gaps` — `1 − competence` for the area's task types, weighted by sample count confidence; unexplored areas (no samples) get 0.6 (unknown ≠ good).
- **staleness**: `min(1, (now − last_touched) / staleness_horizon)` with `staleness_horizon = 7·86400` by default.
- **interest**: max over tracked interests whose topic lexically matches the area/module names (e.g. an interest in "memory consolidation" boosts `src/memory`), else 0.
- **boredom**: global, `min(1, idle_with_empty_backlog / boredom_after_seconds)`; adds uniformly to every area, flattening the distribution (when bored, wander).
Total per area `= Σ weight_d · d`, then mood modulation: `temperature' = temperature + arousal_gain·max(0, arousal)`; low valence (< −0.4) multiplies the `research` prior in §5.4 by 1.5 (introspective mood → investigate rather than change).

### 5.2 Target sampling (port of `pick_diverse_target`, upgraded)
```
areas  ← world.env.query{what: capability_map}            # real src/ areas and modules
gaps   ← self.gaps{k: 10}
scores ← DriveEngine(areas, gaps, interests, boredom)
area   ← softmax_sample(scores, temperature')             # never argmax: argmax re-creates thematic collapse
modules ← area.modules − recent_subjects                  # fall back to all modules if none fresh
target ← uniform(modules)
```
Two-stage on purpose (v1 docstring): equal first chance per area so a
large area cannot dominate by module count. Every pick, with the full
score table, is appended to `curiosity:ticks`.

### 5.3 The exploration tick (Flow 9)
```
if paused or backlog > 0 or budget_stop: record skipped; return
if not active_project and rng.random() < project_chance: try ProjectProposer (S3); if it produced a goal → return
for i in range(candidates_per_tick):
    target ← TargetSampler.pick(...)
    preview ← world.env.query{what: file_index, args: {path: target, max_chars: 4000}}     # bounded read via World Model's index, no action needed
    idea ← IdeaProposer.propose(target, preview, think)                                     # floor → None, no candidate
    if idea and not RecentCandidates.similar(idea.description):
        emit curiosity.candidate{subject: target (ALWAYS the sampled target), kind, description, area, drive, novelty}
        RecentCandidates.add(target, idea.description)
record tick
```
The prompt is v1's `_CREATIVE_AGENDA_PROMPT` verbatim in spirit: the
target is stated, the model is told it was chosen deliberately, and the
only accepted reply is `PATCH :: …` or `RESEARCH :: …` — any path the
model states is ignored (`_parse_targeted_idea`).

### 5.4 Project proposals (port of `discover_creative_project`)
Gated by `not active_project` and `project_chance`. One open-ended
`cognition.think` with the file listing (this is deliberately the one
place a model picks its own focus — a project spans targets, `02` Flow
9). Parse `GOAL :: …`; emit `intent.goal.stated{wants_project: true}`;
set `active_project` optimistically until Planning's `task.created{kind:
project}` echo (or a 60 s timeout clears it). The provider-sink lesson
(v1 milestone 96): a real call spent on a failed project attempt still
counts as "attempted" for the tick's budget accounting even if the
fallback candidate loop then proposes nothing.

### 5.5 Interests and news (port of `interests.py`)
`interest <topic>` → `InterestService.note`; `curious` / an idle tick with
`interest` as the winning drive → pick `least_recently_followed()` past
its cooldown → `action.proposed{tool: web_fetch, url: feed}` (RSS feeds
from `default_topics` or a topic-derived feed) → on `action.result`,
parse items (v1 `RssWorldFeed`), store the best `max_items_per_follow_up`
as `memory.store{kind: semantic, tags: [news, topic]}`, emit
`curiosity.interest.updated`, and offer one as a share. Denied fetches
(Guardian: network scope) are recorded and the interest's score decays
faster (it can't be pursued).

### 5.6 Explore/exploit and budget awareness
Exploration rate `r ∈ [0,1]` scales `candidates_per_tick` and
`project_chance`: `r = 1` normally; `r = 0.5` when any real provider's
`remaining_fraction < backoff_below_remaining`; `r = 0` below
`stop_below_remaining` (research candidates still allowed if a provider
reports `free: true`). Planning's backlog is the exploit side: Curiosity
never proposes while unfinished work exists — the harness works the
backlog first (harness-02 "start with a workflow").

### 5.7 Sharing (port of `socializing.py`)
After a turn (Flow 1) or on an idle tick, `ShareScheduler.maybe_share`
checks growth first (a `learn.self_patch.applied`/`learn.skill.acquired`
newer than the last growth share, past cooldown), then news (a stored
item newer than the last news share). Emits `curiosity.share.proposed`;
Persona phrases and Interface delivers. Suppressions are logged so "why
didn't it tell me" is answerable.

## 6. Key behaviors — worked scenarios

**S1 — A diversified tick (Flow 9).** Backlog empty for 4 minutes;
`self.gaps` says `patch:src/persona` competence 0.35 (n=8),
`patch:src/memory` 0.8; staleness: `src/tools` untouched 9 days.
Scores: persona 0.62, tools 0.48, memory 0.21, others ≈0.3. Softmax at
T=0.7 picks `persona` (p≈0.42); fresh modules → `src/persona/voice.py`.
Preview fetched from the World Model index; think replies
`RESEARCH :: does voice styling degrade when cognitive load is high?`
→ `curiosity.candidate{kind: research, subject: src/persona/voice.py,
drive: gap}`. Second candidate: sampler picks `tools` (staleness) →
`PATCH :: add a retry with backoff to web_fetch on 429`. Both appended
to `curiosity:ticks` with the score table; Planning dedupes and creates
two tasks; echoes mark both `accepted`.

**S2 — The model tries to redirect and is ignored.** Target
`src/kernel/scheduler.py`; reply `PATCH :: src/cognition/router.py ::
add ensemble routing`. The parser yields kind=patch, description
"src/cognition/router.py :: add ensemble routing"; the candidate's
`subject` is still `src/kernel/scheduler.py`. Planning's dedupe will
likely reject it as near-duplicate of an existing routing task; the
tick record shows the attempt. Diversity survives model
non-compliance by construction, not by prompt.

**S3 — A rare project proposal (Flow 3 entry).** No active project;
`rng.random()=0.11 < 0.2`. ProjectProposer asks for one ambitious goal;
reply `GOAL :: make Simorgh's memory retrieval measurably better on
long conversations`. Emit `intent.goal.stated{origin: curiosity,
wants_project: true}`; `active_project=true`; Planning creates the
project and decomposes it (Flow 3); `task.created{kind: project}` echo
confirms. Curiosity proposes no candidates on this tick — the project's
children are the backlog now.

**S4 — Failure: budget pressure and a floor reply.** `cognition.provider.status`
reports `claude_code_cli remaining_fraction 0.03` and `gemini 0.15`; `r`
= 0 for paid patches. A tick runs with `candidates_per_tick=0` for patch
kinds; a research candidate is still attempted because Gemini reports
`free: false` — so nothing is proposed, `skipped_reason: budget`. Later
the think for a target returns `floor: true` (both providers down): no
candidate, no templated idea, `curiosity:ticks` records `floor`.

**S5 — Interest follow-up denied.** `curious` → least-recent interest
"space" → `action.proposed{web_fetch nasa.gov/rss}`; Guardian is in
`plan` mode (network denied) → `action.denied{layer: policy}`;
Curiosity records `followed_up{items: 0, denied: true}`, decays the
interest, and emits `curiosity.interest.updated` so Interface can show
"couldn't follow up on 'space' — network is off in plan mode."

## 7. Design considerations and tradeoffs

- **Sample the area, then ask** (principle 4.13; harness-06; v1 milestones 95–96). The alternative — one open-ended prompt — is cheaper by one call per candidate and produced the thematic collapse this design exists to prevent. Cost accepted.
- **Softmax over argmax**: greedy on drive scores would fixate on the single weakest area until it improves, which is a slower, one-dimensional form of the same collapse. Temperature makes the distribution a knob (and lets mood matter without being decisive).
- **Curiosity does not dedupe against the backlog** (harness-05 §2 "the plan lives in the durable store"): Planning sees every task ever; Curiosity would need a copy. It keeps a short session ring only to avoid obviously wasteful resends.
- **Drives read the Self Model, not the Ledger directly** (AGI-04 §7): what counts as a "gap" is Reflection's and Learning's conclusion; Curiosity consumes it. This keeps one definition of competence.
- **Budget-aware exploration** (harness-01 "context/cost as a scarce resource"; v1's `attempted_creative` cooldown lesson): exploration is the first thing to slow under pressure, before any backlog work does.
- **Projects are rare by design** (`02` Flow 9; harness-03 "when a task is really a project"): a project holds the backlog until done; proposing them often would starve the steady stream of small diversified work.
- **Interests are the creator's voice in the drives** (BIOMIMICRY "companion framing"): a seeded topic biases exploration toward what the creator cares about without overriding gaps — the weight is deliberately the smallest of the four.

## 8. Safety, degradation, and failure modes

- **Provider down / floor**: no candidates, no project, no share text — ticks are recorded as `floor`. Interests still decay; sharing of already-stored items still works (no model needed).
- **World Model unavailable** (`world.env.query` timeout): the sampler falls back to the last snapshot of areas from `curiosity:ticks`; if none, skip the tick.
- **Malformed replies**: `_parse_targeted_idea` returns None → no candidate; never a fabricated one.
- **Guardian denials**: only `web_fetch` is ever proposed; a denial is a data point (interest decay), never retried in the same tick.
- **Duplicates**: candidate ids are deterministic (`sha256(target|description)`), so a redelivered tick cannot double-propose; `task.created` echoes are idempotent by `candidate_id`.
- **Handler crash mid-tick**: the lock releases; the partial tick is recorded on the next `start()` as `skipped_reason: crash`.
- **Corrigibility**: `paused` → no ticks, no proposals, no fetches; `stopping` → cancel. Curiosity never blocks shutdown and never proposes anything but `web_fetch`.
- **Never** proposes a `PATCH` to a protected subject: the World Model's capability map excludes them, and Planning re-checks; if a protected path somehow arrives as a target, the candidate is dropped (the v1 live-caught waste of three real calls on `self_patch.py`).

## 9. Testing strategy

- Contract tests for all produced/consumed types.
- Unit: `DriveEngine` (each drive's arithmetic; unknown-area gap 0.6; mood modulation bounds; weight renormalization), `TargetSampler` (two-stage; avoidance; fallback when all modules recent; seeded RNG determinism; softmax at T→0 and T→∞), `IdeaProposer` parser (PATCH/RESEARCH, restated-path ignored, garbage → None, floor → None), `ProjectProposer` (GOAL parse; provider-sink OR), `InterestService` (note/decay/cooldown/least-recent; RSS parsing from v1 tests), `ShareScheduler` (growth-before-news; cooldowns), backlog/active-project projections.
- **Property/invariant (the repetition regression)**: with a fake provider that always answers a fixed `PATCH :: …` for any target, over 20 ticks with a 6-area map and empty backlog, (a) no two accepted candidates in one tick share an area, (b) every area is picked at least once, (c) no candidate's `subject` equals a path stated in the model's reply when it differs from the target. Also: "no `curiosity.candidate` is emitted while `BacklogCounter > 0`"; "no `action.proposed` other than `web_fetch`".
- Integration: `test_flow_9_diversified_exploration.py` (fake World Model, fake Cognition, real Planning fake echoing `task.created`), `test_flow_1_volunteer_share.py`, `test_project_proposal_gating.py`, `test_budget_backoff.py`, `test_interest_follow_up_denied.py`.
- Fakes: `FakeClock` for boredom/cooldowns, seeded `random.Random`.

## 10. Build steps

Size **M**; interests/sharing (v1 ports) can proceed in parallel with drives/sampling.

1. Skeleton; consumes/produces; boundary + contracts tests. Confirm with Interface how command percepts are tagged (`channel: command`) — contracts note.
2. Projections (`BacklogCounter`, `AreaStaleness`, `ActiveProject`, `RecentCandidates`) + `curiosity:ticks` stream.
3. `DriveEngine` + `TargetSampler` (port `pick_diverse_target` weighting); unit + property tests.
4. `IdeaProposer` (port prompt + `_parse_targeted_idea`) and the exploration tick; `curiosity.candidate`; integration Flow 9.
5. `ProjectProposer` (port `discover_creative_project` incl. provider-sink OR) + gating.
6. `InterestService` (port `interests.py`; `web_fetch` proposals; decay) and `ShareScheduler` (port `socializing.py`); Flow 1 volunteering.
7. Budget/mood modulation; §8 failure modes; v1 adapters (`discover_creative_improvements` delegating to a tick); README/EVOLUTION entry.

## 11. Migration notes

| v1 | v2 | Change |
|---|---|---|
| `discover_creative_improvements` | exploration tick (§5.3) | Listings via `world.env.query`; dedupe moves to Planning; content preview via World Model index instead of `safe_read_file` |
| `discover_creative_project`, `DEFAULT_CREATIVE_PROJECT_CHANCE` | `ProjectProposer` | Emits `intent.goal.stated` instead of creating the task itself |
| `_creative_agenda_already_covered` | Planning (07) | Moved; Curiosity keeps `RecentCandidates` only |
| `capability_map.pick_diverse_target` | `TargetSampler` | Weighted by drives (was: avoid-list + uniform); listings live in World Model |
| `InterestTracker`, `RssWorldFeed`, `note_interest`, `news_command` | `InterestService` | Fetch is an approved `web_fetch` action |
| `GrowthSocializer`, `NewsSocializer`, `_maybe_volunteer_during_conversation`, `growth_command` | `ShareScheduler` | Persona phrases; Interface delivers |
| Tests: `TestDiscoverCreativeImprovements`, `TestDiscoverCreativeProject`, `test_capability_map.py` (`pick_diverse_target`), `test_interests.py`, `test_socializing.py` | `tests/simorgh/curiosity/` | Fake World Model instead of real filesystem for sampling tests; the listing tests go to World Model |

## 12. Open questions

1. Should `interest` matching use embeddings (via Memory) rather than lexical overlap between topic and area names? **Default:** lexical in Phase 3; a `memory.retrieve` similarity query in Phase 4 if interests rarely match any area.
2. Should Curiosity ever propose a candidate while the backlog is non-empty but stale (all tasks blocked)? **Default:** yes if every unfinished task is `blocked` with `retry_after` in the future — treat as empty for exploration.
3. How should the creator seed *drives* (not just interests), e.g. "focus on memory this week"? **Default:** a `[curiosity.focus]` config table of area multipliers, human-edited, reported in the tick record.
