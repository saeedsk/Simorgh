"""`[growth]`'s own keys are named once, where growth reads them.

2026-09-29: switching on the paid propose and measure steps
(`propose_policies`, `measure_policies`, `held_out`) made Sim's config
check warn "nothing reads them" -- its list of growth keys stopped at
`nightly_usd` -- while growth/service.py read every one."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from simorgh.growth.night import TOP_LEVEL_KEYS

GROWTH = Path(__file__).resolve().parents[3] / "simorgh" / "growth"


class GrowthNamesTheKeysItReads(unittest.TestCase):
    def test_every_key_read_from_growth_is_named(self):
        read = set()
        for name in ("propose.py", "measure.py", "service.py"):
            text = (GROWTH / name).read_text(encoding="utf-8")
            read |= set(re.findall(r'section\.get\("([a-z_]+)"', text))
            read |= set(re.findall(r'\(config or \{\}\)\.get\("([a-z_]+)"', text))
        self.assertTrue(read, "the scan found nothing -- the pattern no longer matches the code")
        self.assertEqual(sorted(read - TOP_LEVEL_KEYS), [], "read but not named in TOP_LEVEL_KEYS")

    def test_the_config_check_does_not_call_them_unread(self):
        from simorgh.kernel.config import LoadedConfig
        from simorgh.kernel.configcheck import unknown_growth_keys

        config = LoadedConfig({"growth": {"propose_policies": True, "measure_policies": True,
                                          "held_out": {"patch": "code"}, "nightly_usd": 6.0,
                                          "propose_polices": True}}, None)
        self.assertEqual(unknown_growth_keys(config), ["propose_polices"], "a typo still warns")


if __name__ == "__main__":
    unittest.main()
