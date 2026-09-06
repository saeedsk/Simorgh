import unittest

from src.cognition.provider import CognitionRouter, LLMResponse
from src.orchestrator.tasks import PATCH_TASK, Task
from src.orchestrator.verification import verify_task_completion


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


def _task(description="fix the thing"):
    return Task(
        id="abc123",
        description=description,
        kind=PATCH_TASK,
        subject="src/x.py",
        status="in_progress",
        discovered_via="user",
        created_at=0.0,
        updated_at=0.0,
    )


class TestVerifyTaskCompletion(unittest.TestCase):
    def test_yes_answer_passes(self):
        cognition = CognitionRouter([FakeProvider("YES\nThis directly fixes the bug.")])

        result = verify_task_completion(cognition, _task(), "[APPLIED] fixed it")

        self.assertTrue(result.passed)

    def test_no_answer_fails(self):
        cognition = CognitionRouter([FakeProvider("NO\nThis doesn't address the task at all.")])

        result = verify_task_completion(cognition, _task(), "[APPLIED] unrelated change")

        self.assertFalse(result.passed)

    def test_case_insensitive_yes(self):
        cognition = CognitionRouter([FakeProvider("yes, looks right")])

        result = verify_task_completion(cognition, _task(), "[APPLIED] fixed it")

        self.assertTrue(result.passed)

    def test_a_rambling_answer_that_never_states_a_verdict_defers_to_true(self):
        # Live-caught: Claude Code CLI narrated instead of answering
        # ("I'll check the actual file that was modified to verify the
        # claim.\n\n{}") and wrongly BLOCKed an already-correct,
        # already-tested, already-committed self-patch. A non-answer must
        # never be read as a NO.
        cognition = CognitionRouter(
            [FakeProvider("I'll check the actual file that was modified to verify the claim.\n\n{}")]
        )

        result = verify_task_completion(cognition, _task(), "[APPLIED] fixed it")

        self.assertTrue(result.passed)
        self.assertIn("didn't contain a clear YES/NO verdict", result.explanation)

    def test_a_verdict_that_appears_after_narration_is_still_honored(self):
        cognition = CognitionRouter(
            [FakeProvider("Let me think about this.\nNO\nThis is an unrelated change.")]
        )

        result = verify_task_completion(cognition, _task(), "[APPLIED] unrelated change")

        self.assertFalse(result.passed)

    def test_no_real_provider_defers_to_true(self):
        cognition = CognitionRouter()  # deterministic fallback only

        result = verify_task_completion(cognition, _task(), "[APPLIED] fixed it")

        self.assertTrue(result.passed)
        self.assertIn("no real reviewer", result.explanation)

    def test_prompt_includes_task_description_and_result(self):
        provider = FakeProvider("YES\nok")
        cognition = CognitionRouter([provider])

        verify_task_completion(cognition, _task("fix the scheduler bug"), "[APPLIED] scheduler.py")

        self.assertIn("fix the scheduler bug", provider.prompts[0])
        self.assertIn("scheduler.py", provider.prompts[0])


if __name__ == "__main__":
    unittest.main()
