"""`simorgh/worldmodel/selfmodel.py`'s dynamic-section mutators (Phase 4
roadmap item 6: "competence per task type, calibration, limitations,
open questions"; `docs/blueprint/subsystems/06-worldmodel.md` section 5's
ingestion-rules table). The end-to-end wiring through a real `Service`
and Kernel -- events in, `SELF.md` re-rendered on disk -- is
`tests/simorgh/integration/test_self_model_completeness.py`; this file
covers each pure mutator's own merge/dedupe/bounding logic in isolation.
"""

from __future__ import annotations

import unittest

from simorgh.worldmodel.selfmodel import (
    Identity,
    SelfModel,
    add_change,
    add_limitation,
    add_skill,
    bump_restarts,
    mitigate_limitations,
    render_summary,
    update_competence,
    update_goals,
)


def _model(**overrides) -> SelfModel:
    identity = Identity(name="Simorgh", soul_sha256="abc123", directives=(), summary="a test persona")
    defaults = dict(version=1, updated_at=0.0, identity=identity)
    defaults.update(overrides)
    return SelfModel(**defaults)


class TestIdentityRendering(unittest.TestCase):
    """Live-caught: rendered as plain descriptive text ("I am X"), the
    identity section was never strong enough to override a real
    provider's own default identity -- asked directly, it said it was
    Claude Code, not Simorgh. This is delivered as a real system prompt
    now (cognition/service.py, ClaudeCodeProvider's --system-prompt),
    but the wording itself must also be a direct instruction to respond
    in character, not a fact being reported."""

    def test_identity_section_is_a_direct_instruction_not_a_bare_fact(self):
        text, _tokens = render_summary(_model(), budget_tokens=300)
        self.assertIn("You are Simorgh.", text)
        self.assertIn("Respond fully in character as Simorgh", text)
        self.assertIn("never break character", text)
        self.assertIn("a test persona", text)  # the identity summary itself still comes through

    def test_identity_instruction_explicitly_names_the_underlying_model_it_must_not_default_to(self):
        text, _tokens = render_summary(_model(), budget_tokens=300)
        self.assertIn("Claude Code", text)


class TestUpdateCompetence(unittest.TestCase):
    def test_learn_competence_updated_sets_rate_samples_calibration(self):
        model = update_competence(_model(), "patch", updated_at=10.0, success_rate=0.71, samples=58, calibration=0.8)
        entry = model.competence["patch"]
        self.assertEqual(entry["success_rate"], 0.71)
        self.assertEqual(entry["samples"], 58)
        self.assertEqual(entry["calibration"], 0.8)
        self.assertEqual(model.updated_at, 10.0)

    def test_reflect_calibration_updated_merges_into_the_same_entry(self):
        model = update_competence(_model(), "patch", updated_at=1.0, success_rate=0.71, samples=58)
        model = update_competence(model, "patch", updated_at=2.0, stated_confidence=0.9, empirical_accuracy=0.71)
        entry = model.competence["patch"]
        self.assertEqual(entry["success_rate"], 0.71)  # earlier field survives the second, narrower update
        self.assertEqual(entry["stated_confidence"], 0.9)
        self.assertEqual(entry["empirical_accuracy"], 0.71)

    def test_overconfident_flag_set_when_stated_exceeds_empirical_by_more_than_a_tenth(self):
        model = update_competence(_model(), "patch", updated_at=1.0, stated_confidence=0.9, empirical_accuracy=0.71)
        self.assertTrue(model.competence["patch"]["overconfident"])

    def test_not_overconfident_when_within_a_tenth(self):
        model = update_competence(_model(), "patch", updated_at=1.0, stated_confidence=0.75, empirical_accuracy=0.71)
        self.assertFalse(model.competence["patch"]["overconfident"])

    def test_independent_task_types_do_not_clobber_each_other(self):
        model = update_competence(_model(), "patch", updated_at=1.0, success_rate=0.9, samples=5)
        model = update_competence(model, "research", updated_at=2.0, success_rate=0.5, samples=2)
        self.assertEqual(model.competence["patch"]["success_rate"], 0.9)
        self.assertEqual(model.competence["research"]["success_rate"], 0.5)


class TestAddLimitation(unittest.TestCase):
    def test_new_limitation_gets_an_id_and_open_status(self):
        model = add_limitation(_model(), text="full-file rewrites over 100 lines rarely parse", evidence=["ep#1"], since=5.0, updated_at=5.0)
        [lim] = model.limitations
        self.assertEqual(lim["id"], "lim-1")
        self.assertEqual(lim["status"], "open")
        self.assertEqual(lim["evidence"], ["ep#1"])

    def test_fuzzy_duplicate_merges_evidence_instead_of_appending(self):
        model = add_limitation(_model(), text="full-file rewrites over 100 lines rarely parse", evidence=["ep#1"], since=5.0, updated_at=5.0)
        model = add_limitation(model, text="full-file rewrites over 100 lines rarely produce valid python", evidence=["ep#2"], since=6.0, updated_at=6.0)
        self.assertEqual(len(model.limitations), 1)
        self.assertEqual(set(model.limitations[0]["evidence"]), {"ep#1", "ep#2"})

    def test_unrelated_text_is_a_second_entry(self):
        model = add_limitation(_model(), text="full-file rewrites over 100 lines rarely parse", evidence=[], since=5.0, updated_at=5.0)
        model = add_limitation(model, text="review verdicts sometimes narrate instead of answering", evidence=[], since=6.0, updated_at=6.0)
        self.assertEqual(len(model.limitations), 2)


class TestMitigateLimitations(unittest.TestCase):
    def test_open_limitation_naming_the_subject_becomes_mitigated(self):
        model = add_limitation(_model(), text="src/orchestrator/retry.py has flaky retries", evidence=[], since=1.0, updated_at=1.0)
        model = mitigate_limitations(model, subject="src/orchestrator/retry.py", updated_at=2.0)
        self.assertEqual(model.limitations[0]["status"], "mitigated")

    def test_limitation_not_naming_the_subject_is_untouched(self):
        model = add_limitation(_model(), text="review verdicts sometimes narrate", evidence=[], since=1.0, updated_at=1.0)
        model = mitigate_limitations(model, subject="src/orchestrator/retry.py", updated_at=2.0)
        self.assertEqual(model.limitations[0]["status"], "open")

    def test_empty_subject_is_a_no_op(self):
        base = add_limitation(_model(), text="x", evidence=[], since=1.0, updated_at=1.0)
        result = mitigate_limitations(base, subject="", updated_at=2.0)
        self.assertIs(result, base)


class TestAddChange(unittest.TestCase):
    def test_appends_an_entry_with_the_given_fields(self):
        model = add_change(_model(), ts=1.0, kind="self_patch", summary="added jitter", updated_at=1.0, subject="s.py", commit="abc")
        [entry] = model.change_history
        self.assertEqual(entry["kind"], "self_patch")
        self.assertEqual(entry["subject"], "s.py")
        self.assertEqual(entry["commit"], "abc")

    def test_bounded_history_drops_the_oldest(self):
        model = _model()
        for i in range(210):
            model = add_change(model, ts=float(i), kind="self_patch", summary=f"change {i}", updated_at=float(i))
        self.assertLessEqual(len(model.change_history), 200)
        self.assertEqual(model.change_history[-1]["summary"], "change 209")


class TestUpdateGoals(unittest.TestCase):
    """Live-caught (post-cutover review): the World Model never consumed
    `task.*` events, so `goals.pending_tasks` was a constant 0 -- right
    after `propose` created a real task, a chat "show your tasks" was
    answered from this line: "queue is completely clear"."""

    def test_created_task_is_counted_as_pending(self):
        model = update_goals(_model(), updated_at=1.0, task_id="t1", kind="skill", status="pending",
                             description="outcome feedback skill", area="learning")
        self.assertEqual(model.goals["pending_tasks"], 1)
        self.assertEqual(model.goals["recent_focus_areas"], ["learning"])
        self.assertIn("1 pending task(s)", render_summary(model, budget_tokens=400)[0])

    def test_completed_or_failed_task_leaves_the_pending_count(self):
        model = update_goals(_model(), updated_at=1.0, task_id="t1", kind="skill", status="pending")
        model = update_goals(model, updated_at=2.0, task_id="t2", kind="patch", status="pending")
        model = update_goals(model, updated_at=3.0, task_id="t1", status="completed")
        self.assertEqual(model.goals["pending_tasks"], 1)
        model = update_goals(model, updated_at=4.0, task_id="t2", status="failed")
        self.assertEqual(model.goals["pending_tasks"], 0)

    def test_blocked_task_is_still_outstanding(self):
        model = update_goals(_model(), updated_at=1.0, task_id="t1", kind="research", status="pending")
        model = update_goals(model, updated_at=2.0, task_id="t1", status="blocked")
        self.assertEqual(model.goals["pending_tasks"], 1)

    def test_project_kind_is_also_an_active_project_until_done(self):
        model = update_goals(_model(), updated_at=1.0, task_id="p1", kind="project", status="pending",
                             description="make memory self-correcting")
        self.assertEqual([p["project_id"] for p in model.goals["active_projects"]], ["p1"])
        self.assertIn("1 active project(s)", render_summary(model, budget_tokens=400)[0])
        model = update_goals(model, updated_at=2.0, task_id="p1", status="completed")
        self.assertEqual(model.goals["active_projects"], [])

    def test_replaying_the_same_event_is_a_no_op(self):
        base = update_goals(_model(), updated_at=1.0, task_id="t1", kind="skill", status="pending", description="x")
        again = update_goals(base, updated_at=2.0, task_id="t1", kind="skill", status="pending", description="x")
        self.assertIs(again, base)
        done = update_goals(base, updated_at=3.0, task_id="t1", status="completed")
        self.assertIs(update_goals(done, updated_at=4.0, task_id="t1", status="completed"), done)


class TestAddSkillAndRestarts(unittest.TestCase):
    def test_add_skill_appends_and_replaces_by_name(self):
        model = add_skill(_model(), name="github_skill", tests=4, updated_at=1.0)
        model = add_skill(model, name="github_skill", tests=6, updated_at=2.0)  # re-acquired with more tests
        skills = model.capabilities["skills"]
        self.assertEqual(len(skills), 1)
        self.assertEqual(skills[0]["tests"], 6)

    def test_bump_restarts_sets_the_count(self):
        model = bump_restarts(_model(), restarts=3, updated_at=9.0)
        self.assertEqual(model.continuity["restarts"], 3)
        self.assertEqual(model.updated_at, 9.0)


if __name__ == "__main__":
    unittest.main()
