"""Stage 4 item 7: the agents are files. Each profile round-trips through
agents/<name>.md, the scaffold text lives there once, notes never reach
the prompt, and Guardian protects the folder."""

import tempfile
import unittest
from pathlib import Path

from simorgh.orchestration import profiles, scaffolds
from simorgh.orchestration.tools import offered_tools


class TheFiles(unittest.TestCase):
    def test_the_agents_load(self):
        self.assertEqual(set(profiles.AGENTS), {"chat", "voice_chat", "patch", "research", "plan", "skill",
                                                # the helper roles (stage 7 item 2)
                                                "planner", "verify", "skill-writer", "browser"})
        self.assertEqual(profiles.VOICE_CHAT.name, "chat", "a spoken chat is still a chat to the session")
        self.assertEqual(profiles.VOICE_CHAT.body, profiles.CHAT.body, "extends takes the body")
        self.assertEqual(profiles.VOICE_CHAT.max_steps, 6)
        self.assertIn("apply_source_patch", profiles.PATCH.tools)

    def test_notes_are_for_people(self):
        for agent in profiles.AGENTS.values():
            self.assertNotIn("<!--", agent.body)
            self.assertNotIn("<!--", scaffolds.render(agent, task="x"))

    def test_the_scaffold_text_is_the_file(self):
        self.assertIn(profiles.PATCH.body, scaffolds.render(profiles.PATCH, task="x"))
        self.assertIn(scaffolds.keyless_sources_block(), scaffolds.scaffold_body(profiles.RESEARCH))

    def test_a_bad_file_is_refused_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "x.md").write_text('+++\nname = "x"\nmodel_tier = "strong"\n+++\nbody\n')
            with self.assertRaises(profiles.AgentFileError) as caught:
                profiles.load(Path(tmp))
            self.assertIn("model_tier", str(caught.exception), "a key nothing reads is refused")
            Path(tmp, "x.md").write_text('+++\nname = "x"\nextends = "y"\n+++\n')
            Path(tmp, "y.md").write_text('+++\nname = "y"\nextends = "x"\n+++\n')
            with self.assertRaises(profiles.AgentFileError):
                profiles.load(Path(tmp))

    def test_extends_overrides_only_what_it_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "base.md").write_text('+++\nname = "b"\ntools = ["a"]\nread_only = true\nmax_steps = 3\n'
                                            'max_revisions = 0\nscaffold = "chat"\n+++\n<!-- why -->\nDo it.\n')
            Path(tmp, "kid.md").write_text('+++\nextends = "base"\nmax_steps = 9\n+++\n')
            agents = profiles.load(Path(tmp))
            self.assertEqual((agents["kid"].max_steps, agents["kid"].tools, agents["kid"].body), (9, ("a",), "Do it."))


class Globs(unittest.TestCase):
    def test_a_pattern_offers_the_matching_tools(self):
        offered = offered_tools(("read_file", "cam_*"))
        self.assertIn("read_file", offered)
        self.assertIn("cam_stream", offered)
        self.assertNotIn("cam_*", offered)


class Guarded(unittest.TestCase):
    def test_guardian_protects_the_folder(self):
        from simorgh.guardian.config import DEFAULT_PROTECTED_SUBJECTS

        self.assertIn("agents/", DEFAULT_PROTECTED_SUBJECTS)


if __name__ == "__main__":
    unittest.main()


class TheHelperRoles(unittest.TestCase):
    """Stage 7 item 2: the roles a task can spawn as helpers, each with a
    tool allowlist that is actually enforced."""

    def test_they_load_with_the_tools_they_are_allowed(self):
        agents = profiles.AGENTS
        self.assertEqual(set(agents) >= {"planner", "verify", "skill-writer", "browser"}, True)
        self.assertTrue(agents["verify"].read_only, "a checker that can change what it checks is not a checker")
        self.assertNotIn("apply_source_patch", agents["verify"].tools)
        self.assertIn("browse_page", agents["browser"].tools)
        self.assertNotIn("run_shell", agents["browser"].tools)
        self.assertEqual(agents["planner"].scaffold, "plan")
        self.assertEqual(agents["skill-writer"].scaffold, "skill")

    def test_the_verifier_is_not_itself_verified(self):
        """Verifying the verifier turns one yes-or-no into four calls."""
        self.assertFalse(profiles.AGENTS["verify"].verify)
        self.assertFalse(profiles.AGENTS["browser"].verify)

    def test_the_browser_is_told_what_it_may_not_press(self):
        body = profiles.AGENTS["browser"].body
        for rule in ("password", "one-time code", "place an order"):
            self.assertIn(rule, body)

    def test_the_verifier_may_answer_not_enough_evidence(self):
        self.assertIn("not enough evidence", profiles.AGENTS["verify"].body.lower())
