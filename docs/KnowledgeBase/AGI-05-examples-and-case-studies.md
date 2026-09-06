# AGI: Examples and Case Studies

This file has two parts: **real systems** that each demonstrate a piece
of the AGI-03 capability inventory particularly well (and, honestly,
where each still falls short of full generality), and **long worked
use-case walkthroughs** that trace what a genuinely general system would
need to do, end-to-end, for a realistic task — not just abstractly name
the capability, but show the actual sequence of subsystem interactions
from AGI-04.

## Part 1 — Real systems, by capability demonstrated

### AlphaGo / AlphaZero / AlphaFold (DeepMind) — deep, narrow mastery

AlphaGo (2016) defeated the world Go champion using deep reinforcement
learning combined with Monte Carlo tree search — a planning/reasoning
engine (tree search) paired with a learned evaluation function (the
neural network) approximating a world model's predictive value.
AlphaZero generalized the same architecture to chess and shogi *without
any human game data*, learning purely from self-play — a striking
demonstration of sample-efficient learning *within* a narrow,
well-specified environment with a clear reward signal. AlphaFold later
applied a related deep-learning approach to protein structure
prediction, solving a 50-year-old open problem in structural biology.

**What it demonstrates**: extremely strong planning and learning
*within* a narrow, well-defined domain with a clean success signal.
**What it doesn't demonstrate**: any of this transfers outside its
domain — AlphaGo cannot play chess, let alone write an essay or plan a
product launch. This is the textbook example of "Expert-to-Superhuman
Narrow" on DeepMind's Levels of AGI matrix (AGI-01) — extremely deep,
essentially zero breadth.

### GPT-4/5 and Claude/Gemini family — broad but uneven generalist competence

Frontier large language models (OpenAI's GPT series, Anthropic's Claude
family, Google's Gemini family) represent the most significant present
push toward *breadth*: a single model handling conversational language,
code generation and debugging, mathematical reasoning, document
analysis, and (in multi-modal versions) image and audio understanding,
all without task-specific retraining. This breadth is what makes them
plausible "General" entries on DeepMind's axis, at "Competent" to
"Expert" performance levels on many individual tasks, while still
falling to near-zero on ARC-AGI-3's interactive novel-task suite
(AGI-06) — a sharp, concrete illustration of AGI-02's throughline:
broad *trained* competence and genuine on-the-fly *generalization* are
not the same thing, and can diverge enormously even in the same system.

**What it demonstrates**: strong language, broad world knowledge,
substantial in-context learning, increasingly strong tool use via
agentic scaffolding. **What it doesn't demonstrate**: reliable
long-horizon autonomy (hours, not weeks), robust calibrated uncertainty,
or generalization to structurally novel problem types outside the
training distribution's implicit coverage.

### Voyager and similar embodied-in-simulation agents

Voyager (an autonomous Minecraft-playing agent built on an LLM) is a
frequently-cited example of a system combining several AGI-04 subsystems
explicitly: an LLM as the planning/reasoning engine, a persistent
**skill library** (explicit procedural memory — successfully-executed
code for a task is saved and can be reused/composed later, rather than
re-derived from scratch each time), and an automatic curriculum
(self-generated goals, proposing its own next objective based on what it
currently can and can't do — a concrete instance of AGI-02's
open-ended-coverage-via-self-directed-goals). It demonstrates lifelong,
continually expanding competence within one persistent environment
without human-specified task lists.

**What it demonstrates**: procedural memory accumulation, self-directed
goal generation, and genuinely long-horizon (many in-game hours)
autonomous operation within a bounded simulated world. **What it doesn't
demonstrate**: transfer outside that world — the accumulated skill
library and world knowledge don't carry over to an unrelated domain.

### Autonomous software-engineering agents (SWE-bench-style systems)

Modern coding agents (commercial and open-source) that can be pointed at
a real GitHub issue, autonomously explore an unfamiliar codebase, write
and test a fix, and open a mergeable pull request are one of the most
economically consequential current instances of the AGI-04 architecture
in production: perception over a real, messy codebase; a planning loop
(explore → hypothesize → implement → test → iterate); real tool use
(a shell, a test runner, version control); and — critically — a
verification step that closes the loop against *ground truth* (do the
tests actually pass?) rather than trusting the model's own self-report.
This ground-truth verification is a big part of *why* this domain has
become a leading benchmark space (SWE-bench, AGI-06) — software has an
unusually crisp, automatically-checkable notion of "did it work."

### Robotics stacks (e.g. Gemini Robotics and similar vision-language-action systems)

Systems that connect a large vision-language model's reasoning to a
robot's low-level motor control represent the current frontier of
*embodied* AGI research (AGI-03 §11). These stacks typically layer a
high-level planner (using the same kind of reasoning as a text-only LLM,
producing a plan like "pick up the red block, then place it in the
box") on top of a lower-level, often separately-trained
vision-and-force-feedback control policy that executes the fine
motor sequence — an explicit architectural split between deliberative
planning and reactive low-level execution (AGI-04 §4). This layering
exists because a single end-to-end model that's simultaneously excellent
at abstract task planning *and* millisecond-timescale motor control
remains a hard, unsolved integration problem — the two jobs have very
different timescales and error tolerances.

## Part 2 — Long worked use cases

Each of these walks through what a genuinely general system needs to do
end-to-end, naming the AGI-04 subsystem each step engages.

### Use case A: A general research assistant

**Task**: "Find out whether there's good evidence that intermittent
fasting improves cognitive performance in healthy adults, and summarize
what's actually well-supported versus overstated."

1. **Communication interface**: parses the request, notes it's actually
   two distinct sub-questions (does evidence exist; how strong/overstated
   is it), rather than one.
2. **Planning**: decomposes into: find primary research (not just
   secondary sources repeating a claim), assess study quality
   (sample size, controls, replication), separate correlational from
   causal claims, and check for a scientific consensus statement if one
   exists.
3. **Tool use**: web search and document fetch tools pull actual papers
   and systematic reviews, not just the first plausible-sounding blog
   post.
4. **Reasoning (inductive + abductive)**: weighs conflicting findings —
   if three small studies show an effect and one large, well-controlled
   study doesn't, inductive reasoning about *evidence quality*, not just
   *vote counting* across studies, has to govern the conclusion.
5. **Meta-cognition**: explicitly flags where evidence is weak or mixed,
   rather than presenting a confident, clean-sounding answer that
   overstates certainty — this is precisely the calibration capability
   from AGI-03 §9, and its absence is one of the most common real
   failure modes of research-assistant-style agents today (confidently
   summarizing contested claims as settled).
6. **Memory**: if this is a multi-turn research session, prior findings
   (which papers were already checked, what was already ruled out) need
   to persist in working/episodic memory so the agent doesn't redo work
   or contradict itself turn to turn.
7. **Communication interface** (again): the final answer needs to
   separate "well-supported," "plausible but under-evidenced," and
   "overstated by popular sources" — not flatten nuance into one verdict.

### Use case B: An autonomous software engineer fixing a production incident

**Task**: "Users are reporting intermittent 500 errors on checkout since
last night's deploy. Find and fix the root cause."

1. **Perception**: ingest logs, error traces, recent commit history, and
   metrics dashboards — heterogeneous, partly unstructured data.
2. **Reasoning (abductive)**: generate plausible hypotheses ranked by
   likelihood given the timing (correlates with a specific deploy) and
   error signature (a specific exception type narrows the search space
   dramatically before any code is even read).
3. **World model**: predict, before making any change, what a proposed
   fix's *side effects* would likely be — does patching this code path
   risk affecting unrelated functionality? A system without a decent
   world model here just tries changes and hopes, rather than reasoning
   about consequences in advance.
4. **Tool use**: read the actual suspect code, run the test suite
   locally, reproduce the error in a safe environment rather than
   theorizing only.
5. **Planning (deliberative + reactive)**: an overall plan (isolate →
   reproduce → fix → verify → deploy) with reactive adaptation within
   each step (the first hypothesis is wrong; abduction generates a
   second, informed by what was just ruled out — not starting from
   scratch).
6. **Safety/alignment layer**: before deploying anything to production,
   a hard gate — automated tests must pass, and depending on the
   system's configured autonomy level (DeepMind's autonomy axis, AGI-01),
   either deploys automatically within pre-approved scope or produces a
   reviewable pull request for a human, never silently exceeding its
   granted authority regardless of how confident its own reasoning is.
7. **Self-monitoring**: after the fix ships, watches the same metrics
   that revealed the original incident to confirm the fix actually
   worked, rather than assuming success from the tests passing alone —
   real-world ground truth, not just internal self-report.
8. **Learning/memory**: the specific failure pattern and its fix get
   recorded (episodic), and if this class of bug recurs, that record
   should inform faster diagnosis next time (a step toward semantic
   consolidation) — this is structurally identical to what Simorgh's
   `ReflectionAgent` does with recurring failure patterns.

### Use case C: A household robot asked to "tidy the kitchen"

**Task**: an underspecified, common-sense-laden instruction with no
formal task specification.

1. **Common sense** (AGI-02 §5): "tidy" implicitly means: dishes go in
   the sink or dishwasher (not the trash), food goes in the fridge or
   pantry (not left out), surfaces get wiped, but *personal, ambiguous*
   items (mail, a half-finished craft project) should probably be left
   alone or flagged, not "tidied" into an unknown location — none of
   this is stated in the instruction and all of it is assumed.
2. **Perception (embodied, multi-modal)**: visual recognition of
   objects and their state (is this glass clean or needs washing?),
   plus tactile/force feedback while manipulating (a full glass of
   liquid needs to be handled differently than an empty one — a purely
   visual system might not reliably distinguish these without touch/
   weight feedback).
3. **Theory of mind**: if a family member is present, "is this OK to
   move?" reasoning benefits from modeling what that person would
   *want*, not just executing a literal instruction — e.g., not moving
   something a person is actively using, inferred from their attention
   and posture, not stated.
4. **World model + planning**: sequencing actions so they don't
   interfere with each other (don't wipe a counter you're about to put
   more dishes on), and predicting physical consequences of an action
   before taking it (will this stack of plates be stable if picked up
   this way?) — a genuinely physical prediction problem a text-only
   world model has no grounding for.
5. **Safety layer**: hard constraints around physical safety (don't
   damage fragile items, don't operate near an occupied stove burner)
   that need to be inviolable regardless of how the planning layer
   reasons about efficiency.
6. **Meta-cognition**: recognizing genuine ambiguity ("I'm not sure if
   this note on the counter is trash or important — I'll leave it and
   ask") rather than guessing wrong on something a wrong guess could be
   costly for.

This use case is deliberately included because it's a domain where
**every one of the AGI-03 capabilities is simultaneously load-bearing**,
and where the embodiment debate (AGI-03 §11) is most concrete — a purely
text-based system, however capable at language and reasoning, simply
has no way to perform steps 2 and 4 without a real or high-fidelity
simulated body.

### Use case D: A scientific-discovery agent proposing a novel hypothesis

**Task**: given a body of existing experimental data in a research area,
propose a novel, testable hypothesis that isn't just a restatement of
what's already published.

1. **Semantic memory**: broad, accurate knowledge of the existing
   literature and its findings — table stakes, but genuinely
   substantial in scope.
2. **Reasoning + creativity**: this is where generalization-vs-memorization
   (AGI-02 §6) is most sharply tested — a hypothesis that's a trivial
   recombination of two existing published findings is not a genuine
   contribution; a valuable hypothesis needs to identify a real,
   previously-unnoticed *gap or tension* in the existing evidence and
   propose something that would resolve it, which requires the kind of
   far-transfer and structural (not surface) pattern recognition that's
   also the hardest capability to verify a system genuinely has (AGI-02).
3. **World model**: predicting, before recommending an expensive
   real-world experiment, what the likely outcome space is and whether
   the proposed experiment would actually be *informative* — a
   hypothesis test that can't discriminate between competing
   explanations isn't useful even if well-formed.
4. **Meta-cognition**: honestly representing confidence — a genuinely
   novel hypothesis is, by definition, less certain than an established
   finding, and overstating confidence here is a serious real-world
   failure mode (misdirecting expensive experimental resources).
5. **Tool use**: potentially querying specialized scientific databases,
   running statistical analyses on existing datasets, or even
   proposing/running computational simulations as part of building the
   case for the hypothesis before it's ever tested in the real world.

This use case is closest to genuinely "superhuman-general" territory —
it's the kind of task where success would represent a real, hard-to-fake
demonstration of generality, which is part of why "can an AI system make
a genuinely novel, verified scientific discovery, autonomously, at a
rate exceeding human researchers" is one of the benchmarks serious AGI
forecasters watch most closely, distinct from and harder than passing
any fixed static benchmark.

## What these examples have in common

Across all four use cases, notice that **no single capability from
AGI-03 is ever sufficient on its own** — every realistic general-intelligence
task requires several capabilities working together through the
feedback loop described at the end of AGI-04, and the cases where
current systems fall short are rarely a total absence of a capability;
they're usually a *specific, identifiable* subsystem being weaker than
the others (meta-cognitive calibration in use case A, long-horizon
planning coherence in use case B, embodied grounding in use case C,
genuine novelty-generation in use case D) — which is exactly why
DeepMind's Levels-of-AGI framing (AGI-01) treats capability as a
multi-dimensional profile rather than a single pass/fail line, and why
"is it AGI yet" is a much less useful question in practice than "which
specific subsystem is the current bottleneck for this class of task."

## Sources

- DeepMind, AlphaGo/AlphaZero/AlphaFold — primary publications and
  DeepMind's own research pages
- Voyager: *Voyager: An Open-Ended Embodied Agent with Large Language
  Models* (Wang et al.) — skill-library and automatic-curriculum design
- SWE-bench and GAIA — see AGI-06 for full citations on current results
- Google DeepMind Gemini Robotics program (announced March 2025) as a
  current vision-language-action embodiment example
- General framing throughout drawn from the same sources cited in
  AGI-01 through AGI-04
