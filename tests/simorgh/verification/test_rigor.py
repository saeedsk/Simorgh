"""`select_rigor` -- `max(by_kind, by_reversibility)`, clamped by a
forced-rigor override (docs/blueprint/subsystems/10-verification.md
section 5.2)."""

import os
import unittest
from unittest import mock

from simorgh.verification.api import Rigor, VerifyRequest
from simorgh.verification.config import VerificationConfig
from simorgh.verification.rigor import select_rigor


def _req(kind="task", reversibility="reversible") -> VerifyRequest:
    return VerifyRequest(verification_id="v1", task_id="t1", kind=kind, subject={}, reversibility=reversibility)


class TestSelectRigor(unittest.TestCase):
    def setUp(self):
        self.config = VerificationConfig()

    def test_chat_kind_alone_is_none_but_reversibility_can_raise_it(self):
        # by_kind[chat]=NONE, but no reversibility maps to NONE in the
        # default table -- read_only's LIGHT wins via max().
        self.assertEqual(self.config.rigor_by_kind["chat"], Rigor.NONE)
        self.assertEqual(select_rigor(_req(kind="chat", reversibility="read_only"), self.config), Rigor.LIGHT)

    def test_self_patch_read_only_takes_the_higher_of_the_two(self):
        # by_kind[self_patch]=FULL, by_reversibility[read_only]=LIGHT -> FULL wins
        self.assertEqual(select_rigor(_req(kind="self_patch", reversibility="read_only"), self.config), Rigor.FULL)

    def test_research_irreversible_takes_the_higher_of_the_two(self):
        # by_kind[research]=LIGHT, by_reversibility[irreversible]=FULL -> FULL wins
        self.assertEqual(select_rigor(_req(kind="research", reversibility="irreversible"), self.config), Rigor.FULL)

    def test_plan_reversible_is_standard(self):
        self.assertEqual(select_rigor(_req(kind="plan", reversibility="reversible"), self.config), Rigor.STANDARD)

    def test_unknown_kind_and_reversibility_default_to_standard(self):
        self.assertEqual(select_rigor(_req(kind="mystery", reversibility="mystery"), self.config), Rigor.STANDARD)

    def test_forced_rigor_overrides_everything(self):
        config = VerificationConfig(forced_rigor=Rigor.NONE)
        self.assertEqual(select_rigor(_req(kind="self_patch", reversibility="irreversible"), config), Rigor.NONE)

    def test_forced_rigor_from_env_var(self):
        with mock.patch.dict(os.environ, {"SIMORGH_VERIFICATION_RIGOR": "light"}):
            config = VerificationConfig.from_mapping({})
        self.assertEqual(select_rigor(_req(kind="self_patch", reversibility="irreversible"), config), Rigor.LIGHT)


if __name__ == "__main__":
    unittest.main()
