"""Where to look next, by how little Sim knows (stage 8 item 7).

The drive-weighted sampler picks an area by score, softmaxed, with a
temperature that boredom flattens. That is a good answer to "what is
interesting"; it is not an answer to "what do I not know", because a
score says nothing about how sure Sim is of it. An area it has tried
twice and an area it has tried two hundred times can score the same,
and the sampler will treat them the same.

Thompson sampling asks the second question properly. Each target has a
Beta posterior -- the competence table already keeps one per task type
-- and each round draws one number from each. **The lowest draw wins**:
Sim goes where it is worst, and an area with few samples has a wide
posterior, so it draws low often enough to get looked at without ever
being forced. Exploration falls out of the uncertainty rather than
being bolted on as a bonus term.

What can be explored is deliberately wider than the repo (the plan's
list): an area of code, a question somebody keeps asking that has no
good answer, a fact that is queried often and has gone stale, a device
nothing has ever probed, a skill nothing has exercised. They are all
the same shape here -- something with a name and a posterior -- and the
ones with no evidence at all share a prior that says "no idea", not
"probably fine".

Diversity is not optional here, and finding that out was the useful
part: lowest-draw-wins ALONE is a way of finding the worst thing, not
a way of exploring. A target measured 80 times that always fails
draws tightly around 0.01 and beats a flat prior 99 times in 100, so
one hopeless area took 393 of 400 rounds in the first version of this
and the unmeasured targets never came up. `recent` keeps the
sampler's own rule -- just-visited targets go to the back until
everything is recent, then a fresh lap -- and the same 400 rounds
spread 134 / 133 / 131 across the three uncertain targets, with two
for the one Sim is confidently good at.

Boredom still flattens by temperature, which here widens the draws
rather than the softmax: a bored Sim should be more willing to look
somewhere it thinks it already understands, which is the same thing
said in the other vocabulary.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

#: The kinds of thing worth exploring. Repo areas were the whole list
#: until stage 8 item 7.
KINDS: tuple[str, ...] = ("area", "question", "fact", "device", "skill")

#: What a target with no evidence at all is worth. Beta(1, 1) is a flat
#: prior -- "no idea" -- which draws all over the place and therefore
#: gets looked at. A confident prior here would quietly decide that
#: everything unmeasured is fine.
PRIOR = (1.0, 1.0)


@dataclass(frozen=True)
class Unknown:
    """One thing Sim could go and find out about."""

    name: str
    kind: str = "area"
    alpha: float = PRIOR[0]
    beta: float = PRIOR[1]
    #: How many real observations are behind (alpha, beta). Zero means
    #: the prior and nothing else.
    samples: int = 0

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    def draw(self, rng: random.Random, *, temperature: float = 1.0) -> float:
        """One sample from this target's posterior.

        `temperature` above 1 widens it by thinning the evidence: a
        bored Sim is more willing to look somewhere it thinks it
        already understands. It never narrows below the prior, because
        no amount of boredom is evidence.
        """
        scale = 1.0 / max(1e-6, temperature)
        alpha = max(1e-6, PRIOR[0] + (self.alpha - PRIOR[0]) * scale)
        beta = max(1e-6, PRIOR[1] + (self.beta - PRIOR[1]) * scale)
        return rng.betavariate(alpha, beta)


def from_posterior(name: str, posterior, *, kind: str = "area") -> Unknown:
    """An `Unknown` from a `(alpha, beta, samples)` triple -- the shape
    `CompetenceTable.posterior` already returns."""
    alpha, beta, samples = posterior
    return Unknown(name=name, kind=kind, alpha=float(alpha), beta=float(beta), samples=int(samples))


def order(unknowns, *, rng: random.Random, temperature: float = 1.0, recent=()) -> list[Unknown]:
    """Everything worth exploring, lowest draw first.

    One draw each, one ordering: a caller that wants the next target
    takes the head, and a caller that wants a plan for the night takes
    as many as its budget allows without drawing again.

    `recent` is the sampler's diversity rule, kept (stage 8 item 7),
    and it is not a detail. Lowest-draw-wins on its own is a way of
    finding the worst thing, not a way of exploring: a target Sim has
    measured 80 times and always failed draws tightly around 0.01 and
    beats a flat prior 99 times in 100, so one hopeless area would
    take every night and the unmeasured ones would never come up.
    Recently visited targets go to the back, and only once everything
    is recent does the whole space become eligible again -- a fresh
    lap, exactly as `DriveWeightedSampler` does it.
    """
    seen = {str(name) for name in (recent or ())}
    drawn = [(u.name in seen, u.draw(rng, temperature=temperature), u.name, u) for u in unknowns]
    if all(row[0] for row in drawn):        # everything is recent: a fresh lap
        drawn = [(False, *row[1:]) for row in drawn]
    drawn.sort(key=lambda row: (row[0], row[1], row[2]))
    return [u for _recent, _value, _name, u in drawn]


def pick(unknowns, *, rng: random.Random, temperature: float = 1.0, recent=()) -> Unknown | None:
    """The one to look at now: the lowest draw of the ones not just
    looked at."""
    ranked = order(unknowns, rng=rng, temperature=temperature, recent=recent)
    return ranked[0] if ranked else None


def unknowns_from(*, competence=None, task_types=(), questions=(), stale_facts=(),
                  unprobed_devices=(), unexercised_skills=()) -> list[Unknown]:
    """The whole target space, in one list (stage 8 item 7).

    Everything but the task types arrives with the flat prior, because
    nothing has measured them: a question nobody could answer, a fact
    that has gone stale, a device never probed and a skill never run
    are all things Sim has no evidence about, which is exactly what
    the prior says.
    """
    out: list[Unknown] = []
    for task_type in task_types:
        if competence is not None:
            out.append(from_posterior(task_type, competence.posterior(task_type), kind="area"))
        else:
            out.append(Unknown(name=task_type, kind="area"))
    for kind, names in (("question", questions), ("fact", stale_facts),
                        ("device", unprobed_devices), ("skill", unexercised_skills)):
        out.extend(Unknown(name=str(name), kind=kind) for name in names if str(name).strip())
    return out


__all__ = ["KINDS", "PRIOR", "Unknown", "from_posterior", "order", "pick", "unknowns_from"]
