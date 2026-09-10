"""`[benchmark]` config."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    # A whole GAIA run is 165 validation questions, each a real
    # multi-step task with real model calls. The default is a sample,
    # not the set: someone typing `benchmark run gaia` should get a
    # useful number in minutes, and ask for the full set on purpose.
    default_cases: int = 10
    # Per case. A GAIA Level 3 question can legitimately take many
    # steps; beyond this it is not going to arrive.
    case_timeout_s: float = 600.0
    # The step cap handed to each benchmark task (task.create.max_steps).
    # Above the patch profile's own 20 because a benchmark question is
    # research with tools, and the point is to measure the ceiling.
    case_max_steps: int = 30
    # One case at a time. The system under test has one worker and a
    # shared budget; running cases in parallel would measure contention
    # rather than capability.
    concurrency: int = 1
    fetch_timeout_s: float = 30.0
    # Where downloaded suites are cached. Empty means
    # `datasets.DEFAULT_CACHE` (~/.simorgh/benchmarks). Deliberately
    # outside the repository: GAIA's terms forbid resharing the set, and
    # a cache inside a git tree is one `git add -A` from being published.
    cache_dir: str = ""
    history_limit: int = 200
    # -- SWE-bench. Each case gets a real checkout of the instance's
    # repository, copied out of its own container image, under Sim's
    # workspace (the one directory that is both readable and writable
    # by the file tools). Removed again once the patch has been read:
    # a Django checkout is ~300 MB and a 100-case run would be 30 GB.
    swebench_checkout_dir: str = "workspace/swebench"
    # Where each case's test log is kept. This is the evidence behind
    # the score, and the only place a disputed result can be settled.
    swebench_log_dir: str = "results/swebench"
    # A full Django suite under amd64 emulation on an arm64 host takes
    # about ten minutes; the cap is generous because a timeout here is
    # recorded as unmeasured, not as a wrong answer.
    swebench_eval_timeout_s: float = 3600.0
    swebench_setup_timeout_s: float = 1800.0

    @classmethod
    def from_mapping(cls, data: dict | None) -> "Config":
        data = dict(data or {})
        fields = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        return cls(**fields)


__all__ = ["Config"]
