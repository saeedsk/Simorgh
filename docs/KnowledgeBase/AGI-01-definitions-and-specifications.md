# AGI: Definitions and Specifications

There is no single technical, universally-accepted definition of
Artificial General Intelligence. That is not a rhetorical hedge — it's
the actual state of the field, and it matters practically: whether
someone believes AGI has arrived, is imminent, or is decades away often
comes down to *which* definition they're using, not a disagreement about
the underlying facts. This file walks through the major serious framings,
what each is actually claiming, and where they conflict.

## 1. The Turing Test and its descendants

Alan Turing's 1950 "imitation game" proposed that a machine could be
considered intelligent if a human judge, conversing via text, couldn't
reliably distinguish it from a human. This is the oldest and most
culturally famous framing, but it has two well-known problems as a
definition of *general* intelligence specifically:

- It measures **conversational indistinguishability**, not capability.
  A system can be a very good conversational mimic (or exploit judges'
  expectations, as the chatbot ELIZA and later "Turing test winners"
  arguably did) without being able to do much of anything else — plan a
  research project, control a robot, or solve a novel logic puzzle.
- It says nothing about *how* the intelligence is achieved, which is
  precisely why it was originally proposed — Turing wanted to sidestep
  "can machines think?" as unanswerable and substitute a behavioral
  test. That deliberate vagueness is a feature for the philosophical
  question and a weakness for an engineering specification.

Modern practice has largely moved past the literal Turing test as an AGI
yardstick, but its descendants persist: any benchmark of the form "can a
human tell the difference" (image generation realism, voice synthesis,
long-form writing) is a Turing-test variant, and all inherit the same
limitation — indistinguishability in one narrow modality is not
generality.

## 2. The economic / capability definition (OpenAI's Charter)

OpenAI's charter (published 2018) defines AGI as **"highly autonomous
systems that outperform humans at most economically valuable work."**
([OpenAI Charter](https://openai.com/charter/))

This definition has two load-bearing parts:

1. **Breadth of competence** — "most economically valuable work," not
   one job. A system that is superhuman at chess but can't be a
   paralegal, a customer-support agent, or a software engineer doesn't
   qualify.
2. **Autonomy** — "highly autonomous," meaning the system can carry out
   that work without a human directing every step. A tool that requires
   constant human steering (even if, steered, it produces
   economically-valuable output) doesn't fully meet this bar either.

This definition is popular precisely because it's operational — it maps
onto something measurable in principle (labor-market displacement,
task-completion rates on real jobs) — but it's also contested. Critics
note:

- "Economically valuable" is culturally and temporally relative — a
  task's economic value depends on wages, automation costs, and market
  structure, not just the cognitive difficulty of the task, so this
  definition can shift without any change in the underlying system's
  capability.
- It has no explicit generality requirement beyond "most" — a system
  that automates 70% of jobs by economic value but is completely unable
  to do open-ended scientific research or long-horizon creative work
  could arguably satisfy a literal reading while missing what most
  people intuitively mean by "general."
- There's no universally accepted technical benchmark attached to it —
  it's a strategic/mission statement, not a test protocol.

## 3. Legg & Hutter's Universal Intelligence Measure

Shane Legg and Marcus Hutter (2007) proposed the most mathematically
rigorous attempt at a definition: **"Intelligence measures an agent's
ability to achieve goals in a wide range of environments."**
([Universal Intelligence: A Definition of Machine Intelligence](https://www.researchgate.net/publication/1904177_Universal_Intelligence_A_Definition_of_Machine_Intelligence))

Formally, it's built on:

- **Solomonoff induction** — a formalization of Occam's razor: among all
  computable hypotheses consistent with the data, weight the simpler
  (shorter-program) ones more heavily.
- **Kolmogorov complexity** — using program length as an environment's
  complexity measure, so "a wide range of environments" can be made
  precise: every computable environment, weighted by simplicity.
- **AIXI** (Hutter's own theoretical agent) — a hypothetical agent that
  is provably optimal at maximizing reward across all computable
  environments, given unbounded computation.

The **universal intelligence measure**, informally called the
**Legg-Hutter score**, formalizes intelligence as the *expected
performance of an agent, averaged across every computable environment,
weighted by simplicity*. This is the most theoretically clean definition
in the field — it's non-anthropocentric (doesn't presuppose
human-like cognition) and precisely general (it explicitly ranges over
*all* possible environments, not a curated task suite).

Its practical limitation is severe: **the measure is only asymptotically
computable.** You cannot actually run it — computing it requires summing
over an infinite set of environments weighted by Kolmogorov complexity,
which is itself uncomputable in general. So while Legg-Hutter gives the
field a north star for what "fully general intelligence" would mean
mathematically, it cannot be used directly as a test. Later work (e.g.
"An Approximation of the Universal Intelligence Measure," Legg &
Veness) has tried to build *computable approximations*, but these
necessarily give up some generality to become tractable, reintroducing
the same "which subset of environments do we actually test" problem the
measure was meant to escape.

## 4. Chollet's generalization framing ("On the Measure of Intelligence")

François Chollet's 2019 paper reframes the question away from "what can
the system do" and toward **"how efficiently does the system acquire new
skill, relative to its prior knowledge, experience, and generalization
difficulty."** His core claim: measuring *skill at a fixed set of
tasks* (which is what most benchmarks, including many "AGI" benchmarks,
actually do) rewards systems that have simply been exposed to those
tasks or near-variants during training — it doesn't distinguish a system
that generalizes from one that memorized.

Chollet's own operationalization is the **Abstraction and Reasoning
Corpus (ARC-AGI)**: a set of visual puzzle-grid tasks, each solvable by a
human in seconds with **zero task-specific training**, designed so that
the pattern needed to solve each puzzle cannot plausibly have been seen
verbatim in any training corpus. The benchmark's whole premise is that
"skill acquisition efficiency" — not the amount of static knowledge a
system carries — is the right proxy for the "generality" component of
general intelligence.

Chollet is explicit — including in 2026 commentary on ARC-AGI-3
([source](https://x.com/fchollet/status/2095599835932135919)) — that
*saturating* the ARC benchmark does not, by itself, mean a system is
AGI. It means the specific hypothesis ARC tests (fluid, on-the-fly
abstraction on novel tasks) has been satisfied; other hypotheses (e.g.
open-ended embodied interaction, which ARC-AGI-3 attempts to probe more
directly) remain untested. This is a useful discipline: treat any single
benchmark, including the ones this knowledge base cites heavily, as
testing *a* component of general intelligence, not the whole construct.

## 5. DeepMind's "Levels of AGI" (2023)

Google DeepMind's paper *"Levels of AGI: Operationalizing Progress on the
Path to AGI"* ([arXiv:2311.02462](https://arxiv.org/pdf/2311.02462)) is
less a single definition than a framework for **classifying systems along
two axes**, explicitly built because the authors found existing
definitions (including several above) individually inadequate but the
underlying intuitions worth preserving.

The two axes:

- **Performance** (depth) — how *good* is the system at tasks, ranging
  from "No AI" through Emerging, Competent, Expert, Virtuoso, to
  Superhuman.
- **Generality** (breadth) — how *wide* a range of tasks does that
  performance level cover, from Narrow (a specific task or set of tasks)
  to General (a wide range of tasks, including metacognitive ones like
  learning new skills).

Crossing these gives a matrix: a system can be a "Competent Narrow AI"
(reliably good at one thing) or an "Emerging General AI" (weakly capable
but across a wide range), and so on up to "Artificial Superintelligence"
(superhuman performance, general breadth). The paper's stated intent is
to let researchers, policymakers, and the public say something more
precise than "is it AGI yet" — e.g., "current frontier LLMs are arguably
Competent-to-Expert on many narrow-to-moderately-general tasks, but not
yet Expert-General."

The paper also proposes six levels of **autonomy** (tool → consultant →
collaborator → expert → agent → fully autonomous), treating autonomy as
a separate, orthogonal axis from capability — a system can be highly
capable but deliberately kept at low autonomy (human approves every
action), which matters for both safety framing and for comparing systems
that are equally *capable* but different in how much they're *trusted to
act unsupervised*. This autonomy axis is one of the clearest points of
contact with practical system design: see AGI-04's discussion of the
safety/oversight layer, and note that Simorgh's own audit-gate design
(`docs/SOUL.md`, `src/orchestrator/audit.py`) is effectively a
hard-coded low-autonomy-by-default policy on top of a system that could
otherwise act with much higher autonomy.

## 6. Where the definitions actually conflict

It's worth being explicit about the disagreements, since they aren't
just wording differences:

| Question | Turing-style | OpenAI (economic) | Legg-Hutter | Chollet | DeepMind Levels |
|---|---|---|---|---|---|
| Is a system with vast static knowledge but poor on-the-fly generalization "AGI"? | Possibly yes (fools judges) | Possibly yes (economically useful) | No (low score without efficient goal achievement across novel environments) | No (that's exactly what it's designed to catch) | Depends — high Performance, contested Generality |
| Does autonomy matter, separate from capability? | Not addressed | Yes, explicitly required | Not explicitly separated | Not addressed | Yes, a separate axis |
| Is the definition computable/testable today? | Loosely (human-judge panels) | No formal test | No (only asymptotically) | Yes (ARC-AGI is a real, running benchmark) | Yes, but requires subjective/expert calibration of the level matrix |
| Does it require generality across *all* domains, or "most"? | Not addressed (one modality) | "Most" economically valuable work | All computable environments (in the limit) | All *sufficiently novel* tasks, not literally all domains | A spectrum, not a threshold |

The practical upshot: when you see a claim like "AI system X has reached
AGI" or "AGI is N years away," the first useful question is *"by which
of these definitions?"* — the answer is very often different depending
on which one is used, and reporting or discussion that doesn't specify
is usually not making a precise claim at all.

## Sources

- OpenAI, [OpenAI Charter](https://openai.com/charter/) (2018)
- Shane Legg & Marcus Hutter, [Universal Intelligence: A Definition of
  Machine Intelligence](https://www.researchgate.net/publication/1904177_Universal_Intelligence_A_Definition_of_Machine_Intelligence)
  (2007); see also [An Approximation of the Universal Intelligence
  Measure](https://arxiv.org/pdf/1109.5951)
- François Chollet, *On the Measure of Intelligence* (2019), and
  [ARC Prize](https://arcprize.org/arc-agi) / [ARC-AGI-1](https://arcprize.org/arc-agi/1)
- Google DeepMind, [Levels of AGI: Operationalizing Progress on the Path
  to AGI](https://arxiv.org/pdf/2311.02462) (arXiv:2311.02462, 2023)
- Metaculus/METR background framing, [AGI: Definitions and Potential
  Impacts](https://metr.org/agi.pdf)
