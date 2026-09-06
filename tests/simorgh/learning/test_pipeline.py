import unittest

from simorgh.ledger.factory import make_ledger
from simorgh.learning.config import Config
from simorgh.learning.correlator import Correlator
from simorgh.learning.pipeline import PatchPipeline


class _Harness:
    """Drives a PatchPipeline with scripted responses per tool -- each
    fake resolves the correlator synchronously inside `propose_action`/
    `request_verify`, which works because `_propose_and_await`/
    `_verify_once` register the waiting Future *before* invoking the
    callback (see pipeline.py)."""

    def __init__(self, *, draft_results=None, verify_results=None, apply_ok=True, commit_ok=True,
                 activate_ok=True, revert_ok=True):
        self.published: list[tuple[str, dict]] = []
        self.proposed: list[dict] = []
        self._draft_results = list(draft_results or [{"ok": True, "output_ref": "blob:abc"}])
        self._verify_results = list(verify_results or [{"verdict": "pass", "checklist": [],
                                                          "trajectory": {"steps": 1, "wasted": 0, "recovered_errors": 0},
                                                          "mechanical": {"baseline": 10, "patched": 10}}])
        self.apply_ok = apply_ok
        self.commit_ok = commit_ok
        self.activate_ok = activate_ok
        self.revert_ok = revert_ok
        self.action_correlator = Correlator(id_field="action_id")
        self.verify_correlator = Correlator(id_field="verification_id")

    async def publish(self, type_, payload):
        self.published.append((type_, payload))

    async def propose_action(self, *, action_id, tool, args, scope, reversibility, rationale, task_id):
        self.proposed.append({"action_id": action_id, "tool": tool, "args": args})
        if tool in ("self_patch.draft", "skill.draft"):
            result = dict(self._draft_results.pop(0))
        elif tool in ("apply_source_patch", "apply_skill"):
            result = {"ok": self.apply_ok, "output_ref": "", "stdout_preview": "", "duration_ms": 1, "side_effects": []}
        elif tool == "git_commit":
            result = {"ok": self.commit_ok, "output_ref": "", "stdout_preview": "abc123" if self.commit_ok else "", "duration_ms": 1, "side_effects": []}
        elif tool in ("hot_swap", "relaunch"):
            result = {"ok": self.activate_ok, "output_ref": "", "stdout_preview": "", "duration_ms": 1, "side_effects": []}
        elif tool == "git_revert_range":
            result = {"ok": self.revert_ok, "output_ref": "", "stdout_preview": "", "duration_ms": 1, "side_effects": []}
        else:
            raise AssertionError(f"unexpected tool {tool!r}")
        payload = {"action_id": action_id, **{k: v for k, v in result.items() if k != "ok"}, "ok": result["ok"]}
        if not result["ok"] and "error" in result:
            payload["error"] = result["error"]
        self.action_correlator.resolve(payload)

    async def request_verify(self, *, verification_id, task_id, kind, subject_ref, checklist_hint):
        result = dict(self._verify_results.pop(0))
        payload = {"verification_id": verification_id, "task_id": task_id, **result}
        self.verify_correlator.resolve(payload)

    def pipeline(self, *, task_id="t1", kind="patch", subject="src/memory/x.py", config=None, ledger=None,
                 prior_reasons=None):
        return PatchPipeline(
            task_id=task_id, kind=kind, description="add recency weighting", subject=subject,
            prior_reasons=prior_reasons or [], config=config or Config(), ledger=ledger,
            clock=lambda: 1000.0, propose_action=self.propose_action, request_verify=self.request_verify,
            action_correlator=self.action_correlator, verify_correlator=self.verify_correlator,
            publish=self.publish,
        )


async def _memory_ledger():
    ledger = make_ledger({"backend": "memory"})
    await ledger.start()
    return ledger


class TestPatchPipelineHappyPath(unittest.IsolatedAsyncioTestCase):
    async def test_clean_patch_applies_commits_and_activates(self):
        h = _Harness()
        ledger = await _memory_ledger()
        result = await h.pipeline(ledger=ledger).run()

        self.assertEqual(result["outcome"], "applied")
        self.assertEqual(result["commit"], "abc123")
        tools = [p["tool"] for p in h.proposed]
        self.assertEqual(tools, ["self_patch.draft", "apply_source_patch", "git_commit", "relaunch"])
        types = [t for t, _ in h.published]
        self.assertIn("learn.self_patch.applied", types)
        self.assertIn("learn.pipeline.completed", types)

    async def test_hot_swap_slot_uses_hot_swap_not_relaunch(self):
        h = _Harness()
        ledger = await _memory_ledger()
        result = await h.pipeline(ledger=ledger, subject="logic").run()

        self.assertEqual(result["outcome"], "applied")
        self.assertIn("hot_swap", [p["tool"] for p in h.proposed])

    async def test_skill_pipeline_never_activates(self):
        h = _Harness()
        ledger = await _memory_ledger()
        result = await h.pipeline(ledger=ledger, kind="skill", subject="simorgh_skills/x.py").run()

        self.assertEqual(result["outcome"], "applied")
        tools = [p["tool"] for p in h.proposed]
        self.assertEqual(tools, ["skill.draft", "apply_skill", "git_commit"])
        self.assertIn("learn.skill.acquired", [t for t, _ in h.published])


class TestPatchPipelineRetry(unittest.IsolatedAsyncioTestCase):
    async def test_a_failed_verify_retries_with_feedback_then_succeeds(self):
        h = _Harness(verify_results=[
            {"verdict": "fail", "checklist": [], "trajectory": {"steps": 1, "wasted": 0, "recovered_errors": 0},
             "mechanical": {}, "feedback": {"items": [{"what": "docstring", "why": "docstring dropped", "suggested_fix": "keep it"}]}},
            {"verdict": "pass", "checklist": [], "trajectory": {"steps": 1, "wasted": 0, "recovered_errors": 0},
             "mechanical": {"baseline": 5, "patched": 5}},
        ], draft_results=[{"ok": True, "output_ref": "blob:1"}, {"ok": True, "output_ref": "blob:2"}])
        ledger = await _memory_ledger()
        result = await h.pipeline(ledger=ledger).run()

        self.assertEqual(result["outcome"], "applied")
        draft_calls = [p for p in h.proposed if p["tool"] == "self_patch.draft"]
        self.assertEqual(len(draft_calls), 2)
        self.assertIn("docstring dropped", draft_calls[1]["args"]["prior_reasons"])

    async def test_exhausting_all_attempts_is_rejected(self):
        h = _Harness(verify_results=[
            {"verdict": "fail", "checklist": [], "trajectory": {"steps": 1, "wasted": 0, "recovered_errors": 0}, "mechanical": {}},
        ] * 3, draft_results=[{"ok": True, "output_ref": f"blob:{i}"} for i in range(3)])
        ledger = await _memory_ledger()
        result = await h.pipeline(ledger=ledger, config=Config(max_draft_attempts=3)).run()

        self.assertEqual(result["outcome"], "rejected")
        self.assertIn("3 attempt(s)", result["detail"])
        draft_calls = [p for p in h.proposed if p["tool"] == "self_patch.draft"]
        self.assertEqual(len(draft_calls), 3)

    async def test_a_draft_failure_retries_using_the_error_as_feedback(self):
        h = _Harness(draft_results=[
            {"ok": False, "error": "invalid Python"},
            {"ok": True, "output_ref": "blob:2"},
        ])
        ledger = await _memory_ledger()
        result = await h.pipeline(ledger=ledger).run()

        self.assertEqual(result["outcome"], "applied")
        draft_calls = [p for p in h.proposed if p["tool"] == "self_patch.draft"]
        self.assertEqual(len(draft_calls), 2)
        self.assertIn("invalid Python", draft_calls[1]["args"]["prior_reasons"])

    async def test_insufficient_evidence_gets_one_bounded_reverify_not_a_redraft(self):
        h = _Harness(verify_results=[
            {"verdict": "insufficient_evidence", "checklist": [], "trajectory": {"steps": 1, "wasted": 0, "recovered_errors": 0}, "mechanical": {}},
            {"verdict": "pass", "checklist": [], "trajectory": {"steps": 1, "wasted": 0, "recovered_errors": 0}, "mechanical": {}},
        ])
        ledger = await _memory_ledger()
        result = await h.pipeline(ledger=ledger).run()

        self.assertEqual(result["outcome"], "applied")
        draft_calls = [p for p in h.proposed if p["tool"] == "self_patch.draft"]
        self.assertEqual(len(draft_calls), 1)  # a non-answer never charges a redraft


class TestPatchPipelineDenialAndFailure(unittest.IsolatedAsyncioTestCase):
    async def test_a_denied_draft_is_rejected_without_retry(self):
        h = _Harness()

        async def deny(*, action_id, tool, args, scope, reversibility, rationale, task_id):
            h.action_correlator.resolve({"action_id": action_id, "reasons": ["protected subject"], "layer": "protected", "denied": True})

        h.propose_action = deny
        ledger = await _memory_ledger()
        result = await h.pipeline(ledger=ledger).run()

        self.assertEqual(result["outcome"], "rejected")
        self.assertIn("denied", result["detail"])

    async def test_activation_failure_reverts_and_records_reverted(self):
        h = _Harness(activate_ok=False)
        ledger = await _memory_ledger()
        result = await h.pipeline(ledger=ledger).run()

        self.assertEqual(result["outcome"], "reverted")
        self.assertIn("git_revert_range", [p["tool"] for p in h.proposed])
        self.assertIn("learn.self_patch.reverted", [t for t, _ in h.published])
        self.assertNotIn("learn.self_patch.applied", [t for t, _ in h.published])

    async def test_apply_failure_is_rejected_without_committing(self):
        h = _Harness(apply_ok=False)
        ledger = await _memory_ledger()
        result = await h.pipeline(ledger=ledger).run()

        self.assertEqual(result["outcome"], "rejected")
        self.assertNotIn("git_commit", [p["tool"] for p in h.proposed])


class TestPatchPipelineTimeoutAndCheckpoints(unittest.IsolatedAsyncioTestCase):
    async def test_a_draft_action_that_never_resolves_times_out_and_is_rejected(self):
        h = _Harness()

        async def never_resolve(**kwargs):
            h.proposed.append({"action_id": kwargs["action_id"], "tool": kwargs["tool"], "args": kwargs["args"]})
            # deliberately never resolves the correlator

        h.propose_action = never_resolve
        ledger = await _memory_ledger()
        result = await h.pipeline(ledger=ledger, config=Config(action_timeout_seconds=0.01)).run()

        self.assertEqual(result["outcome"], "rejected")
        self.assertIn("timed out", result["detail"])

    async def test_every_transition_is_checkpointed_to_its_own_stream(self):
        h = _Harness()
        ledger = await _memory_ledger()
        await h.pipeline(ledger=ledger, task_id="t9").run()

        events = await ledger.read("learn:patch:t9", limit=None)
        types = [e.type for e in events]
        self.assertEqual(types[0], "started")
        self.assertEqual(types[-1], "finished")
        self.assertIn("draft_result", types)
        self.assertIn("verify_result", types)

    async def test_patch_kind_requires_a_subject(self):
        h = _Harness()
        with self.assertRaises(ValueError):
            h.pipeline(subject=None)


if __name__ == "__main__":
    unittest.main()
