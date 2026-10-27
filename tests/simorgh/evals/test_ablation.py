"""Stage 14 item 4: the ablation runner, with a fake child.

The child is the expensive part (a whole Sim per run), and every rule
worth testing lives in the parent: which runs start at all, what config
each one is handed, when the cap stops the matrix, and what counts as a
skip. So the parent runs here against a child that returns outcomes it
was told to, and records the environment it was given.
"""

import asyncio
import contextlib
import io
import json
import os
import re
import tempfile
import tomllib
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from simorgh.evals import ablation
from simorgh.evals.ablation import Model, PRESETS
from simorgh.evals.api import Case, FAILED, Outcome, PASSED, SKIPPED

REPO = Path(__file__).resolve().parents[3]
PLAN = REPO / "docs" / "plan" / "stage-14-toolchain-evals-and-ablation.md"


@dataclass(frozen=True)
class _Scenario:
    id: str
    needs_model: bool = True
    needs_model_because: str = ""
    stage: str = "14"


def _outcome(scenario_id, status=PASSED, *, run=None, why=""):
    detail = {"scenario": scenario_id}
    if run is not None:
        detail["run"] = run
    return Outcome(case=Case(name="an expectation", kind="expectation", detail=detail), status=status, why=why)


class _FakeChild:
    """Returns `script[scenario.id]` (default: one pass), records envs."""

    def __init__(self, script=None, *, cost=0.0, steps=3, raises=False):
        self.script, self.cost, self.steps, self.raises = dict(script or {}), cost, steps, raises
        self.envs: list[dict] = []

    async def __call__(self, scenario, env):
        self.envs.append(env)
        if self.raises:
            raise RuntimeError("no interpreter")
        status = self.script.get(scenario.id, PASSED)
        run = {"steps": self.steps, "cost_usd": self.cost, "model_answers": 2,
               "floor_answers": 0, "model_errors": 0}
        return [_outcome(scenario.id, status, run=run, why="" if status == PASSED else "no home_call")]


def _run(coro):
    return asyncio.run(coro)


class ThePresets(unittest.TestCase):
    def test_the_table_is_the_plans_table(self):
        """Names and switches exactly as the plan's Definitions table: a
        renamed preset would compare against nothing in the findings."""
        rows = {}
        for line in PLAN.read_text().splitlines():
            m = re.match(r"\|\s*`(\w+)`\s*\|\s*`(\[.*?\])`\s*\|\s*`(\[.*?\])`\s*\|", line)
            if m:
                rows[m.group(1)] = {"orchestration": tuple(json.loads(m.group(2))),
                                    "cognition": tuple(json.loads(m.group(3)))}
        self.assertEqual(len(rows), 7)
        self.assertEqual(rows, PRESETS)

    def test_every_switch_is_one_its_module_knows(self):
        from simorgh.cognition.config import ABLATE_SWITCHES
        from simorgh.orchestration.config import ABLATABLE

        for name, switches in PRESETS.items():
            self.assertLessEqual(set(switches["orchestration"]), set(ABLATABLE), name)
            self.assertLessEqual(set(switches["cognition"]), set(ABLATE_SWITCHES), name)

    def test_no_preset_touches_guardian(self):
        for name in PRESETS:
            config = ablation.preset_config(name, Model("together", "m"), spend_cap_usd=1.0)
            self.assertEqual(set(config), {"orchestration", "cognition"}, name)

    def test_parse_presets(self):
        self.assertEqual(ablation.parse_presets(""), list(PRESETS))
        self.assertEqual(ablation.parse_presets("bare, sim,bare"), ["bare", "sim"])
        with self.assertRaises(ValueError):
            ablation.parse_presets("sim,no_guardian")

    def test_parse_models(self):
        self.assertEqual(ablation.parse_models("together:a/b, ollama:qwen3:4b"),
                         [Model("together", "a/b"), Model("ollama", "qwen3:4b")])
        for bad in ("", "together", ":m", "together:"):
            with self.assertRaises(ValueError, msg=bad):
                ablation.parse_models(bad)


class TheChildsConfig(unittest.TestCase):
    def test_provider_order_and_model(self):
        config = ablation.preset_config("no_rescue", Model("together", "some/model"), spend_cap_usd=2.5)
        cognition = config["cognition"]
        self.assertEqual(cognition["provider_order"], ["together"])
        self.assertEqual(cognition["ablate"], ["rescue"])
        self.assertEqual(config["orchestration"]["ablate"], [])
        table = cognition["providers"]["together"]
        self.assertEqual(table["model"], "some/model")
        # The shipped prices survive: cognition replaces a provider's whole table.
        self.assertGreater(table["price_in"], 0)
        self.assertEqual(table["max_spend_usd"], 2.5)
        self.assertEqual(cognition["max_spend_usd"], 2.5)
        json.dumps(config)  # it has to cross a process boundary

    def test_the_floor_names_no_provider_table(self):
        config = ablation.preset_config("bare", Model("floor", "floor"))
        self.assertEqual(config["cognition"]["provider_order"], ["floor"])
        self.assertNotIn("providers", config["cognition"])
        self.assertNotIn("max_spend_usd", config["cognition"])

    def test_the_child_reads_it_merged_over_the_sandbox(self):
        from simorgh.evals.house import run

        config = ablation.preset_config("bare", Model("together", "m"), spend_cap_usd=1.0)
        with mock.patch.dict(os.environ, {"SIMORGH_HOUSE_CONFIG": json.dumps(config)}, clear=False):
            os.environ.pop("SIMORGH_HOUSE_PAID", None)
            self.assertEqual(run.house_config(), config)
            self.assertEqual(run._sandbox_args()["config"], config)  # noqa: SLF001
        with mock.patch.dict(os.environ, {"SIMORGH_HOUSE_CONFIG": "[1]"}):
            with self.assertRaises(ValueError):
                run.house_config()
        with mock.patch.dict(os.environ, {"SIMORGH_HOUSE_CONFIG": ""}):
            self.assertEqual(run.house_config(), {})

    def test_the_merge_is_deep(self):
        from simorgh.evals.house.sandbox import _merge

        merged = _merge({"cognition": {"provider_order": ["a"], "providers": {"a": {"model": "x", "price_in": 1}}}},
                        {"cognition": {"providers": {"a": {"model": "y"}}, "ablate": ["rescue"]}})
        self.assertEqual(merged, {"cognition": {"provider_order": ["a"], "ablate": ["rescue"],
                                                "providers": {"a": {"model": "y", "price_in": 1}}}})

    def test_paid_only_reaches_a_paid_real_model(self):
        run = ablation.Run(Model("together", "m"), "sim", _Scenario("toolchain/x/y"), 1)
        floor = ablation.Run(Model("floor", "floor"), "sim", _Scenario("toolchain/x/y"), 1)
        with mock.patch.dict(os.environ, {"SIMORGH_HOUSE_PAID": "1"}):
            self.assertNotIn("SIMORGH_HOUSE_PAID", ablation.child_env(run, paid=False, spend_cap_usd=None))
            self.assertNotIn("SIMORGH_HOUSE_PAID", ablation.child_env(floor, paid=True, spend_cap_usd=None))
            self.assertEqual(ablation.child_env(run, paid=True, spend_cap_usd=1.0)["SIMORGH_HOUSE_PAID"], "1")


class TheMatrix(unittest.TestCase):
    def setUp(self):
        self.scenarios = [_Scenario("toolchain/a/one"), _Scenario("toolchain/b/two")]
        self.models = [Model("together", "m")]

    def _go(self, child, *, presets=("sim", "bare"), repeats=2, paid=True, cap=10.0, models=None, log=None):
        runs = ablation.matrix(models or self.models, list(presets), self.scenarios, repeats)
        return _run(ablation.run_matrix(runs, suite="toolchain", paid=paid, cap_usd=cap, child=child, log=log))

    def test_repeat_major_order(self):
        runs = ablation.matrix(self.models, ["sim", "bare"], self.scenarios, 2)
        self.assertEqual(len(runs), 8)
        self.assertEqual([r.repeat for r in runs], [1, 1, 1, 1, 2, 2, 2, 2])

    def test_each_child_gets_its_preset(self):
        child = _FakeChild()
        self._go(child, repeats=1)
        ablated = [json.loads(e["SIMORGH_HOUSE_CONFIG"])["orchestration"]["ablate"] for e in child.envs]
        bare = list(PRESETS["bare"]["orchestration"])
        self.assertEqual(ablated, [[], [], bare, bare])

    def test_success_failure_steps_and_dollars(self):
        child = _FakeChild({"toolchain/b/two": FAILED}, cost=0.25, steps=4)
        results = self._go(child, presets=("sim",), repeats=2)
        cell = ablation.cells(results)[0]
        self.assertEqual((cell.passed, len(cell.counted), cell.skipped), (2, 4, 0))
        self.assertEqual(cell.mean_steps, 4)
        self.assertAlmostEqual(cell.cost_usd, 1.0)
        self.assertEqual(results[1].why.split(":")[0], "an expectation")

    def test_the_floor_and_unpaid_never_start_a_child(self):
        child = _FakeChild()
        results = self._go(child, models=[Model("floor", "floor")], paid=False)
        self.assertEqual(child.envs, [])
        self.assertTrue(all(r.status == SKIPPED for r in results))
        results = self._go(child, paid=False)
        self.assertEqual(child.envs, [])
        self.assertIn("not --paid", results[0].why)

    def test_a_scenario_that_needs_no_model_runs_on_the_floor(self):
        self.scenarios = [_Scenario("stage0/door", needs_model=False)]
        child = _FakeChild()
        results = self._go(child, models=[Model("floor", "floor")], paid=False, presets=("bare",), repeats=1)
        self.assertEqual(len(child.envs), 1)
        self.assertEqual(results[0].status, PASSED)

    def test_the_cap_stops_the_matrix_and_says_so(self):
        child = _FakeChild(cost=0.4)
        results = self._go(child, cap=1.0)  # 8 runs at $0.40: three fit
        self.assertEqual(len(child.envs), 3)
        self.assertEqual([r.status for r in results].count(SKIPPED), 5)
        self.assertIn("spend cap reached", results[-1].why)
        # Each child is capped at what was left, not the whole cap.
        caps = [json.loads(e["SIMORGH_HOUSE_CONFIG"])["cognition"]["max_spend_usd"] for e in child.envs]
        self.assertEqual([round(c, 2) for c in caps], [1.0, 0.6, 0.2])

    def test_a_broken_child_is_a_skip(self):
        results = self._go(_FakeChild(raises=True), repeats=1, presets=("sim",))
        self.assertTrue(all(r.status == SKIPPED for r in results))
        self.assertIn("did not run", results[0].why)

    def test_a_model_that_never_answered_is_a_skip_not_a_failure(self):
        run = ablation.Run(Model("together", "m"), "sim", _Scenario("toolchain/a/one"), 1)
        never = {"steps": 1, "cost_usd": 0.0, "model_answers": 0, "floor_answers": 0, "model_errors": 2}
        floor = {"steps": 1, "cost_usd": 0.0, "model_answers": 1, "floor_answers": 1, "model_errors": 0}
        for summary in (never, floor):
            result = ablation.judge(run, [_outcome("toolchain/a/one", FAILED, run=summary)])
            self.assertEqual(result.status, SKIPPED, summary)
        ok = {"steps": 2, "cost_usd": 0.01, "model_answers": 2, "floor_answers": 0, "model_errors": 0}
        self.assertEqual(ablation.judge(run, [_outcome("toolchain/a/one", FAILED, run=ok)]).status, FAILED)

    def test_one_jsonl_row_per_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "deep" / "ablation.jsonl"
            self._go(_FakeChild(), repeats=1, log=log)
            rows = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(len(rows), 4)
        self.assertEqual({"ts", "suite", "model", "preset", "scenario", "repeat", "status", "why", "steps",
                          "cost_usd", "seconds"}, set(rows[0]))
        self.assertEqual(rows[0]["model"], "together:m")


class TheReport(unittest.TestCase):
    def test_wilson(self):
        self.assertEqual(ablation.wilson(0, 0), (0.0, 0.0))
        low, high = ablation.wilson(5, 5)
        self.assertAlmostEqual(low, 0.5655, places=3)
        self.assertEqual(high, 1.0)
        low, high = ablation.wilson(46, 100)
        self.assertLess(low, 0.46)
        self.assertGreater(high, 0.46)

    def test_table_and_dry_run(self):
        scenarios = [_Scenario("toolchain/a/one")]
        runs = ablation.matrix([Model("together", "m")], ["sim", "bare"], scenarios, 1)
        results = _run(ablation.run_matrix(runs, suite="toolchain", paid=True, cap_usd=5.0,
                                           child=_FakeChild(cost=0.1), log=None))
        text = ablation.table(results)
        self.assertIn("together:m", text)
        self.assertIn("bare", text)
        self.assertIn("95% CI", text)
        dry = ablation.dry_run(runs, models=[Model("together", "m")], presets=["sim", "bare"],
                               scenarios=scenarios, repeats=1, paid=True)
        self.assertIn("= 2 runs", dry)
        self.assertIn("estimated total", dry)

    def test_the_rule_on_skips_in_the_row(self):
        results = [ablation.RunResult(ablation.Run(Model("t", "m"), "sim", _Scenario("x/y/z"), 1), s)
                   for s in (PASSED, FAILED, SKIPPED)]
        cell = ablation.cells(results)[0]
        self.assertEqual((cell.passed, len(cell.counted), cell.skipped, cell.rate), (1, 2, 1, 0.5))


class TheCommand(unittest.TestCase):
    def _main(self, *argv):
        from simorgh.evals.__main__ import main

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_dry_run_needs_no_key_and_spends_nothing(self):
        keyless = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
        with mock.patch.dict(os.environ, keyless, clear=True), \
                mock.patch.object(ablation, "run_matrix", side_effect=AssertionError("ran")):
            code, out, _ = self._main("ablate", "--suite", "toolchain", "--models", "together:m,floor:floor",
                                      "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("7 preset(s)", out)
        for name in PRESETS:
            self.assertIn(name, out)

    def test_refuses_to_spend_without_paid_and_a_cap(self):
        code, _, err = self._main("ablate", "--models", "together:m")
        self.assertEqual(code, 2)
        self.assertIn("--paid", err)
        code, _, err = self._main("ablate", "--models", "together:m", "--paid")
        self.assertEqual(code, 2)
        self.assertIn("--cap-usd", err)

    def test_a_floor_run_reports_every_case_skipped_and_exits_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "a.jsonl"
            code, out, _ = self._main("ablate", "--suite", "toolchain", "--models", "floor:floor",
                                      "--presets", "sim,bare", "--log", str(log))
            rows = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(code, 0)
        self.assertTrue(rows)
        self.assertTrue(all(r["status"] == SKIPPED for r in rows))
        self.assertIn("skipped", out)


class TheRunSummary(unittest.TestCase):
    def test_steps_cost_and_who_answered(self):
        from simorgh.evals.house.record import Record
        from simorgh.evals.house.run import run_summary, with_run_summary

        record = Record()
        for type_, payload in [
            ("task.step", {"task_id": "t", "step_no": 1}), ("task.step", {"task_id": "t", "step_no": 1}),
            ("task.step", {"task_id": "t", "step_no": 2}),
            ("cognition.think.reply", {"cost_usd": 0.01}), ("cognition.think.reply", {"cost_usd": 0.02}),
            ("cognition.think.reply", {"ok": False, "error": {"code": "x"}}),
        ]:
            record.saw(SimpleNamespace(type=type_, payload=payload))
        summary = run_summary(record)
        self.assertEqual(summary, {"steps": 2, "cost_usd": 0.03, "model_answers": 2,
                                   "floor_answers": 0, "model_errors": 1})
        outs = with_run_summary([_outcome("s"), _outcome("s")], record)
        self.assertEqual([o.cost_usd for o in outs], [0.03, 0.0])
        self.assertTrue(all(o.case.detail["run"] == summary for o in outs))


class NeverInTheLiveSim(unittest.TestCase):
    """The plan's "What this must never do": an ablation config must not
    reach the live Sim."""

    def test_the_shipped_config_sets_no_ablate_key(self):
        for name in ("config.toml", "simorgh.toml"):
            path = REPO / name
            if not path.exists():
                continue
            data = tomllib.loads(path.read_text())
            self.assertNotIn("ablate", data.get("orchestration") or {}, name)
            self.assertNotIn("ablate", data.get("cognition") or {}, name)

    def test_nothing_that_boots_live_sim_sets_the_switches(self):
        for name in ("sim.sh", "simloader.py"):
            path = REPO / name
            if path.exists():
                text = path.read_text()
                self.assertNotIn("SIMORGH_HOUSE_CONFIG", text, name)
                self.assertNotIn("ablate", text, name)

    def test_only_the_evals_read_the_house_config(self):
        readers = [p.relative_to(REPO).as_posix() for p in (REPO / "simorgh").rglob("*.py")
                   if "SIMORGH_HOUSE_CONFIG" in p.read_text(errors="replace")]
        self.assertTrue(readers)
        self.assertTrue(all(p.startswith("simorgh/evals/") for p in readers), readers)


if __name__ == "__main__":
    unittest.main()
