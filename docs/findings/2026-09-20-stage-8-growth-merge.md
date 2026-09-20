# Stage 8: the growth merge and the policy loop (2026-09-20)

What was measured while merging learning, reflection and curiosity into
`growth` and building the loop from "this keeps going wrong" to "we do
it differently now".

## The merge (item 1)

| | before | after |
|---|---|---|
| subsystems the Kernel boots | 18 | **16** |
| packages answering "how should Sim be different tomorrow?" | 3 | 1, with 3 parts |
| `learn.*` / `reflect.*` / `curiosity.*` topics still on both sides | — | all of them |
| growth tests | 338 | 369 at the merge, 397 after items 2-8 |

The merge changed the owner, not the wire. The one visible difference
is `source` on the bus and in the ledger: these events now come from
`growth`. Adding `growth` to the manifest test immediately caught an
unrelated hole from the night before -- `voice` subscribed to
`tool.started` without declaring it.

## What an estimate rests on (item 2)

| Source | Weight | Why |
|---|---|---|
| verified task outcome | 1.0 | something checked it |
| unverified completion | 0.25 | a self-report; counted separately so how much of an estimate is self-report can be read off |
| blocked task | 0.5, as a failure | it did not work, but not the way a failure does |
| eval case | 0.5 | a fixture is the same question every time and the house is not in it |

Worked end to end in the acceptance test: four verified outcomes, one
unverified, and 5-of-7 on the trial suite gives **Beta(5.5, 5.0) over
12 samples**.

## Clustering, against a 30-failure fixture (item 3)

The fixture plants two patterns in noise. The first run returned
**five** clusters, not two: a task type whose *only* failures are
timeouts scores a share of 1.0 and looks specific to itself, so the
share-against-baseline test passed it. "Patch tasks time out" is advice
nobody can act on. A failure mode seen at strength across three or more
kinds of work is now dropped as a property of the system, and the
fixture yields exactly the two planted clusters.

## Exploration (item 7)

The plan says "draw per area, pick the lowest draw ... with the
sampler's diversity kept". The second half is load-bearing, and the
numbers say why -- 400 rounds over four targets:

| | hopeless (81 samples, always fails) | shaky (12) | untouched (0) | solid (92, good) |
|---|---|---|---|---|
| lowest-draw-wins alone | **393** | 0 | 7 | 0 |
| with the sampler's recent-target rule | 134 | 133 | 131 | 2 |

Lowest-draw-wins alone finds the worst thing rather than exploring: a
tightly-measured hopeless target draws around 0.01 and beats a flat
prior 99 times in 100. Starving the confidently-good target is correct
-- there is nothing left to learn there.

## The night (item 8)

Three steps today (evals, review, diagnose), all free, cheapest first
so stopping early loses the least. Cap: **$0.50/day**, checked *before*
each step runs, because a model call cannot be taken back once made. A
step that does not report what it spent is charged its estimate.

## Not measured yet

Item 10 asks for policies adopted vs retired and surviving 30 days,
eval delta per adoption, regressions attributed to a policy (target 0),
exploration yield and nightly cost. None of those exist until nights
have actually run: the loop was finished today and has produced no
policies. The numbers above are what could be measured without waiting.

Item 5's core -- evaluating a candidate on a held-out set in a worktree
and landing an adoption through `action.proposed` -- is still open and
needs paid runs. Its safety half landed: `rules/`, `agents/` and
`simorgh/evals/` are protected subjects, so the loop cannot edit the
suite that judges it.

One near-miss worth recording: adding `simorgh_skills/` to the
protected list (as item 5's text says) denied `apply_skill` outright --
the tool whose whole job is writing there. It is already human-only, so
the protection bought nothing and cost a capability, and no test failed.
Protection and human-only are different tools: one says never, the
other says not without somebody.
