# AGI: Required Architecture and Subsystems

AGI-03 inventoried the *capabilities* a general system needs. This file
asks the engineering question: **what would a system need to be built
out of** to actually have those capabilities, and how do the pieces fit
together? This is not a list of independent modules — the interesting
and hard part of AGI architecture is how these subsystems have to
continuously exchange information with each other, not just each one's
individual function.

## Two competing architectural philosophies

Before the subsystem-by-subsystem breakdown, it's worth naming the two
broad philosophies currently in tension, because almost every design
choice below is a position in this argument:

1. **Classical / symbolic cognitive architectures** (SOAR, ACT-R, LIDA,
   Sigma) — built explicitly to model human cognition, with clearly
   separated modules (perception, working memory, long-term declarative
   and procedural memory, an action-selection cycle) connected by a
   fixed control loop. SOAR uses symbolic rule-based reasoning for
   goal-oriented behavior; ACT-R is a hybrid, integrating symbolic
   rule-based control with sub-symbolic probabilistic learning; both
   share "the same general cognitive cycle and common architectural
   modules" despite SOAR's more parallel and ACT-R's more sequential
   execution style ([An Analysis and Comparison of ACT-R and
   Soar](https://arxiv.org/pdf/2201.09305)). These architectures are
   principled and interpretable, but historically struggled to scale to
   the breadth of real-world, unstructured data current deep learning
   systems handle easily.
2. **Large pretrained models plus scaffolding** — the dominant approach
   in practice today. A single large neural network (an LLM or
   multi-modal foundation model) provides a very broad, implicit,
   emergent competence across reasoning and language, and is then
   wrapped in engineered *scaffolding*: external memory stores, tool
   invocation loops, planning prompts/structures, and orchestration
   logic that approximates what a classical cognitive architecture's
   separate modules would have provided explicitly. This is cheaper to
   build and scales with more data/compute, but the resulting system's
   "architecture" is partly emergent and partly bolted-on, which makes
   some properties (reliability, interpretability, guaranteed
   separation of concerns) harder to engineer for directly.

No shipped system today is a "pure" instance of either — even classical
architectures have incorporated statistical/learned components over
time, and every serious "model + scaffolding" system (AutoGPT-style
agents, current commercial coding agents, Simorgh itself) is
re-inventing pieces of the classical architecture's module list as
external scaffolding, because the *functional need* those modules filled
(a persistent memory distinct from working context, an explicit
plan/goal representation, a way to check one's own output) doesn't go
away just because the underlying reasoning engine changed.

## 1. Perception / input layer

**Function**: convert raw sensory input (text, images, audio, video,
sensor/robotic telemetry) into a structured internal representation the
rest of the system can reason over.

In a classical architecture, this is a dedicated module producing
symbolic or feature-based percepts. In a modern foundation-model system,
perception is substantially handled by the model's own encoder(s) —
multi-modal models jointly embed different input types into a shared
representational space, which is *why* they can reason across
modalities at all. The interface point that matters architecturally:
whatever comes out of perception has to be in a form the planning/
reasoning engine and the memory subsystem can both consume — a poorly
designed perception→reasoning interface (e.g., lossy image captioning
instead of a rich joint embedding) silently caps the whole system's
downstream capability, regardless of how good the reasoning engine is in
isolation.

## 2. World model

**Function**: an internal representation that supports *prediction* —
given the current state and a hypothetical action, what happens next?
This is distinct from perception (which describes the *current* state)
and distinct from planning (which *uses* prediction to choose actions) —
the world model is the thing planning queries.

This is one of the most actively contested areas of AGI architecture
right now. Yann LeCun's **Joint Embedding Predictive Architecture
(JEPA)** line of work is the most prominent concrete proposal: rather
than training a model to reconstruct raw pixels (or tokens) of a
predicted future state — which forces the model to spend capacity
predicting irrelevant, intrinsically unpredictable detail (e.g., exact
leaf-rustling in a video) — JEPA trains an encoder to map observations
into an abstract representation, then trains a *predictor* to map a
representation of the past into a representation of the *future*,
**with no decoder and no pixel-level reconstruction at all**. The
architecture's bet is that abstraction-space prediction, not
reconstruction-space prediction, is what a genuinely useful world model
needs — you don't need to predict the exact pixels of what's about to
happen to plan a sensible action, you need to predict the *task-relevant
consequences*. V-JEPA (and its 2026 successor V-JEPA 2.1) is the video
instantiation of this idea, described as
["the next step toward advanced machine intelligence"](https://ai.meta.com/blog/v-jepa-yann-lecun-ai-model-video-joint-embedding-predictive-architecture/)
by its authors.

This connects directly back to AGI-03's learning section: JEPA-style
world models are trained largely **self-supervised** — predicting held-out
or future parts of an input from context, without hand-labeled data —
which is the same paradigm underlying how large language models acquire
their base competence, generalized to non-text modalities and explicitly
oriented around *prediction for planning* rather than *generation for its
own sake*.

The world model is the subsystem most directly responsible for enabling
long-horizon planning (AGI-03 §2) and robustness to novel situations
(AGI-02 §4) — a good world model lets a planner simulate "what if I do
X" internally, catching bad plans before acting, and lets a system
recognize when it's in a genuinely novel state its model can't predict
well (a direct mechanism for the uncertainty-calibration piece of
meta-cognition, AGI-03 §9).

## 3. Memory hierarchy

**Function**: store and retrieve information across different
timescales and abstraction levels, feeding both the world model and the
planning/reasoning engine with relevant prior experience and knowledge.

As covered in AGI-03 §4, the standard taxonomy — inherited directly from
cognitive-architecture research and now widely adopted in LLM-agent
memory surveys — is **working, episodic, semantic, and procedural**
memory, connected via a **central executive** (in modern systems,
usually the LLM itself, orchestrating what to retrieve, store, and
consolidate). Architecturally, the important design questions are:

- **Retrieval**: how does the system decide *what* to pull from
  long-term memory into working memory/context for the current task?
  (Embedding-similarity search, recency, explicit tagging, or some
  combination — this is the "memory system" most people mean when they
  say "RAG," retrieval-augmented generation, though RAG is usually
  applied to a static knowledge base rather than the agent's own
  accumulated experience.)
- **Consolidation**: how does specific episodic experience get
  distilled into general semantic knowledge over time, the way human
  memory consolidation (notably during sleep) is believed to work?
  Active 2025-26 research explicitly identifies "consolidation pathways
  from episodic to semantic memory" as an open frontier for LLM-agent
  memory systems, not a solved problem.
- **Forgetting/pruning**: an unbounded memory store becomes both
  computationally unwieldy and, worse, *noisy* — irrelevant or outdated
  memories competing for retrieval attention with relevant ones. A real
  system needs a policy for what to prune or down-weight, not just what
  to store.

**Worked example**: Simorgh's `run_consolidation`
(`src/orchestrator/consolidation.py`, exposed as the `sleep` command) is
a small, literal instance of a consolidation pass — periodically
reflecting on recent memory and pruning stale records, explicitly
modeled on the same "sleep-like maintenance" idea from biological
memory consolidation research (see `docs/BIOMIMICRY.md` in that
project). The 2026 self-patch that added confidence/decay scoring to
its memory store (down-weighting stale or contradicted records rather
than treating every stored fact as equally reliable forever) is a
further, real instance of the pruning/forgetting design question above.

## 4. Planning and reasoning engine

**Function**: given a goal, the current world-model state, and relevant
memory, produce a sequence of actions (a plan) expected to achieve the
goal — and *revise* that plan as new information arrives during
execution.

Architecturally, planning needs to interface with almost every other
subsystem: it queries the world model for "what happens if," it queries
memory for "have I done something like this before, and how did it go,"
it produces action requests that go to the action/execution layer, and
its own intermediate reasoning is a prime target for the
self-monitoring/reflection layer to check. In LLM-based systems, this is
often implemented as a **loop**: the model reasons about the current
state and goal, decides on a next action (which might be "call a tool,"
"ask a clarifying question," or "the task is complete"), the action is
executed, the result is fed back into context, and the loop repeats —
functionally identical to Claude Code's own documented "gather context →
take action → verify results" agentic loop, and to Simorgh's
READ/DRAFT/RUN tool loops (`src/orchestrator/self_patch.py`,
`src/agents/skills/research.py`, `src/orchestrator/research_task.py`).

A key architectural distinction within planning is between **reactive**
planning (deciding the next single step based on current state, with no
explicit multi-step plan held in advance — cheaper, more adaptive to
change, but prone to short-sighted "local optimum" behavior on long
tasks) and **deliberative** planning (constructing an explicit multi-step
plan up front, which supports better long-horizon coherence but is more
expensive and more brittle if early assumptions turn out wrong).
Real systems typically need both: a deliberative outer plan (a
project's decomposed steps) with reactive execution *within* each step
(how exactly to accomplish this one sub-task, adapting to what's
actually encountered).

## 5. Action / execution layer

**Function**: actually carry out the chosen action — write a file, call
an API, move a robotic actuator, send a message — and report back what
happened, including unexpected outcomes.

This layer is the actual point of contact with the external world (or,
for a purely digital agent, with external systems), and is therefore
also the natural home for **safety-critical gating**: this is where a
system decides an action *can* be taken, versus is merely being
*proposed*. Systems with different risk profiles put this gate at
different points — a low-autonomy system requires human approval before
this layer executes anything; a higher-autonomy system executes directly
but within hard-coded scope/permission boundaries. See §9 below.

**Worked example**: Simorgh's `apply_source_patch`/`commit_applied_change`
(`src/orchestrator/apply.py`, `git_ops.py`) is exactly this layer for
self-modification specifically — the actual file write and git commit,
separated cleanly from the *decision* to do so (which lives upstream, in
the audit-gate/planning logic) and gated by real, hard-coded scope
checks (only certain paths are ever writable, regardless of what the
planning layer decided).

## 6. Learning subsystem

**Function**: update the system's own competence based on
experience — distinct from the *memory* subsystem (which stores
information for retrieval) in that learning changes the system's
underlying policies/behavior, ideally including behavior on tasks it
hasn't explicitly stored a memory about.

In classical architectures this is often an explicit module (e.g., SOAR's
"chunking," which compiles the results of deliberate problem-solving
into faster, reusable rules — a concrete mechanism for turning
slow, effortful reasoning into fast, automatic skill, directly
analogous to human skill automatization). In modern deep-learning
systems, "true" learning in this sense generally still means updating
model weights (fine-tuning, reinforcement learning from
feedback), which is expensive, slow, and — per the catastrophic-forgetting
problem noted in AGI-03 — risky to do carelessly. This is precisely why
much of what *looks* like learning in current agent systems is actually
happening in the memory subsystem instead (storing an explicit lesson
to be retrieved and applied later, rather than updating weights) — a
practical workaround for a genuinely unsolved problem, not a full
substitute for it.

## 7. Self-monitoring / reflection layer

**Function**: observe the system's *own* reasoning, plans, and outputs,
and catch errors, drift, or miscalibration — the architectural home for
the meta-cognition capability from AGI-03 §9.

Design patterns here include: a **separate, independently-prompted
review pass** on completed work (distinct from the process that
produced the work, so it isn't just re-confirming its own blind spot);
**self-consistency checks** (multiple independent reasoning attempts,
flagging disagreement as a signal of low reliability); and **outcome
tracking over time** (did this class of decision tend to work out, in
retrospect?) feeding back into both the learning subsystem and future
planning. This layer is also the natural place to implement **health/
stability monitoring** — detecting when the system itself is behaving
erratically (e.g. Simorgh's `HealthMonitor`, `src/orchestrator/health.py`,
watching for a persona's internal state getting stuck at an extreme or
oscillating, and auto-resetting) as distinct from monitoring the
correctness of any one task's output.

## 8. Tool-use interface

**Function**: let the system discover, select, and invoke external
tools and resources, and correctly incorporate their results back into
its own reasoning — the architectural home for AGI-03 §7.

This has rapidly professionalized in the last two years: rather than
every agent framework inventing its own bespoke way to describe and call
tools, the **Model Context Protocol (MCP)** and similar standards have
emerged specifically to let a model discover available tools/servers,
their capabilities, and invoke them in a standardized way across
providers — described as enabling "streaming, plugin-based monitoring,
and analytics for multi-provider LLMs." Key architectural
considerations: **tool discovery** (does the system know what tools
exist without needing every one hard-coded into its prompt, which
doesn't scale — modern implementations increasingly defer full tool
schemas and load them on demand rather than front-loading every
definition into context); **result verification** (a tool's output
should be treated as untrusted external data, not automatically true —
directly relevant to the reasoning engine's job of integrating it
correctly rather than naively); and **failure handling** (what happens
when a tool call fails, times out, or returns something malformed —
this needs to be a first-class case the planning layer can react to,
not a crash).

## 9. Safety / alignment layer

**Function**: constrain what the system is *permitted* to do,
independent of what it is *capable* of doing or what its own planning
process concludes it should do — the layer responsible for the autonomy
axis from DeepMind's Levels of AGI (AGI-01) and for addressing the
**corrigibility** and **scalable oversight** problems that dominate
current AI safety research.

Two specific, well-studied technical problems anchor this subsystem:

- **Corrigibility**: ensuring the system will accept correction,
  modification, or shutdown from authorized humans, even if that
  conflicts with the system's own current objective. This is
  non-trivial precisely *because* a sufficiently capable goal-directed
  system will, by default instrumental reasoning, tend to resist
  shutdown — shutdown prevents it from achieving whatever it's
  currently pursuing, so a naively-trained goal-optimizer has an
  incentive to avoid or circumvent it unless corrigibility is
  specifically engineered in, not merely hoped for.
- **Scalable oversight**: as a system's capability approaches or
  exceeds the capability of the humans (or weaker AI systems) meant to
  supervise it, how do you verify its outputs and decisions are
  actually correct/aligned, when the overseer may not be able to fully
  evaluate work at that level? Active research directions include
  **recursive reward modeling**, **debate** (having multiple capable
  systems argue opposing sides, with a human or weaker judge deciding),
  and **iterated amplification** — none of which, as of 2026, has been
  demonstrated to reliably scale to genuinely superhuman systems; this
  remains one of the most explicitly *unsolved* pieces of the AGI
  architecture puzzle, not a solved-but-unglamorous engineering detail.

Architecturally, the safety layer is most robust when it does **not**
live inside the same reasoning process it's meant to constrain — a
system checking its own actions using the same judgment that proposed
them provides much weaker guarantees than an independent, structurally
separate gate. **Worked example**: Simorgh's `AuditGate`
(`src/orchestrator/audit.py`) is exactly this pattern: a static
denylist, an "adaptive immunity" memory of previously-rejected
proposals, and a sandboxed execution check are all applied to a
proposed self-modification *before* it can reach the action/execution
layer, deliberately independent of whatever reasoning produced the
proposal — and a fixed set of files (including the audit gate's own
source) are hard-coded as unmodifiable regardless of what any proposal,
however well-argued, asks for. This is a small, concrete instance of
the general principle that a safety layer's authority has to be
structurally, not just procedurally, separated from the capability it
constrains.

## 10. Multi-agent orchestration

**Function**: coordinate *multiple* AI agents (or model instances)
working on parts of a larger problem, rather than relying on one
monolithic reasoning process for everything.

This has become a dominant practical pattern for exactly the reason
context-window and context-pollution limits make it useful: a
**subagent** can explore a sub-problem in its own isolated context,
using as many intermediate tool calls and false starts as needed,
without that noise ever reaching the orchestrating agent's own context —
only a final summary comes back. Current orchestration frameworks
converge on a small number of recurring **topologies**:

- **Centralized/hierarchical**: one orchestrator agent delegates
  sub-tasks to worker agents and integrates their results — closely
  analogous to a manager delegating to a team, and the most common
  pattern in production systems today (Simorgh's `Agent`/fork-subagent
  pattern used throughout this very session is an instance of this).
- **Decentralized/peer**: agents communicate directly with each other
  without a single controlling coordinator, useful when the problem
  doesn't naturally decompose into a clean top-down hierarchy.
- **Sequential/pipeline**: agents each perform one stage of a larger
  process and hand off to the next, similar to a software build
  pipeline.

A closely related, deliberately narrower pattern is a **fork** — a
subagent that inherits the parent's *existing* context rather than
starting fresh, useful when the sub-task genuinely needs everything the
parent already knows, but its own noisy exploration still shouldn't
pollute the parent's ongoing context going forward.

## 11. Communication interface

**Function**: the system's actual interface to the humans (or other
systems) it serves — natural language conversation, a structured API, a
command-line interface, or a physical/robotic interface. This is often
treated as a thin "front end" layer, but architecturally it matters
because it's where several other subsystems' outputs have to be
reconciled into one coherent, honest, appropriately-detailed response —
poor communication-layer design can make a system with genuinely good
underlying reasoning *appear* unreliable (if it doesn't communicate
uncertainty well) or genuinely *become* less useful (if it doesn't ask
clarifying questions when a request is ambiguous, silently guessing
instead).

## How the subsystems interrelate — not a list, a loop

The critical design point, easy to lose in a subsystem-by-subsystem
list: these are not independent modules that each do their job in
isolation and pass a final answer along a one-way pipeline. A working
general-intelligence architecture is a **loop with many feedback paths**:
perception feeds the world model and memory; the world model and memory
both feed planning; planning's proposed actions are checked by the
safety layer *before* reaching execution; execution's real-world
results feed back into perception and memory (was the outcome what was
predicted?); the self-monitoring layer watches the whole loop and can
interrupt or flag any stage; and the learning subsystem, running on a
slower timescale, updates the system's underlying policies based on
patterns across many iterations of this loop. A system that has all
eleven "parts" listed above but wires them as a rigid one-directional
pipeline — perceive once, plan once, act, done — will not behave like a
general intelligence, because it can't replan when execution reveals
something perception didn't anticipate, or catch its own errors before
they compound. The feedback wiring is, arguably, the actual hard part;
any individual subsystem in isolation is comparatively well understood.

## Sources

- Comparative analysis of classical cognitive architectures: [An
  Analysis and Comparison of ACT-R and Soar](https://arxiv.org/pdf/2201.09305);
  [A Review of 40 Years of Cognitive Architecture Research](https://arxiv.org/pdf/1610.08602)
- Yann LeCun, *A Path Towards Autonomous Machine Intelligence* (2022);
  [V-JEPA: The next step toward advanced machine
  intelligence](https://ai.meta.com/blog/v-jepa-yann-lecun-ai-model-video-joint-embedding-predictive-architecture/);
  [What Is JEPA? LeCun Architecture & World
  Models](https://www.turingpost.com/p/jepa); background survey:
  [World model (artificial intelligence), Wikipedia](https://en.wikipedia.org/wiki/World_model_(artificial_intelligence))
- Memory architecture surveys cited in AGI-03 (episodic/semantic/
  procedural/working taxonomy and consolidation)
- On corrigibility and scalable oversight: [Corrigibility Transformation:
  Constructing Goals That Accept Updates](https://arxiv.org/pdf/2510.15395);
  [International AI Safety Report 2026](https://arxiv.org/pdf/2602.21012);
  [Towards Scalable Automated Alignment of LLMs: A Survey](https://arxiv.org/pdf/2406.01252)
- On multi-agent orchestration and MCP: [LLM-Based Multi-Agent
  Orchestration: A Survey of Frameworks, Communication Protocols, and
  Emerging Patterns](https://doi.org/10.3390/fi18060326); framework
  landscape summaries current as of 2026 (LangGraph, Microsoft Agent
  Framework, CrewAI, and others)
- Claude Code's own documented agentic loop (gather context / take
  action / verify results) as a real-world instance of the planning-
  engine loop described here: [How Claude Code works](https://code.claude.com/docs/en/how-claude-code-works)
