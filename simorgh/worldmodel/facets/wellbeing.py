"""`world:wellbeing` (stage 10 item 2): how each person seems, against their own usual.

The creator's ask: notice when somebody in the family is low, and ask
gently. Two constraints shape how, and both are structural here rather
than promises in a prompt.

**Consent, not inference.** The facet keeps nothing about a person that
`contracts.people.may_check_in` refuses: an adult who said yes, once, at
onboarding. A child, a guest, a voice nobody placed, an adult who has not
said yes -- `observe` returns False and stores nothing, and revoking the
permission deletes what was kept. That gate is applied on the way *in*,
so there is no record to leak later.

**Estimation, not rules.** Each person has a *baseline* of how they
usually talk to Sim, learnt from cheap features of their own turns: how
much they say (log word count), how fast (words per second, when the
turn was spoken), and whether Sim's reply tone was soft (`warm` or
`sorry` -- the model's own read of the moment, folded as evidence rather
than as a rule). A turn is scored against that baseline as a composite
z; a turn well below it is a low-side trial, well above a high-side one.
The state is a Beta posterior over the *rate of low-side turns lately*,
where "lately" is a half-life on the weight of each trial -- the same
shape as `growth/estimate/competence.py::posterior`, pointed at a person
instead of a task type. `low` needs the posterior mean at or above
`LOW_AT` *and* at least `MIN_EVIDENCE` turns' worth of fresh weight;
anything less is `unknown`, which is a visible answer and never `fine`.

The baseline learns from every turn *after* scoring it, so somebody who
changes for weeks becomes their own new usual, and Sim does not ask the
same question every day for a month. A quiet person is not "low" for
being quiet: their baseline is quiet.

What is kept is small and inspectable in one file beside `people.json`:
per person, the moments of each feature and a bounded window of
`(when, z)` pairs. Never the words. `now_block(person=)` renders one
person, for that person's own turns; nothing here is a diagnosis or a
label, only "quieter than usual lately" with the numbers it rests on.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

#: A trial's weight as evidence halves every six hours: this morning's
#: turns matter, last week's do not.
HALF_LIFE_S = 6 * 3600.0
#: Turns before a feature's baseline is trusted enough to score against.
BASELINE_MIN = 12
#: How many turns the baseline effectively remembers (the EWMA horizon).
BASELINE_HORIZON = 100
#: Trials kept per person; older ones have decayed to nothing anyway.
WINDOW_MAX = 64
#: A composite z at or beyond this is a low-side (or high-side) trial.
Z_EDGE = 1.0
#: The posterior mean of the low-side rate at or above which the state is
#: `low` (and, mirrored, `high`). Under the baseline the rate is ~0.16.
LOW_AT = 0.5
#: Weighted turns' worth of fresh evidence before any state but `unknown`.
MIN_EVIDENCE = 3.0
#: Nobody heard from for this long has no state, whatever the posterior.
FRESH_S = 24 * 3600.0
#: Sim's reply tones that read as a soft moment (`contracts/tone.py`).
SOFT_TONES: tuple[str, ...] = ("warm", "sorry")
#: The features, with the sign that makes "lower" mean "quieter": fewer
#: words and slower speech point down; a softer reply tone points down
#: too, so its sign is flipped.
FEATURES: dict[str, int] = {"words": +1, "rate": +1, "soft": -1}
#: A floor on each feature's spread, so a very steady baseline does not
#: turn an ordinary turn into a three-sigma event.
SD_FLOOR: dict[str, float] = {"words": 0.35, "rate": 0.5, "soft": 0.25}
STATES: tuple[str, ...] = ("unknown", "usual", "low", "high")

Consent = Callable[[str], tuple[bool, str]]


def features_of(text: str, *, seconds: float | None = None, tone: str = "") -> dict[str, float]:
    """The cheap, deterministic features of one turn. Detection is the one
    part of this that is a rule; everything after it is estimation."""
    words = len((text or "").split())
    out: dict[str, float] = {}
    if words > 0:
        out["words"] = math.log1p(words)
        if seconds is not None and seconds > 0.3:
            out["rate"] = words / float(seconds)
    if tone:
        out["soft"] = 1.0 if tone in SOFT_TONES else 0.0
    return out


def decayed(weight: float, seconds: float) -> float:
    """`weight` after `seconds` with the half-life."""
    if weight <= 0.0 or seconds <= 0.0:
        return max(0.0, weight)
    return weight * (0.5 ** (seconds / HALF_LIFE_S))


@dataclass
class Moments:
    """An exponentially-weighted mean and variance: one feature's baseline."""

    n: int = 0
    mean: float = 0.0
    var: float = 0.0

    def z(self, x: float, *, floor: float) -> float | None:
        """How far `x` is from usual, in spreads; None before the baseline
        is worth trusting."""
        if self.n < BASELINE_MIN:
            return None
        sd = max(math.sqrt(max(self.var, 0.0)), floor)
        return max(-3.0, min(3.0, (x - self.mean) / sd))

    def learn(self, x: float) -> None:
        # Welford while young, EWMA once the horizon is reached: converges
        # quickly at first and keeps following the person after.
        alpha = 1.0 / min(self.n + 1, BASELINE_HORIZON)
        delta = x - self.mean
        self.mean += alpha * delta
        self.var = (1.0 - alpha) * self.var + alpha * delta * (x - self.mean)
        self.n += 1

    def to_dict(self) -> dict:
        return {"n": self.n, "mean": round(self.mean, 6), "var": round(self.var, 6)}

    @classmethod
    def from_dict(cls, data: dict) -> "Moments":
        return cls(n=int(data.get("n") or 0), mean=float(data.get("mean") or 0.0), var=float(data.get("var") or 0.0))


@dataclass
class _Record:
    baseline: dict[str, Moments] = field(default_factory=dict)
    trials: list[tuple[float, float]] = field(default_factory=list)      # (at, composite z)
    last_at: float = 0.0

    def to_dict(self) -> dict:
        return {"baseline": {k: m.to_dict() for k, m in self.baseline.items()},
                "trials": [[round(at, 1), round(z, 4)] for at, z in self.trials], "last_at": self.last_at}

    @classmethod
    def from_dict(cls, data: dict) -> "_Record":
        rec = cls()
        rec.baseline = {str(k): Moments.from_dict(v) for k, v in (data.get("baseline") or {}).items()}
        rec.trials = [(float(a), float(z)) for a, z in (data.get("trials") or []) if isinstance((a, z), tuple) or True][-WINDOW_MAX:]
        rec.last_at = float(data.get("last_at") or 0.0)
        return rec


def _refused(_name: str) -> tuple[bool, str]:
    return False, "no consent source"


class WellbeingFacet:
    """Per-person baselines, the deviation posterior, and the state note."""

    name = "wellbeing"

    def __init__(self, path: Path | None = None, *, clock=None, consent: Consent | None = None) -> None:
        self._path = Path(path) if path else None
        self._clock = clock or time.time
        # Who may be tracked at all. The default tracks nobody: a facet
        # nobody told about consent has no business keeping anything.
        self._consent: Consent = consent or _refused
        self._people: dict[str, _Record] = {}
        self._loaded = False
        self._last_state: dict[str, str] = {}

    def _now(self) -> float:
        return float(self._clock() if callable(self._clock) else self._clock.now())

    # -- the file --------------------------------------------------------------------
    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if self._path is None or not self._path.is_file():
            return
        try:
            data = json.loads(self._path.read_text())
        except (OSError, ValueError):
            return          # an unreadable file is a fresh start, not a crash
        for name, rec in (data.get("people") or {}).items():
            try:
                self._people[str(name)] = _Record.from_dict(rec)
            except (TypeError, ValueError):
                continue

    def save(self) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps({"people": {n: r.to_dict() for n, r in self._people.items()}}, indent=1))
        except OSError:
            pass

    # -- evidence in -------------------------------------------------------------------
    def observe(self, person: str, *, text: str, seconds: float | None = None, tone: str = "",
                at: float | None = None) -> bool:
        """One turn by `person`. False, and nothing kept, unless they may be
        tracked; True when the turn was folded in (whether or not it was
        scored -- the first `BASELINE_MIN` only teach the baseline)."""
        person = (person or "").strip()
        if not person:
            return False
        ok, _why = self._consent(person)
        if not ok:
            return False
        feats = features_of(text, seconds=seconds, tone=tone)
        if not feats:
            return False
        self.load()
        rec = self._people.setdefault(person, _Record())
        now = at if at is not None else self._now()
        # Score against the past first, then learn from the turn: the
        # baseline that judges a turn must not already contain it.
        zs = []
        for feat, x in feats.items():
            z = rec.baseline.setdefault(feat, Moments()).z(x, floor=SD_FLOOR[feat])
            if z is not None:
                zs.append(FEATURES[feat] * z)
        if zs:
            rec.trials.append((now, sum(zs) / len(zs)))
            del rec.trials[:-WINDOW_MAX]
        for feat, x in feats.items():
            rec.baseline[feat].learn(x)
        rec.last_at = max(rec.last_at, now)
        self.save()
        return True

    def forget(self, person: str) -> bool:
        """Drop everything kept about `person`: what revoking means."""
        self.load()
        gone = self._people.pop((person or "").strip(), None) is not None
        self._last_state.pop((person or "").strip(), None)
        if gone:
            self.save()
        return gone

    # -- questions out -------------------------------------------------------------------
    def posterior(self, person: str, *, now: float | None = None) -> tuple[float, float, float, float]:
        """`(alpha_low, beta_low, alpha_high, evidence)`: Beta(1, 1) plus the
        decayed weight of each trial on its side. `evidence` is the total
        weight -- how many fresh turns' worth this rests on."""
        self.load()
        now = self._now() if now is None else now
        rec = self._people.get((person or "").strip())
        a_low = b_low = a_high = 1.0
        evidence = 0.0
        if rec is not None:
            for at, z in rec.trials:
                w = decayed(1.0, now - at)
                if w < 1e-4:
                    continue
                evidence += w
                if z <= -Z_EDGE:
                    a_low += w
                else:
                    b_low += w
                if z >= Z_EDGE:
                    a_high += w
        return a_low, b_low, a_high, evidence

    def estimate(self, person: str, *, now: float | None = None) -> dict:
        """What Sim believes about how `person` seems, with what it rests
        on -- the shape `world.env.query{what: "wellbeing"}` answers."""
        self.load()
        now = self._now() if now is None else now
        person = (person or "").strip()
        ok, why = self._consent(person)
        rec = self._people.get(person)
        out = {"person": person, "state": "unknown", "tracked": bool(ok), "low": None, "high": None, "spread": None,
               "evidence": 0.0, "samples": 0, "baseline_turns": 0, "last_seen_s": None, "why": ""}
        if not ok:
            out["why"] = why
            return out
        if rec is None:
            out["why"] = "no turns yet"
            return out
        baseline_turns = min((m.n for m in rec.baseline.values()), default=0) if rec.baseline else 0
        out["baseline_turns"] = max((m.n for m in rec.baseline.values()), default=0)
        out["samples"] = len(rec.trials)
        out["last_seen_s"] = round(max(0.0, now - rec.last_at), 1) if rec.last_at else None
        a_low, b_low, a_high, evidence = self.posterior(person, now=now)
        total = a_low + b_low
        mean_low = a_low / total
        # The high side shares the denominator: a trial is on at most one
        # side, and the rest is the middle.
        mean_high = a_high / total
        variance = (a_low * b_low) / ((total ** 2) * (total + 1.0))
        out.update(low=round(mean_low, 4), high=round(mean_high, 4), spread=round(math.sqrt(variance), 4),
                   evidence=round(evidence, 3))
        if out["baseline_turns"] < BASELINE_MIN or baseline_turns == 0:
            out["why"] = f"baseline forming ({out['baseline_turns']}/{BASELINE_MIN} turns)"
            return out
        if rec.last_at and now - rec.last_at > FRESH_S:
            out["why"] = "not heard from lately"
            return out
        if evidence < MIN_EVIDENCE:
            out["why"] = f"too little recent evidence ({evidence:.1f} of {MIN_EVIDENCE:.0f} turns' worth)"
            return out
        if mean_low >= LOW_AT:
            out["state"] = "low"
        elif mean_high >= LOW_AT:
            out["state"] = "high"
        else:
            out["state"] = "usual"
        return out

    def state_of(self, person: str, *, now: float | None = None) -> str:
        return str(self.estimate(person, now=now)["state"])

    def tracked(self) -> list[str]:
        """Everybody with a record, whose consent still holds."""
        self.load()
        return sorted(p for p in self._people if self._consent(p)[0])

    def changes(self, *, now: float | None = None) -> list[tuple[str, dict]]:
        """`(person, estimate)` for every tracked person whose state moved
        since this was last asked. Flips only: a state that has not
        moved is not news."""
        now = self._now() if now is None else now
        moved = []
        for person in self.tracked():
            est = self.estimate(person, now=now)
            if self._last_state.get(person, "unknown") != est["state"]:
                moved.append((person, est))
            self._last_state[person] = est["state"]
        return moved

    def now_block(self, *, now: float | None = None, person: str = "", limit: int = 5) -> str:
        """A line per tracked person -- or one person's line -- for a
        prompt's per-turn note. Numbers, never words of theirs, never a
        label: "quieter than usual lately" and what it rests on.

        A consumer must pass `person=` for the turn's own speaker (stage
        10 item 5): one person's state is not for another's turn.
        """
        now = self._now() if now is None else now
        names = [person.strip()] if person else self.tracked()[:limit]
        lines = []
        for name in names:
            est = self.estimate(name, now=now)
            if not est["tracked"]:
                continue
            ago = est["last_seen_s"]
            last = f", last heard {int(ago // 60)} min ago" if ago is not None and ago < 6 * 3600 else ""
            if est["state"] == "low":
                lines.append(f"- {name} seems quieter than usual lately ({est['low']:.0%} of about "
                             f"{est['evidence']:.0f} recent turns{last})")
            elif est["state"] == "high":
                lines.append(f"- {name} seems brighter than usual lately ({est['high']:.0%} of about "
                             f"{est['evidence']:.0f} recent turns{last})")
            elif est["state"] == "usual":
                lines.append(f"- {name}: about their usual{last}")
            else:
                lines.append(f"- {name}: no recent read ({est['why']})")
        return "\n".join(lines)

    async def get(self, args: dict) -> dict:
        """`world.env.query{what: "wellbeing"}`: one person, or everybody
        tracked. Never anybody who may not be tracked, beyond saying so."""
        now = self._now()
        person = str(args.get("person") or "")
        if person:
            est = self.estimate(person, now=now)
            return {**est, "note": self.now_block(now=now, person=person)}
        return {"people": [self.estimate(p, now=now) for p in self.tracked()]}


__all__ = ["BASELINE_MIN", "FEATURES", "FRESH_S", "HALF_LIFE_S", "LOW_AT", "MIN_EVIDENCE", "Moments", "SOFT_TONES",
           "STATES", "WINDOW_MAX", "WellbeingFacet", "Z_EDGE", "decayed", "features_of"]
