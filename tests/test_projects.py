import unittest

from src.cognition.provider import CognitionRouter, LLMResponse
from src.memory.long_term import InMemoryStore
from src.orchestrator.projects import (
    decompose_project,
    next_unfinished_child,
    parse_project_steps,
    project_status,
)
from src.orchestrator.tasks import (
    BLOCKED,
    DONE,
    FAILED,
    IN_PROGRESS,
    PATCH_TASK,
    PENDING,
    RESEARCH_TASK,
    TaskStore,
)


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


class TestParseProjectSteps(unittest.TestCase):
    def test_parses_a_patch_line(self):
        steps = parse_project_steps("1. src/orchestrator/foo.py :: fix the thing", 1)

        self.assertEqual(steps, [(PATCH_TASK, "src/orchestrator/foo.py", "fix the thing")])

    def test_parses_a_research_line(self):
        steps = parse_project_steps("1. RESEARCH :: is this worth doing", 1)

        self.assertEqual(steps, [(RESEARCH_TASK, None, "is this worth doing")])

    def test_research_line_is_not_misparsed_as_a_patch_to_a_file_named_research(self):
        steps = parse_project_steps("1. RESEARCH :: a question", 1)

        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0][0], RESEARCH_TASK)

    def test_mixed_lines_parse_in_order(self):
        text = (
            "1. RESEARCH :: figure out the right approach\n"
            "2. src/memory/long_term.py :: implement it\n"
        )

        steps = parse_project_steps(text, 2)

        self.assertEqual(steps[0][0], RESEARCH_TASK)
        self.assertEqual(steps[1], (PATCH_TASK, "src/memory/long_term.py", "implement it"))

    def test_skills_dir_targets_are_excluded(self):
        steps = parse_project_steps("1. src/agents/skills/rocketry.py :: add a skill", 1)

        self.assertEqual(steps, [])

    def test_non_matching_lines_are_ignored(self):
        text = "Sure, here's my plan:\n1. src/orchestrator/foo.py :: do it\nHope that helps!"

        steps = parse_project_steps(text, 1)

        self.assertEqual(steps, [(PATCH_TASK, "src/orchestrator/foo.py", "do it")])

    def test_truncates_to_expected_count(self):
        text = "\n".join(f"{i}. src/a.py :: idea {i}" for i in range(1, 6))

        self.assertEqual(len(parse_project_steps(text, 3)), 3)


class TestDecomposeProject(unittest.TestCase):
    def setUp(self):
        self.store = TaskStore(InMemoryStore())
        self.project = self.store.add("build a better memory system", "project")

    def test_no_real_provider_returns_no_children(self):
        children = decompose_project(CognitionRouter(), self.store, self.project, files=[])

        self.assertEqual(children, [])
        self.assertEqual(self.store.children(self.project.id), [])

    def test_creates_children_linked_to_the_project(self):
        provider = FakeProvider(
            "1. RESEARCH :: what approach fits best\n"
            "2. src/memory/long_term.py :: add the chosen approach\n"
        )
        cognition = CognitionRouter([provider])

        children = decompose_project(cognition, self.store, self.project, files=["src/memory/long_term.py"])

        self.assertEqual(len(children), 2)
        self.assertTrue(all(c.parent_id == self.project.id for c in children))
        self.assertEqual(children[0].kind, RESEARCH_TASK)
        self.assertEqual(children[1].kind, PATCH_TASK)
        self.assertEqual(children[1].subject, "src/memory/long_term.py")

    def test_a_protected_subject_step_is_skipped(self):
        provider = FakeProvider(
            "1. src/orchestrator/self_patch.py :: rewrite the whole pipeline\n"
            "2. src/memory/long_term.py :: a reachable step\n"
        )
        cognition = CognitionRouter([provider])

        children = decompose_project(cognition, self.store, self.project, files=[])

        self.assertEqual(len(children), 1)
        self.assertEqual(children[0].subject, "src/memory/long_term.py")

    def test_prompt_includes_the_goal_and_file_listing(self):
        provider = FakeProvider("1. src/a.py :: idea\n")
        cognition = CognitionRouter([provider])

        decompose_project(cognition, self.store, self.project, files=["src/a.py", "src/b.py"])

        self.assertIn("build a better memory system", provider.prompts[0])
        self.assertIn("src/a.py", provider.prompts[0])
        self.assertIn("src/b.py", provider.prompts[0])


def _task(store, status, kind=PATCH_TASK, parent_id=None):
    task = store.add("step", kind, discovered_via="project", parent_id=parent_id)
    store.update_status(task.id, status)
    return store.get(task.id)


class TestProjectStatus(unittest.TestCase):
    def test_no_children_is_pending(self):
        self.assertEqual(project_status([]), PENDING)

    def test_all_done_children_is_done(self):
        store = TaskStore(InMemoryStore())
        children = [_task(store, DONE), _task(store, DONE)]

        self.assertEqual(project_status(children), DONE)

    def test_all_terminal_but_one_failed_is_failed(self):
        store = TaskStore(InMemoryStore())
        children = [_task(store, DONE), _task(store, FAILED)]

        self.assertEqual(project_status(children), FAILED)

    def test_any_in_progress_child_is_in_progress(self):
        store = TaskStore(InMemoryStore())
        children = [_task(store, DONE), _task(store, IN_PROGRESS)]

        self.assertEqual(project_status(children), IN_PROGRESS)

    def test_some_done_some_pending_is_in_progress_not_pending(self):
        store = TaskStore(InMemoryStore())
        children = [_task(store, DONE), _task(store, PENDING)]

        self.assertEqual(project_status(children), IN_PROGRESS)

    def test_blocked_with_no_progress_is_blocked(self):
        store = TaskStore(InMemoryStore())
        children = [_task(store, BLOCKED), _task(store, PENDING)]

        self.assertEqual(project_status(children), BLOCKED)

    def test_all_pending_is_pending(self):
        store = TaskStore(InMemoryStore())
        children = [_task(store, PENDING), _task(store, PENDING)]

        self.assertEqual(project_status(children), PENDING)


class TestNextUnfinishedChild(unittest.TestCase):
    def test_returns_the_first_non_terminal_child(self):
        store = TaskStore(InMemoryStore())
        done = _task(store, DONE)
        pending = _task(store, PENDING)

        self.assertEqual(next_unfinished_child([done, pending]).id, pending.id)

    def test_returns_none_when_every_child_is_terminal(self):
        store = TaskStore(InMemoryStore())
        children = [_task(store, DONE), _task(store, FAILED)]

        self.assertIsNone(next_unfinished_child(children))

    def test_blocked_counts_as_unfinished(self):
        store = TaskStore(InMemoryStore())
        blocked = _task(store, BLOCKED)

        self.assertEqual(next_unfinished_child([blocked]).id, blocked.id)


if __name__ == "__main__":
    unittest.main()
