"""When the suite check cannot tell whose failures they are, it says so.

A red whole-suite run is not automatically the change's fault: the
check tries to ATTRIBUTE the failures, and passes the change when
every failing test already fails at the session's base revision. When
that attribution cannot run it returns "no opinion" and the check
falls back to "the whole suite was run and it FAILED -- the change is
not checked until the suite passes".

That fallback is true and useless. In a repo whose suite is already
red it is an impossible bar, and from the outside there is no way to
tell whether attribution was never attempted or attempted and gave
up. The kill-and-resume drill spent 23 steps against that message on
2026-09-20, and reading four source files was the only way to narrow
it down. The reason is on the result now.
"""

import unittest

from simorgh.verification.checks import fullsuiteran


class Asyncio(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _req(**subject):
        class _Req:
            pass

        req = _Req()
        req.subject = dict(subject)
        return req

    async def test_no_base_ref_says_so(self):
        why: dict = {}
        out = await fullsuiteran._attribution(self._req(), [], why)
        self.assertIsNone(out)
        self.assertIn("base_ref", why["no_attribution"])

    async def test_no_written_paths_says_so(self):
        why: dict = {}
        out = await fullsuiteran._attribution(self._req(base_ref="abc123"), [], why)
        self.assertIsNone(out)
        self.assertIn("written paths", why["no_attribution"])

    async def test_the_reason_is_a_sentence_a_person_can_act_on(self):
        """Not a code. Whoever reads this is deciding whether to change
        the task or the checker."""
        why: dict = {}
        await fullsuiteran._attribution(self._req(), [], why)
        reason = why["no_attribution"]
        self.assertGreater(len(reason.split()), 4, reason)
        self.assertEqual(reason, reason.strip())

    async def test_without_the_dict_it_behaves_exactly_as_before(self):
        """The parameter is optional: every existing caller and test
        passes two arguments and must keep working."""
        self.assertIsNone(await fullsuiteran._attribution(self._req(), []))


if __name__ == "__main__":
    unittest.main()
