# AGI: Core Attributes — What Makes Intelligence "General"

If AGI-01 covers *how the field tries to define AGI*, this file covers a
narrower, more concrete question: **what specific properties separate a
"general" intelligence from a "narrow" one?** These are the attributes
that recur across nearly every definition in AGI-01, even when the
definitions disagree about how to measure them.

## 1. Transfer learning

**Transfer** is the ability to apply knowledge or skill learned in one
context to a *different* context, without needing to relearn from
scratch. It's the most fundamental building block of generality, because
without it, every new task requires new training data — which is the
definition of narrow AI.

Concretely, transfer shows up at several granularities:

- **Near transfer**: applying a skill to a task very similar to the
  training task (a model trained on Python bug-fixing applying the same
  skill to a slightly different Python codebase).
- **Far transfer**: applying a skill to a *structurally different*
  domain (a model that learned logical deduction in a text context
  applying the same deductive structure to a visual puzzle).
- **Zero-shot transfer**: succeeding at a task with no task-specific
  examples at all, based purely on general capability plus a
  description of the task.
- **Cross-modal transfer**: applying a concept learned in one modality
  (e.g. text) to another (e.g. vision or robotic control) — this is an
  active, difficult research area, since most models are still trained
  with modality-specific pretraining even in "multimodal" systems.

Modern LLMs display substantial near and zero-shot transfer within the
domains their training data covers (this is most of what "few-shot
prompting" and "in-context learning" exploit) but transfer is markedly
weaker for tasks that are *structurally* novel rather than just
differently-worded — which is exactly the gap ARC-AGI is built to expose
(see AGI-01, AGI-06).

## 2. Sample efficiency

**Sample efficiency** is how much data or experience a system needs
before it can perform a new task well. Humans are strikingly sample
efficient at many things — a child can learn what a "giraffe" is from
one or two examples and correctly generalize to giraffes photographed
from unusual angles, in different lighting, at different ages. Most deep
learning systems, by contrast, are extremely sample *in*efficient by
comparison: modern LLMs are pretrained on trillions of tokens, and even
"few-shot" adaptation typically means dozens of examples, not one or two.

This matters for AGI specifically because **the world does not supply
unlimited labeled data for every task a general agent might encounter.**
An agent that needs a thousand examples to learn a new user's
preferences, a new codebase's conventions, or a new robot's physical
dynamics is not going to function well in an open-ended deployment where
novel situations are the norm, not the exception. Few-shot and zero-shot
learning research (meta-learning approaches like MAML, prototypical
networks, in-context learning in transformers) exists specifically to
close this gap — training a system not just to perform tasks, but to
*learn new tasks quickly*, sometimes called "learning to learn."

## 3. Open-ended domain coverage

A narrow system is built (or trained) for a bounded, pre-specified set
of tasks — a chess engine plays chess; a spam filter classifies email. A
general system needs to function across a domain space that is not fully
specified in advance — including tasks nobody anticipated when the
system was built. This is a genuinely different engineering target: it's
not "handle more tasks" (which can be done by adding more narrow modules)
but "handle tasks not enumerated ahead of time."

Practically, open-endedness is often approximated today by:

- **General-purpose pretraining** on broad, unfiltered-by-task data (the
  strategy behind LLMs' apparent breadth) — the model absorbs an
  enormous implicit task distribution rather than a curated one.
- **Compositional tool use** — rather than the model itself knowing
  everything, giving it the ability to call out to specialized tools
  (calculators, code interpreters, search engines, other models) to
  cover domains it wasn't directly trained to be expert in. This
  reframes "open-ended coverage" from "know everything" to "know how to
  find or invoke the right capability" — see AGI-03's tool-use section
  and AGI-04's tool-use interface subsystem.
- **Self-directed goal generation** — a system that can propose its own
  sub-goals and tasks in response to a broad objective, rather than only
  ever executing an externally specified task list. (Simorgh's own
  `discover_creative_improvements`/`discover_creative_project`
  mechanisms, `src/main.py`, are a small, concrete instance of this:
  the system proposes its own next task rather than only reacting to
  human-typed commands.)

## 4. Robustness to novel situations

Related to but distinct from transfer: **robustness** is about *not
failing badly* when a situation is genuinely outside prior experience,
even if the system can't fully solve it. A robust system degrades
gracefully — it recognizes uncertainty, asks for help, or falls back to
a safe default — rather than confidently producing a wrong or dangerous
output ("hallucinating" with high apparent confidence, or a robot
continuing a manipulation action into an unanticipated obstacle).

This is one of the sharpest known gaps in current frontier systems:
LLMs are well documented to produce fluent, confident-sounding output
even when factually wrong or reasoning invalidly, and there is no
reliable, general mechanism (as of 2026) for a model to *know what it
doesn't know* with high fidelity. This connects directly to the
meta-cognition capability discussed in AGI-03 and the self-monitoring
subsystem in AGI-04 — robustness to novelty is, in large part, a
downstream consequence of good meta-cognitive calibration.

## 5. Common-sense reasoning

**Common sense** is the vast body of everyday, usually-unstated
knowledge about how the physical and social world works — water is wet,
objects fall when unsupported, people don't want to be embarrassed in
public, a full glass will spill if tilted. It's foundational to general
intelligence because almost no task is fully specified without relying
on it: instructions to "get me a drink from the fridge" implicitly
assume you won't walk through the wall, won't grab the neighbor's fridge,
and will bring the drink upright rather than poured out on the way.

Common sense is *hard* to test directly (most of it is too obvious for
humans to think to state, which is exactly why it's a gap for machines
that haven't lived a physical, social life), and it's a longstanding
open problem — from Cyc (a decades-long hand-built common-sense
knowledge base project, largely considered to have fallen short of its
goals) through today's LLMs, which absorb a great deal of common sense
implicitly from text (because humans write about the world in ways that
presuppose it) but still fail on some surprisingly basic physical and
causal reasoning, particularly when a question is phrased to avoid
pattern-matching a commonly-seen textual formulation of the same
scenario.

## 6. Generalization vs. memorization — the throughline

Every attribute above is, in a sense, a facet of one underlying question:
**does the system's competence come from having genuinely learned
transferable structure, or from having seen something similar enough
before?** This is the throughline of Chollet's critique (AGI-01) and it
is why "the model gets a high score on benchmark X" is treated with
real caution in serious AGI discussion — a high score can come from
either source, and only one of them is evidence of generality.

Concrete diagnostic questions used in practice to tell these apart:

- **Does performance degrade when surface features change but the
  underlying structure doesn't?** (E.g., renaming variables in a coding
  problem, or using unfamiliar words for a familiar logical structure.)
  A system relying on memorized pattern-matching typically degrades
  more than one relying on genuine structural understanding.
- **Does performance hold on tasks constructed *after* the model's
  training cutoff*, specifically to avoid contamination?** This is why
  benchmarks like ARC-AGI are deliberately kept partly private/rotated,
  and why "the same benchmark, retested on a freshly-generated variant"
  is considered stronger evidence than a single fixed public test set.
- **Can the system explain *why*, in a way that predicts its behavior
  on a related but different case?** Genuine understanding should let a
  system's stated reasoning predict its own future behavior; memorized
  pattern-matching often produces post-hoc explanations that don't
  actually track what determined the output.

## Summary table

| Attribute | What it means | Why it's hard | Where it shows up in current systems |
|---|---|---|---|
| Transfer | Applying learned skill to a new context | Far/cross-modal transfer requires structural, not surface, learning | Strong near-transfer in LLMs; weak far-transfer to structurally novel tasks |
| Sample efficiency | Learning from little data | Deep learning is naturally data-hungry; efficient learning needs strong priors | In-context learning is a partial win; true few-shot learning of *new skills* (not just new facts) remains limited |
| Open-ended coverage | Handling tasks not enumerated in advance | Requires either near-total pretraining coverage or compositional tool use | Approximated via broad pretraining + tool-calling; genuinely novel domains still fail |
| Robustness to novelty | Failing gracefully, not confidently-wrong | Requires accurate self-uncertainty estimates | Known weak point — confident hallucination remains common |
| Common sense | Unstated everyday world knowledge | Too pervasive/implicit to fully specify or test | Substantially present via text-derived priors; gaps in physical/causal edge cases |
| Generalization vs. memorization | Whether competence transfers to genuinely new structure | Hard to tell apart from outside; requires careful benchmark design | Actively, currently debated for every major frontier model release |

## Sources

- François Chollet, *On the Measure of Intelligence* (2019) and the [ARC
  Prize](https://arcprize.org/) program
- Survey: [A Comprehensive Survey of Few-shot Learning: Evolution,
  Applications, Challenges, and Opportunities](https://dl.acm.org/doi/10.1145/3582688)
- Shane Legg & Marcus Hutter, Universal Intelligence (see AGI-01 for full
  citation) — the "wide range of environments" framing underlies the
  open-ended-coverage and robustness attributes here
- General background: Google DeepMind, [Levels of AGI](https://arxiv.org/pdf/2311.02462)
  (the Generality axis is effectively this file's throughline, formalized)
