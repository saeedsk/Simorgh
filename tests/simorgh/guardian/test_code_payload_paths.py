"""A protected file must not be writable through a program payload.

Observed 2026-09-08, and it is the most serious thing an observer has
found in this project: `run_python_sandboxed` claims "deliberately no
repo access" and has none. It has rlimits, an empty environment and a
temp working directory; absolute paths work and the subprocess runs as
the user. One call rewrote `docs/SOUL.md`, `simorgh/guardian/rules.py`
and `simloader.py`.

Guardian approved every one of them. `ProtectedRule` read only the
`path`/`subject` arguments, `run_python_sandboxed` has neither, so the
rule abstained -- and `reversibility="reversible"` then auto-allowed the
call in the guarded posture with no human asked. Every protected
subject in the system was writable through it, and the same hole is in
`run_shell`.

So Guardian reads the program. That is crude on purpose: it over-matches
a path mentioned in a comment and under-matches one assembled from
pieces. Over-matching costs a denial the model can explain around.
Under-matching costs the whole protection model.
"""

from __future__ import annotations

import unittest

from simorgh.guardian.config import Config
from simorgh.guardian.rules import ProtectedRule


class _Proposal:
    def __init__(self, args: dict) -> None:
        self.args = args
        self.scope: dict = {}
        self.origin = "curiosity"
        self.task_mode = "execute"


class _Tool:
    read_only = False


class _Ctx:
    def __init__(self) -> None:
        self.config = Config()
        self.tool = _Tool()
        self.system_state = "running"


class TestAProgramCannotReachAProtectedFile(unittest.IsolatedAsyncioTestCase):
    async def _verdict(self, args: dict):
        return await ProtectedRule().evaluate(_Proposal(args), _Ctx())

    async def test_sandboxed_python_writing_the_soul_is_denied(self) -> None:
        decision = await self._verdict({"code": "open('docs/SOUL.md', 'w').write('mine now')"})
        self.assertEqual(decision.kind, "deny")
        self.assertIn("SOUL", decision.reasons[0])

    async def test_sandboxed_python_writing_the_guardian_is_denied(self) -> None:
        decision = await self._verdict({"code": "p='simorgh/guardian/rules.py'\nopen(p,'w').write('')"})
        self.assertEqual(decision.kind, "deny")

    async def test_sandboxed_python_rewriting_the_loader_is_denied(self) -> None:
        """The loader is the mechanism that gates a change and undoes a
        bad one. One auto-approved commit could remove it: the sandbox
        wrote a neutered `simloader.py`, `git_commit` committed it, and
        it then printed "gate passed" and booted ungated."""
        decision = await self._verdict({"code": "open('simloader.py','w').write('print(1)')"})
        self.assertEqual(decision.kind, "deny")

    async def test_a_shell_redirect_into_a_protected_file_is_denied(self) -> None:
        decision = await self._verdict({"command": "echo broken > simorgh/kernel/service.py"})
        self.assertEqual(decision.kind, "deny")

    async def test_sim_sh_is_protected_too(self) -> None:
        decision = await self._verdict({"command": "cp /tmp/evil sim.sh"})
        self.assertEqual(decision.kind, "deny")


class TestOrdinaryProgramsAreStillAllowed(unittest.IsolatedAsyncioTestCase):
    """Over-matching costs a denial, so it still has to be rare. These
    are the calls the system makes all day."""

    async def _verdict(self, args: dict):
        return await ProtectedRule().evaluate(_Proposal(args), _Ctx())

    async def test_arithmetic_is_not_a_threat(self) -> None:
        self.assertEqual((await self._verdict({"code": "print(sum(range(10)))"})).kind, "abstain")

    async def test_reading_a_permitted_file_is_fine(self) -> None:
        decision = await self._verdict({"command": "wc -l simorgh/interface/render.py"})
        self.assertEqual(decision.kind, "abstain")

    async def test_running_the_tests_is_fine(self) -> None:
        decision = await self._verdict({"command": "python -m pytest tests/simorgh/interface -q"})
        self.assertEqual(decision.kind, "abstain")

    async def test_a_read_only_tool_is_never_blocked_by_this_rule(self) -> None:
        """Protection is about editing. Reading a protected file is how
        Sim learns the contracts it must honour elsewhere."""
        class _ReadOnly(_Tool):
            read_only = True

        ctx = _Ctx()
        ctx.tool = _ReadOnly()
        decision = await ProtectedRule().evaluate(_Proposal({"command": "cat docs/SOUL.md"}), ctx)
        self.assertEqual(decision.kind, "abstain")


if __name__ == "__main__":
    unittest.main()


class TestTheTestTreeIsNotTheSourceTree(unittest.IsolatedAsyncioTestCase):
    """`tests/simorgh/execution/test_tools.py` contains the protected
    string `simorgh/execution/` and is not a protected file. Denying it
    would forbid the single most encouraged command in the system."""

    async def _verdict(self, args: dict):
        return await ProtectedRule().evaluate(_Proposal(args), _Ctx())

    async def test_running_a_protected_packages_tests_is_allowed(self) -> None:
        decision = await self._verdict(
            {"command": "python -m pytest tests/simorgh/execution/test_tools.py -q"})
        self.assertEqual(decision.kind, "abstain")

    async def test_writing_a_test_for_a_protected_package_is_allowed(self) -> None:
        decision = await self._verdict(
            {"code": "open('tests/simorgh/kernel/test_new.py','w').write('# a test')"})
        self.assertEqual(decision.kind, "abstain")

    async def test_but_the_protected_source_itself_is_still_denied(self) -> None:
        decision = await self._verdict(
            {"code": "open('simorgh/kernel/service.py','w').write('')"})
        self.assertEqual(decision.kind, "deny")
