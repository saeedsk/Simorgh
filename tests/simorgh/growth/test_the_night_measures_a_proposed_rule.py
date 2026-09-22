"""Stage 8 item 5, the live half: the night measures a PROPOSED rule on
its task type's held-out suite and lands an adopted one as
`action.proposed(policy_adopt)`.

Before this, `measure_and_decide` had no caller, so no policy could ever
be adopted. Every case here uses fakes: no model is called, no suite is
run, no money is spent.
"""

import asyncio
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from simorgh.contracts import topics
from simorgh.growth.measure import MeasureConfig, SuiteCases, copy_repo, measure_config, place_rule
from simorgh.growth.policies import PolicyStore

LESSON = "Cite the page a fact came from."


class _Clock:
    def now(self) -> float:
        return 1_000_000.0


class _Bus:
    source = "growth"

    def __init__(self):
        self.sent = []

    async def publish(self, message):
        self.sent.append(message)


class _Logger:
    def info(self, *_a, **_k):
        pass

    warning = error = info


class _Ctx:
    def __init__(self):
        self.bus, self.clock, self.logger, self.config = _Bus(), _Clock(), _Logger(), {}


class _Estimate:
    _config = None
    _competence = None

    @staticmethod
    def load_evals(_path):
        return 0


class _Monitors:
    class _Patterns:
        @staticmethod
        def mine(_now):
            return []

    _patterns = _Patterns()

    @staticmethod
    async def _record_candidates(_patterns):
        return []


class _Explore:
    pass


def _fake_cases(with_rule: dict, without: dict, calls: list, cost_per_run: float = 0.10):
    """`cases_for` returning a run that answers from a table."""

    def cases_for(suite, task_type, cfg):
        class _Run:
            spent_usd = 0.0

            async def __call__(self, rules):
                calls.append((suite, task_type, rules))
                self.spent_usd += cost_per_run
                return dict(with_rule if rules else without)
        return _Run()
    return cases_for


def _service(config: dict, *, cases_for=None, budget: float | None = None):
    from simorgh.growth.service import Service

    service = Service(estimate=_Estimate(), monitors=_Monitors(), explore=_Explore())
    service._ctx = _Ctx()  # noqa: SLF001
    service._measure = measure_config(config)  # noqa: SLF001
    service._cases_for = cases_for  # noqa: SLF001
    if budget is not None:
        service._nightly_usd = budget  # noqa: SLF001
    service.policies = PolicyStore(clock=lambda: 1000.0)
    return service


def _night(service, *, task_type="research", kind="rule"):
    async def go():
        policy = await service.policies.propose(kind=kind, task_type=task_type, body=LESSON,
                                                evidence_refs=("task:1",))
        await service._on_sleep(None)  # noqa: SLF001
        return policy, next(p for p in service.policies.all() if p.id == policy.id)
    return asyncio.run(go())


def _step(service, prefix):
    return [s for s in service.last_night.steps if s.name.startswith(prefix)]


ON = {"measure_policies": True, "held_out": {"research": "research"}, "measure_usd_per_run": 0.05}


class TheNightMeasures(unittest.TestCase):
    def test_a_rule_that_fixes_a_held_out_case_is_adopted_and_proposed_for_landing(self):
        calls: list = []
        service = _service(ON, cases_for=_fake_cases({"a": True, "b": True}, {"a": True, "b": False}, calls),
                           budget=1.0)
        before, after = _night(service)
        self.assertEqual(after.status, "adopted")
        self.assertEqual(len(calls), 6, "three repeats a side")
        self.assertEqual({(s, t) for s, t, _ in calls}, {("research", "research")})
        self.assertEqual(sum(1 for *_x, r in calls if r == LESSON), 3)
        landed = [m for m in service._ctx.bus.sent if m.type == topics.ACTION_PROPOSED]  # noqa: SLF001
        self.assertEqual(len(landed), 1)
        payload = landed[0].payload
        self.assertEqual((payload["tool"], payload["args"]["path"], payload["args"]["rule"]),
                         ("policy_adopt", "rules/research.md", LESSON))
        self.assertEqual(payload["args"]["policy_id"], before.id)
        # What the bus would carry must pass the schema Guardian reads.
        import simorgh.contracts.messages  # noqa: F401 -- registers the schemas
        from simorgh.contracts.registry import get_spec

        self.assertEqual(get_spec(topics.ACTION_PROPOSED).validate(payload), [])
        step = _step(service, "measure:")[0]
        self.assertIn("adopted", step.detail)
        self.assertAlmostEqual(step.spent_usd, 0.6)
        self.assertAlmostEqual(service.last_night.spent_usd, 0.6)

    def test_a_rule_that_breaks_a_case_is_refused_and_nothing_lands(self):
        service = _service(ON, cases_for=_fake_cases({"a": False, "b": True}, {"a": True, "b": False}, []),
                           budget=1.0)
        _before, after = _night(service)
        self.assertEqual(after.status, "refused")
        self.assertEqual([m for m in service._ctx.bus.sent if m.type == topics.ACTION_PROPOSED], [])  # noqa: SLF001

    def test_no_held_out_suite_is_skipped_and_recorded_never_adopted(self):
        calls: list = []
        service = _service(ON, cases_for=_fake_cases({"a": True}, {"a": False}, calls), budget=1.0)
        _before, after = _night(service, task_type="chat")
        self.assertEqual(after.status, "proposed")
        self.assertEqual(calls, [])
        step = _step(service, "measure:")[0]
        self.assertIn("no held-out suite for chat", step.skipped)
        self.assertNotIn(step.name, service.last_night.ran)

    def test_over_budget_is_skipped_before_anything_runs(self):
        calls: list = []
        # 2 sides x 3 repeats x $0.05 = $0.30 against a $0.20 night.
        service = _service(ON, cases_for=_fake_cases({"a": True}, {"a": False}, calls), budget=0.20)
        _before, after = _night(service)
        self.assertEqual(calls, [])
        self.assertEqual(after.status, "proposed")
        step = _step(service, "measure:")[0]
        self.assertIn("$0.30", step.skipped)
        self.assertEqual(service.last_night.stopped_at, step.name)

    def test_the_default_budget_does_not_cover_a_measurement_at_the_default_price(self):
        """At the default price (the sandbox's $0.50 cap a run) one rule is
        $3.00, over the default $0.50 night: switching it on is not enough,
        the creator also raises the budget, and that is on purpose."""
        from simorgh.growth.night import DEFAULT_NIGHTLY_USD

        self.assertGreater(MeasureConfig().est_usd(), DEFAULT_NIGHTLY_USD)

    def test_off_by_default_nothing_runs(self):
        calls: list = []
        service = _service({"held_out": {"research": "research"}},
                           cases_for=_fake_cases({"a": True}, {"a": False}, calls), budget=100.0)
        _before, after = _night(service)
        self.assertEqual(calls, [])
        self.assertEqual(after.status, "proposed")
        self.assertEqual([s.name for s in _step(service, "measure")], ["measure"])
        self.assertIn("off", _step(service, "measure")[0].skipped)
        self.assertFalse(measure_config({}).enabled)
        self.assertFalse(measure_config({"measure_policies": "yes"}).enabled, "only a real true switches it on")

    def test_only_a_rule_is_measured(self):
        calls: list = []
        service = _service(ON, cases_for=_fake_cases({"a": True}, {"a": False}, calls), budget=1.0)
        _before, after = _night(service, kind="skill")
        self.assertEqual(calls, [])
        self.assertEqual(after.status, "proposed")

    def test_a_run_where_every_case_was_skipped_decides_nothing(self):
        """An outage is not a measurement: the rule stays proposed rather
        than being refused for ever."""
        service = _service(ON, cases_for=_fake_cases({}, {}, []), budget=1.0)
        _before, after = _night(service)
        self.assertEqual(after.status, "proposed")
        self.assertIn("left proposed", _step(service, "measure:")[0].detail)


class TheSuiteRunsInACopy(unittest.TestCase):
    def test_the_candidate_is_written_into_the_copy_and_the_suite_runs_there(self):
        seen = {}
        with tempfile.TemporaryDirectory() as live:
            live_rules = Path(live) / "rules"
            live_rules.mkdir()
            (live_rules / "research.md").write_text("Already adopted.\n")

            def fake_copy(repo, into):
                import shutil

                shutil.copytree(repo, into)
                return into

            async def fake_spawn(argv, cwd, env, timeout):
                rules = Path(cwd) / "rules" / "research.md"
                seen.setdefault("rules", []).append(rules.read_text())
                seen["argv"], seen["cwd"], seen["pythonpath"] = argv, cwd, env["PYTHONPATH"]
                rows = [{"name": "q1", "status": "passed", "detail": {"cost_usd": 0.02}},
                        {"name": "q2", "status": "failed", "detail": {"cost_usd": 0.03}},
                        {"name": "q3", "status": "skipped", "why": "no attachment"}]
                return 1, json.dumps({"cases": rows}), ""

            run = SuiteCases("research", "research", MeasureConfig(cases=2), repo=Path(live),
                             spawn=fake_spawn, copy=fake_copy)
            without = asyncio.run(run(None))
            with_it = asyncio.run(run(LESSON))
            self.assertEqual((live_rules / "research.md").read_text(), "Already adopted.\n",
                             "the live repo's rules are never touched")
        self.assertEqual(without, {"q1": True, "q2": False}, "a skipped case is neither a pass nor a fail")
        self.assertEqual(with_it, without)
        self.assertEqual(seen["rules"][0], "Already adopted.\n")
        self.assertEqual(seen["rules"][1], f"Already adopted.\n\n{LESSON}\n")
        self.assertEqual(seen["argv"][2:5], ["simorgh.evals", "run", "research"])
        self.assertIn("--paid", seen["argv"])
        self.assertEqual(seen["argv"][-2:], ["--cases", "2"])
        self.assertTrue(seen["pythonpath"].startswith(seen["cwd"]))
        self.assertFalse(Path(seen["cwd"]).exists(), "the copy is removed after the run")
        self.assertAlmostEqual(run.spent_usd, 0.10)

    def test_a_run_that_reports_nothing_is_charged_its_cap_and_fails(self):
        async def dead(argv, cwd, env, timeout):
            return 1, "", "Traceback: boom"

        run = SuiteCases("research", "research", MeasureConfig(usd_per_run=0.4),
                         spawn=dead, copy=lambda repo, into: (into.mkdir(parents=True), into)[1])
        with self.assertRaises(RuntimeError):
            asyncio.run(run(LESSON))
        self.assertAlmostEqual(run.spent_usd, 0.4)

    def test_copy_repo_takes_the_committed_tree_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
            subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
            (repo / "kept.txt").write_text("committed\n")
            subprocess.run(["git", "-C", str(repo), "add", "kept.txt"], check=True, env=env)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "c"], check=True, env=env)
            (repo / "loose.txt").write_text("untracked\n")
            out = copy_repo(repo, Path(tmp) / "copy")
            self.assertEqual((out / "kept.txt").read_text(), "committed\n")
            self.assertFalse((out / "loose.txt").exists())
            place_rule(out, "patch", LESSON)
            self.assertEqual((out / "rules" / "patch.md").read_text(), LESSON + "\n")


class TheConfig(unittest.TestCase):
    def test_keys_are_read(self):
        cfg = measure_config({"measure_policies": True, "held_out": {"research": "research", "bad": 3},
                              "measure_repeats": 5, "measure_usd_per_run": 0.2, "measure_cases": 3,
                              "measure_timeout_s": 60})
        self.assertEqual((cfg.enabled, cfg.held_out, cfg.repeats, cfg.cases, cfg.timeout_s),
                         (True, {"research": "research"}, 5, 3, 60.0))
        self.assertAlmostEqual(cfg.est_usd(), 2.0)

    def test_an_unreadable_price_falls_back_rather_than_to_free(self):
        self.assertEqual(measure_config({"measure_usd_per_run": "cheap"}).usd_per_run,
                         MeasureConfig().usd_per_run)


if __name__ == "__main__":
    unittest.main()
