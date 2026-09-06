# `simorgh/curiosity/`

Intrinsic motivation and diversified discovery. See
`docs/blueprint/subsystems/13-curiosity.md` for the full spec. This
package owns: drive-weighted target sampling, one-narrow-question idea
proposals, rare open-ended project proposals, tracked interests (RSS/Atom
follow-up via a proposed `web_fetch` action, never a direct network
call), and proactive share-timing decisions. It does not own backlog
dedupe (Planning), which areas exist or competence gaps (World Model),
running tasks (Orchestration), fetching feeds itself (Execution/Guardian),
or how/when a share actually renders (Persona/Interface).

## The lesson this package exists to fix (v1 milestones 95-96)

Asking a model one open-ended "propose an improvement" question,
repeatedly, clusters on the same neighborhood of ideas even when worded
differently each time. The fix is structural, not a better prompt:
sample the *target* first, by weighted randomness over a real, cheap,
non-hallucinating inventory (`world.env.query{what: capability_map}` /
`self.gaps`) -- *then* ask one narrow question about that pre-chosen
target. The model's reply is parsed for exactly `PATCH ::` / `RESEARCH
::` + a description (`idea.py::parse_targeted_idea`); a reply that
ignores "don't second-guess the target" and names a different file
anyway still produces a candidate whose `subject` is the *originally
sampled* `Target` (`service.py::_emit_candidate`), never anything the
model claims. `sampler.py` picks by softmax over `DriveEngine` scores,
never argmax -- greedy selection on drive scores just fixates on the
single weakest area, a slower one-dimensional version of the same
collapse.

## Layout

- `api.py` -- in-package data shapes/protocols (not on the wire).
- `config.py` -- `Config`, one frozen dataclass, every default carrying
  its v1 name in a comment.
- `drives.py` -- `DriveEngine`: gap/staleness/interest/boredom -> a
  per-area score, mood-modulated temperature and research-prior.
- `sampler.py` -- `DriveWeightedSampler`: two-stage softmax sampling
  (area, then module within it, weighted away from recent subjects).
- `idea.py` -- `TargetedIdeaProposer`: one narrow `cognition.think` call
  per sampled target; parser only ever extracts `PATCH`/`RESEARCH`.
- `projectproposal.py` -- `OpenEndedProjectProposer`: the deliberately
  rare exception where the model *does* pick its own focus, because a
  whole project spans more ground than one sampled target represents.
- `projections.py` -- in-process, session-local projections
  (`BacklogCounter`, `AreaStaleness`, `ActiveProject`,
  `RecentCandidates`) built by watching bus events go by, never by
  reading another subsystem's Ledger streams directly.
- `interests.py` -- `InterestService` (pure in-memory tracker) plus the
  stdlib-only RSS/Atom parser, ported from v1's `RssWorldFeed`.
- `sharing.py` -- `ShareScheduler`: growth checked before news (a direct
  v1 creator complaint -- "I don't see evidence of self-improving" --
  was more pointed than "share more news").
- `service.py` -- the real `Subsystem`: wires all of the above to bus
  messages and appends audit records to the `curiosity:*` Ledger
  streams. One exploration tick in flight at a time; a tick still
  awaiting Cognition when the next `system.tick.idle` arrives is
  skipped and recorded, never queued or re-entered.

## Known simplifications against the spec (see 13-curiosity.md section 12)

- `DriveEngine.research_prior_multiplier` (valence -> bias toward
  `RESEARCH` over `PATCH` when mood is low) is implemented but not yet
  wired into `idea.py`'s prompt/parsing -- the model alone currently
  decides `PATCH` vs `RESEARCH`. Follow-up: thread it into the prompt as
  a soft hint, or bias which of the two the parser accepts when both
  would be plausible.
- The explore/exploit budget's free-provider carve-out (spec section
  5.6: "research candidates still allowed if a provider reports
  `free: true`, even under `budget_stop`") is honored only as an
  all-or-nothing flag (`_BudgetState.any_free`) gating the tick, not as
  a per-candidate `kind` restriction to `research`-only. A tick that
  proceeds on a free provider can still emit `patch` candidates.
- `world.env.query{what: file_index}` field names (`path`/`max_chars`
  for a single-file preview, `files`/`content` in the reply) were
  cross-checked directly against World Model's real
  `facets/file_index.py` and `facets/capability_map.py` (built
  concurrently, in a separate fork, and already on disk at the time
  this package was finished) -- not just inferred from the contract.
  `self.gaps` currently always replies with empty `gaps`/
  `unexplored_areas` (Phase 3 stub in `selfmodel.py::compute_gaps`), so
  `drives.py::_gap`'s per-gap field access (`competence`/`task_type`/
  `score`/`samples`) is exercised only by this package's own unit tests
  today, not by a real reply, until competence tracking lands.
