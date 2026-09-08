"""A setting that does nothing has to say so.

Every subsystem's `from_mapping` ignores a key it does not recognise --
right for forward compatibility, wrong for a typo. `[planing]` for
`[planning]`, or `lease_secs` for `lease_seconds`, was silently
indistinguishable from a setting that works: the creator edits the
file, the system does exactly what it did before, and nothing appears
on screen.

This is the other half of the 2026-09-08 config work. Making eleven
subsystems read their section is worth little if a mistyped key in that
section still vanishes.
"""

from __future__ import annotations

import unittest

from simorgh.kernel.configcheck import dead_sections, report


class _Config:
    def __init__(self, raw: dict) -> None:
        self.raw = raw

    def section(self, name: str) -> dict:
        return dict(self.raw.get(name, {}))


class _Logger:
    def __init__(self) -> None:
        self.warnings: list[tuple[str, dict]] = []

    def warning(self, event: str, **fields) -> None:
        self.warnings.append((event, fields))


class TestSpottingASectionThatDoesNothing(unittest.TestCase):
    def test_a_mistyped_key_is_reported(self) -> None:
        self.assertEqual(dead_sections(_Config({"planning": {"lease_secs": 99}})), ["planning"])

    def test_a_key_that_works_is_not_reported(self) -> None:
        self.assertEqual(dead_sections(_Config({"planning": {"lease_seconds": 99}})), [])

    def test_an_absent_section_is_not_reported(self) -> None:
        """Writing nothing is not a mistake. Only a section that was
        written and had no effect is worth a line."""
        self.assertEqual(dead_sections(_Config({})), [])
        self.assertEqual(dead_sections(_Config({"planning": {}})), [])

    def test_several_sections_are_each_reported(self) -> None:
        dead = dead_sections(_Config({
            "planning": {"lease_secs": 99},
            "persona": {"histry_limit": 3},
            "memory": {"nonsense": True},
        }))
        self.assertEqual(dead, ["memory", "persona", "planning"])

    def test_a_section_no_subsystem_owns_is_left_alone(self) -> None:
        """`[runtime]`, `[bus]` and `[ledger]` are the Kernel's own and
        are not parsed by any of these classes; reporting them would be
        a false alarm on every boot."""
        self.assertEqual(dead_sections(_Config({"runtime": {"mode": "local"}})), [])

    def test_an_unparseable_section_is_not_reported_here(self) -> None:
        """A value the parser rejects outright is that subsystem's to
        raise at its own boot. This must not turn it into a warning
        about a typo, and must not crash the boot it is checking."""
        self.assertEqual(dead_sections(_Config({"planning": {"lease_seconds": object()}})), [])


class TestTheWarning(unittest.TestCase):
    def test_it_names_the_section_and_where_to_look(self) -> None:
        logger = _Logger()
        dead = report(_Config({"planning": {"lease_secs": 99}}), logger)
        self.assertEqual(dead, ["planning"])
        self.assertEqual(len(logger.warnings), 1)
        event, fields = logger.warnings[0]
        self.assertEqual(fields["section"], "planning")
        self.assertIn("simorgh/planning/config.py", fields["detail"])

    def test_a_clean_config_says_nothing(self) -> None:
        logger = _Logger()
        report(_Config({"planning": {"lease_seconds": 99}}), logger)
        self.assertEqual(logger.warnings, [])


if __name__ == "__main__":
    unittest.main()
