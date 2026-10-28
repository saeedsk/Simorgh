"""The guardrail ablation runner (stage 14 item 4).

    python -m simorgh.evals ablate --suite toolchain --presets sim,bare \\
        --models together:<model>,gemini:<model> --repeats 5 --paid --cap-usd 20
    python -m simorgh.evals ablate --suite toolchain --models floor:floor --dry-run

Every guardrail in Sim was added after a live failure and none has been
measured switched off. This runs the same scenarios once per (model,
preset, scenario, repeat), each in its own child process exactly as
`house/run.py` does, with the preset's switches and the model reaching
the child through `SIMORGH_HOUSE_CONFIG`. It prints one row per (model,
preset): the success rate, a Wilson 95% interval, the mean steps and the
dollars; and it appends one JSONL row per run.

Three rules it keeps, all from the plan's "What this must never do":

- **No spend without `--paid` and a cap.** A model other than the floor
  needs both; `--dry-run` needs neither, because it spends nothing.
- **A skip is not a failure.** A run the floor cannot judge, a house that
  did not boot, a model that never answered, or a run the cap stopped
  leaves the denominator and is counted in its own column.
- **Guardian is not a switch.** The presets below touch only
  `[orchestration] ablate` and `[cognition] ablate`.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import math
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from .api import FAILED, Outcome, PASSED, SKIPPED

#: The plan's preset table, as data. `sim` is Sim as it ships; `bare` is
#: every switch at once. Names and contents are fixed by
#: docs/plan/stage-14-toolchain-evals-and-ablation.md ("Definitions").
PRESETS: dict[str, dict[str, tuple[str, ...]]] = {
    "sim": {"orchestration": (), "cognition": ()},
    "no_scaffold": {"orchestration": ("scaffold",), "cognition": ()},
    "no_verify": {"orchestration": ("verify",), "cognition": ()},
    "no_revisions": {"orchestration": ("revisions",), "cognition": ()},
    "no_recovery": {"orchestration": ("recovery",), "cognition": ()},
    "no_rescue": {"orchestration": (), "cognition": ("rescue",)},
    # Stage 16 item 3: forge's own guardrails, ported by stage 16 items 1-2.
    "no_nudge": {"orchestration": ("nudge",), "cognition": ()},
    "no_steps": {"orchestration": ("steps",), "cognition": ()},
    "bare": {"orchestration": ("scaffold", "verify", "revisions", "recovery", "nudge", "steps"),
             "cognition": ("rescue",)},
}

#: Presets that turn a shipped-off feature ON over `sim` (stage 17's
#: measurements), kept apart from `PRESETS` because that table is the
#: plan's ablation table and a test holds it to the plan. Each is `sim`'s
#: switches (none) plus the `[orchestration]` settings named here.
SETTINGS: dict[str, dict[str, dict]] = {
    "mask2": {"orchestration": {"mask_after_steps": 2}},
    "routed": {"orchestration": {"tool_routing": "on"}},
}


def switches_for(preset: str) -> dict[str, tuple[str, ...]]:
    """A preset's ablation switches; a `SETTINGS` preset has none."""
    return PRESETS.get(preset) or PRESETS["sim"]


#: Which scenario prefix each `--suite` name runs. A raw id prefix (any text
#: with a "/") is accepted too, for a one-category look (`toolchain/recovery/`).
SUITE_PREFIXES: dict[str, str] = {"toolchain": "toolchain/", "crew": "toolchain/crew/"}

#: The model name that means "no model": the floor provider costs
#: nothing and needs no `--paid`.
FLOOR = "floor"

#: The dry-run estimate's assumptions, per run. Rough on purpose -- it is
#: there to say "about two dollars" or "about two hundred" before
#: anything is spent, not to bill. A chat turn's prompt with 72 tools is
#: most of the input; a tool chain is a few steps.
EST_STEPS_PER_RUN = 4
EST_INPUT_TOKENS_PER_STEP = 9_000
EST_OUTPUT_TOKENS_PER_STEP = 300

#: The most one run may spend, whatever is left of the total cap. A
#: child's spend is read from its ledger when it finishes; a child that
#: dies or times out first reports nothing, and is then charged this
#: whole share -- the most it could have spent -- so the total cap holds
#: even when the dollars are unknown. Without a per-run share, that
#: charge would have to be everything left, and one hung house would end
#: the matrix.
PER_RUN_CAP_USD = 1.0

#: Where the per-run rows go, relative to the repo root (gitignored).
DEFAULT_LOG = Path(__file__).resolve().parents[2] / ".simorgh_evals" / "ablation.jsonl"


@dataclass(frozen=True)
class Model:
    provider: str
    model: str

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"

    @property
    def is_floor(self) -> bool:
        return self.provider == FLOOR


@dataclass(frozen=True)
class Run:
    """One cell of the matrix: one child process."""

    model: Model
    preset: str
    scenario: object
    repeat: int


@dataclass
class RunResult:
    run: Run
    status: str
    why: str = ""
    steps: int | None = None
    cost_usd: float = 0.0
    seconds: float = 0.0
    #: False when the child never said what it spent (it died, timed
    #: out, or its ledger could not be read). `run_matrix` then charges
    #: the run its whole share of the cap.
    spend_known: bool = True
    #: How a safety scenario's gate held (`house.script.gate_held`):
    #: "asked", "denied" or "declined" (the model proposed nothing); ""
    #: for a run with no gate in it.
    gate: str = ""

    def row(self, suite: str) -> dict:
        return {"ts": round(time.time(), 3), "suite": suite, "model": self.run.model.label,
                "preset": self.run.preset, "scenario": self.run.scenario.id, "repeat": self.run.repeat,
                "status": self.status, "why": self.why[:300], "steps": self.steps,
                "cost_usd": round(self.cost_usd, 6), "seconds": round(self.seconds, 2),
                **({"gate": self.gate} if self.gate else {})}


@dataclass
class Cell:
    """One row of the table: every run of one (model, preset)."""

    model: str
    preset: str
    results: list[RunResult] = field(default_factory=list)

    @property
    def counted(self) -> list[RunResult]:
        return [r for r in self.results if r.status != SKIPPED]

    @property
    def passed(self) -> int:
        return sum(1 for r in self.counted if r.status == PASSED)

    @property
    def skipped(self) -> int:
        return len(self.results) - len(self.counted)

    @property
    def rate(self) -> float | None:
        return self.passed / len(self.counted) if self.counted else None

    @property
    def interval(self) -> tuple[float, float] | None:
        return wilson(self.passed, len(self.counted)) if self.counted else None

    @property
    def mean_steps(self) -> float | None:
        steps = [r.steps for r in self.counted if r.steps is not None]
        return sum(steps) / len(steps) if steps else None

    @property
    def cost_usd(self) -> float:
        return sum(r.cost_usd for r in self.results)


# -- parsing ------------------------------------------------------------------------------------

def parse_presets(text: str) -> list[str]:
    """`"sim,bare"` -> names, in the order given; empty means all of them.
    An unknown name is a `ValueError` naming the ones that exist."""
    names = [p.strip() for p in (text or "").split(",") if p.strip()] or list(PRESETS)
    unknown = [n for n in names if n not in PRESETS and n not in SETTINGS]
    if unknown:
        raise ValueError(f"no preset {', '.join(unknown)}; there is {', '.join([*PRESETS, *SETTINGS])}")
    return list(dict.fromkeys(names))


def parse_models(text: str) -> list[Model]:
    """`"together:glm,floor:floor"` -> models. `provider:model`, where the
    model may itself contain colons (`ollama:qwen3:4b`)."""
    out = []
    for item in (p.strip() for p in (text or "").split(",")):
        if not item:
            continue
        provider, sep, model = item.partition(":")
        if not sep or not provider or not model:
            raise ValueError(f"{item!r} is not provider:model")
        out.append(Model(provider.strip(), model.strip()))
    if not out:
        raise ValueError("--models names no model")
    return out


def scenarios_for(suite: str) -> list:
    from .house.scenarios import by_prefix

    prefix = SUITE_PREFIXES.get(suite) or (suite if "/" in suite else "")
    if not prefix:
        raise ValueError(f"no suite {suite!r}; there is {', '.join(SUITE_PREFIXES)} or a scenario id prefix containing /")
    found = by_prefix(prefix)
    if not found:
        raise ValueError(f"no scenario under {prefix!r}")
    return found


# -- the config a child gets -----------------------------------------------------------------------

def preset_config(preset: str, model: Model, *, spend_cap_usd: float | None = None) -> dict:
    """The JSON a child merges over its sandbox config.

    `[cognition] provider_order = [provider]`, and that provider's
    `model`, as the plan says. The provider's table starts from the
    shipped defaults (prices, call caps, timeouts) because cognition
    replaces a provider's whole table when one is given: naming only the
    model would zero the prices the router's pre-call estimate uses.

    The cap is the provider's own `max_spend_usd` -- the one cognition's
    budget enforces. `[cognition]` has no section-wide `max_spend_usd`;
    writing one would be a key nothing reads.
    """
    switches = switches_for(preset)
    cognition: dict = {"ablate": list(switches["cognition"]), "provider_order": [model.provider]}
    if not model.is_floor:
        table = _provider_defaults(model.provider)
        table["model"] = model.model
        if spend_cap_usd is not None:
            table["max_spend_usd"] = float(spend_cap_usd)
        cognition["providers"] = {model.provider: table}
    orchestration = {"ablate": list(switches["orchestration"]),
                     **SETTINGS.get(preset, {}).get("orchestration", {})}
    return {"orchestration": orchestration, "cognition": cognition}


def _provider_defaults(provider: str) -> dict:
    from simorgh.cognition.config import Config

    shipped = Config().providers.get(provider)
    if shipped is None:
        return {}
    return {k: (list(v) if isinstance(v, tuple) else v) for k, v in dataclasses.asdict(shipped).items()}


def estimate_usd(model: Model) -> float | None:
    """A rough dollar figure for one run; `None` when the price is not
    known (a provider with no shipped price), `0.0` for the floor."""
    if model.is_floor:
        return 0.0
    table = _provider_defaults(model.provider)
    price_in, price_out = float(table.get("price_in") or 0.0), float(table.get("price_out") or 0.0)
    if not price_in and not price_out:
        return None
    tokens_in = EST_STEPS_PER_RUN * EST_INPUT_TOKENS_PER_STEP
    tokens_out = EST_STEPS_PER_RUN * EST_OUTPUT_TOKENS_PER_STEP
    return (tokens_in * price_in + tokens_out * price_out) / 1_000_000


# -- the matrix --------------------------------------------------------------------------------------

def matrix(models: list[Model], presets: list[str], scenarios: list, repeats: int) -> list[Run]:
    """Every run, repeat-major: all of repeat 1 before any of repeat 2.

    So that when the cap stops the run, every (model, preset) has the
    same number of repeats behind it, rather than `sim` finished and
    `bare` never started -- a matrix with one column missing compares
    nothing.
    """
    return [Run(model, preset, scenario, repeat)
            for repeat in range(1, max(1, repeats) + 1)
            for model in models for preset in presets for scenario in scenarios]


#: A child runner: (scenario, env) -> the child's raw outcomes. The real
#: one is `house/run.py::_in_a_child`; tests pass a fake.
Child = Callable[[object, dict], Awaitable[list[Outcome]]]


async def _real_child(scenario, env: dict) -> list[Outcome]:
    from .house.run import _in_a_child

    return await _in_a_child(scenario, env=env)


def child_env(run: Run, *, paid: bool, spend_cap_usd: float | None) -> dict:
    """This environment, plus the preset and model for one child, plus
    `SIMORGH_HOUSE_PAID` only for a paid run of a real model."""
    from .house.run import HOUSE_CONFIG_ENV

    env = dict(os.environ)
    env.pop("SIMORGH_HOUSE_PAID", None)
    if not run.model.is_floor:
        # Cognition lets this override `provider_order` (the test session
        # sets it to `floor`); inherited, it would quietly measure the
        # floor under the model's name.
        env.pop("SIMORGH_COGNITION_PROVIDER_ORDER", None)
    if paid and not run.model.is_floor:
        env["SIMORGH_HOUSE_PAID"] = "1"
    env[HOUSE_CONFIG_ENV] = json.dumps(preset_config(run.preset, run.model, spend_cap_usd=spend_cap_usd))
    return env


def judge(run: Run, outcomes: list[Outcome], *, child_cap_usd: float | None = None) -> RunResult:
    """One run's raw outcomes as one result, by the plan's definition of
    success (`house/run.py::per_scenario`), with the steps and dollars
    the child read off the bus.

    A real model that never answered -- every think came back an error,
    or from the floor -- is a skip ("no provider"), not a failed chain.
    So is a run that reached its share of the cap (`child_cap_usd`)
    before it finished: the plan's "spend cap reached".
    """
    from .house.run import per_scenario

    folded = per_scenario(outcomes, [run.scenario])
    one = next((o for o in folded if o.case.name == run.scenario.id), None) or folded[0]
    summary = next((o.case.detail.get("run") for o in outcomes if isinstance(o.case.detail.get("run"), dict)), {})
    cost = float(summary.get("cost_usd") or 0.0) if summary else sum(o.cost_usd for o in outcomes)
    steps = summary.get("steps") if summary else None
    status, why = one.status, one.why
    capped = bool(summary.get("budget_errors")) or (
        child_cap_usd is not None and cost >= child_cap_usd * 0.95 and bool(summary.get("floor_answers")))
    if status != PASSED and status != SKIPPED and not run.model.is_floor and summary and capped:
        status, why = SKIPPED, f"spend cap reached during the run (${cost:.2f} of its ${child_cap_usd or 0:.2f})"
    elif status != SKIPPED and not run.model.is_floor and summary:
        if summary.get("floor_answers"):
            status, why = SKIPPED, f"{summary['floor_answers']} answer(s) came from the floor, not {run.model.label}"
        elif not summary.get("model_answers") and summary.get("model_errors"):
            status, why = SKIPPED, f"{run.model.label} never answered ({summary['model_errors']} error replies)"
    return RunResult(run=run, status=status, why=why, steps=steps, cost_usd=cost,
                     seconds=sum(o.seconds for o in outcomes),
                     spend_known=bool(summary) and summary.get("known", True) is not False,
                     gate=str(one.case.detail.get("gate") or "") if status == PASSED else "")


def _skip(run: Run, why: str) -> RunResult:
    return RunResult(run=run, status=SKIPPED, why=why)


async def run_matrix(runs: list[Run], *, suite: str, paid: bool, cap_usd: float = 0.0,
                     child: Child | None = None, log: Path | None = DEFAULT_LOG,
                     progress: Callable[[RunResult], None] | None = None) -> list[RunResult]:
    """Every run, one child at a time, under one total dollar cap.

    The cap is checked before each run and handed to the child as its
    provider's `max_spend_usd`: what is left, at most `PER_RUN_CAP_USD`,
    so no single run can spend past it either. A child that reports no
    spend is charged that whole share. Once the cap is reached the rest
    are skipped "spend cap reached" and reported, never dropped.

    A scenario that needs a model, on the floor or without `--paid`, is
    skipped here without a child: the answer is the same and a matrix of
    a hundred such runs should list them in a second.
    """
    child = child or _real_child
    spent, out = 0.0, []
    for run in runs:
        spends = paid and not run.model.is_floor
        if run.scenario.needs_model and not spends:
            why = (getattr(run.scenario, "needs_model_because", "")
                   or "needs a model; the floor provider proposes nothing")
            result = _skip(run, why if run.model.is_floor else f"{why} (not --paid)")
        elif spends and cap_usd and spent >= cap_usd:
            result = _skip(run, f"spend cap reached (${spent:.2f} of ${cap_usd:.2f})")
        else:
            share = min(max(0.0, cap_usd - spent), PER_RUN_CAP_USD) if spends and cap_usd else None
            env = child_env(run, paid=paid, spend_cap_usd=share)
            started = time.monotonic()
            try:
                result = judge(run, await child(run.scenario, env), child_cap_usd=share)
            except Exception as exc:  # noqa: BLE001 -- one broken child is one skipped run
                result = _skip(run, f"the child did not run: {exc!r}")
                result.spend_known = False
            result.seconds = result.seconds or round(time.monotonic() - started, 2)
            if share is not None and not result.spend_known:
                # Unknown is not free: count the most it could have cost.
                result.cost_usd = max(result.cost_usd, share)
                result.why = (result.why + "; " if result.why else "") + \
                    f"spend unknown, counted as its ${share:.2f} share of the cap"
            spent += result.cost_usd
        out.append(result)
        if log is not None:
            _append(log, result.row(suite))
        if progress is not None:
            progress(result)
    return out


def _append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


# -- reporting ----------------------------------------------------------------------------------------

def wilson(passed: int, total: int, *, z: float = 1.959964) -> tuple[float, float]:
    """The Wilson score 95% interval on `passed / total`.

    Wilson rather than the bootstrap here: an ablation cell is often
    5/5 or 0/5, where a bootstrap collapses to a zero-width interval and
    claims a certainty five runs cannot give.
    """
    if total <= 0:
        return (0.0, 0.0)
    p = passed / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return (round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4))


def cells(results: list[RunResult]) -> list[Cell]:
    """One cell per (model, preset), in the order first seen."""
    found: dict[tuple[str, str], Cell] = {}
    for result in results:
        key = (result.run.model.label, result.run.preset)
        found.setdefault(key, Cell(model=key[0], preset=key[1])).results.append(result)
    return list(found.values())


def table(results: list[RunResult]) -> str:
    rows = cells(results)
    # A preset that cannot change these scenarios is marked `*`, so its
    # row reads as a second `sim`, not as a guardrail that did nothing.
    presets = list(dict.fromkeys(c.preset for c in rows))
    scenarios = list({r.run.scenario.id: r.run.scenario for r in results}.values())
    inert = inert_presets(presets, scenarios)
    width = max([len("model"), *(len(c.model) for c in rows)])
    lines = [f"{'model':<{width}}  {'preset':<14} {'pass':>7} {'rate':>6}  {'95% CI':<13} "
             f"{'skip':>4} {'steps':>6} {'$':>8}"]
    for c in rows:
        rate = f"{c.rate:.0%}" if c.rate is not None else "-"
        ci = f"[{c.interval[0]:.2f}, {c.interval[1]:.2f}]" if c.interval else "-"
        steps = f"{c.mean_steps:.1f}" if c.mean_steps is not None else "-"
        name = c.preset + ("*" if c.preset in inert else "")
        lines.append(f"{c.model:<{width}}  {name:<14} {f'{c.passed}/{len(c.counted)}':>7} {rate:>6}  "
                     f"{ci:<13} {c.skipped:>4} {steps:>6} {c.cost_usd:>8.4f}")
    if inert:
        lines.append("")
        lines.append(f"* {', '.join(inert)} {INERT_NOTE}")
    gated = [c for c in rows if any(r.gate for r in c.results)]
    if gated:
        # A safety pass is "asked", "denied" or "declined" (no hazardous
        # call proposed at all). Only the first two exercised Guardian; a
        # row that passes on declines alone has not tested the gate.
        lines.append("")
        lines.append("safety gate per passed run, asked / denied / declined "
                     "(only the first two exercised Guardian):")
        for c in gated:
            n = {g: sum(1 for r in c.results if r.gate == g) for g in ("asked", "denied", "declined")}
            lines.append(f"  {c.model:<{width}}  {c.preset:<14} {n['asked']} / {n['denied']} / {n['declined']}")
    skipped = [r for r in results if r.status == SKIPPED]
    if skipped:
        reasons: dict[str, int] = {}
        for r in skipped:
            reasons[r.why] = reasons.get(r.why, 0) + 1
        lines.append("")
        lines.append(f"skipped {len(skipped)} of {len(results)} runs:")
        lines += [f"  {n:>4}  {why[:110]}" for why, n in sorted(reasons.items(), key=lambda kv: -kv[1])]
    failed = [r for r in results if r.status == FAILED]
    if failed:
        lines.append("")
        lines.append(f"failed {len(failed)}:")
        lines += [f"  {r.run.model.label} {r.run.preset} {r.run.scenario.id}: {r.why[:90]}" for r in failed[:40]]
    return "\n".join(lines)


def dry_run(runs: list[Run], *, models: list[Model], presets: list[str], scenarios: list,
            repeats: int, paid: bool) -> str:
    """The matrix and a cost estimate, spending nothing."""
    lines = [f"ablation matrix: {len(models)} model(s) x {len(presets)} preset(s) x "
             f"{len(scenarios)} scenario(s) x {repeats} repeat(s) = {len(runs)} runs", ""]
    inert = inert_presets(presets, scenarios)
    for name in presets:
        switches = switches_for(name)
        lines.append(f"  {name:<13} orchestration={list(switches['orchestration'])} "
                     f"cognition={list(switches['cognition'])}"
                     + (f" sets={SETTINGS[name]}" if name in SETTINGS else "") + ("  (inert here)" if name in inert else ""))
    if inert:
        lines.append(f"  note: {', '.join(inert)} {INERT_NOTE}")
    lines.append("")
    total, unknown = 0.0, []
    for model in models:
        per_run = estimate_usd(model)
        n = sum(1 for r in runs if r.model == model
                and (not r.scenario.needs_model or (paid and not model.is_floor)))
        would = sum(1 for r in runs if r.model == model)
        if per_run is None:
            unknown.append(model.label)
            cost = "price unknown"
        else:
            total += per_run * would if not model.is_floor else 0.0
            cost = f"~${per_run * would:.2f} (~${per_run:.4f}/run)"
        note = "" if model.is_floor or paid else f"; without --paid {n} of {would} would run"
        lines.append(f"  {model.label:<40} {would} runs  {cost}{note}")
    lines.append("")
    lines.append(f"estimated total: ~${total:.2f}" + (f" plus {', '.join(unknown)} at an unknown price" if unknown else "")
                 + f"  (assumes {EST_STEPS_PER_RUN} steps x {EST_INPUT_TOKENS_PER_STEP} in / "
                   f"{EST_OUTPUT_TOKENS_PER_STEP} out tokens per run)")
    return "\n".join(lines)


#: What `--dry-run` and `table` say after naming the inert presets.
INERT_NOTE = ("change nothing for these scenarios -- every one is a chat turn, and the chat profiles "
              "already run with that guardrail off (verify = false, max_revisions = 0, no required_steps, "
              "terminal_tools or prerequisites); those rows can only equal sim")


def inert_presets(presets: list[str], scenarios: list) -> list[str]:
    """The presets that cannot change anything for `scenarios`: those
    whose only switches are ones the chat profiles already have off,
    when every scenario is a chat turn (typed or spoken, never a task).
    `verify` is off when no chat profile verifies, `revisions` when none
    has a revision, `steps` when none declares `required_steps`,
    `terminal_tools` or `prerequisites` (all that stage 16's step
    enforcement reads, `guardrails.steps_for`). `scaffold`, `recovery`,
    `nudge` and `rescue` act on every chat turn and are never inert.
    Paying for an inert row buys a second `sim` row, so `--dry-run` and
    `table` say so; the preset stays, because on a pack with a task in
    it the same switch is not inert."""
    from simorgh.orchestration import profiles

    beats = [b for s in scenarios for b in (getattr(s, "beats", None) or ())]
    if not beats or not all(getattr(s, "beats", None) for s in scenarios) \
            or any(not getattr(b, "says", "") or getattr(b, "proposes", None) for b in beats):
        return []
    chats = (profiles.for_percept("cli"), profiles.for_percept("voice"))
    off = set()
    if not any(c.verify for c in chats):
        off.add("verify")
    if not any(c.max_revisions for c in chats):
        off.add("revisions")
    if not any(getattr(c, "required_steps", ()) or getattr(c, "terminal_tools", ())
               or getattr(c, "prerequisites", {}) for c in chats):
        off.add("steps")
    return [p for p in presets
            if p in PRESETS and PRESETS[p]["orchestration"] and set(PRESETS[p]["orchestration"]) <= off
            and not PRESETS[p]["cognition"]]


__all__ = ["Cell", "DEFAULT_LOG", "FLOOR", "INERT_NOTE", "PER_RUN_CAP_USD", "inert_presets", "Model", "PRESETS", "Run", "RunResult", "SETTINGS", "SUITE_PREFIXES",
           "switches_for",
           "cells", "child_env", "dry_run", "estimate_usd", "judge", "matrix", "parse_models",
           "parse_presets", "preset_config", "run_matrix", "scenarios_for", "table", "wilson"]
