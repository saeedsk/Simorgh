# AGI: Benchmarks and Evaluation

If AGI-01 covers *how the field defines* AGI, this file covers *how the
field currently measures progress toward it* — what the major benchmarks
actually test, what current systems score, and the well-known critiques
of each measure. As emphasized throughout this knowledge base: no single
benchmark tests "general intelligence" as a whole; each tests a specific
operationalized hypothesis about what general intelligence requires.
Reading benchmark results without knowing *which* hypothesis is being
tested is a common source of overclaiming in both directions (both "AGI
is basically here" and "AGI is nowhere close" claims often cherry-pick
whichever benchmark supports the pre-existing conclusion).

## 1. ARC-AGI (Abstraction and Reasoning Corpus)

**What it tests**: on-the-fly abstraction and generalization to genuinely
novel visual puzzle tasks, deliberately designed to resist being solved
by pattern-matching against likely training data (see AGI-01 for the
underlying philosophy). Each task is a small set of input→output grid
transformation examples; the system must infer the rule and apply it to
a new input. Humans solve the vast majority of tasks quickly with zero
task-specific training; this is the benchmark's whole point — it isolates
*fluid* reasoning from accumulated *crystallized* knowledge.

**Current results** (as of early-to-mid 2026): ARC-AGI-1 (2019) is now
largely saturated by frontier systems augmented with heavy
test-time compute. ARC-AGI-2, a harder successor, saw a striking jump —
OpenAI's GPT-5.2 scored 54% in December 2025, then rapidly progressed to
98% by April 2026 as models specifically adapted to this task shape.
**ARC-AGI-3**, launched March 25, 2026, shifted from static grid puzzles
to a **fully interactive** format — and frontier models' scores collapsed
back down: the best-performing frontier model (Gemini 3.1 Pro) scored
just **0.37%**, Claude Opus 4.6 scored 0.25%, and GPT-5.4 scored near
zero, versus humans solving essentially 100% of the same tasks.

**The critique, direct from the benchmark's own creator**: François
Chollet has explicitly and repeatedly stated that saturating any given
ARC-AGI generation does **not**, by itself, constitute proof of AGI —
each version tests a specific hypothesis (static abstraction for v1/v2,
interactive/embodied-adjacent reasoning for v3), and a system solving one
generation says nothing directly about the next. The dramatic
score collapse from ARC-AGI-2 (98%) to ARC-AGI-3 (under 1%) is itself
the clearest empirical illustration in this entire knowledge base of
AGI-02's core theme: **very high performance on one operationalization
of "novel-task generalization" does not transfer to a different
operationalization** — a system that appears to have "solved"
abstraction in a static, single-step format can fail almost completely
the moment the format shifts to interactive, sequential decision-making,
which strongly suggests the earlier success was, at least partly,
adaptation to the *specific task shape* rather than the fully general
underlying capacity the benchmark series is trying to isolate.

## 2. GAIA (General AI Assistants benchmark)

**What it tests**: realistic, tool-augmented assistant tasks requiring
web browsing, multi-step reasoning, and multi-modal handling — designed
to be conceptually simple for a human but to require genuine multi-step
tool orchestration for an AI system. Questions have unambiguous, checkable
answers (avoiding the subjective-grading problem many open-ended
benchmarks face). Three difficulty tiers: Level 1 (≤5 steps, minimal
tools), Level 2 (5–10 steps, multiple tools), Level 3 (complex, many-step
sequences requiring advanced general-assistance behavior).

**Current results**: at launch (2023), GPT-4 with plugins scored **15%**
against a **92%** human baseline — a huge gap. By 2025, more capable
systems substantially closed this: Claude Opus 4 (High reasoning mode,
May 2025) reached **64.8%** using the HAL Generalist Agent scaffold. This
trajectory — a large early gap closing substantially within about two
years — is a useful data point for how fast *tool-augmented, multi-step
assistant* competence specifically has improved, distinct from the more
stubborn ARC-AGI-3 gap on interactive novel-task reasoning.

**Critique**: GAIA's questions, while designed to have unambiguous
answers, still draw on a bounded, real-world question distribution;
strong performance demonstrates competent orchestration of search,
browsing, and multi-step tool use within roughly human-familiar task
shapes, which is a different (and, per the ARC-AGI-3 result above,
apparently easier) capability than genuinely novel abstract reasoning.

## 3. SWE-bench (and SWE-bench Verified)

**What it tests**: real-world autonomous software engineering — given a
real GitHub issue and the corresponding real repository, can the agent
generate a patch that actually resolves the issue, verified by running
the project's real test suite? "Verified" is a human-curated subset
specifically filtered to remove ambiguous or under-specified issues,
addressing an early critique that some original SWE-bench tasks were
themselves poorly specified or had multiple valid solutions the original
scoring didn't account for.

**Why it matters for AGI evaluation specifically**: software engineering
is one of the few real-world professional domains with an automatically
and objectively checkable notion of success (tests pass or they don't),
which makes it unusually well-suited to rigorous agent evaluation
compared to domains requiring subjective human grading. This is part of
why coding-agent capability has become one of the most closely tracked
public proxies for general agentic competence — not because coding is
uniquely important to AGI as a concept, but because it's one of the
cleanest domains to *measure* long-horizon, tool-using, verifiable agent
behavior in, at scale, cheaply and repeatably.

**Critique**: strong SWE-bench performance demonstrates real agentic
competence within software engineering specifically — codebase
navigation, tool use, iterative debugging — but doesn't directly
establish generality outside that domain; and because SWE-bench draws
from real public GitHub history, there's an ongoing, serious concern
about **training data contamination** (some issues/fixes may overlap
with what frontier models were trained on), which is exactly the
"memorization vs. generalization" concern from AGI-02 — mitigated
somewhat by using recent, post-cutoff issues, but never fully eliminated
for a benchmark built from historically-scraped public data.

## 4. METR's time-horizon methodology

**What it tests**: not a fixed task set at all, but a **methodology**
for measuring how *long* (in human-expert-equivalent time) a task an AI
agent can reliably complete autonomously — arguably the most influential
recent shift in how the field talks about AGI progress, precisely
because static benchmarks tend to saturate while this metric is designed
to keep being meaningful as capability grows.

**Methodology, concretely**: METR estimates how long it would take a
skilled human professional to complete each task in a diverse task suite,
then measures what fraction of tasks of a given human-time-length an AI
agent completes successfully. Fitting a logistic curve to this data
yields the **"50% time horizon"**: the task length (in human-expert time)
at which the agent succeeds half the time. This single number is
strongly correlated with overall capability (task length and success
rate showed R² = 0.83 in METR's own analysis) and, crucially, is a
continuous metric that doesn't stop being informative once a fixed task
set is solved.

**Current results and trend**: as of the February–March 2026 measurement
window, the observed 50%-time-horizon of a frontier "thinking" model was
around **2 hours 15 minutes** (with a 65-minute to 4.5-hour 95%
confidence interval) on a broad task suite — notably *shorter* than the
same models' performance specifically on software-reimplementation-style
tasks, where time horizons run several times longer, illustrating that
this metric, too, is domain-sensitive rather than a single universal
number. The headline trend, however, is the **doubling time**: this
metric has grown roughly exponentially over roughly six years, doubling
approximately every **7 months**. Extrapolated (with appropriate caution
about extrapolating any exponential trend indefinitely), METR notes that
continuation of this trend through the end of the decade would put
frontier systems at autonomous *month-long* project horizons.

**Critique**: the metric depends heavily on accurate human-time-equivalent
estimates for each task, which are themselves somewhat subjective and
task-suite-dependent (as the software-reimplementation-vs-broad-suite gap
above shows); it measures successful task *completion*, which conflates
several different underlying capabilities (planning coherence, error
recovery, tool reliability) into one number; and — the standard caution
with any fast-improving metric — a smooth historical trend line is not a
guarantee of continued smooth extrapolation, especially across a
transition as significant as "hour-scale" to "month-scale" autonomous
operation, which likely requires qualitatively new architecture (e.g.,
genuinely solving the continual-learning and long-horizon-memory
problems from AGI-03/AGI-04), not just more of the same scaling.

## 5. Theory-of-mind and social-reasoning benchmarks

**What they test**: TMBench (8 tasks, 31 sub-abilities in social
cognition), TOMVALLEY (1,100 social contexts, 78,100 mental-state
questions), OpenToM, MuMA-ToM (multimodal, multi-agent belief/goal
inference), and others test the theory-of-mind capability from AGI-03
§8 across varied formats specifically to probe whether success is
genuine or format-specific pattern-matching.

**Current results**: performance is real but inconsistent — models often
do well on canonical, well-known task formats (e.g. the classic
false-belief "Sally-Anne" structure) while degrading measurably on
rephrased, multi-agent, or otherwise varied presentations of
structurally the same underlying reasoning problem; on several
benchmarks, even leading models lag human performance by **more than 10
percentage points**.

**Critique**: this is one of the most actively, explicitly *contested*
capability areas in the current literature — researchers are genuinely
divided on whether current results reflect emerging, genuine mental-
state modeling or superficial correlation with linguistic cues that
happen to co-occur with mental-state language in training data, and the
consistency gap between canonical and varied task formats is frequently
cited as evidence for the latter, more skeptical reading.

## 6. Composite/holistic evaluation efforts

Recognizing that no single benchmark captures general capability,
2025–26 has seen growth in **holistic, multi-benchmark leaderboards**
(e.g., the Holistic Agent Leaderboard concept) that report performance
across many distinct benchmark types simultaneously, explicitly to avoid
the trap of one number standing in for "how AGI-like is this system."
This mirrors DeepMind's Levels-of-AGI framing (AGI-01): the field is
converging, at least among careful researchers, toward reporting
capability as a **profile across dimensions**, not a single AGI/not-AGI
verdict.

## Summary table

| Benchmark | Tests | Recent frontier result | Human baseline | Main critique |
|---|---|---|---|---|
| ARC-AGI-2 | Static novel-puzzle abstraction | 98% (Apr 2026, up from 54% Dec 2025) | ~100% (untrained) | Rapid saturation once task shape is specifically targeted |
| ARC-AGI-3 | Interactive novel-task reasoning | <1% (best model 0.37%) | ~100% | New, deliberately harder; shows prior "solved" result didn't generalize across format |
| GAIA | Tool-augmented assistant tasks | 64.8% (2025, up from 15% in 2023) | 92% | Tests familiar task shapes more than genuine novelty |
| SWE-bench Verified | Real-world software engineering | Actively improving, contamination risk noted | Not directly comparable (professional baseline) | Domain-specific; possible training-data overlap |
| METR time horizon | Autonomous task duration | ~2h15m 50%-horizon (early 2026), doubling ~7 months | Effectively unbounded for a skilled professional | Human-time estimates are somewhat subjective; conflates multiple sub-capabilities |
| ToM benchmarks (TMBench etc.) | Social/mental-state reasoning | Real but format-inconsistent; >10pp behind humans on several | Consistent across format | Genuine-vs-pattern-matched capability is actively disputed |

## The meta-lesson

Every benchmark in this file has, at some point, been described in
press coverage as "AI reaches human-level at X" — and in nearly every
case, a closer look reveals either a narrower claim (human-level at *this
specific operationalization* of X) or a result that didn't hold up when
the test format shifted (ARC-AGI-2 → ARC-AGI-3 being the starkest recent
example in this file). The single most useful evaluation habit this
knowledge base can recommend: **when you see an AGI capability claim,
ask which specific benchmark it's based on, and then ask what that
specific benchmark does and doesn't test** — the answer is very often
narrower than the headline.

## Sources

- ARC Prize Foundation, [ARC-AGI](https://arcprize.org/arc-agi),
  [ARC-AGI-1](https://arcprize.org/arc-agi/1); François Chollet's own
  2026 commentary on ARC-AGI-3 result interpretation
  ([source](https://x.com/fchollet/status/2095599835932135919));
  [ARC-AGI in 2026: Why Frontier Models Still Don't
  Generalize](https://labs.adaline.ai/p/what-is-the-arc-agi-benchmark-and);
  [ARC-AGI-3: why all AIs fail Chollet's intelligence
  test](https://anthemcreation.com/en/artificial-intelligence/arc-agi-3-why-every-ai-fails-the-intelligence-test/)
- GAIA: [GAIA: a benchmark for General AI
  Assistants](https://arxiv.org/abs/2311.12983); comparative results
  discussion in [AI Agent Benchmarking Infrastructure
  Guide](https://www.spheron.network/blog/ai-agent-benchmarking-gpu-cloud-swebench-gaia/)
- METR: [Task-Completion Time Horizons of Frontier AI
  Models](https://metr.org/time-horizons/); [Time Horizon
  1.1](https://metr.org/blog/2026-1-29-time-horizon-1-1/);
  [Measuring AI Ability to Complete Long Software
  Tasks](https://metr.org/blog/2025-03-19-measuring-ai-ability-to-complete-long-tasks/);
  [Frontier Risk Report (Feb–Mar 2026)](https://metr.org/blog/2026-05-19-frontier-risk-report/)
- Theory-of-mind benchmarks: see AGI-03 sources for full citations
  (TMBench, TOMVALLEY, OpenToM, MuMA-ToM)
- Composite evaluation: [Holistic Agent Leaderboard: The Missing
  Infrastructure for AI Agent Evaluation](https://arxiv.org/pdf/2510.11977)
