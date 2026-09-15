# Sim benchmark analysis — 9/14/26

You have built a highly capable foundation. Building a custom AI agent harness from scratch that can successfully navigate these benchmarks is a significant engineering achievement. Your results show an agent that is exceptionally strong at instruction following and discrete tool use, but it currently hits a cognitive wall when forced to maintain context over long, unstructured horizons.

Here is a breakdown of exactly where your harness stands compared to the current mid-2026 state-of-the-art (SOTA).

## Benchmark Comparison

| Benchmark Suite | Your Harness Score | Current SOTA (Mid-2026) | Verdict |
|---|---|---|---|
| BFCL Parallel | 77% | 90%+ | Strong. Reliable schema parsing and concurrent tool execution. |
| GAIA Level 1 | ~65% – 84% | 82% – 86% | Excellent. Highly competent at zero-shot instruction following. |
| GAIA Level 2 | 63% | 72% – 74% | Competitive. Capable of multi-step reasoning. |
| GAIA Level 3 | 0% | 53% – 65% | Needs Work. Fails at sustained, long-horizon planning. |
| SWE-bench Verified | 25% | 83% – 95% | Entry-level. Struggles with repository-wide context and patch verification. |

## Deep Dive: Where You Excel and Where You Break

### 1. Tool Calling (BFCL Parallel - 77%)

Hitting 77% on parallel function calling means the core plumbing of your agent is fundamentally sound. It can look at an array of available tools, map the user's intent to multiple discrete actions, and fire them off simultaneously without hallucinating bad JSON or crossing parameter streams.

### 2. General Reasoning (GAIA - Strong Early Levels, 0% on Level 3)

Your GAIA scores are the most revealing.

- **Levels 1 & 2:** Scoring 84% (on your subset) for Level 1 and 63% on Level 2 means your agent can easily handle tasks requiring a few steps and basic retrieval. It behaves similarly to early-2025 production models.
- **Level 3:** Scoring 0% on Level 3 is a classic symptom of context degradation. Level 3 removes the ceiling on steps and tools. Your agent is likely getting caught in action loops, forgetting its original objective, or failing to verify intermediate facts before proceeding.

### 3. Software Engineering (SWE-bench Verified - 25%)

A 25% resolve rate on SWE-bench Verified means the agent can fix localized, single-file bugs. However, modern SOTA models like Claude Fable 5 and Claude Mythos are hitting the 90%+ mark. Your harness is likely failing when a bug requires tracing logic across multiple files, executing test suites, and iteratively debugging its own failed patches.

## Strategic Next Steps

To push your agent architecture from "competent" to "state-of-the-art," you will need to focus heavily on memory and state management rather than just raw model intelligence.

- **Long-Horizon Memory Management:** To conquer GAIA Level 3, the agent needs a cognitive framework that separates immediate scratchpad memory from long-term objective tracking. Implementing a mechanism that forces the agent to summarize its progress against the original prompt every 5–7 steps can prevent it from wandering off track.
- **Codebase Sandboxing:** Pushing that SWE-bench score up requires shifting from a simple read/write paradigm to an active execution loop. Integrating deeper Model Context Protocol (MCP) tooling alongside strict microVM sandboxing will allow the agent to safely compile code, run bash commands, and test its own patches in an isolated environment before submitting an answer.
- **Agent Orchestration:** For complex multi-agent execution platforms like AgentPods or Simorgh, you might consider isolating domains. Instead of one agent trying to solve a SWE-bench issue, orchestrate a primary "planner" agent that delegates discrete code-search tasks to specialized sub-agents via shared memory execution.

Are you currently relying on a single underlying LLM for all routing and execution in the harness, or have you started experimenting with an orchestrator-worker setup?

---

## Appendix: the measured results behind this analysis

Benchmark wave `w20260914b`, 2026-09-14. Parallel isolated Sim copies (`tools/bench_instance.py`), model `zai-org/GLM-5.3-Flash` on Together. Only runs from 13:17 onward are counted: before commit 3b6dc01, cases answered by Cognition's offline floor were scored as wrong. After it, those cases are skipped. Raw rows are in `~/.simorgh/benchmark-waves/w20260914b/results.jsonl`, and the combined totals are in Sim's `benchmark:runs` history (run ids `w0914b-*`).

| Suite | Correct | Runs | Distinct cases covered |
|---|---|---|---|
| BFCL parallel | 225/291 (77.3%), 1 skipped | 17 | 88/88 (most cases scored 3–4 times) |
| GAIA level 1 (`gaia-l1`) | 53/82 (64.6%) | 9 | 53/53 |
| GAIA all levels (`gaia`) | 30/50 (60.0%) | 5 | 50/165 |
| — level 1 | 11/13 (85%) | | |
| — level 2 | 19/30 (63%) | | |
| — level 3 | 0/7 (0%) | | |
| SWE-bench Verified | 3/12 (25.0%), 3 skipped | 5 | 15/500 |

Caveats:

- GAIA level 3 (7 cases) and SWE-bench Verified (12 scored cases) are small samples.
- The "~65% – 84%" GAIA level 1 range above is two measurements: 64.6% across the whole level-1 suite, and 85% on the 13 level-1 cases drawn in the all-levels runs.
- Several correct GAIA answers were rejected by Sim's own verifier ("verification failed after max revisions"). The benchmark scores the answer anyway, but the behaviour is a real harness defect.
- Three SWE-bench cases were skipped by the scorer ("named tests never appeared in the log"), which points to a harness-side log-parsing gap, not a model failure.
