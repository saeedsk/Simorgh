"""The workbench, `run_analysis` (stage 19 items 1-3,
docs/plan/stage-19-code-first-problem-solving.md).

Every call here goes the way a model's call goes: proposed on the bus,
answered by a Guardian (the test stand-in, or the real one), verified and
run by `Service._on_approved`, its rows written to `results/`. The
program's nested `sim.call`s go the same way, one action each.
"""

from __future__ import annotations

import collections
import dataclasses
import json
import os
import time
import unittest
from pathlib import Path

from simorgh.contracts.protocols import ToolContext, ToolResult
from simorgh.execution.config import Config as ExecutionConfig
from simorgh.execution.workbench import RunAnalysisTool, bridge_refusal, job_id, ref_note
from tests.simorgh.execution.test_service import _ExecutionServiceTestCase

_SENDERS = ["ann@x.com", "bob@y.org", "cat@z.net", "dan@x.com", "eve@y.org"]


def _mail_rows(n: int = 200) -> list[dict]:
    # Uneven on purpose: sender i gets a share that a 67-line page cannot reveal.
    return [{"id": i, "sender": _SENDERS[(i * i + i // 7) % len(_SENDERS)], "subject": f"s{i}"} for i in range(n)]


class _RowsTool:
    """A read-only data tool: its rows go through the full-rows store."""

    def __init__(self, name: str, rows_for, *, read_only: bool = True, reversibility: str = "read_only") -> None:
        self.name = name
        self.read_only = read_only
        self.reversibility = reversibility
        self.description = name
        self.args_schema = {"type": "object"}
        self.calls: list[dict] = []
        self._rows_for = rows_for

    async def run(self, args, *, ctx):
        self.calls.append(dict(args))
        rows = self._rows_for(args)
        lines = "\n".join(json.dumps(r) for r in rows[:5])
        return ToolResult(ok=True, output=f"{len(rows)} rows\n{lines}", metadata={"rows": rows})


class _Case(_ExecutionServiceTestCase):
    async def _boot(self, **config) -> None:
        settings = {"repo_root": self.root}
        settings.update(config)
        await self._start(config=ExecutionConfig(**settings))
        self.guardian = await self._guardian(approve=True)

    def _add(self, *tools) -> None:
        for tool in tools:
            self.service._registry[tool.name] = tool  # noqa: SLF001

    async def _call(self, tool: str, args: dict, *, job: str = "job-1") -> ToolResult:
        """A call the way a session proposes one, with its task id."""
        return await self.service._self_actions.run(  # noqa: SLF001
            tool, args, rationale="test step", extra={"task_id": job, "requester": "saeed"})

    async def _analyse(self, code: str, *, inputs=None, job: str = "job-1") -> ToolResult:
        args = {"code": code}
        if inputs is not None:
            args["inputs"] = inputs
        return await self._call("run_analysis", args, job=job)

    def _proposal(self, tool: str) -> list[dict]:
        return [p for p in self.guardian.proposals if p["tool"] == tool]


class TestTheWorkbenchComputesOverTheFullData(_Case):
    """Item 1's acceptance: a 200-row result, counted exactly by a program."""

    async def test_a_program_counts_200_rows_by_a_column_exactly(self):
        await self._boot()
        rows = _mail_rows(200)
        self._add(_RowsTool("fake_mail", lambda _a: rows))
        fetched = await self._call("fake_mail", {"query": "this month"})
        self.assertTrue(fetched.ok, fetched.error)
        ref = self._proposal("fake_mail")[0]["action_id"]

        result = await self._analyse(
            "import collections, json\n"
            f"rows = sim.rows({ref!r})\n"
            "counts = collections.Counter(r['sender'] for r in rows)\n"
            "print(json.dumps(dict(counts), sort_keys=True))\n"
            "sim.result([{'sender': s, 'n': n} for s, n in counts.most_common()])\n",
            inputs=[ref])
        self.assertTrue(result.ok, (result.error, result.output))
        printed = json.loads(result.output.splitlines()[0])
        self.assertEqual(printed, dict(collections.Counter(r["sender"] for r in rows)))
        self.assertEqual(sum(printed.values()), 200)
        # The run's own rows are stored like any tool's, with a ref.
        run_id = self._proposal("run_analysis")[0]["action_id"]
        stored = json.loads((self.root / "results" / f"{run_id}.json").read_text())
        self.assertEqual(stored[0]["n"], max(printed.values()))
        self.assertIn(ref_note(run_id, len(stored)), result.output)
        # The input is a read-only copy in the job's directory.
        copy = self.root / "results" / "work" / "job-1" / "inputs" / f"{ref}.json"
        self.assertEqual(json.loads(copy.read_text()), rows)
        self.assertFalse(os.access(copy, os.W_OK))

    async def test_last_names_the_newest_result_of_this_job(self):
        await self._boot()
        self._add(_RowsTool("fake_mail", lambda a: [{"n": a["n"]}] * a["n"]))
        await self._call("fake_mail", {"n": 3})
        await self._call("fake_mail", {"n": 7})
        await self._call("fake_mail", {"n": 11}, job="another-job")
        result = await self._analyse("print(len(sim.rows('last')))", inputs=["last"])
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.output.splitlines()[0], "7")
        # Every result of this job is in, without being named; the other job's is not.
        listed = await self._analyse("import os\nprint(len(os.listdir('inputs')))")
        self.assertEqual(listed.output.splitlines()[0], "2")

    async def test_work_db_written_in_one_call_is_read_in_the_next(self):
        await self._boot()
        first = await self._analyse(
            "con = sim.db()\n"
            "con.execute('create table seen(sender text, n int)')\n"
            "con.executemany('insert into seen values (?, ?)', [('ann', 3), ('bob', 5)])\n"
            "print('written')\n")
        self.assertTrue(first.ok, (first.error, first.output))
        second = await self._analyse("print(sim.db().execute('select sum(n) from seen').fetchone()[0])")
        self.assertTrue(second.ok, (second.error, second.output))
        self.assertEqual(second.output.splitlines()[0], "8")
        # Another job has its own directory, and no such table.
        other = await self._analyse("print(sim.db().execute('select count(*) from seen').fetchone())",
                                    job="job-2")
        self.assertFalse(other.ok)
        self.assertIn("no such table", other.error)

    async def test_save_writes_a_file_in_the_workdir_and_names_it(self):
        await self._boot()
        result = await self._analyse(
            "path = sim.save('top.csv', [{'sender': 'ann', 'n': 3}])\n"
            "print(path)\n"
            "print(sim.rows('top.csv'))\n")
        self.assertTrue(result.ok, (result.error, result.output))
        self.assertEqual(result.output.splitlines()[0], "results/work/job-1/top.csv")
        self.assertIn("'sender': 'ann'", result.output)
        self.assertIn("files: results/work/job-1/top.csv", result.output)
        self.assertTrue((self.root / "results" / "work" / "job-1" / "top.csv").is_file())

    async def test_files_outside_the_workdir_and_the_jobs_results_are_not_readable(self):
        await self._boot()
        (self.root / "secret.txt").write_text("the household's secret")
        (self.root / "results").mkdir(exist_ok=True)
        (self.root / "results" / "someone-else.json").write_text('[{"x": 1}]')
        probes = {
            "repo file": str(self.root / "secret.txt"),
            "another job's result": str(self.root / "results" / "someone-else.json"),
            "relative escape": "../../../secret.txt",
            "home": os.path.expanduser("~/.zshrc"),
        }
        code = ("import json\nout = {}\n"
                f"for label, path in {probes!r}.items():\n"
                "    try:\n"
                "        open(path).read(); out[label] = 'READ'\n"
                "    except PermissionError as exc:\n"
                "        out[label] = 'refused'\n"
                "    except OSError:\n"
                "        out[label] = 'refused'\n"
                "for label, fn in (('write outside', lambda: open('../../../planted.txt', 'w')),\n"
                "                  ('write an input', lambda: open('inputs/x.json', 'w')),\n"
                "                  ('subprocess', lambda: __import__('subprocess')),\n"
                "                  ('socket', lambda: __import__('socket').socket()),\n"
                "                  ('attach', lambda: sim.db().execute(\"attach database '../../../x.db' as x\"))):\n"
                "    try:\n"
                "        fn(); out[label] = 'ALLOWED'\n"
                "    except Exception as exc:\n"
                "        out[label] = 'refused'\n"
                "print(json.dumps(out))\n")
        result = await self._analyse(code)
        self.assertTrue(result.ok, (result.error, result.output))
        outcome = json.loads(result.output.splitlines()[0])
        self.assertEqual(set(outcome.values()), {"refused"}, outcome)
        self.assertFalse((self.root / "planted.txt").exists())
        self.assertFalse((self.root / "x.db").exists())

    async def test_an_unknown_input_is_refused_by_name(self):
        await self._boot()
        result = await self._analyse("print(1)", inputs=["nope123"])
        self.assertFalse(result.ok)
        self.assertIn("nope123", result.error)
        self.assertEqual(result.error_kind, "refused")

    async def test_a_runaway_program_is_stopped_at_the_timeout(self):
        await self._boot(workbench_timeout_s=1.0)
        started = time.monotonic()
        result = await self._analyse("import time\ntime.sleep(30)")
        self.assertFalse(result.ok)
        self.assertIn("timeout", result.error)
        self.assertLess(time.monotonic() - started, 15)

    async def test_old_job_directories_are_swept(self):
        await self._boot(workbench_keep_days=1.0)
        stale = self.root / "results" / "work" / "old-job"
        (stale / "inputs").mkdir(parents=True)
        (stale / "inputs" / "a.json").write_text("[]")
        (stale / "inputs" / "a.json").chmod(0o444)
        long_ago = time.time() - 3 * 86400
        os.utime(stale, (long_ago, long_ago))
        await self._analyse("print('hi')")
        self.assertFalse(stale.exists())
        self.assertTrue((self.root / "results" / "work" / "job-1").is_dir())

    async def test_workbench_off_registers_no_tool(self):
        await self._start(config=ExecutionConfig(repo_root=self.root, workbench=False))
        self.assertNotIn("run_analysis", self.service._registry)  # noqa: SLF001


class TestTheToolBridge(_Case):
    """Item 2's acceptance: paginate 1200 items, each call its own action."""

    def _source(self):
        items = [{"id": i, "sender": _SENDERS[i % 5]} for i in range(1200)]

        def page(args):
            offset, limit = int(args.get("offset", 0)), int(args.get("limit", 200))
            return items[offset: offset + min(limit, 200)]
        return items, _RowsTool("fake_source", page)

    async def test_a_program_paginates_1200_items_and_gets_every_one(self):
        # One slot: the nested calls must not wait on the slot their parent holds.
        await self._boot(max_concurrent_actions=1)
        items, source = self._source()
        self._add(source)
        result = await self._analyse(
            "seen, offset = [], 0\n"
            "while True:\n"
            "    page = sim.call('fake_source', offset=offset, limit=200)\n"
            "    assert page['ok'], page\n"
            "    seen.extend(page['rows'])\n"
            "    if len(page['rows']) < 200:\n"
            "        break\n"
            "    offset += 200\n"
            "print(len(seen), len({r['id'] for r in seen}))\n"
            "print(sum(1 for r in seen if r['sender'] == 'ann@x.com'))\n")
        self.assertTrue(result.ok, (result.error, result.output))
        lines = result.output.splitlines()
        self.assertEqual(lines[0], "1200 1200")
        self.assertEqual(lines[1], str(sum(1 for r in items if r["sender"] == "ann@x.com")))
        self.assertEqual(len(source.calls), 7, "six full pages and the empty one that ends the loop")

        parent = self._proposal("run_analysis")[0]
        nested = self._proposal("fake_source")
        self.assertEqual(len(nested), 7, "Guardian saw every nested call")
        for proposal in nested:
            self.assertEqual(proposal["parent_action_id"], parent["action_id"])
            self.assertEqual(proposal["task_id"], "job-1")
            self.assertEqual(proposal["requester"], "saeed", "the parent's requester, not the console's")
            self.assertEqual(proposal["proposed_by"], "execution")
            stream = [e.type for e in await self.ledger.read(f"action:{proposal['action_id']}")]
            self.assertIn("received", stream)
            self.assertIn("verified", stream, "each nested call is its own verified action")
        recorded = [e.payload for e in await self.ledger.read(f"action:{parent['action_id']}")
                    if e.type == "nested_call"]
        self.assertEqual([r["action_id"] for r in recorded], [p["action_id"] for p in nested])
        # The nested results are this job's: in `inputs/`, readable next run.
        again = await self._analyse(f"print(len(sim.rows({nested[0]['action_id']!r})))")
        self.assertEqual(again.output.splitlines()[0], "200")

    async def test_a_write_tool_and_an_unknown_tool_are_refused_by_name(self):
        await self._boot()
        writer = _RowsTool("fake_write", lambda _a: [{"x": 1}], read_only=False, reversibility="reversible")
        self._add(writer)
        result = await self._analyse(
            "import json\n"
            "print(json.dumps([sim.call('fake_write', x=1), sim.call('no_such_tool'),\n"
            "                  sim.call('run_analysis', code='print(1)')]))\n")
        self.assertTrue(result.ok, (result.error, result.output))
        write, unknown, nested = json.loads(result.output.splitlines()[0])
        self.assertFalse(write["ok"])
        self.assertIn("fake_write", write["error"])
        self.assertIn("not read-only", write["error"])
        self.assertFalse(unknown["ok"])
        self.assertIn("no_such_tool", unknown["error"])
        self.assertFalse(nested["ok"])
        self.assertEqual(writer.calls, [])
        self.assertEqual([p["tool"] for p in self.guardian.proposals], ["run_analysis"],
                         "nothing refused was proposed")

    async def test_the_per_run_cap_holds(self):
        await self._boot(workbench_max_calls=3)
        _items, source = self._source()
        self._add(source)
        result = await self._analyse(
            "print([sim.call('fake_source', offset=i * 200)['ok'] for i in range(5)])\n"
            "print(sim.call('fake_source')['error'])\n")
        self.assertTrue(result.ok, (result.error, result.output))
        lines = result.output.splitlines()
        self.assertEqual(lines[0], "[True, True, True, False, False]")
        self.assertIn("workbench_max_calls", lines[1])
        self.assertEqual(len(source.calls), 3)

    async def test_a_denied_nested_call_comes_back_as_not_ok(self):
        await self._boot()
        _items, source = self._source()
        self._add(source)
        # Guardian approves the run, then says no to what it calls.
        decide = self.guardian._on_proposed  # noqa: SLF001

        async def _no_to_nested(message):
            self.guardian.approve = not message.payload.get("parent_action_id")
            await decide(message)
        await self.guardian._sub.unsubscribe()  # noqa: SLF001
        from simorgh.contracts import topics
        self.guardian._sub = await self.guardian._bus.subscribe(  # noqa: SLF001
            topics.ACTION_PROPOSED, _no_to_nested, group="guardian")
        result = await self._analyse("r = sim.call('fake_source')\nprint(r['ok'], 'denied' in r['error'])")
        self.assertTrue(result.ok, (result.error, result.output))
        self.assertEqual(result.output.splitlines()[0], "False True")
        self.assertEqual(source.calls, [])


class TestWithTheRealGuardian(_Case):
    async def test_guarded_mode_approves_a_nested_read(self):
        from simorgh.bus.factory import make_client
        from simorgh.contracts.protocols import Context
        from simorgh.guardian.config import Config as GuardianConfig
        from simorgh.guardian.service import Service as GuardianService
        from tests.simorgh.execution.test_own_calls_go_through_guardian import _Logger

        await self._start(config=ExecutionConfig(repo_root=self.root))
        bus = make_client(self.backend, source="guardian", ledger=self.ledger, clock=self.clock)
        await bus.start()
        ctx = Context(name="guardian", instance_id="", run_id="test", mode="single", bus=bus,
                      ledger=self.ledger, config={}, secrets={"__hmac__": self.ctx.secrets["__hmac__"]},
                      clock=self.clock, logger=_Logger(), data_dir=self.root / "guardian")
        guardian = GuardianService(config=GuardianConfig(mode="guarded"))
        await guardian.start(ctx)
        self.addAsyncCleanup(guardian.stop)
        source = _RowsTool("fake_source", lambda a: [{"i": i} for i in range(int(a.get("n", 3)))])
        self._add(source)
        result = await self.service._self_actions.run(  # noqa: SLF001
            "run_analysis", {"code": "r = sim.call('fake_source', n=4)\nprint(r['ok'], len(r['rows']))"},
            rationale="test step")
        self.assertTrue(result.ok, (result.error, result.output))
        self.assertEqual(result.output.splitlines()[0], "True 4")
        self.assertEqual(len(source.calls), 1)


class TestWithoutABridge(unittest.IsolatedAsyncioTestCase):
    async def test_sim_call_says_the_bridge_is_unavailable(self):
        import tempfile

        from tests.simorgh.helpers import FakeClock

        with tempfile.TemporaryDirectory() as tmp:
            config = ExecutionConfig(repo_root=Path(tmp))
            tool = RunAnalysisTool(config)
            ctx = ToolContext(action_id="a1", task_id="t1", scope={}, constraints={}, data_dir=Path(tmp),
                              clock=FakeClock(), logger=None, ledger=None)
            result = await tool.run({"code": "r = sim.call('read_file', path='x')\nprint(r['ok'], r['error'])"},
                                    ctx=ctx)
            self.assertTrue(result.ok, (result.error, result.output))
            self.assertIn("False", result.output)
            self.assertIn("bridge is unavailable", result.output)


class TestRefsOnEveryStructuredResult(_Case):
    """Item 3's acceptance: three different tools, each result's last line
    names its ref and how to compute over it."""

    async def test_three_tools_each_end_with_their_ref(self):
        await self._boot(results_max_rows=50)
        self._add(_RowsTool("fake_mail", lambda _a: _mail_rows(20)),
                  _RowsTool("fake_calendar", lambda _a: [{"day": d, "hours": 2} for d in range(7)]),
                  _RowsTool("fake_files", lambda _a: [{"path": f"f{i}", "bytes": i} for i in range(120)]))
        for tool, count in (("fake_mail", 20), ("fake_calendar", 7), ("fake_files", 50)):
            with self.subTest(tool=tool):
                result = await self._call(tool, {})
                action_id = self._proposal(tool)[0]["action_id"]
                lines = result.output.splitlines()
                self.assertEqual(lines[-1], f"ref: {action_id} ({count} rows) -- use run_analysis "
                                            f"inputs=[{action_id}] to compute over all of it")
                self.assertTrue(lines[-2].startswith(f"full data: results/{action_id}.json"), lines[-2])
                # Orchestration's cut keeps everything from "\n\nfull data: " on.
                self.assertIn(lines[-1], result.output[result.output.rfind("\n\nfull data: "):])

    async def test_a_result_without_rows_gets_no_ref(self):
        await self._boot()
        self._add(_RowsTool("fake_empty", lambda _a: []))
        result = await self._call("fake_empty", {})
        self.assertNotIn("ref:", result.output)

    async def test_workbench_off_drops_the_ref_line(self):
        await self._start(config=ExecutionConfig(repo_root=self.root, workbench=False))
        self.guardian = await self._guardian(approve=True)
        self._add(_RowsTool("fake_mail", lambda _a: _mail_rows(5)))
        result = await self._call("fake_mail", {})
        self.assertIn("full data:", result.output)
        self.assertNotIn("run_analysis", result.output)


class TestTheHelpers(unittest.TestCase):
    def test_job_ids_are_safe_directory_names(self):
        self.assertEqual(job_id("chat-12", "a1"), "chat-12")
        self.assertEqual(job_id("../../etc", "a1"), "etc")
        self.assertEqual(job_id(None, "a1"), "action-a1")

    def test_bridge_refusal_names_the_tool(self):
        class _T:
            read_only, reversibility = True, "irreversible"
        self.assertIn("x_tool", bridge_refusal("x_tool", _T()))
        self.assertIn("unknown tool 'ghost'", bridge_refusal("ghost", None))
        _T.reversibility = "read_only"
        self.assertEqual(bridge_refusal("x_tool", _T()), "")


if __name__ == "__main__":
    unittest.main()
