"""Stage 19 item 8: the code-first suite, offline.

What is proved here, with no model and no money:

- the World is the same household for the same seed and day, and each
  domain is bigger than one tool page;
- the expected answers are exact and unambiguous (no tie at a cut);
- a scripted model that READS ONE PAGE through Sim's real tools scores
  wrong on every case, and one that COMPUTES over everything scores
  right -- so the fakes, the expected answers and the scorer agree;
- the scorer reads prose, lists and tables alike, and still fails an
  answer one number off;
- the method check counts `run_analysis` by name only, so it works
  before and after the workbench exists;
- a booted sandbox gets the World through the tools' own seams, the
  question reaches Sim, and a floor answer is skipped, not scored.
"""

import asyncio
import contextlib
import io
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from simorgh.evals.codefirst import cases as C
from simorgh.evals.codefirst import models as M
from simorgh.evals.codefirst import run as R
from simorgh.evals.codefirst import world as W
from simorgh.evals.codefirst.method import method_of, ran_program, tally


def _world(seed: int = W.DEFAULT_SEED, anchor: date = W.TEST_ANCHOR) -> W.World:
    return W.build(seed, anchor)


async def _attempt(model: str, case_id: str, world: W.World) -> M.Attempt:
    with tempfile.TemporaryDirectory() as tmp:
        return await M.MODELS[model](case_id, M.Bench(world, tmp))


class TheWorld(unittest.TestCase):
    def test_the_same_seed_and_day_is_the_same_household(self):
        a, b = _world(), _world()
        self.assertEqual(a.mail, b.mail)
        self.assertEqual(a.events, b.events)
        self.assertEqual(a.files, b.files)
        self.assertEqual(a.telemetry, b.telemetry)
        self.assertEqual(a.named, b.named)
        self.assertNotEqual(a.files, _world(seed=W.DEFAULT_SEED + 1).files)

    def test_every_domain_is_bigger_than_a_page(self):
        world = _world()
        in_window = [m for m in world.mail if world.mail_since <= m["date"].date() <= world.mail_until]
        self.assertGreater(len(in_window), 900)
        self.assertGreater(len(world.mail), len(in_window), "nothing outside the month to leave out")
        self.assertGreater(len([e for e in world.events if not e.all_day]), 1.5 * M.PAGE)
        self.assertTrue(any(e.all_day for e in world.events), "no all-day event to leave out")
        self.assertEqual(len(world.files), 3000)
        self.assertGreater(len(world.telemetry), 3000)
        self.assertEqual(len({s.address for s in world.named}), 25)

    def test_every_file_name_is_unique(self):
        names = [p.rsplit("/", 1)[1] for _s, p in _world().files]
        self.assertEqual(len(names), len(set(names)))

    def test_the_files_land_where_read_file_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _world().install(tmp)
            self.assertEqual([p.relative_to(tmp).as_posix() for p in paths], [W.FILES_INDEX, W.TELEMETRY_LOG])
            self.assertEqual(len(paths[0].read_text().splitlines()), 3001)


class TheExpectedAnswers(unittest.TestCase):
    def test_no_tie_decides_a_cut(self):
        for seed in (W.DEFAULT_SEED, 1, 2, 3):
            world = _world(seed)
            top = C.mail_top_expected(world)
            counts = [n for _a, n in top]
            self.assertEqual(len(set(counts)), 5, top)
            lo, hi = world.mail_since, world.mail_until
            from collections import Counter
            every = Counter(m["from"] for m in world.mail if lo <= m["date"].date() <= hi).most_common()
            self.assertGreater(counts[-1], every[5][1], "the sixth sender ties the fifth")
            for ext in C.FILE_TYPES:
                sizes = sorted((s for s, p in world.files if p.endswith("." + ext)), reverse=True)
                self.assertGreater(sizes[9], sizes[10], f".{ext}: the 10th and 11th are the same size")

    def test_the_answers_have_the_asked_shape(self):
        world = _world()
        self.assertEqual(list(C.calendar_expected(world)), list(C.WEEKDAYS))
        self.assertEqual(set(C.files_expected(world)), set(C.FILE_TYPES))
        self.assertTrue(all(len(v) == 10 for v in C.files_expected(world).values()))
        failures = C.telemetry_expected(world)
        self.assertEqual(failures["kb_search"], 0, "kb_search fails only before the week; it must count 0")
        latest = C.latest_expected(world)
        self.assertEqual(len(latest), 25)
        self.assertTrue(any(day < world.mail_since for day in latest.values()),
                        "no named sender wrote only before the month")


class TheScriptedModels(unittest.TestCase):
    """The acceptance: a page reader scores wrong, a program scores right."""

    def test_reading_one_page_is_wrong_on_every_case(self):
        world = _world()
        for case in C.CASES:
            attempt = asyncio.run(_attempt("reader", case.id, world))
            score = case.score(attempt.text, world)
            self.assertFalse(score.exact, f"{case.id}: one page answered it\n{attempt.text}")
            self.assertEqual(method_of(attempt.tools), "reading")
            self.assertEqual(len(attempt.tools), 1, attempt.tools)

    def test_computing_over_everything_is_right_on_every_case(self):
        world = _world()
        for case in C.CASES:
            attempt = asyncio.run(_attempt("computer", case.id, world))
            score = case.score(attempt.text, world)
            self.assertTrue(score.exact, f"{case.id}: {score.why}\n{attempt.text}")
            self.assertTrue(ran_program(attempt.tools))
            self.assertTrue(set(attempt.tools) - {"run_analysis"} <= set(case.reads), attempt.tools)

    def test_the_per_item_case_really_loops(self):
        attempt = asyncio.run(_attempt("computer", "mail/latest-per-sender", _world()))
        self.assertEqual(tally(attempt.tools)["mail_search"], 25)

    def test_the_free_suite_passes_for_other_households_too(self):
        for seed, anchor in ((3, date(2027, 1, 4)), (11, date(2026, 3, 1))):
            outcomes = asyncio.run(R.scripted_outcomes(seed=seed, anchor=anchor))
            self.assertEqual([o.status for o in outcomes], ["passed"] * 5, [o.why for o in outcomes])
            self.assertEqual({o.case.level for o in outcomes}, {"mail", "calendar", "files", "telemetry"})


class TheScorer(unittest.TestCase):
    def setUp(self):
        self.world = _world()

    def _case(self, case_id):
        return C.by_id(case_id)

    def test_senders_in_prose_or_a_table(self):
        top = C.mail_top_expected(self.world)
        name = {s.address: s.name for s in self.world.senders}
        prose = "Biggest first: " + ", then ".join(f"{name[a]} with {n:,} emails" for a, n in top) + "."
        table = "| sender | messages |\n|---|---|\n" + "\n".join(f"| {a} | {n} |" for a, n in top)
        case = self._case("mail/top-senders-30-days")
        self.assertTrue(case.score(prose, self.world).exact, case.score(prose, self.world).why)
        self.assertTrue(case.score(table, self.world).exact)
        off = table.replace(f"| {top[2][1]} |", f"| {top[2][1] + 1} |")
        self.assertFalse(case.score(off, self.world).exact)
        swapped = "\n".join(f"{a}: {n}" for a, n in [top[1], top[0], *top[2:]])
        self.assertIn("rank order", case.score(swapped, self.world).why)

    def test_hours_in_any_unit_within_a_rounding(self):
        want = C.calendar_expected(self.world)
        case = self._case("calendar/hours-per-weekday")
        decimal = "Monday through Sunday, in hours:\n" + "\n".join(f"{d}: {h:.1f}" for d, h in want.items())
        minutes = " ".join(f"{d[:3]} {round(h * 60)} minutes;" for d, h in want.items() if h)
        self.assertTrue(case.score(decimal, self.world).exact, case.score(decimal, self.world).why)
        self.assertTrue(case.score(minutes, self.world).exact, case.score(minutes, self.world).why)
        wrong = decimal.replace(f"Monday: {want['Monday']:.1f}", f"Monday: {want['Monday'] + 1:.1f}")
        self.assertFalse(case.score(wrong, self.world).exact)

    def test_files_by_name_or_path_and_not_a_dump(self):
        want = C.files_expected(self.world)
        case = self._case("files/largest-per-type")
        paths = {p.rsplit("/", 1)[1]: p for _s, p in self.world.files}
        answer = "\n".join(paths[n] for names in want.values() for n in names)
        self.assertTrue(case.score(answer, self.world).exact)
        dump = W.World.files_index_text(self.world)
        self.assertFalse(case.score(dump, self.world).exact, "listing every file is not an answer")
        self.assertFalse(case.score(answer.replace(want["pdf"][9], "nothing.pdf"), self.world).exact)

    def test_failures_leave_zero_tools_out_but_never_invent_one(self):
        want = C.telemetry_expected(self.world)
        case = self._case("telemetry/failures-per-tool")
        answer = ", ".join(f"{t} failed {n} times" for t, n in want.items() if n)
        self.assertTrue(case.score(answer, self.world).exact, case.score(answer, self.world).why)
        self.assertFalse(case.score(answer + ", kb_search failed 4 times", self.world).exact)

    def test_dates_in_any_common_form_and_without_a_year(self):
        want = C.latest_expected(self.world)
        case = self._case("mail/latest-per-sender")
        forms = (lambda d: d.isoformat(), lambda d: f"{d:%B} {d.day}, {d.year}", lambda d: f"{d.day} {d:%b}",
                 lambda d: f"{d:%a} {d.day} {d:%B}")
        for form in forms:
            answer = "\n".join(f"- {addr}: last wrote {form(day)}" for addr, day in want.items())
            self.assertTrue(case.score(answer, self.world).exact, (form(date(2026, 10, 3)), case.score(answer, self.world).why))
        addr = next(iter(want))
        broken = "\n".join(f"{a}: {d.isoformat() if a != addr else '2020-01-01'}" for a, d in want.items())
        self.assertEqual(case.score(broken, self.world).got, "24/25")


class TheMethodCheck(unittest.TestCase):
    def test_counted_by_tool_name_only(self):
        self.assertEqual(method_of(["mail_search", "mail_search"]), "reading")
        self.assertEqual(method_of(["cal_list", "run_analysis"]), "program")
        self.assertFalse(ran_program([]))
        self.assertEqual(tally(["a", "b", "a", ""]), {"a": 2, "b": 1})


class TheWiring(unittest.TestCase):
    def test_the_suites_are_registered_and_the_sim_one_costs_money(self):
        from simorgh.evals.suites import PAID, SUITES

        self.assertIn("code_first", SUITES)
        self.assertIn("code_first_scripted", SUITES)
        self.assertIn("code_first", PAID)
        self.assertNotIn("code_first_scripted", PAID)

    def test_the_command_refuses_sim_without_paid_and_runs_the_scripted_check(self):
        from simorgh.evals.__main__ import main

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SIMORGH_HOUSE_PAID", None)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["code-first"]), 2)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(["code-first", "--scripted"]), 0)
            self.assertIn("5/5 exact", out.getvalue())

    def test_without_a_model_every_sim_case_is_skipped_not_failed(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SIMORGH_HOUSE_PAID", None)
            os.environ.pop("SIMORGH_EVALS_PAID", None)
            outcomes = asyncio.run(R.sim_outcomes())
        self.assertEqual({o.status for o in outcomes}, {"skipped"})
        self.assertEqual(len(outcomes), 5)


class TheSandbox(unittest.TestCase):
    """One real boot (floor provider, no keys): the World reaches Sim's
    tools through their own seams, the question reaches Sim, and the
    floor's reply is skipped rather than scored."""

    def test_a_booted_sim_gets_the_world_and_a_floor_answer_is_skipped(self):
        asyncio.run(self._run())

    async def _run(self):
        from simorgh.contracts.protocols import ToolContext
        from simorgh.evals.house.director import Director
        from simorgh.evals.house.sandbox import Sandbox

        world = W.build(W.DEFAULT_SEED, date.today())
        case = C.by_id("mail/top-senders-30-days")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SIMORGH_EXECUTION_REPO_ROOT", None)
            async with Sandbox(config={"execution": {"repo_root": tmp}}) as box:
                with contextlib.redirect_stdout(io.StringIO()):
                    root = R.wire(box, world)
                    self.assertEqual(root, Path(tmp).resolve())
                    registry = box.service("execution")._registry  # noqa: SLF001
                    ctx = ToolContext(action_id="t", task_id=None, scope={}, constraints={}, data_dir=Path(tmp),
                                      clock=None, logger=None, ledger=None)
                    counted = await registry["mail_search"].run(
                        {"group_by": "sender", "since": world.mail_since.isoformat(), "top": 5}, ctx=ctx)
                    self.assertEqual([(r["sender"].split("<")[1].rstrip(">"), r["messages"])
                                      for r in counted.metadata["rows"][:5]], C.mail_top_expected(world))
                    events = await registry["cal_list"].run({"range": "91 days"}, ctx=ctx)
                    self.assertEqual(events.metadata["events"], len(world.events))
                    index = await registry["read_file"].run({"path": W.FILES_INDEX + ":1-3"}, ctx=ctx)
                    self.assertIn("of 3001", index.output)

                    director = Director(box)
                    mark = director.now()
                    typing = asyncio.ensure_future(director.type(case.question(world), wait=False))
                    answer, floor = await R._answer(director, mark, 60.0)  # noqa: SLF001
                    typing.cancel()
            self.assertIsNotNone(answer, "the question never got an answer")
            self.assertTrue(floor, "a sandbox with no keys answered with something other than the floor")
            self.assertFalse(case.score(answer, world).exact)

    def test_wire_refuses_to_write_into_this_checkout(self):
        from simorgh.execution.config import find_repo_root

        class _Exec:
            _registry = {}
            _config = type("C", (), {"repo_root": find_repo_root()})()

        class _Box:
            def service(self, name):
                return _Exec()

        tools = []
        for name in ("cal_list", "mail_search", "mail_read"):
            tool = type("T", (), {"name": name, "_given": None})()
            tools.append(tool)
        _Exec._registry = {t.name: t for t in tools}
        with self.assertRaisesRegex(RuntimeError, "this checkout"):
            R.wire(_Box(), _world())
        self.assertFalse((find_repo_root() / W.FILES_INDEX).exists())


if __name__ == "__main__":
    unittest.main()
