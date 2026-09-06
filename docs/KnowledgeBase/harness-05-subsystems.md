# Harness Subsystems, One at a Time

For each subsystem below: what it does, one effective concrete way to build it, and the real design tradeoffs. Sources for the Claude Code-specific details are file 01's own citations; general points draw on file 02's citations plus [Governing What You Cannot Observe: Adaptive Runtime Governance for Autonomous AI Agents](https://arxiv.org/pdf/2604.24686) and [Towards trustworthy agentic AI: a comprehensive survey](https://arxiv.org/pdf/2605.23989).

## 1. Context / memory management

**Functionality.** Decides what the model actually sees on each call, out of everything that's accumulated (conversation history, tool outputs, project instructions, prior learnings) — because context is finite and expensive, and stuffing everything in degrades both cost and quality.

**An effective method.** A graduated pipeline of increasingly expensive/lossy interventions tried in order (file 01's five-layer compaction), rather than one blunt truncate-when-full step. Separately: split *persistent* instructions (a CLAUDE.md-style file, loaded fresh every session) from *conversational* context (which decays/gets compacted) — persistent rules should never be at risk of being compacted away, because they're not really "history," they're configuration.

**Tradeoffs.** More layers = more engineering and more edge cases (what happens when even the cheapest layer isn't enough, fast?), but a single-layer "summarize when full" approach either summarizes far too eagerly (losing detail that was still needed) or not eagerly enough (a sudden expensive summarization at the worst moment). The read-time-projection idea (context collapse, file 01) is worth calling out specifically: it decouples "what the model sees this turn" from "what's actually stored," which means a later resume or a differently-scoped summary isn't working from already-destroyed data — a real design insight, not just an implementation detail.

## 2. Planning / task decomposition

**Functionality.** Turns an under-specified goal into a concrete, trackable set of steps, and updates that plan as new information arrives.

**An effective method.** A distinct, explicit planning phase (file 03) that produces a real artifact — not an implicit byproduct of just starting to execute — reviewable before execution begins where the stakes warrant it (Plan Mode's hard-enforced read-only state is the strongest version of this). The plan should live in the same durable, queryable store as everything else (not just in the live context window), with parent/child rollup for anything genuinely multi-step.

**Tradeoffs.** A mandatory plan-then-approve phase adds latency and, for a human-in-the-loop system, an extra interaction the human has to actually attend to — worth it for irreversible or expensive work, pure overhead for a two-line fix. The judgment of *when* to require an explicit plan (vs. just executing) is itself a design decision worth making deliberately, not defaulting either way universally.

## 3. Tool-use and execution

**Functionality.** The actual mechanism by which the model's decisions become real-world effects — file reads/writes, commands, network calls, code execution.

**An effective method.** Treat the tool's *interface* as seriously as its implementation (file 02's ACI principle): clear docs, example usage, mistake-proofed argument shapes, and a format the model has already seen a lot of in training rather than a bespoke one. Isolate genuinely risky execution (arbitrary code, shell access) in a sandboxed environment with the minimum privileges the task actually needs, not the privileges that happen to be convenient to grant.

**Tradeoffs.** Sandbox isolation that's too strict can make legitimate operations (e.g., a self-patch that needs to import sibling modules) structurally impossible regardless of code quality — the isolation boundary needs to match what the *class* of code genuinely needs, not be maximally restrictive by default without regard to that. Too loose, and the sandbox isn't actually providing the safety property it exists for.

## 4. Verification / evaluation

**Functionality.** Independently checks whether a completed action actually achieved its intent, distinct from whether it executed without error (file 04).

**An effective method.** A separately-prompted evaluator call (not the same context grading its own work), ideally against an explicit checklist derived from the task rather than one holistic judgment, with a genuine "insufficient evidence" category rather than a forced binary, and — critically — a rule that a non-answer or ambiguous response defers to existing mechanical checks rather than being read as a rejection.

**Tradeoffs.** Every extra evaluation pass is a real, additional cost (latency and, for a paid model, money) — evaluating everything at maximum rigor is rarely worth it; the return is highest for changes with real consequences (self-modifying code, anything hard to reverse) and lowest for cheap, easily-reversible, low-stakes actions, which argues for the same reversibility-weighted scaling used for permissions (file 01) applied to verification effort too.

## 5. Permission / safety gating

**Functionality.** Decides, before an action happens, whether it's allowed to proceed automatically, needs a human's explicit approval, or is denied outright.

**An effective method.** Multiple independent layers using genuinely different techniques — a fast static rule pass (deny-list/allow-list) first, since it's cheap and catches the obvious cases instantly; an adaptive/learned layer for the ambiguous middle (an ML classifier, or — as Sim already has — a similarity check against previously-rejected proposals so a known-bad pattern doesn't have to be rediscovered from scratch every time); and a graduated trust posture that can tighten or loosen over time as evidence accumulates, rather than one fixed permissiveness level forever. Deny should always win over a more specific allow, never the reverse.

**Tradeoffs.** More layers catch more cases but add latency and false-positive risk (blocking something that was actually fine); a graduated/adaptive posture is more accurate over time but requires the system to actually track a trust signal and requires care that the signal itself can't be gamed. A gate scoped too narrowly for the actual risk (Sim's own live-caught example: a sandbox check that was structurally impossible for a legitimate self-patch to pass, regardless of code quality) doesn't add safety, it just adds friction that gets worked around or that blocks all the good along with the bad — precisely why that specific check was rescoped rather than left in place once the gap was found.

## 6. Multi-agent orchestration / delegation

**Functionality.** Splits work across multiple model instances (or calls) so that exploration noise, tool restrictions, or parallelism can be handled separately from the main line of work.

**An effective method.** Isolation as the default (a delegated instance starts fresh, or explicitly forks when it genuinely needs the parent's accumulated context — file 01), with only a final summary crossing back into the orchestrating context, never the intermediate noise. A bounded delegation depth (subagents spawning subagents) prevents unbounded recursive fan-out. This is the direct justification for Sim's own `RESEARCH_TASK`: an investigation's exploratory READ/LIST calls stay local to that task's own loop; only the written finding — the "summary" — ever becomes durable, shared state.

**Tradeoffs.** Delegation adds real latency (spinning up a fresh context, re-establishing what it needs to know) and, for a fresh (non-forked) delegate, a genuine re-explanation cost — worth it specifically when the delegated work would otherwise pollute the main context with volume it doesn't need to carry forward, not worth it for a quick, low-volume side question that's cheaper to just answer inline.

## 7. Persistence / session continuity

**Functionality.** Ensures work, plans, and learnings survive beyond a single continuous run — a crash, a restart, a deliberate pause and resume later.

**An effective method.** Append-only durable logs (file 01's own principle) rather than mutable snapshots — every state change is a new record referencing what came before, so current state is always reconstructible by replay, and nothing is ever silently overwritten or lost to a bad write mid-mutation. Separate the *durable record* (what actually happened) from *derived/computed views* (a rollup status, a current backlog) so the derived views can always be recomputed from the record rather than risking drifting out of sync with it. Sim's own event-sourced `MemoryStore`/`TaskStore` — and `project_status()`'s status being computed fresh from children rather than stored independently — already follows this principle directly.

**Tradeoffs.** Append-only logs grow without bound unless something prunes or consolidates them (Sim's own `sleep`/consolidation pass), and replaying a long history to reconstruct current state gets more expensive as the log grows — worth periodic compaction/summarization of the *record* itself (distinct from context-window compaction, which operates on what's shown to the model, not on what's durably stored), but that compaction needs its own care not to silently discard information a later process might still need.
