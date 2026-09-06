import tempfile
import unittest
from pathlib import Path

from src.cognition.provider import CognitionRouter, LLMResponse
from src.memory.long_term import InMemoryStore
from src.orchestrator.research_task import RESEARCH_FINDING_KIND, run_research_task
from src.orchestrator.tasks import PATCH_TASK, RESEARCH_TASK, TaskStore


class FakeProvider:
    def __init__(self, text, name="fake"):
        self.name = name
        self._text = text
        self.prompts = []

    def available(self):
        return True

    def complete(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return LLMResponse(text=self._text, provider_name=self.name)


class ScriptedProvider:
    def __init__(self, responses, name="scripted"):
        self.name = name
        self._responses = responses
        self.prompts = []

    def available(self):
        return True

    def complete(self, prompt, **kwargs):
        self.prompts.append(prompt)
        index = min(len(self.prompts) - 1, len(self._responses) - 1)
        text, provider_name = self._responses[index]
        return LLMResponse(text=text, provider_name=provider_name or self.name)


class TestRunResearchTask(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)
        (self.repo_root / "src" / "orchestrator").mkdir(parents=True)
        (self.repo_root / "src" / "orchestrator" / "other.py").write_text("OTHER = 1\n")
        self.store = InMemoryStore()
        self.task_store = TaskStore(self.store)
        self.task = self.task_store.add(
            "should Sim add vector-based memory search", RESEARCH_TASK
        )

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_no_real_provider_returns_none_recorded(self):
        result = run_research_task(
            CognitionRouter(), self.task, self.store, self.task_store, repo_root=self.repo_root
        )

        self.assertIn("no real reviewer", result)
        self.assertEqual(self.store.query(kind=RESEARCH_FINDING_KIND), [])

    def test_a_real_finding_is_recorded(self):
        provider = FakeProvider("Not worth it -- keyword search already covers this well.")
        cognition = CognitionRouter([provider])

        result = run_research_task(
            cognition, self.task, self.store, self.task_store, repo_root=self.repo_root
        )

        self.assertTrue(result.startswith("[RESEARCHED]"))
        findings = self.store.query(kind=RESEARCH_FINDING_KIND)
        self.assertEqual(len(findings), 1)
        self.assertIn("keyword search", findings[0].content)
        self.assertEqual(findings[0].metadata["task_id"], self.task.id)

    def test_a_follow_up_line_spawns_a_child_patch_task(self):
        provider = FakeProvider(
            "This is worth doing.\n"
            "FOLLOW-UP: src/memory/long_term.py :: add embedding-based retrieval"
        )
        cognition = CognitionRouter([provider])

        result = run_research_task(
            cognition, self.task, self.store, self.task_store, repo_root=self.repo_root
        )

        self.assertIn("spawned follow-up task", result)
        children = self.task_store.children(self.task.id)
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0].kind, PATCH_TASK)
        self.assertEqual(children[0].subject, "src/memory/long_term.py")

    def test_no_follow_up_line_spawns_nothing(self):
        provider = FakeProvider("Not worth pursuing further -- already covered.")
        cognition = CognitionRouter([provider])

        run_research_task(cognition, self.task, self.store, self.task_store, repo_root=self.repo_root)

        self.assertEqual(self.task_store.children(self.task.id), [])

    def test_a_protected_follow_up_target_is_not_spawned(self):
        provider = FakeProvider(
            "Worth doing.\nFOLLOW-UP: src/orchestrator/self_patch.py :: rewrite it"
        )
        cognition = CognitionRouter([provider])

        result = run_research_task(
            cognition, self.task, self.store, self.task_store, repo_root=self.repo_root
        )

        self.assertNotIn("spawned follow-up", result)
        self.assertEqual(self.task_store.children(self.task.id), [])

    def test_read_tool_pulls_in_context_before_concluding(self):
        provider = ScriptedProvider(
            [
                ("READ: src/orchestrator/other.py", None),
                ("Already covered by OTHER -- not worth duplicating.", None),
            ]
        )
        cognition = CognitionRouter([provider])

        result = run_research_task(
            cognition, self.task, self.store, self.task_store, repo_root=self.repo_root
        )

        self.assertIn("OTHER", provider.prompts[1])
        self.assertTrue(result.startswith("[RESEARCHED]"))

    def test_list_tool_is_available(self):
        provider = ScriptedProvider(
            [
                ("LIST: src/orchestrator", None),
                ("Confirmed nothing else touches this -- worth pursuing.", None),
            ]
        )
        cognition = CognitionRouter([provider])

        result = run_research_task(
            cognition, self.task, self.store, self.task_store, repo_root=self.repo_root
        )

        self.assertIn("other.py", provider.prompts[1])
        self.assertTrue(result.startswith("[RESEARCHED]"))

    def test_loop_is_bounded_by_max_tool_steps(self):
        from src.orchestrator.research_task import ResearchAgent

        provider = ScriptedProvider([("READ: src/orchestrator/other.py", None)] * 10)
        cognition = CognitionRouter([provider])
        agent = ResearchAgent(cognition, repo_root=self.repo_root, max_tool_steps=3)

        agent.run(self.task, self.store, self.task_store)

        self.assertEqual(len(provider.prompts), 3)

    def test_final_step_prompt_warns_no_more_tools(self):
        from src.orchestrator.research_task import ResearchAgent

        provider = ScriptedProvider([("READ: src/orchestrator/other.py", None)] * 10)
        cognition = CognitionRouter([provider])
        agent = ResearchAgent(cognition, repo_root=self.repo_root, max_tool_steps=2)

        agent.run(self.task, self.store, self.task_store)

        self.assertIn("last step", provider.prompts[-1])

    def test_activity_log_records_tool_calls(self):
        class FakeLog:
            def __init__(self):
                self.calls = []

            def record_tool_call(self, *args):
                self.calls.append(args)

        provider = ScriptedProvider(
            [("READ: src/orchestrator/other.py", None), ("A finding.", None)]
        )
        cognition = CognitionRouter([provider])
        log = FakeLog()
        from src.orchestrator.research_task import ResearchAgent

        agent = ResearchAgent(cognition, repo_root=self.repo_root, activity_log=log)
        agent.run(self.task, self.store, self.task_store)

        self.assertEqual(len(log.calls), 1)
        self.assertEqual(log.calls[0][0], "research")
        self.assertEqual(log.calls[0][1], "READ")


if __name__ == "__main__":
    unittest.main()
