import unittest

from src.agents.logic.base import LogicAgent
from src.cognition.provider import CognitionRouter, LLMResponse, ProviderUnavailable
from src.memory.long_term import InMemoryStore
from src.memory.short_term import ShortTermMemory
from src.memory.shared_bus import SharedMemoryBus
from src.orchestrator.activity_log import ActivityLog
from src.orchestrator.persona_state import PersonaState
from src.orchestrator.router import AgentRequest
from src.sandboxing.sandbox import SandboxResult
from src.tools.web_fetch import WebFetchTool


class FakeProvider:
    def __init__(self, name="fake", text="a real llm reply", raises=None):
        self.name = name
        self._text = text
        self._raises = raises
        self.prompts = []

    def available(self):
        return True

    def complete(self, prompt, **kwargs):
        self.prompts.append(prompt)
        if self._raises is not None:
            raise self._raises
        return LLMResponse(text=self._text, provider_name=self.name)


class ScriptedProvider:
    """Returns each of `responses` (a list of (text, provider_name) pairs)
    in order across successive complete() calls, repeating the last one if
    called more times than scripted.
    """

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


class FakeSandbox:
    def __init__(self, result: SandboxResult):
        self._result = result
        self.calls: list[str] = []

    def run(self, code, timeout=None):
        self.calls.append(code)
        return self._result


def _fake_web_fetch(opener, resolver):
    return WebFetchTool(InMemoryStore(), opener=opener, resolver=resolver)


class TestLogicAgent(unittest.TestCase):
    def test_default_mood_gives_plain_framing(self):
        agent = LogicAgent()
        bus = SharedMemoryBus()

        response = agent.handle(AgentRequest(text="what's the weather"), bus)

        self.assertEqual(response.output, "Here's my take: what's the weather")

    def test_negative_high_arousal_mood_gives_calming_framing(self):
        state = PersonaState()
        state.set_state(valence=-0.8, arousal=0.8)
        bus = SharedMemoryBus(state)
        agent = LogicAgent()

        response = agent.handle(AgentRequest(text="everything is broken"), bus)

        self.assertTrue(response.output.startswith("Let's slow down"))

    def test_positive_high_arousal_mood_gives_energetic_framing(self):
        state = PersonaState()
        state.set_state(valence=0.8, arousal=0.8)
        bus = SharedMemoryBus(state)
        agent = LogicAgent()

        response = agent.handle(AgentRequest(text="let's ship it"), bus)

        self.assertTrue(response.output.startswith("Let's dive right in"))

    def test_high_cognitive_load_gives_focused_framing(self):
        state = PersonaState()
        state.set_state(cognitive_load=0.9)
        bus = SharedMemoryBus(state)
        agent = LogicAgent()

        response = agent.handle(AgentRequest(text="one more thing"), bus)

        self.assertTrue(response.output.startswith("Focusing carefully here"))

    def test_raises_cognitive_load_after_handling(self):
        bus = SharedMemoryBus()
        agent = LogicAgent()

        agent.handle(AgentRequest(text="hi"), bus)

        self.assertAlmostEqual(bus.read().cognitive_load, 0.05)


class TestLogicAgentWithCognition(unittest.TestCase):
    def test_uses_llm_response_when_a_real_provider_answers(self):
        fake = FakeProvider(text="Hi! Great to hear from you.")
        agent = LogicAgent(cognition=CognitionRouter([fake]))
        bus = SharedMemoryBus()

        response = agent.handle(AgentRequest(text="hello"), bus)

        self.assertEqual(response.output, "Hi! Great to hear from you.")
        self.assertEqual(response.metadata["source"], "llm")

    def test_falls_back_to_rule_based_when_provider_raises(self):
        fake = FakeProvider(raises=ProviderUnavailable("down"))
        agent = LogicAgent(cognition=CognitionRouter([fake]))
        bus = SharedMemoryBus()

        response = agent.handle(AgentRequest(text="hello"), bus)

        self.assertEqual(response.output, "Here's my take: hello")
        self.assertEqual(response.metadata["source"], "rule_based")

    def test_falls_back_to_rule_based_when_only_the_deterministic_floor_answers(self):
        # CognitionRouter() with no real providers -> deterministic_fallback
        agent = LogicAgent(cognition=CognitionRouter())
        bus = SharedMemoryBus()

        response = agent.handle(AgentRequest(text="hello"), bus)

        self.assertEqual(response.output, "Here's my take: hello")
        self.assertEqual(response.metadata["source"], "rule_based")

    def test_prompt_includes_persona_and_mood(self):
        fake = FakeProvider()
        agent = LogicAgent(cognition=CognitionRouter([fake]))
        bus = SharedMemoryBus()

        agent.handle(AgentRequest(text="hello"), bus)

        prompt = fake.prompts[0]
        self.assertIn("Sim", prompt)
        self.assertIn("valence", prompt)
        self.assertIn("hello", prompt)

    def test_prompt_includes_recent_history_when_short_term_given(self):
        fake = FakeProvider()
        short_term = ShortTermMemory()
        short_term.add("what's your name", "I'm Sim.")
        agent = LogicAgent(cognition=CognitionRouter([fake]), short_term=short_term)
        bus = SharedMemoryBus()

        agent.handle(AgentRequest(text="nice to meet you"), bus)

        prompt = fake.prompts[0]
        self.assertIn("what's your name", prompt)
        self.assertIn("I'm Sim.", prompt)

    def test_without_cognition_behaves_exactly_as_before(self):
        agent = LogicAgent()
        bus = SharedMemoryBus()

        response = agent.handle(AgentRequest(text="hello"), bus)

        self.assertEqual(response.output, "Here's my take: hello")
        self.assertEqual(response.metadata["source"], "rule_based")


class FakeHTTPResponse:
    def __init__(self, status, data):
        self.status = status
        self._data = data

    def read(self, n):
        return self._data[:n]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _fake_opener(response=None, exception=None):
    def opener(request, timeout=None):
        if exception is not None:
            raise exception
        return response

    return opener


def _fake_resolver(ip="93.184.216.34"):
    import socket

    def resolver(host, port):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    return resolver


class TestLogicAgentToolLoop(unittest.TestCase):
    def test_fetch_tool_retries_after_failure_and_uses_final_answer(self):
        web_fetch = WebFetchTool(
            InMemoryStore(),
            resolver=_fake_resolver(),
            opener=_fake_opener(exception=TimeoutError("first url failed")),
        )
        provider = ScriptedProvider(
            [
                ("FETCH: https://bad.example", None),
                ("Couldn't get that one, but here's the answer anyway.", None),
            ]
        )
        agent = LogicAgent(cognition=CognitionRouter([provider]), web_fetch=web_fetch)
        bus = SharedMemoryBus()

        response = agent.handle(AgentRequest(text="get me that page"), bus)

        self.assertEqual(response.output, "Couldn't get that one, but here's the answer anyway.")
        self.assertEqual(len(provider.prompts), 2)
        self.assertIn("FAILED", provider.prompts[1])

    def test_fetch_tool_success_is_reported_back(self):
        web_fetch = WebFetchTool(
            InMemoryStore(),
            resolver=_fake_resolver(),
            opener=_fake_opener(response=FakeHTTPResponse(200, b"hello page")),
        )
        provider = ScriptedProvider(
            [
                ("FETCH: https://good.example", None),
                ("Got it -- here's a summary.", None),
            ]
        )
        agent = LogicAgent(cognition=CognitionRouter([provider]), web_fetch=web_fetch)
        bus = SharedMemoryBus()

        response = agent.handle(AgentRequest(text="get me that page"), bus)

        self.assertEqual(response.output, "Got it -- here's a summary.")
        self.assertIn("hello page", provider.prompts[1])

    def test_fetch_marker_not_offered_without_web_fetch_configured(self):
        provider = FakeProvider(text="a plain reply")
        agent = LogicAgent(cognition=CognitionRouter([provider]))  # no web_fetch

        agent.handle(AgentRequest(text="hello"), SharedMemoryBus())

        self.assertNotIn("FETCH:", provider.prompts[0])

    def test_run_tool_reports_result_and_continues(self):
        sandbox = FakeSandbox(
            SandboxResult(stdout="4\n", stderr="", exit_code=0, timed_out=False, duration_seconds=0.01)
        )
        provider = ScriptedProvider(
            [
                ("RUN: print(2 + 2)", None),
                ("The answer is 4.", None),
            ]
        )
        agent = LogicAgent(cognition=CognitionRouter([provider]), sandbox=sandbox)
        bus = SharedMemoryBus()

        response = agent.handle(AgentRequest(text="what's 2+2"), bus)

        self.assertEqual(response.output, "The answer is 4.")
        self.assertEqual(len(sandbox.calls), 1)
        self.assertIn("4", provider.prompts[1])

    def test_run_tool_narration_summarizes_actual_stdout_not_the_literal_header(self):
        import contextlib
        import io

        sandbox = FakeSandbox(
            SandboxResult(
                stdout="42 files found\nmore stuff\n",
                stderr="",
                exit_code=0,
                timed_out=False,
                duration_seconds=0.01,
            )
        )
        provider = ScriptedProvider([("RUN: find_files()", None), ("done", None)])
        agent = LogicAgent(cognition=CognitionRouter([provider]), sandbox=sandbox)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            agent.handle(AgentRequest(text="find things"), SharedMemoryBus())

        self.assertIn("run result: 42 files found", buf.getvalue())
        self.assertNotIn("run result: stdout:", buf.getvalue())

    def test_run_tool_narration_says_no_output_for_empty_stdout(self):
        import contextlib
        import io

        sandbox = FakeSandbox(
            SandboxResult(stdout="", stderr="", exit_code=0, timed_out=False, duration_seconds=0.01)
        )
        provider = ScriptedProvider([("RUN: pass", None), ("done", None)])
        agent = LogicAgent(cognition=CognitionRouter([provider]), sandbox=sandbox)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            agent.handle(AgentRequest(text="run something quiet"), SharedMemoryBus())

        self.assertIn("run result: (no output)", buf.getvalue())

    def test_read_tool_available_even_with_no_fetch_or_sandbox(self):
        provider = FakeProvider(text="a plain reply")
        agent = LogicAgent(cognition=CognitionRouter([provider]))

        agent.handle(AgentRequest(text="hello"), SharedMemoryBus())

        self.assertIn("READ:", provider.prompts[0])

    def test_loop_exhausting_max_tool_steps_forces_a_final_answer_instead_of_rule_based(self):
        # Previously the last step silently discarded whatever the model
        # said and fell back to a generic rule-based echo, wasting every
        # prior tool call. Now the last step is told no more tools will
        # be honored, and whatever text comes back is used verbatim --
        # even here, where a deliberately unhelpful scripted provider
        # keeps "asking" for a tool right up to the last turn.
        provider = ScriptedProvider([("READ: src/main.py", None)] * 10)
        agent = LogicAgent(cognition=CognitionRouter([provider]), max_tool_steps=3)
        bus = SharedMemoryBus()

        response = agent.handle(AgentRequest(text="hello"), bus)

        self.assertEqual(len(provider.prompts), 3)
        self.assertEqual(response.metadata["source"], "llm")
        self.assertEqual(response.output, "READ: src/main.py")

    def test_final_turn_prompt_tells_the_model_no_more_tools_will_be_honored(self):
        provider = ScriptedProvider([("READ: src/main.py", None), ("final answer", None)])
        agent = LogicAgent(cognition=CognitionRouter([provider]), max_tool_steps=2)

        agent.handle(AgentRequest(text="hello"), SharedMemoryBus())

        self.assertIn("last turn", provider.prompts[1].lower())

    def test_final_turn_produces_a_real_answer_using_what_was_learned(self):
        provider = ScriptedProvider(
            [
                ("READ: src/main.py", None),
                ("Based on what I found, yes, that exists.", None),
            ]
        )
        agent = LogicAgent(cognition=CognitionRouter([provider]), max_tool_steps=2)

        response = agent.handle(AgentRequest(text="does X exist?"), SharedMemoryBus())

        self.assertEqual(response.output, "Based on what I found, yes, that exists.")
        self.assertEqual(response.metadata["source"], "llm")

    def test_no_tools_configured_still_works_via_final_answer(self):
        provider = FakeProvider(text="a real llm reply")
        agent = LogicAgent(cognition=CognitionRouter([provider]))

        response = agent.handle(AgentRequest(text="hello"), SharedMemoryBus())

        self.assertEqual(response.output, "a real llm reply")
        self.assertEqual(response.metadata["source"], "llm")

    def test_recall_marker_not_offered_without_activity_log_configured(self):
        provider = FakeProvider(text="a plain reply")
        agent = LogicAgent(cognition=CognitionRouter([provider]))

        agent.handle(AgentRequest(text="hello"), SharedMemoryBus())

        self.assertNotIn("RECALL:", provider.prompts[0])

    def test_recall_tool_returns_recent_activity_and_continues(self):
        store = InMemoryStore()
        activity_log = ActivityLog(store)
        activity_log.record_conversation_turn("earlier prompt", "earlier reply")
        provider = ScriptedProvider(
            [("RECALL:", None), ("final answer after recalling", None)]
        )
        agent = LogicAgent(cognition=CognitionRouter([provider]), activity_log=activity_log)

        response = agent.handle(AgentRequest(text="how did that go?"), SharedMemoryBus())

        self.assertEqual(len(provider.prompts), 2)
        self.assertIn("earlier prompt", provider.prompts[1])
        self.assertEqual(response.output, "final answer after recalling")

    def test_recall_tool_records_itself_as_a_tool_call(self):
        store = InMemoryStore()
        activity_log = ActivityLog(store)
        provider = ScriptedProvider([("RECALL:", None), ("final answer", None)])
        agent = LogicAgent(cognition=CognitionRouter([provider]), activity_log=activity_log)

        agent.handle(AgentRequest(text="hello"), SharedMemoryBus())

        tool_calls = store.query(kind="tool_call")
        self.assertEqual(len(tool_calls), 1)
        self.assertEqual(tool_calls[0].metadata["tool"], "RECALL")

    def test_recall_tool_with_no_activity_recorded_yet_says_so(self):
        store = InMemoryStore()
        activity_log = ActivityLog(store)
        provider = ScriptedProvider([("RECALL:", None), ("final answer", None)])
        agent = LogicAgent(cognition=CognitionRouter([provider]), activity_log=activity_log)

        agent.handle(AgentRequest(text="hello"), SharedMemoryBus())

        self.assertIn("nothing recorded yet", provider.prompts[1])

    def test_remind_marker_is_always_offered(self):
        # No activity_log, web_fetch, or sandbox given -- REMIND still
        # shows up, unlike FETCH/RUN/RECALL which are conditional.
        provider = FakeProvider(text="a plain reply")
        agent = LogicAgent(cognition=CognitionRouter([provider]))

        agent.handle(AgentRequest(text="hello"), SharedMemoryBus())

        self.assertIn("REMIND:", provider.prompts[0])

    def test_remind_tool_schedules_and_reports_success(self):
        provider = ScriptedProvider([("REMIND: 1m wake up", None), ("done", None)])
        agent = LogicAgent(cognition=CognitionRouter([provider]))

        response = agent.handle(AgentRequest(text="remind me to wake up in a minute"), SharedMemoryBus())

        self.assertIn("scheduled", provider.prompts[1])
        self.assertEqual(response.output, "done")

    def test_remind_tool_reports_an_invalid_duration(self):
        provider = ScriptedProvider([("REMIND: whenever wake up", None), ("done", None)])
        agent = LogicAgent(cognition=CognitionRouter([provider]))

        agent.handle(AgentRequest(text="hello"), SharedMemoryBus())

        self.assertIn("FAILED", provider.prompts[1])
        self.assertIn("isn't a valid duration", provider.prompts[1])

    def test_remind_tool_records_itself_as_a_tool_call(self):
        store = InMemoryStore()
        activity_log = ActivityLog(store)
        provider = ScriptedProvider([("REMIND: 1m wake up", None), ("done", None)])
        agent = LogicAgent(cognition=CognitionRouter([provider]), activity_log=activity_log)

        agent.handle(AgentRequest(text="hello"), SharedMemoryBus())

        tool_calls = store.query(kind="tool_call")
        self.assertEqual(len(tool_calls), 1)
        self.assertEqual(tool_calls[0].metadata["tool"], "REMIND")
        self.assertTrue(tool_calls[0].metadata["succeeded"])

    def test_propose_marker_not_offered_without_a_propose_fn(self):
        provider = FakeProvider(text="a plain reply")
        agent = LogicAgent(cognition=CognitionRouter([provider]))

        agent.handle(AgentRequest(text="add a rocketry skill"), SharedMemoryBus())

        self.assertNotIn("PROPOSE:", provider.prompts[0])

    def test_propose_tool_calls_the_injected_function_and_reports_result(self):
        calls = []
        provider = ScriptedProvider([("PROPOSE: rocketry", None), ("done", None)])
        agent = LogicAgent(
            cognition=CognitionRouter([provider]),
            propose_skill_fn=lambda topic: calls.append(topic) or "[APPLIED] src/agents/skills/rocketry.py",
        )

        response = agent.handle(AgentRequest(text="add a rocketry skill"), SharedMemoryBus())

        self.assertEqual(calls, ["rocketry"])
        self.assertIn("APPLIED", provider.prompts[1])
        self.assertEqual(response.output, "done")

    def test_patch_tool_calls_the_injected_function_with_path_and_description(self):
        calls = []
        provider = ScriptedProvider(
            [("PATCH: src/agents/logic/base.py handle 403s better", None), ("done", None)]
        )
        agent = LogicAgent(
            cognition=CognitionRouter([provider]),
            propose_patch_fn=lambda path, desc: calls.append((path, desc)) or "[APPLIED] ok",
        )

        agent.handle(AgentRequest(text="fix the 403 handling"), SharedMemoryBus())

        self.assertEqual(calls, [("src/agents/logic/base.py", "handle 403s better")])

    def test_patch_tool_reports_malformed_argument(self):
        provider = ScriptedProvider([("PATCH: onlyonetoken", None), ("done", None)])
        agent = LogicAgent(cognition=CognitionRouter([provider]), propose_patch_fn=lambda p, d: "unused")

        agent.handle(AgentRequest(text="fix something"), SharedMemoryBus())

        self.assertIn("FAILED", provider.prompts[1])

    def test_batch_tool_calls_the_injected_function_with_count_and_theme(self):
        calls = []
        provider = ScriptedProvider([("BATCH: 5 digital world skills", None), ("done", None)])
        agent = LogicAgent(
            cognition=CognitionRouter([provider]),
            propose_batch_fn=lambda theme, count: calls.append((theme, count)) or "[batch] 5/5 applied",
        )

        agent.handle(AgentRequest(text="add 5 digital world skills"), SharedMemoryBus())

        self.assertEqual(calls, [("digital world skills", 5)])

    def test_plan_tool_calls_the_injected_function_with_count_and_goal(self):
        calls = []
        provider = ScriptedProvider([("PLAN: 3 improve resilience", None), ("done", None)])
        agent = LogicAgent(
            cognition=CognitionRouter([provider]),
            plan_fn=lambda goal, count: calls.append((goal, count)) or "[plan] saved 3 steps",
        )

        agent.handle(AgentRequest(text="plan out resilience improvements"), SharedMemoryBus())

        self.assertEqual(calls, [("improve resilience", 3)])

    def test_evolve_marker_not_offered_without_an_evolve_fn(self):
        provider = FakeProvider(text="a plain reply")
        agent = LogicAgent(cognition=CognitionRouter([provider]))

        agent.handle(AgentRequest(text="evolve yourself"), SharedMemoryBus())

        self.assertNotIn("EVOLVE:", provider.prompts[0])

    def test_evolve_tool_calls_the_injected_function_with_goal_and_count(self):
        calls = []
        provider = ScriptedProvider([("EVOLVE: 3 improve resilience", None), ("done", None)])
        agent = LogicAgent(
            cognition=CognitionRouter([provider]),
            propose_evolve_fn=lambda goal, count: calls.append((goal, count))
            or "[evolve] 3/3 architectural change(s) applied",
        )

        agent.handle(AgentRequest(text="evolve yourself to be more resilient"), SharedMemoryBus())

        self.assertEqual(calls, [("improve resilience", 3)])

    def test_evolve_tool_reports_malformed_argument(self):
        provider = ScriptedProvider([("EVOLVE: notanumber goal", None), ("done", None)])
        agent = LogicAgent(cognition=CognitionRouter([provider]), propose_evolve_fn=lambda g, c: "unused")

        agent.handle(AgentRequest(text="evolve yourself"), SharedMemoryBus())

        self.assertIn("FAILED", provider.prompts[1])

    def test_evolve_tool_records_success_correctly(self):
        store = InMemoryStore()
        activity_log = ActivityLog(store)
        provider = ScriptedProvider([("EVOLVE: 2 resilience", None), ("done", None)])
        agent = LogicAgent(
            cognition=CognitionRouter([provider]),
            activity_log=activity_log,
            propose_evolve_fn=lambda g, c: "[evolve] 2/2 architectural change(s) applied",
        )

        agent.handle(AgentRequest(text="evolve yourself"), SharedMemoryBus())

        tool_calls = store.query(kind="tool_call")
        self.assertEqual(tool_calls[0].metadata["tool"], "EVOLVE")
        self.assertTrue(tool_calls[0].metadata["succeeded"])

    def test_evolve_tool_records_failure_when_nothing_applied(self):
        store = InMemoryStore()
        activity_log = ActivityLog(store)
        provider = ScriptedProvider([("EVOLVE: 2 resilience", None), ("done", None)])
        agent = LogicAgent(
            cognition=CognitionRouter([provider]),
            activity_log=activity_log,
            propose_evolve_fn=lambda g, c: "[evolve] 0/2 architectural change(s) applied",
        )

        agent.handle(AgentRequest(text="evolve yourself"), SharedMemoryBus())

        tool_calls = store.query(kind="tool_call")
        self.assertFalse(tool_calls[0].metadata["succeeded"])

    def test_propose_tool_records_itself_as_a_tool_call(self):
        store = InMemoryStore()
        activity_log = ActivityLog(store)
        provider = ScriptedProvider([("PROPOSE: rocketry", None), ("done", None)])
        agent = LogicAgent(
            cognition=CognitionRouter([provider]),
            activity_log=activity_log,
            propose_skill_fn=lambda topic: "[APPLIED] ok",
        )

        agent.handle(AgentRequest(text="add a skill"), SharedMemoryBus())

        tool_calls = store.query(kind="tool_call")
        self.assertEqual(len(tool_calls), 1)
        self.assertEqual(tool_calls[0].metadata["tool"], "PROPOSE")
        self.assertTrue(tool_calls[0].metadata["succeeded"])


if __name__ == "__main__":
    unittest.main()
