# Knowledge Base

Reference material for Simorgh -- distinct from `docs/EVOLUTION.md` (the
chronological build log) and `docs/architecture.md` (what's implemented
and where). This is where durable, standalone reference content lives:
research findings worth keeping past a single session, background
material, and anything else that's reference rather than a record of
what changed and when.

## Contents

- **[AGI-00: Overview](./AGI-00-overview.md)** -- start here. Index,
  reading order, and the short version of the whole knowledge base.
- **[AGI-01: Definitions and Specifications](./AGI-01-definitions-and-specifications.md)**
  -- the Turing test, OpenAI's economic definition, Legg-Hutter's
  universal intelligence measure, Chollet's generalization framing,
  DeepMind's Levels of AGI, and where they disagree.
- **[AGI-02: Core Attributes](./AGI-02-core-attributes.md)** -- what
  makes intelligence general vs. narrow: transfer, sample efficiency,
  open-endedness, robustness to novelty, common sense, generalization
  vs. memorization.
- **[AGI-03: Capabilities and Skills](./AGI-03-capabilities-and-skills.md)**
  -- reasoning, planning, learning, memory, perception, language, tool
  use, theory of mind, meta-cognition, creativity, embodiment -- each
  with worked examples.
- **[AGI-04: Architecture and Subsystems](./AGI-04-architecture-and-subsystems.md)**
  -- what a system needs to be built out of: perception, world model,
  memory hierarchy, planning engine, action layer, learning subsystem,
  self-monitoring, safety/alignment, tool-use interface, multi-agent
  orchestration, and how they interconnect.
- **[AGI-05: Examples and Case Studies](./AGI-05-examples-and-case-studies.md)**
  -- real systems (AlphaGo, frontier LLMs, Voyager, coding agents,
  robotics stacks) and long worked use-case walkthroughs.
- **[AGI-06: Benchmarks and Evaluation](./AGI-06-benchmarks-and-evaluation.md)**
  -- ARC-AGI, GAIA, SWE-bench, METR's time-horizon methodology,
  theory-of-mind benchmarks: what each tests, current results, and
  known critiques.

Researched from current, cited sources (WebSearch/WebFetch against
primary papers, lab publications, and benchmark technical reports) as of
2026 -- see each file's own Sources section.

- **[harness-00: Overview](./harness-00-overview.md)** -- north star for
  leveling up Sim's own harness. Start here for this set.
- **[harness-01: Claude Code Deep Dive](./harness-01-claude-code-deep-dive.md)**
  -- the agentic loop, five human values / thirteen design principles,
  the five-layer context-compaction pipeline, seven permission modes and
  the ML classifier, subagents (fork vs. fresh), checkpoints, Plan Mode,
  and the TodoWrite-to-Task evolution.
- **[harness-02: Design Principles](./harness-02-design-principles.md)**
  -- workflows vs. agents, the five composable workflow patterns
  (prompt chaining, routing, parallelization, orchestrator-workers,
  evaluator-optimizer), and tool/agent-computer-interface design.
- **[harness-03: Project Decomposition and Focus](./harness-03-project-decomposition-and-focus.md)**
  -- when a task is really a project, hierarchical planning, and
  concrete anti-divergence mechanisms for long-running agents.
- **[harness-04: Completion and Verification](./harness-04-completion-and-verification.md)**
  -- why "it ran" isn't "it's done," checklist-based evaluator patterns,
  and how to avoid a multi-step effort silently stalling.
- **[harness-05: Subsystems](./harness-05-subsystems.md)** -- an
  iterative breakdown of context/memory, planning, tool-use,
  verification, permissions, multi-agent orchestration, and persistence
  -- functionality, an effective method, and the real tradeoffs for each.
- **[harness-06: Gap Analysis for Simorgh](./harness-06-gap-analysis-simorgh.md)**
  -- the actual point: a concrete, file-by-file comparison of what Sim's
  harness already gets right against this research, prioritized gaps,
  and where to spend effort next.
