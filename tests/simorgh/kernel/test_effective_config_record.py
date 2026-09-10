"""The Kernel writes down what config is actually in force.

Every subsystem's `from_mapping` silently ignores a key it does not
recognise, so a typo in simorgh.toml is indistinguishable from a
setting that works: the file changes, the system does not, and nothing
says so. The boot warning says it once and scrolls past. This is the
record the `config` command reads back afterwards, and it exists only
because the Kernel is the one place holding every subsystem's config
object at the same time."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.service import Kernel, _config_scalar


class ScalarTestCase(unittest.TestCase):
    """Paths and tuples appear constantly in these configs and neither
    survives JSON, so the Ledger append would fail and the whole record
    would be silently missing."""

    def test_a_path_becomes_a_string(self):
        self.assertEqual(_config_scalar(Path("/a/b")), "/a/b")

    def test_a_tuple_becomes_a_list(self):
        self.assertEqual(_config_scalar(("a", "b")), ["a", "b"])

    def test_a_nested_dict_is_converted_through(self):
        self.assertEqual(_config_scalar({"k": Path("/x")}), {"k": "/x"})

    def test_plain_values_pass_through(self):
        for value in (1, 1.5, True, None, "text"):
            self.assertEqual(_config_scalar(value), value)

    def test_anything_else_becomes_its_repr_rather_than_breaking_the_append(self):
        class _Odd:
            def __repr__(self):
                return "<odd>"

        self.assertEqual(_config_scalar(_Odd()), "<odd>")


class RecordTestCase(unittest.IsolatedAsyncioTestCase):
    """Drives `_record_effective_config` against a real memory Ledger --
    the wire from the Kernel to the stream the CLI reads, which is the
    half that is usually left unconnected."""

    async def asyncSetUp(self):
        from simorgh.ledger.factory import make_ledger

        from tests.simorgh.helpers import FakeClock

        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock.now)
        await self.ledger.start()

    async def asyncTearDown(self):
        await self.ledger.stop()
        self._tmp.cleanup()

    async def _record(self, raw: dict, dead=()) -> dict:
        kernel = Kernel.__new__(Kernel)
        kernel.config = LoadedConfig(raw, Path(self._tmp.name) / "simorgh.toml")
        kernel.ledger = self.ledger
        kernel._clock = self.clock
        await kernel._record_effective_config(list(dead))
        events = await self.ledger.read(Kernel.CONFIG_STREAM)
        self.assertTrue(events, "nothing was recorded")
        return events[-1].payload

    async def test_every_setting_is_recorded_with_its_source(self):
        payload = await self._record({"execution": {"notify_provider": "ntfy"}})
        execution = payload["sections"]["execution"]
        self.assertEqual(execution["notify_provider"]["source"], "file")
        self.assertEqual(execution["notify_provider"]["value"], "ntfy")
        self.assertEqual(execution["shell"]["source"], "default")

    async def test_a_value_equal_to_the_default_is_still_marked_as_set(self):
        """This is the whole reason `source` is recorded separately from
        the value."""
        payload = await self._record({"execution": {"shell": False}})
        self.assertEqual(payload["sections"]["execution"]["shell"]["source"], "file")

    async def test_the_new_domain_settings_are_all_there(self):
        payload = await self._record({})
        execution = payload["sections"]["execution"]
        for key in ("knowledge_index_path", "pim_accounts", "security_findings_path",
                    "home_aliases", "energy_meters", "media_quiet_hours"):
            self.assertIn(key, execution, key)

    async def test_paths_and_tuples_survive_the_append(self):
        payload = await self._record({})
        self.assertIsInstance(payload["sections"]["execution"]["repo_root"]["value"], str)
        self.assertIsInstance(payload["sections"]["execution"]["readable_roots"]["value"], list)

    async def test_dead_sections_and_fields_are_carried(self):
        payload = await self._record({}, dead=["typoed"])
        self.assertEqual(payload["dead_sections"], ["typoed"])
        self.assertIn("dead_fields", payload)

    async def test_the_file_path_is_recorded_so_a_person_knows_which_one(self):
        payload = await self._record({})
        self.assertTrue(payload["path"].endswith("simorgh.toml"))

    async def test_a_value_of_the_wrong_type_is_recorded_as_written(self):
        """The dataclass does not coerce, so a string where a number
        belongs is stored as that string. Recording it as written is the
        useful behaviour -- `config` then shows the person exactly the
        wrong thing they typed, which is what they need to see."""
        payload = await self._record({"execution": {"max_concurrent_actions": "not a number"}})
        recorded = payload["sections"]["execution"]["max_concurrent_actions"]
        self.assertEqual(recorded["value"], "not a number")
        self.assertEqual(recorded["source"], "file")

    async def test_a_section_that_genuinely_will_not_parse_is_listed_rather_than_dropped(self):
        payload = await self._record({"execution": {"mcp_servers": [{"no_name_field": True}]}})
        self.assertIn("error", payload["sections"]["execution"])

    async def test_a_ledger_that_refuses_does_not_break_the_boot(self):
        """A diagnostic that can stop a boot is a worse problem than the
        one it diagnoses."""

        class _Broken:
            async def append(self, *a, **k):
                raise RuntimeError("ledger is down")

        kernel = Kernel.__new__(Kernel)
        kernel.config = LoadedConfig({}, None)
        kernel.ledger = _Broken()
        kernel._clock = self.clock
        await kernel._record_effective_config([])   # no raise
