"""Stage 4 item 7: the agents are files. Each profile round-trips through
agents/<name>.md, the scaffold text lives there once, notes never reach
the prompt, and Guardian protects the folder."""

import tempfile
import unittest
from pathlib import Path

from simorgh.orchestration import profiles, scaffolds
from simorgh.orchestration.tools import offered_tools


class TheFiles(unittest.TestCase):
    def test_the_six_agents_load(self):
        self.assertEqual(set(profiles.AGENTS), {"chat", "voice_chat", "patch", "research", "plan", "skill"})
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
