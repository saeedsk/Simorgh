"""Sim should know what is thinking for it.

Live-caught, 2026-09-07. Asked "which llm model are you using?", Sim
answered: "Honestly, I don't know -- and that's not me being coy ... the
cognition layer that actually does the thinking doesn't expose its model
name to me." That was accurate. `SelfModel.capabilities["providers"]` was
declared when the self model was written, populated by nobody, and
rendered by no section, so its own cognition backend was the single fact
about itself Sim could not see.
"""

from __future__ import annotations

import unittest

from simorgh.worldmodel.selfmodel import Identity, SelfModel, render_summary


def _model(providers: list[dict] | None = None, **fields) -> SelfModel:
    model = SelfModel(
        version=1, updated_at=0.0,
        identity=Identity(name="Simorgh", soul_sha256="", directives=(), summary="I am Simorgh."),
        **fields,
    )
    # `SelfModel` is frozen; its dicts are not. Mutating `capabilities` in
    # place is exactly how the WorldModel service records this.
    if providers is not None:
        model.capabilities["providers"] = providers
    return model


def _summary(providers: list[dict] | None) -> str:
    return render_summary(_model(providers), 4000)[0]


class TestTheSubstrateSection(unittest.TestCase):
    def test_the_selected_provider_and_its_model_are_named(self):
        text = _summary([
            {"name": "together", "model": "zai-org/GLM-5.3-Flash", "available": True, "selected": True},
        ])
        self.assertIn("together", text)
        self.assertIn("zai-org/GLM-5.3-Flash", text)

    def test_the_others_are_listed_as_configured_not_as_answering(self):
        text = _summary([
            {"name": "together", "model": "zai-org/GLM-5.3-Flash", "available": True, "selected": True},
            {"name": "gemini", "model": "gemini-3.8-flash", "available": True, "selected": False},
        ])
        line = next(l for l in text.splitlines() if l.startswith("Thinking with"))
        self.assertLess(line.index("together"), line.index("Also configured"))
        self.assertGreater(line.index("gemini"), line.index("Also configured"))

    def test_an_unavailable_provider_says_so(self):
        text = _summary([
            {"name": "together", "model": "m", "available": True, "selected": True},
            {"name": "gemini", "model": "gemini-3.8-flash", "available": False, "selected": False},
        ])
        self.assertIn("[unavailable]", text)

    def test_a_provider_with_no_model_name_is_still_named(self):
        """The `claude` CLI picks its own model from the caller's
        subscription, so this provider names none. It must not vanish."""
        text = _summary([{"name": "claude_code_cli", "model": "", "available": True, "selected": True}])
        self.assertIn("claude_code_cli", text)

    def test_nothing_is_claimed_before_any_status_has_arrived(self):
        """Silence beats a guess: until Cognition has broadcast, the
        summary says nothing about the substrate at all."""
        text = _summary(None)
        self.assertNotIn("Thinking with", text)

    def test_it_sits_directly_after_identity(self):
        """"Which model are you" is a question about who is answering, so
        it belongs next to who Sim is, not at the end behind truncation."""
        text = _summary([{"name": "together", "model": "m", "available": True, "selected": True}])
        lines = text.splitlines()
        self.assertTrue(lines[1].startswith("Thinking with"), lines[:3])

    def test_it_survives_a_tight_token_budget(self):
        model = _model(
            [{"name": "together", "model": "zai-org/GLM-5.3-Flash", "available": True, "selected": True}],
            competence={"patch": {"success_rate": 0.5, "samples": 4}},
            open_questions=[{"text": "q" * 500}],
        )
        text, _ = render_summary(model, 80)
        self.assertIn("Thinking with", text)


if __name__ == "__main__":
    unittest.main()
