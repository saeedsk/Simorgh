"""`CompetenceTable`: the projection over `learn:outcomes` (spec section
3.4/4). A pure function of the append-only log (principle 01 section
4.4) -- `apply()` never does anything a fresh `rebuild()` wouldn't also
produce, which is what the property test in `test_competence.py` checks.

Math is exactly spec section 4's: Laplace-smoothed success rate, shrunk
toward 0.5 below `min_samples_for_trust`, ranked for exploration with a
UCB1-shaped bonus. Calibration is the mean absolute gap between a
recorded outcome's `stated_confidence` and whether it actually
succeeded, over outcomes that reported one -- 1.0 is perfectly
calibrated, 0.0 is maximally wrong; `None`/no-data outcomes don't count
either way (never fabricate a number from nothing).
"""

from __future__ import annotations

import math

from simorgh.contracts.envelope import Event

from .models import Outcome, StrategyScore, StrategyStats, TaskTypeStats


class _Projection:
    """Duck-typed stand-in for `simorgh.ledger.api.Projection`: the
    module boundary rule (`tests/simorgh/test_module_boundaries.py`)
    only allows a subsystem to import `simorgh.ledger.client`, not
    `simorgh.ledger.api` -- and `LedgerClient.rebuild()`/`materialize()`
    only ever call `.load`/`.fold`/`.state`/`.applied_seq`/
    `.snapshot_seq`/`.snapshot_every` on whatever it's given (see
    `simorgh/ledger/projection.py`), never `isinstance`. `fold()`'s
    bookkeeping is copied verbatim from the real base."""

    stream_prefix: str = ""
    snapshot_every: int = 200

    def __init__(self) -> None:
        self.applied_seq = 0
        self.snapshot_seq = 0

    def fold(self, event: Event) -> None:
        if event.seq <= self.applied_seq:
            return
        self.apply(event)
        self.applied_seq = event.seq


#: How long it takes for an outcome to count half as much (stage 6
#: item 1's "exponential forgetting, half-life config").
#:
#: Thirty days, because what Sim was bad at in the spring should not
#: outvote what it is good at now, and a month is roughly how long a
#: capability here survives without something changing under it. The
#: alternative -- never forgetting -- makes the table a monument: a
#: bad fortnight in a task type keeps routing away from it long after
#: the bug behind it was fixed, and nothing it does afterwards can
#: outweigh enough history.
HALF_LIFE_S = 30.0 * 86_400.0

#: Below this the sums are treated as gone. A table nobody has fed for
#: a year should read as "no idea" (Beta(1,1)) rather than as a
#: vanishing fraction of an opinion.
FORGOTTEN_BELOW = 0.01

#: How many (confidence, outcome) pairs to keep per task type for
#: `calibration()`. The ECE bins keep the long view in ten integers.
CONFIDENCE_SAMPLES_KEPT = 500


def _aged(value: float, elapsed_s: float, half_life_s: float) -> float:
    if value <= 0.0 or elapsed_s <= 0.0 or half_life_s <= 0.0:
        return value
    faded = value * (0.5 ** (elapsed_s / half_life_s))
    return 0.0 if faded < FORGOTTEN_BELOW else faded


class CompetenceTable(_Projection):
    stream_prefix = "learn:outcomes"

    def __init__(self, *, half_life_s: float = HALF_LIFE_S) -> None:
        super().__init__()
        self.half_life_s = max(0.0, float(half_life_s))
        self._by_type: dict[str, TaskTypeStats] = {}
        self._confidence_samples: dict[str, list[tuple[float, bool]]] = {}

    # -- Projection protocol -------------------------------------------------
    def apply(self, event: Event) -> None:
        if event.type != "outcome":
            return
        p = event.payload
        self._record(
            task_type=p["task_type"],
            succeeded=bool(p["succeeded"]),
            weight=float(p.get("weight", 1.0)),
            cost_usd=float(p.get("cost_usd", 0.0)),
            duration_s=float(p.get("duration_s", 0.0)),
            strategy=p.get("strategy"),
            stated_confidence=p.get("stated_confidence"),
            at=float(getattr(event, "ts", 0.0) or 0.0),
        )

    def state(self) -> dict:
        return {
            "by_type": {
                t: {
                    "n": s.n, "successes_w": s.successes_w, "cost_sum": s.cost_sum, "dur_sum": s.dur_sum,
                    "at": s.at,
                    "calib_bins": {str(k): v for k, v in s.calib_bins.items()},
                    "strategies": {k: {"n": v.n, "successes_w": v.successes_w, "cost_sum": v.cost_sum, "at": v.at}
                                   for k, v in s.strategies.items()},
                }
                for t, s in self._by_type.items()
            },
            "confidence_samples": {t: list(v) for t, v in self._confidence_samples.items()},
        }

    def load(self, state: dict) -> None:
        self._by_type = {}
        for t, d in state.get("by_type", {}).items():
            stats = TaskTypeStats(n=d["n"], successes_w=d["successes_w"], cost_sum=d["cost_sum"],
                                  dur_sum=d["dur_sum"], at=float(d.get("at", 0.0)))
            stats.calib_bins = {int(k): v for k, v in d.get("calib_bins", {}).items()}
            stats.strategies = {k: StrategyStats(**v) for k, v in d.get("strategies", {}).items()}
            self._by_type[t] = stats
        self._confidence_samples = {t: [tuple(x) for x in v] for t, v in state.get("confidence_samples", {}).items()}

    # -- writer ---------------------------------------------------------------
    def _age(self, stats, at: float) -> None:
        """Fade what is already there to `at`, before adding to it.

        Aged on write rather than on read: the sums are all this table
        keeps, so decaying them in place is exact and costs one
        multiply, where decaying at read time would need every
        outcome's timestamp kept forever. The cost is that a table
        nobody has written to does not fade until the next outcome
        arrives -- which is the right way round, because a stale
        table's real problem is that nothing is happening, and
        inventing decay for it would just hide that.
        """
        if not at or not stats.at:
            stats.at = at or stats.at
            return
        elapsed = at - stats.at
        if elapsed <= 0.0:
            return          # out-of-order replay: never age backwards
        stats.n = _aged(stats.n, elapsed, self.half_life_s)
        stats.successes_w = _aged(stats.successes_w, elapsed, self.half_life_s)
        stats.cost_sum = _aged(stats.cost_sum, elapsed, self.half_life_s)
        if hasattr(stats, "dur_sum"):
            stats.dur_sum = _aged(stats.dur_sum, elapsed, self.half_life_s)
        stats.at = at

    def _record(self, *, task_type: str, succeeded: bool, weight: float, cost_usd: float, duration_s: float,
                strategy: str | None, stated_confidence: float | None, at: float = 0.0) -> None:
        stats = self._by_type.setdefault(task_type, TaskTypeStats())
        self._age(stats, at)
        stats.n += 1
        stats.successes_w += weight if succeeded else 0.0
        stats.cost_sum += cost_usd
        stats.dur_sum += duration_s
        if strategy:
            s = stats.strategies.setdefault(strategy, StrategyStats())
            self._age(s, at)
            s.n += 1
            s.successes_w += weight if succeeded else 0.0
            s.cost_sum += cost_usd
        if stated_confidence is not None:
            bucket = min(9, max(0, int(stated_confidence * 10)))
            bin_ = stats.calib_bins.setdefault(bucket, [0, 0])
            bin_[0] += 1
            bin_[1] += 1 if succeeded else 0
            kept = self._confidence_samples.setdefault(task_type, [])
            kept.append((float(stated_confidence), succeeded))
            if len(kept) > CONFIDENCE_SAMPLES_KEPT:
                # Bounded, because this list is persisted in `state()`
                # and nothing ever dropped from it: a year of turns
                # would put a megabyte of floats in every snapshot for
                # a number the last few hundred already answer. The
                # ECE bins are ten integers and carry the long view.
                del kept[:-CONFIDENCE_SAMPLES_KEPT]

    # -- reader -----------------------------------------------------------------
    def get(self, task_type: str) -> TaskTypeStats | None:
        return self._by_type.get(task_type)

    def success_rate(self, task_type: str) -> float:
        stats = self._by_type.get(task_type)
        return stats.rate() if stats is not None else 0.5

    def calibration(self, task_type: str) -> float:
        samples = self._confidence_samples.get(task_type, [])
        if not samples:
            return 0.5
        gap = sum(abs(conf - (1.0 if hit else 0.0)) for conf, hit in samples) / len(samples)
        return max(0.0, 1.0 - gap)

    def provider_quality(self, provider: str, *, purpose: str = "") -> tuple[float, float, float]:
        """`(alpha, beta, samples)` for a provider, across every task
        type it has served (stage 6 item 1's per-provider quality).

        The data was already here and only askable one task type at a
        time: strategies are keyed `provider:purpose[:edit_mode]`
        (`models.Strategy.key`), so "how good is together at drafting"
        was a question the table could answer and had no way to be
        asked. This rolls the same counts up across types.

        Beta(1,1) -- "no idea" -- when that provider has served
        nothing, which is the honest answer for one just configured
        and must not read as half the time.
        """
        want = f"{provider}:{purpose}" if purpose else f"{provider}:"
        alpha, beta, samples = 1.0, 1.0, 0.0
        for stats in self._by_type.values():
            for key, per in stats.strategies.items():
                if key != want and not key.startswith(f"{want}:" if purpose else want):
                    continue
                alpha += per.successes_w
                beta += max(0.0, per.n - per.successes_w)
                samples += per.n
        return alpha, beta, samples

    def providers(self) -> list[tuple[str, float, float]]:
        """`(provider, mean, samples)` for every provider seen, worst
        first -- the order somebody reading this wants, because the
        useful question is which one to stop using."""
        names = {key.split(":", 1)[0] for stats in self._by_type.values() for key in stats.strategies}
        out = []
        for name in sorted(n for n in names if n):
            alpha, beta, samples = self.provider_quality(name)
            if samples <= 0:
                continue
            out.append((name, round(alpha / (alpha + beta), 4), samples))
        return sorted(out, key=lambda row: row[1])

    def expected_calibration_error(self, task_type: str) -> float | None:
        """How far Sim's stated confidence is from what happens, binned
        (stage 6 item 1). `None` when nothing has been recorded.

        The standard ECE: outcomes are bucketed by the confidence Sim
        claimed, each bucket compares its claimed confidence against
        what actually happened, and the buckets are averaged weighted
        by how many outcomes are in them. 0 is perfect; 0.3 means Sim
        is routinely a third out.

        `calibration()` above is a different number and stays: the
        mean absolute gap per outcome, which punishes confident
        mistakes harder. ECE is the one that answers "when Sim says
        80%, does it happen 80% of the time" -- and the bins it needs
        have been recorded and persisted since the table was written,
        and read by nothing at all until today.
        """
        stats = self._by_type.get(task_type)
        if stats is None or not stats.calib_bins:
            return None
        total = sum(n for n, _hits in stats.calib_bins.values())
        if total <= 0:
            return None
        error = 0.0
        for bucket, (n, hits) in stats.calib_bins.items():
            if n <= 0:
                continue
            claimed = (int(bucket) + 0.5) / 10.0    # the bucket's midpoint
            happened = hits / n
            error += (n / total) * abs(claimed - happened)
        return round(error, 4)

    def samples(self, task_type: str) -> int:
        stats = self._by_type.get(task_type)
        return stats.n if stats is not None else 0

    def record_eval(self, suite: str, *, passed: int, total: int, weight: float = 0.5) -> None:
        """An eval report as evidence about a task type (stage 8 item 2).

        The second of the two sources a posterior rests on. Kept under
        its own key (`eval:<suite>`) rather than mixed into the task
        type's own counts, so "what a fixture says" and "what actually
        happened in this house" stay separable and either can be read
        alone. `weight` is per case, and below 1 on purpose: an eval is
        the same question every time and the house is not in it.
        """
        if total <= 0:
            return
        stats = self._by_type.setdefault(f"eval:{suite}", TaskTypeStats())
        stats.n += total
        stats.successes_w += max(0, min(passed, total)) * max(0.0, weight)

    def posterior(self, task_type: str, *, strategy: str | None = None,
                  eval_suite: str | None = None, eval_weight: float = 1.0) -> tuple[float, float, int]:
        """`(alpha, beta, samples)` for a task type, or one of its
        strategies (stage 6 item 1).

        Beta(1, 1) with nothing recorded -- a flat prior, which reads as
        "no idea", not as "half the time". The counts are the weighted
        successes and failures the outcomes already carry, so a posterior
        is a view of the same projection rather than a second record of
        the same facts.

        `eval_suite` folds that suite's cases in as the second source
        (stage 8 item 2), scaled by `eval_weight`. Two sources, weighted,
        and neither of them a chat turn saying it went well: a strategy
        ranked on self-reports ranks confidence, not competence.
        """
        stats = self._by_type.get(task_type)
        if strategy is not None:
            if stats is None:
                return 1.0, 1.0, 0
            per = stats.strategies.get(strategy)
            if per is None:
                return 1.0, 1.0, 0
            return 1.0 + per.successes_w, 1.0 + max(0.0, per.n - per.successes_w), per.n
        alpha, beta, samples = 1.0, 1.0, 0
        if stats is not None:
            alpha += stats.successes_w
            beta += max(0.0, stats.n - stats.successes_w)
            samples += stats.n
        if eval_suite:
            from_eval = self._by_type.get(f"eval:{eval_suite}")
            if from_eval is not None and from_eval.n:
                scale = max(0.0, eval_weight)
                alpha += from_eval.successes_w * scale
                beta += max(0.0, from_eval.n - from_eval.successes_w) * scale
                samples += from_eval.n
        return alpha, beta, samples

    def estimate(self, task_type: str, *, strategy: str | None = None,
                 eval_suite: str | None = None, eval_weight: float = 1.0) -> dict:
        """What Sim believes about its own competence at something, in the
        shape `self.estimate.reply` carries: the posterior mean, how much
        it rests on, and the calibration when there is one."""
        alpha, beta, samples = self.posterior(task_type, strategy=strategy,
                                              eval_suite=eval_suite, eval_weight=eval_weight)
        mean = alpha / (alpha + beta)
        # The variance of a Beta says how much the mean is worth: with two
        # samples it is wide, and a consumer should not escalate on it.
        variance = (alpha * beta) / (((alpha + beta) ** 2) * (alpha + beta + 1.0))
        out = {"task_type": task_type, "mean": round(mean, 4), "samples": samples,
               "alpha": round(alpha, 3), "beta": round(beta, 3), "spread": round(variance ** 0.5, 4)}
        if strategy is not None:
            out["strategy"] = strategy
        if eval_suite:
            out["eval_suite"] = eval_suite
        calibration = self.calibration(task_type)
        if calibration is not None:
            out["calibration"] = calibration
        ece = self.expected_calibration_error(task_type)
        if ece is not None:
            out["ece"] = ece
        return out

    def suggest(self, task_type: str, *, explore_bonus: float, min_samples_for_trust: int) -> list[StrategyScore]:
        """Ranked strategies for `task_type`, highest score first. Empty
        when nothing has ever been recorded for this type -- the caller
        treats that as `floor: true` (spec section 3.3)."""
        stats = self._by_type.get(task_type)
        if stats is None or not stats.strategies:
            return []
        n_total = stats.n
        scores: list[StrategyScore] = []
        for key, s in stats.strategies.items():
            p = s.rate()
            k = min_samples_for_trust
            shrunk = (s.n * p + k * 0.5) / (s.n + k) if s.n < k else p
            bonus = explore_bonus * math.sqrt(math.log(n_total + 1) / (s.n + 1))
            scores.append(StrategyScore(strategy=key, success_rate=shrunk, n=s.n, score=shrunk + bonus))
        scores.sort(key=lambda x: x.score, reverse=True)
        return scores
