"""`crew`, `crew <id>`, `crew cancel <handle>`, and the dashboard's
`/api/crews` (stage 18 item 5).

Both read the `crew:<id>` streams through the same fold, so the console
and the page never disagree, and a crew started before this session --
or from the phone -- is still listed.
"""

from __future__ import annotations

import asyncio
import http.client
import json
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from simorgh.contracts import topics
from simorgh.interface.dispatch import dispatch
from simorgh.interface.httpapi import HttpApi
from simorgh.interface.parser import COMMAND_NAMES, parse
from simorgh.interface.vitals import VitalsCache

from .test_crew_tree import ROOT, six_member_crew


class _Ledger:
    def __init__(self, streams: dict[str, list]) -> None:
        self._streams = streams

    async def streams(self, prefix: str) -> list[str]:
        return [s for s in self._streams if s.startswith(prefix)]

    async def read(self, stream: str, *, from_seq: int = 0, limit=None):
        events = self._streams.get(stream, [])
        return events[max(0, from_seq - 1):][:limit] if limit else events[max(0, from_seq - 1):]

    async def head(self, stream: str) -> int:
        return len(self._streams.get(stream, []))


def _events(pairs, start: float = 100.0) -> list:
    return [SimpleNamespace(type=t, payload=p, ts=start + i, seq=i + 1) for i, (t, p) in enumerate(pairs)]


class _Bus:
    def __init__(self) -> None:
        self.published = []

    def new(self, type_, payload, **_kw):
        return SimpleNamespace(type=type_, payload=payload)

    async def publish(self, message) -> None:
        self.published.append(message)


def _ledger() -> _Ledger:
    other = [(topics.CREW_SPAWNED, {"crew_id": "old00001", "handle": "x1", "parent": "old00001",
                                    "agent": "research", "brief_ref": "an older crew"}),
             (topics.CREW_REPORT, {"crew_id": "old00001", "handle": "x1", "report": {"status": "ok", "summary": "done"}})]
    return _Ledger({f"crew:{ROOT}": _events(six_member_crew(), start=200.0), "crew:old00001": _events(other),
                    "task:abc": []})


async def _run(line: str, *, ledger=None, bus=None) -> str:
    outcome = await dispatch(parse(line), bus=bus or _Bus(), clock=SimpleNamespace(now=lambda: 0.0),
                             session_id="s1", vitals=VitalsCache(), ledger=ledger or _ledger())
    return outcome.text


def _at(columns: int):
    return mock.patch("shutil.get_terminal_size", return_value=os.terminal_size((columns, 24)))


class TheCommand(unittest.TestCase):
    def test_it_is_in_the_command_table(self):
        self.assertIn("crew", COMMAND_NAMES)
        self.assertEqual(parse("crew cancel h1").name, "crew")

    def test_crew_lists_every_crew_newest_first(self):
        with _at(120):
            text = asyncio.run(_run("crew"))
        lines = text.splitlines()
        self.assertIn(f"crew {ROOT}", lines[0])
        self.assertIn("6 members", lines[0])
        self.assertIn("crew old00001", lines[1])

    def test_no_crews_says_so(self):
        self.assertIn("no crews yet", asyncio.run(_run("crew", ledger=_Ledger({}))))

    def test_crew_id_draws_the_tree_and_the_messages(self):
        with _at(120):
            text = asyncio.run(_run(f"crew {ROOT[:6]}"))
        self.assertIn("price of dishwasher A", text)
        self.assertIn("│", text)
        self.assertIn("messages (newest", text)
        self.assertIn("which postcode", text)

    def test_cancel_publishes_a_cascading_crew_cancel(self):
        bus = _Bus()
        text = asyncio.run(_run("crew cancel h1aaaa too slow", bus=bus))
        self.assertIn("asked research h1aaaaaa to stop", text)
        sent = bus.published[0]
        self.assertEqual(sent.type, topics.CREW_CANCEL)
        self.assertEqual(sent.payload, {"crew_id": ROOT, "handle": "h1aaaaaaaaaa", "reason": "too slow",
                                        "cascade": True})

    def test_cancel_of_a_finished_or_unknown_member_publishes_nothing(self):
        bus = _Bus()
        self.assertIn("already done", asyncio.run(_run("crew cancel h2bbbbbbbbbb", bus=bus)))
        self.assertIn("no crew member", asyncio.run(_run("crew cancel zzz", bus=bus)))
        self.assertEqual(bus.published, [])


class TheDashboardRoute(unittest.IsolatedAsyncioTestCase):
    async def test_api_crews_folds_the_streams_for_the_panel(self):
        api = HttpApi(SimpleNamespace(subscribe=self._subscribe), ledger=_ledger(), host="127.0.0.1", port=0)
        await api.start()
        self.addAsyncCleanup(api.stop)

        def _get(path):
            conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=5)
            conn.request("GET", path)
            resp = conn.getresponse()
            body = json.loads(resp.read())
            conn.close()
            return body

        body = await asyncio.to_thread(_get, "/api/crews")
        self.assertEqual(body["total"], 2)
        crew = body["crews"][0]
        self.assertEqual(crew["crew_id"], ROOT)
        self.assertEqual([m["handle"][:2] for m in crew["tree"]], ["h1", "h4", "h6", "h5", "h2", "h3"])
        self.assertEqual(crew["tree"][1]["depth"], 2)
        one = await asyncio.to_thread(_get, "/api/crews?id=old00001")
        self.assertEqual([c["crew_id"] for c in one["crews"]], ["old00001"])

    async def _subscribe(self, *_a, **_k):
        return SimpleNamespace(unsubscribe=self._noop)

    async def _noop(self):
        return None

    def test_the_dashboard_page_has_the_crew_panel(self):
        from pathlib import Path

        page = (Path(__file__).resolve().parents[3] / "simorgh" / "interface" / "static" / "dashboard.html").read_text()
        self.assertIn('id="crew-panel"', page)
        self.assertIn("/api/crews", page)
