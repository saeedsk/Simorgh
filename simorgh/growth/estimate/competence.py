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


class CompetenceTable(_Projection):
    stream_prefix = "learn:outcomes"

    def __init__(self) -> None:
        super().__init__()
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
        )

    def state(self) -> dict:
        return {
            "by_type": {
                t: {
                    "n": s.n, "successes_w": s.successes_w, "cost_sum": s.cost_sum, "dur_sum": s.dur_sum,
                    "calib_bins": {str(k): v for k, v in s.calib_bins.items()},
                    "strategies": {k: {"n": v.n, "successes_w": v.successes_w, "cost_sum": v.cost_sum}
                                   for k, v in s.strategies.items()},
                }
                for t, s in self._by_type.items()
            },
            "confidence_samples": {t: list(v) for t, v in self._confidence_samples.items()},
        }

    def load(self, state: dict) -> None:
        self._by_type = {}
        for t, d in state.get("by_type", {}).items():
            stats = TaskTypeStats(n=d["n"], successes_w=d["successes_w"], cost_sum=d["cost_sum"], dur_sum=d["dur_sum"])
            stats.calib_bins = {int(k): v for k, v in d.get("calib_bins", {}).items()}
            stats.strategies = {k: StrategyStats(**v) for k, v in d.get("strategies", {}).items()}
            self._by_type[t] = stats
        self._confidence_samples = {t: [tuple(x) for x in v] for t, v in state.get("confidence_samples", {}).items()}

    # -- writer ---------------------------------------------------------------
    def _record(self, *, task_type: str, succeeded: bool, weight: float, cost_usd: float, duration_s: float,
                strategy: str | None, stated_confidence: float | None) -> None:
        stats = self._by_type.setdefault(task_type, TaskTypeStats())
        stats.n += 1
        stats.successes_w += weight if succeeded else 0.0
        stats.cost_sum += cost_usd
        stats.dur_sum += duration_s
        if strategy:
            s = stats.strategies.setdefault(strategy, StrategyStats())
            s.n += 1
            s.successes_w += weight if succeeded else 0.0
            s.cost_sum += cost_usd
        if stated_confidence is not None:
            bucket = min(9, max(0, int(stated_confidence * 10)))
            bin_ = stats.calib_bins.setdefault(bucket, [0, 0])
            bin_[0] += 1
            bin_[1] += 1 if succeeded else 0
            self._confidence_samples.setdefault(task_type, []).append((float(stated_confidence), succeeded))

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
