# AGI: Capabilities and Skills

This file inventories the actual skill set implied by "general
intelligence" — the individual capabilities that, together, are usually
meant when someone describes a system as broadly intelligent. Each
section explains the capability, why it's distinct from the others, how
current systems approach it, and includes a concrete worked example of
what having (or lacking) the capability looks like in practice.

A key theme throughout: **these capabilities are separable.** A system
can be strong in one and weak in another — this is precisely why
DeepMind's "Levels of AGI" (AGI-01) treats generality as a *breadth*
axis rather than a single score, and why the honest current answer to
"how close are we to AGI" is "extremely uneven — strong here, weak
there," not a single number.

## 1. Reasoning

Reasoning is the capacity to derive new conclusions from existing
information. It's usually split into three modes, each doing a
different job:

- **Deductive reasoning**: deriving a conclusion that is *guaranteed*
  true if the premises are true (formal logic, mathematical proof).
  Example: "All employees must badge in. Maria is an employee. Therefore
  Maria must badge in." No new information is created — deduction makes
  explicit what was already implied.
- **Inductive reasoning**: generalizing from specific observations to a
  probable (not guaranteed) general rule. Example: observing that every
  swan seen so far is white and inferring "swans are (probably) white" —
  famously fallible (black swans exist), but essential for learning any
  general pattern from finite evidence.
- **Abductive reasoning**: inferring the most *plausible explanation*
  for an observation. Example: the lawn is wet; the most plausible
  explanation, absent other evidence, is that it rained (rather than
  "someone hosed it," which is possible but less likely without further
  evidence). This is the reasoning mode behind diagnosis, debugging, and
  most everyday inference under uncertainty.

**Worked example — debugging a failing test**: An engineer sees a test
fail with an off-by-one error. Abduction narrows the space of plausible
causes (loop bound, index arithmetic, an inclusive/exclusive boundary
condition) faster than exhaustively checking every line. Deduction then
verifies a specific hypothesis ("if the loop uses `<=` instead of `<`,
the last iteration will read past the array" — check the code, confirm).
Induction generalizes the lesson ("this kind of bug tends to happen at
boundary conditions — watch for that pattern elsewhere"). A general
reasoner uses all three fluidly, in sequence, within one task; current
LLMs demonstrably do a version of this in code-debugging benchmarks
(hence agentic coding tools' real usefulness), though systematic
studies show they are meaningfully less reliable at each mode than
skilled humans, particularly as problem length or novelty grows —
consistent with the sample-efficiency and robustness gaps in AGI-02.

## 2. Planning and long-horizon goal pursuit

Planning is decomposing a goal into an ordered sequence of actions that
achieve it, ideally accounting for uncertainty, resource limits, and the
possibility that early steps will reveal new information that changes
the later plan. **Long-horizon** planning specifically stresses
maintaining a coherent plan and goal across *many* steps and a long
time period, without losing track of the objective or accumulating
drift.

This is one of the most cited current weak points of frontier AI
systems relative to humans. METR's time-horizon research (AGI-06) exists
specifically because this gap is large and quantifiable: as of early
2026, the best frontier models' 50%-reliability time horizon on
real-world software tasks was on the order of **2 hours** of
human-expert-equivalent task length — a huge improvement from a few
years prior (doubling roughly every 7 months), but still far short of
the multi-week or multi-month horizons a human professional routinely
sustains on a real project.

**Worked example — planning a product launch**: A general agent asked
to "launch this feature by the end of the quarter" needs to: decompose
the goal into research, design, implementation, testing, documentation,
and rollout phases; sequence them respecting dependencies (can't test
before implementing); allocate a rough time budget to each; monitor
progress and *replan* when a phase runs long or reveals a blocker
(e.g., implementation surfaces a missing dependency that has its own
sub-plan); and know when to escalate to a human rather than silently
compensating. This is structurally identical to what Simorgh's own
`PROJECT_TASK` decomposition (`src/orchestrator/projects.py`) does at a
small scale — break a goal into ordered child tasks, track each to
completion, roll up status — which is a toy but real instance of the
long-horizon planning subsystem described in AGI-04.

## 3. Learning

"Learning" in the AGI context usually means more than the training
process that produces a model — it means the system's capacity to
**acquire new competence after deployment**, ideally without a full
retraining cycle. Several distinct modes matter:

- **Few-shot / in-context learning**: adapting behavior within a single
  session based on a handful of examples given in the prompt, without
  updating any model weights. This is the dominant mode of "learning"
  in current LLM-based systems.
- **Continual learning**: incorporating new information over an
  extended deployment lifetime *without* catastrophically forgetting
  previously learned skills — a longstanding, still largely unsolved
  problem in deep learning (**catastrophic forgetting**: naively
  fine-tuning a network on new data tends to overwrite/degrade
  performance on old data/tasks unless specifically mitigated).
- **Self-supervised learning**: learning structure from unlabeled data
  by constructing its own training signal (e.g., predicting masked or
  future parts of an input) — the dominant paradigm behind how large
  models acquire their base capabilities in the first place, and
  central to world-model approaches like JEPA (AGI-04).
- **Meta-learning ("learning to learn")**: improving the *learning
  process itself* from experience across many tasks, so that a novel
  task is picked up faster than the first one was — the direct
  mechanism aimed at sample efficiency (AGI-02).

**Worked example — a coding assistant learning a codebase's
conventions**: On first encountering a new repository, a general agent
should notice (without being explicitly told) that this codebase prefers
early returns over nested conditionals, uses a specific test-naming
convention, and avoids a particular library — then *apply* those
conventions to its own new code, without needing them restated every
time. Current systems do a version of this via in-context learning
(reading surrounding code as implicit few-shot examples) and, in more
sophisticated setups, via persistent memory (writing the observed
convention to a durable store — see the memory section below and
AGI-04's memory hierarchy) rather than relearning it fresh each session.

## 4. Memory

Memory is frequently under-emphasized relative to reasoning and language
in popular AGI discussion, but cognitive-architecture research (SOAR,
ACT-R — AGI-04) and recent LLM-agent memory surveys converge on the same
taxonomy, adapted from human cognitive psychology:

- **Working memory**: the immediate, limited-capacity context actively
  being used for the current task — in an LLM system, this is
  substantially the context window itself.
- **Episodic memory**: a record of specific past experiences/events,
  each tied to when and in what context it happened (e.g., "on this
  date, this task failed for this specific reason").
- **Semantic memory**: general factual/world knowledge, decoupled from
  when or how it was learned (e.g., "Python lists are mutable, tuples
  are not" — a fact, not an event).
- **Procedural memory**: knowledge of *how* to do something — skills and
  routines, often not easily verbalized (e.g., the accumulated
  "muscle memory" of how to structure a debugging session), which in
  weight-based models can live implicitly in the trained parameters
  themselves, or explicitly as a stored procedure/skill library.

The distinction between episodic and semantic memory matters
practically: episodic memory lets a system say "this specific approach
failed for me before, in this specific context" (informing *when* a
lesson applies), while semantic memory generalizes that into "this class
of approach tends not to work" (informing broader judgment). A system
without a consolidation pathway from episodic to semantic memory
accumulates a large pile of individual incidents without ever
generalizing a durable lesson from them — a known gap that active 2025-26
research on "memory consolidation" for LLM agents is specifically
targeting.

**Worked example**: Simorgh's own `MemoryStore` (`src/memory/long_term.py`)
plus `ShortTermMemory` (`src/memory/short_term.py`) is a small,
concrete instance of the working/episodic split — durable, timestamped
event records (episodic) versus a bounded recent-turns window (working).
Its `ReflectionAgent` (`src/orchestrator/reflection.py`), which reviews
recent outcomes for recurring patterns and turns them into actionable
proposals, is a basic, rule-based analogue of episodic-to-semantic
consolidation — noticing "this kind of failure keeps happening" (a
semantic-level generalization) from individual logged incidents
(episodic records).

## 5. Perception and multi-modality

Perception is the capacity to extract structured information from raw
sensory input — text, images, audio, video, or (for embodied systems)
proprioceptive/tactile signals. **General** perception means this works
across modalities and, critically, that information learned through one
modality can inform and be checked against another (see AGI-02's
cross-modal transfer) — e.g., a system that reads a recipe (text) and
recognizes when a photographed dish doesn't match the description
(vision), or hears "turn left" (audio) and correctly relates it to a
depth-camera view of the room (vision + spatial reasoning).

Current frontier multi-modal models handle text+image+(often)+audio
jointly with real, useful competence — a major shift from the
single-modality era. The frontier of difficulty has moved to **grounded,
embodied** perception: interpreting sensor data (touch, force, proximity)
in service of physical action in real time, which is materially harder
than interpreting a static image or pre-recorded video, and is a core
justification for the embodiment debate discussed in section 10 below
and in AGI-04.

## 6. Language and communication

Beyond raw text generation, communicative competence for a general
agent includes: adjusting register and detail level to the audience
(explaining a bug differently to a junior engineer versus a product
manager); tracking what's already been said in a conversation to avoid
repetition or contradiction; disambiguating genuinely ambiguous requests
by asking a clarifying question rather than guessing; and communicating
uncertainty honestly rather than presenting a guess with false
confidence. This last point connects directly to the meta-cognition
capability below, and to the robustness attribute in AGI-02 — good
communication of uncertainty is, in effect, meta-cognition made
externally visible.

## 7. Tool use

Tool use is the capacity to extend one's own effective capability by
invoking external resources — a calculator, a code interpreter, a web
search engine, a database, a robotic actuator, or another AI system.
It is, in a real sense, the single biggest practical capability
multiplier for current LLM-based agents: a base model with strong
language and reasoning ability but no tools can only produce text; the
*same* model, given a code interpreter and web search, can verify
arithmetic, look up current facts, and manipulate real files — vastly
expanding effective competence without changing the underlying model at
all.

This reframes part of "generality" (AGI-02's open-ended domain coverage)
from a *knowledge* problem into a *tool-selection and tool-composition*
problem: does the system know *when* to reach for a tool, *which* tool,
and how to chain multiple tools' outputs together toward a goal? Modern
protocols like the **Model Context Protocol (MCP)** exist specifically to
standardize how models discover and invoke tools across many providers
and frameworks, reflecting how central this capability has become to
practical agent design (see AGI-04's tool-use interface subsystem).

**Worked example**: Asked "what's the total cost if I buy 17 units at
$34.99 each, plus 8% tax," a system without reliable tool use might
attempt the arithmetic directly in its own generation and occasionally
make an arithmetic slip on a run of digits; a system with tool use
recognizes this as a case to delegate to a calculator/code interpreter,
getting a reliably correct answer regardless of the model's own raw
arithmetic reliability. Simorgh's own `RUN:` marker (a sandboxed Python
execution tool, `src/sandboxing/sandbox.py`) and `FETCH:`/`READ:`/`LIST:`
markers (`src/tools/web_fetch.py`, `src/cognition/tool_protocol.py`) are
small instances of exactly this pattern.

## 8. Social cognition and theory of mind

**Theory of mind (ToM)** is the ability to model *other agents'* mental
states — their beliefs (which may be false), desires, intentions, and
knowledge (which may differ from your own) — and reason about their
likely behavior on that basis. It's foundational to cooperation,
negotiation, teaching, deception-detection, and any interaction where
what another agent *believes* (not just what's objectively true) governs
what they will do.

The canonical test format is the **false-belief task**: Sally puts a
marble in a basket and leaves the room; Anne moves the marble to a box;
when Sally returns, where will she look for the marble? A correct answer
("the basket" — where *Sally* believes it is, not where it actually is)
requires modeling Sally's belief state as distinct from ground truth.
Current LLM evaluation on this and more elaborate ToM benchmarks
(TMBench, OpenToM, MuMA-ToM — see AGI-06) shows real but inconsistent
competence: models often succeed on canonical-format false-belief
questions but degrade on rephrased, multi-agent, or embedded variants,
and there is active, unresolved debate about whether success reflects
genuine mental-state modeling or surface-pattern matching on a
now-well-known task template (directly the generalization-vs-memorization
question from AGI-02).

**Worked example**: A negotiation agent representing a buyer needs to
reason not just about its own preferences but about the seller's likely
reservation price, what information the seller does and doesn't have
about the buyer's constraints, and how a proposed offer will be
*perceived*, not just what it objectively contains. Getting this wrong
— e.g., revealing information the seller could exploit, or assuming the
seller knows something they don't — is a theory-of-mind failure, not a
reasoning or knowledge failure.

## 9. Meta-cognition and self-reflection

Meta-cognition is *thinking about one's own thinking*: knowing what you
know and don't know, monitoring your own reasoning for errors, deciding
when to double-check versus proceed, and updating your own strategies
based on past performance. It is arguably the capability most directly
responsible for the "robustness to novelty" attribute in AGI-02 — a
system with good meta-cognition can recognize *"I'm in unfamiliar
territory, my confidence should be lower here"* even without external
feedback.

Concrete instances: **self-consistency checking** (generating multiple
independent reasoning paths and checking whether they agree, as a
signal of reliability); **calibrated confidence** (a stated probability
that actually matches empirical accuracy — a well-calibrated system that
says "80% confident" is right about 80% of the time on such claims, not
some other rate); **error detection and self-correction** (noticing a
mistake mid-reasoning and revising, rather than continuing to build on a
flawed premise); and **strategy selection** (recognizing that a first
approach isn't working and deliberately switching, rather than
persisting).

**Worked example**: Simorgh's own `verify_task_completion`
(`src/orchestrator/verification.py`) is a deliberately separate,
independently-prompted review pass on a just-completed task — a crude
but real architectural instance of meta-cognition: the system checking
its own work with fresh judgment, distinct from the process that did the
work, rather than trusting the first pass's own self-report. The session
log behind this knowledge base (`docs/EVOLUTION.md`, milestone 92)
documents a live bug in exactly this subsystem — the reviewer
misreading a rambling non-answer as a rejection — which is itself a good
illustration of how *hard* reliable meta-cognition is to engineer even
in a narrow, deliberately-scoped instance.

## 10. Creativity

Creativity is the generation of outputs that are simultaneously **novel**
(not a direct copy or trivial recombination of seen examples) and
**valuable/appropriate** to some goal or aesthetic criterion — a
random-noise generator is novel but not creative, because it isn't
valuable; a template-filling system can be valuable but isn't creative if
it isn't novel. Both properties are needed, and both are hard to measure
precisely, which is part of why creativity is one of the more
philosophically contested items on this list — critics argue that
large models "merely recombine" training data in ways that only *appear*
novel, while others argue that human creativity is also fundamentally
recombinatory (drawing on prior experience, culture, and technique) and
that the relevant question is the same generalization-vs-memorization
test from AGI-02, applied to generative rather than analytical output.

**Worked example**: Asked to design a new board game mechanic, a
genuinely creative system needs to satisfy real constraints (playable,
balanced, fun) while producing something meaningfully different from
existing mechanics it was exposed to — not literally "chess but with a
different board size." Evaluating this well requires domain expertise
(is it *actually* novel to someone who knows the space, or a known
mechanic under new names?) which is part of why creativity is hard to
benchmark at scale compared to, say, a math problem with a checkable
answer.

## 11. Embodiment — capability, or optional?

Embodiment is the question of whether a system needs a **physical
presence and sensorimotor loop with the real world** — a body, sensors,
actuators — to achieve general intelligence, or whether general
intelligence can be achieved by a purely disembodied system (reading and
writing text, or otherwise operating on abstract/digital inputs and
outputs only).

This is a genuinely live, unresolved debate, not a settled question:

- **The case for embodiment**: proponents of *embodied cognition*
  argue that a great deal of human concept formation is literally
  grounded in having a body that moves through and acts on physical
  space — spatial reasoning, causal understanding of physical
  interaction, and even some abstract reasoning (many spatial metaphors
  used for abstract concepts, e.g. "high" status, "moving forward" with
  a plan) plausibly derive from sensorimotor experience. Robotics
  researchers pursuing "embodied AGI" argue that mastering real physical
  modalities (tactile feedback, force, thermal perception, not just
  vision) is necessary to acquire genuine physical-world common sense
  that a text-only system can only approximate secondhand.
- **The case against strict necessity**: proponents of disembodied
  paths point to large language models' substantial, real physical/causal
  common sense despite having never had a body — evidence that a great
  deal of physical knowledge is transmissible through language *about*
  the physical world (humans write extensively about physics, causality,
  and spatial relationships), even without direct sensorimotor grounding.
  Some prominent researchers explicitly predict transformative,
  broadly-capable systems arriving *without* physical embodiment.

**Where this leaves the question**: embodiment is probably best treated
as *capability-specific* rather than all-or-nothing — a system almost
certainly doesn't need a body to do excellent mathematical reasoning or
software engineering, but very plausibly does need real
sensorimotor grounding (or an extremely good simulated substitute) to
reliably perform tasks whose core difficulty *is* physical interaction —
folding laundry, catching a thrown object, performing surgery. See
AGI-05 for a worked household-robot use case that makes this concrete,
and AGI-04's discussion of embodiment as an *optional* subsystem rather
than a universal requirement.

## Summary: current unevenness

| Capability | Current frontier-system strength (rough, 2026) |
|---|---|
| Deductive/inductive/abductive reasoning | Strong on well-posed problems; degrades on long or highly novel chains |
| Long-horizon planning | Weak relative to skilled humans; improving fast (~2h reliable autonomy, doubling ~7 months) |
| Few-shot/in-context learning | Strong | 
| Continual learning without forgetting | Weak/largely unsolved at the weight level; addressed today mostly via external memory, not weight updates |
| Memory (episodic/semantic/procedural) | Present mostly as engineered scaffolding around the model, not intrinsic to it |
| Multi-modal perception | Strong for vision+text+audio; weak for embodied/tactile |
| Language and communication | Strong |
| Tool use | Strong and rapidly standardizing (MCP and similar protocols) |
| Theory of mind / social cognition | Real but inconsistent; contested whether genuine or pattern-matched |
| Meta-cognition / calibrated uncertainty | A known, significant weak point |
| Creativity | Genuinely contested, both empirically and philosophically |
| Embodiment | Absent by default in most systems; an active, separate research frontier |

## Sources

- Survey: [Memory for Autonomous LLM Agents: Mechanisms, Evaluation, and
  Emerging Frontiers](https://arxiv.org/html/2603.07670v1)
- Survey: [Rethinking Memory Mechanisms of Foundation Agents in the
  Second Half](https://arxiv.org/pdf/2602.06052)
- [Theory of Mind in Large Language Models: Assessment and
  Enhancement](https://arxiv.org/html/2505.00026v1); [TMBench](https://arxiv.org/html/2402.15052v1);
  [OpenToM](https://arxiv.org/pdf/2402.06044); [Evaluating LLMs in
  theory of mind tasks, PNAS](https://www.pnas.org/doi/10.1073/pnas.2405460121)
- METR, [Task-Completion Time Horizons of Frontier AI
  Models](https://metr.org/time-horizons/) and [Measuring AI Ability to
  Complete Long Software Tasks](https://metr.org/blog/2025-03-19-measuring-ai-ability-to-complete-long-tasks/)
- On embodiment: [An Overview of Robot Embodied Intelligence Based on
  Multimodal Models](https://onlinelibrary.wiley.com/doi/10.1155/int/5124400);
  general framing discussion in [Editorial: Narrow and general
  intelligence: embodied, self-referential social cognition and novelty
  production](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12827700/)
- Model Context Protocol as an example of tool-use standardization —
  see AGI-04 for architecture-level discussion and citations
