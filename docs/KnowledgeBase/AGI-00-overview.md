# Artificial General Intelligence — Overview and Index

This is a reference knowledge base on Artificial General Intelligence (AGI):
what it is claimed to mean, what attributes and capabilities it implies,
what architecture and subsystems a system would need to actually have those
capabilities, how progress toward it is measured today, and worked examples
throughout. It was researched from current, real sources (cited inline and
per-file) rather than written from assumption, and last updated in
2026 — a field where the state of the art moves in months, not years, so
treat specific benchmark numbers as a snapshot, not a ceiling.

## Why this exists

"AGI" is one of the most-used and least-agreed-upon terms in computing.
Depending on who is talking, it means: a system that passes the Turing
test; a system that can perform any economically valuable task a human
can; a system with a certain score on a mathematical measure of universal
intelligence; a system that generalizes to novel problems without having
been trained on them; or simply "smarter than GPT-4 at everything." These
are not the same claim, and conflating them is a common source of
confused arguments about whether AGI has arrived, is close, or is
decades away. This knowledge base tries to keep the different framings
distinct and cite where each comes from.

## How to read this

The files build on each other, roughly in this order:

1. **[AGI-01: Definitions and Specifications](./AGI-01-definitions-and-specifications.md)**
   — the major competing definitions of AGI (Turing, Legg-Hutter,
   OpenAI's charter, DeepMind's "Levels of AGI," Chollet's generalization
   framing, economic definitions), what each one is actually claiming,
   and where they conflict.
2. **[AGI-02: Core Attributes](./AGI-02-core-attributes.md)**
   — what makes intelligence *general* rather than *narrow*: transfer,
   sample efficiency, open-endedness, robustness to novelty, common
   sense, and why each of these is hard in a way that scaling alone
   hasn't obviously solved.
3. **[AGI-03: Capabilities and Skills](./AGI-03-capabilities-and-skills.md)**
   — the actual skill inventory: reasoning, planning, learning, memory,
   perception, language, tool use, social cognition, meta-cognition,
   creativity, and the embodiment question — each with concrete worked
   examples of what "having" the capability actually looks like in
   practice.
4. **[AGI-04: Architecture and Subsystems](./AGI-04-architecture-and-subsystems.md)**
   — what a system would need to be *built* out of to have those
   capabilities: perception, world model, memory hierarchy, planning
   engine, action layer, learning subsystem, self-monitoring/reflection,
   safety/alignment layer, tool-use interface, multi-agent orchestration,
   and how they wire together into one system, not a list of parts.
5. **[AGI-05: Examples and Case Studies](./AGI-05-examples-and-case-studies.md)**
   — real systems (AlphaGo/AlphaFold, GPT-4/5 family, Claude, Gemini,
   Voyager, AutoGPT-style agents, robotics stacks) and long worked
   use-case walkthroughs (a research assistant, an autonomous software
   engineer, a household robot, a scientific-discovery agent) that show
   what each capability from AGI-03 has to do end-to-end.
6. **[AGI-06: Benchmarks and Evaluation](./AGI-06-benchmarks-and-evaluation.md)**
   — how progress is actually measured today (ARC-AGI, GAIA, SWE-bench,
   METR's time-horizon methodology, and others), current results, and
   the serious critiques of each measure.

## The short version, if you read nothing else

- **There is no single agreed technical definition of AGI.** The
  closest thing to a consensus framing splits into two families: a
  **capability** framing (can it do the things a human can, across
  domains?) and a **generality/process** framing (does it *generalize*
  the way general intelligence should, rather than just perform well on
  benchmarks it was implicitly prepared for?). See AGI-01.
- **"General" is not the same as "broadly useful."** A system trained
  on trillions of tokens can be extremely broadly useful while still
  failing catastrophically on tasks that are trivial for humans but
  structurally novel — this is the core of François Chollet's critique,
  and it's why ARC-AGI exists as a benchmark distinct from "does it know
  a lot." See AGI-01 and AGI-06.
- **Capability is not one thing.** Reasoning, planning, learning,
  memory, perception, and social cognition are separable skills that
  current frontier systems have in wildly uneven amounts — strong
  language and pattern-completion, weaker long-horizon planning and
  genuine continual learning, and contested performance on theory of
  mind. See AGI-03.
- **No shipped system today is built as a single unified cognitive
  architecture the way classical AI (SOAR, ACT-R) imagined AGI would
  be.** Instead, current frontier systems are large pretrained models
  wrapped in scaffolding — memory stores, tool-calling loops, planning
  prompts, multi-agent orchestration — that approximates some of what a
  unified architecture would provide. Whether that's a temporary
  workaround or the actual shape AGI takes is an open, actively debated
  question. See AGI-04.
- **Progress is now measured less in "did it pass a benchmark" and more
  in "how long a task can it autonomously complete."** METR's
  time-horizon metric — the length of a task (measured in human-expert
  time) that a model can complete autonomously with 50% reliability —
  has become a widely cited proxy specifically because static
  benchmarks saturate. See AGI-06.

## A note on Simorgh

This knowledge base is a general reference, not a Simorgh-specific
document — most of it applies to any AGI-aspiring system. But Simorgh
(see `docs/architecture.md`, `docs/SOUL.md`) is itself an attempt to
build pieces of the architecture described in AGI-04: a memory hierarchy
(`src/memory/`), a reasoning/dispatch layer (`src/orchestrator/router.py`),
a self-modification and reflection loop (`src/orchestrator/self_patch.py`,
`reflection.py`), a safety/audit layer (`src/orchestrator/audit.py`), and,
as of this session, a Task/Research/Project work harness
(`src/orchestrator/tasks.py`, `projects.py`, `research_task.py`) that is a
small, concrete instance of the planning-and-execution subsystem
described in AGI-04. Reading AGI-04 alongside `docs/architecture.md` is a
reasonable way to see which pieces of "what AGI would need" a given
system actually has, and which it's deliberately deferring (Simorgh's own
docs are explicit about this — see `docs/architecture.md`'s "Not yet
implemented" section).

## Sources

This knowledge base draws on primary sources wherever possible —
research papers, lab charters, and benchmark technical reports — cited
in each file's own references section. It does not treat any single
source, including any one lab's marketing material, as authoritative on
its own; where framings conflict, both are presented.
