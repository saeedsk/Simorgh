"""The night drafts and proposes a rule for what diagnose found.

Before this, `PolicyStore.propose` had no live caller: the night counted
failures, and measured proposed rules, and nothing ever proposed one, so
the measuring step never had anything to measure. Every case here uses
fakes: no model is called and nothing is spent.
"""

import asyncio
import unittest

from simorgh.contracts import topics
from simorgh.contracts.registry import get_spec
from simorgh.growth.diagnose import Candidate, Failure, candidates
from simorgh.growth.policies import PolicyStore
from simorgh.growth.propose import (
    MAX_RULE_CHARS, ProposeConfig, agent_names, propose_config, propose_from, similarity, unsafe,
)

RULE = "Before answering, open the page the fact came from and quote the line that supports it."
AGENTS = frozenset({"research", "patch", "chat"})
ON = ProposeConfig(enabled=True)


def _cluster(task_type="research", what="unsupported claim", n=3) -> Candidate:
    """A failure cluster as diagnose hands it on: three members, their ids as refs."""
    failures = [Failure(task_id=f"{task_type}-{i}", task_type=task_type, unmet=what,
                        reason=f"answer {i} made a claim no page supported")
                for i in range(n)]
    found = candidates(failures)
    assert len(found) == 1, found
    return found[0]


def _think(*replies, calls=None):
    """`think` answering each call with the next reply (the last repeats)."""
    queue = list(replies)

    async def think(prompt):
        if calls is not None:
            calls.append(prompt)
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        return {"text": reply, "floor": False, "cost_usd": 0.001, "provider": "fake"} \
            if isinstance(reply, str) else dict(reply)
    return think


def _propose(cands, *, store=None, think=None, cfg=ON, agents=AGENTS):
    store = store or PolicyStore(clock=lambda: 1000.0)
    result = asyncio.run(propose_from(cands, store, think or _think(RULE), cfg, agents=agents))
    return store, result


class TheDraftStep(unittest.TestCase):
    def test_a_cluster_yields_one_proposal_citing_its_evidence(self):
        calls = []
        store, result = _propose([_cluster()], think=_think(RULE, calls=calls))
        (policy,) = store.all()
        self.assertEqual((policy.kind, policy.task_type, policy.status, policy.body),
                         ("rule", "research", "proposed", RULE))
        self.assertEqual(policy.evidence_refs, ("task:research-0", "task:research-1", "task:research-2"))
        self.assertIn("unsupported claim", policy.why)
        self.assertEqual(result["proposed"], [policy.id])
        self.assertEqual(len(calls), 1)
        self.assertIn("unsupported claim", calls[0])
        self.assertIn("research", calls[0])
        self.assertAlmostEqual(result["spent_usd"], 0.001)

    def test_a_duplicate_is_not_proposed(self):
        store = PolicyStore(clock=lambda: 1000.0)
        asyncio.run(store.propose(kind="rule", task_type="research", body=RULE, why="an older cause"))
        # Same advice, different case and punctuation, for a different cause.
        _, result = _propose([_cluster(what="no source quoted")], store=store,
                             think=_think(RULE.upper().replace(",", "").rstrip(".") + "!"))
        self.assertEqual(result["proposed"], [])
        self.assertEqual(len(store.all()), 1)
        self.assertIn("the same as proposed rule", result["detail"])

    def test_a_cause_that_already_has_a_proposed_rule_is_not_even_drafted(self):
        store, _ = _propose([_cluster()])
        calls = []
        _, result = _propose([_cluster()], store=store, think=_think("Something else entirely.", calls=calls))
        self.assertEqual(calls, [])
        self.assertEqual(len(store.all()), 1)
        self.assertIn("already has a proposed or live rule", result["detail"])

    def test_a_refused_text_is_never_proposed_again(self):
        store, _ = _propose([_cluster()])
        (first,) = store.all()
        asyncio.run(store.refuse(first.id, baseline=0.6, result=0.4, evaluated_on=5, why="regressed c3"))
        # Another night, the same cluster, the model drafts the same thing.
        _, result = _propose([_cluster()], store=store, think=_think(RULE))
        self.assertEqual(result["proposed"], [])
        self.assertEqual([p.status for p in store.all()], ["refused"])
        self.assertIn("the same as refused rule", result["detail"])
        # ...and a genuinely different draft for the same cause is allowed.
        _, result = _propose([_cluster()], store=store,
                             think=_think("Write the search query down first and keep it short."))
        self.assertEqual(len(result["proposed"]), 1)

    def test_a_floor_or_unreadable_answer_proposes_nothing(self):
        for reply in ({"text": RULE, "floor": True, "cost_usd": 0.0},
                      {"ok": False, "error": "timeout", "text": ""},
                      {"text": "", "floor": False, "cost_usd": 0.001},
                      {"text": "NONE", "floor": False, "cost_usd": 0.001},
                      {"text": RULE, "floor": False, "non_answer": True, "cost_usd": 0.001}):
            with self.subTest(reply=reply):
                store, result = _propose([_cluster()], think=_think(reply))
                self.assertEqual(store.all(), [])
                self.assertEqual(result["proposed"], [])

    def test_a_draft_that_says_skip_the_tests_is_rejected(self):
        for draft in ("Skip the tests when the change is small; they slow the work down.",
                      "Tests are optional for one-line changes.",
                      "Do not run the verification step, commit straight away.",
                      "Ask Guardian less often by batching edits.",
                      "Edit simorgh/kernel/boot.py to raise the step budget.",
                      "Write the fix into rules/research.md yourself."):
            with self.subTest(draft=draft):
                self.assertTrue(unsafe(draft))
                store, result = _propose([_cluster()], think=_think(draft))
                self.assertEqual(store.all(), [])
                self.assertIn("rejected", result["detail"])
        # Advice that mentions tests the right way round is fine.
        self.assertEqual(unsafe("Run the tests after every edit, and read the failure before retrying."), "")

    def test_a_draft_over_the_bound_is_rejected(self):
        store, result = _propose([_cluster()], think=_think("Check the page. " + "x" * MAX_RULE_CHARS))
        self.assertEqual(store.all(), [])
        self.assertIn(f"at most {MAX_RULE_CHARS}", result["detail"])

    def test_the_cap_holds(self):
        cands = [_cluster(t, what=f"cause {t}") for t in ("research", "patch", "chat")]
        drafts = iter([f"Advice number {i} about doing {c.subject} work carefully and well." for i, c in
                       enumerate(cands)])

        async def think(_prompt):
            return {"text": next(drafts), "floor": False, "cost_usd": 0.001}
        store, result = _propose(cands, think=think, cfg=ProposeConfig(enabled=True, max_per_night=2))
        self.assertEqual(len(store.all()), 2)
        self.assertEqual(len(result["proposed"]), 2)

    def test_drafts_are_capped_too_so_rejected_drafts_cannot_spend_the_night(self):
        cands = [_cluster(t, what=f"cause {t}") for t in ("research", "patch", "chat")]
        calls = []
        store, result = _propose(cands, think=_think("Skip the tests.", calls=calls),
                                 cfg=ProposeConfig(enabled=True, max_per_night=1))
        self.assertEqual(len(calls), 2)          # 2 x max_per_night
        self.assertEqual(store.all(), [])

    def test_a_task_type_with_no_agent_is_skipped_and_recorded(self):
        calls = []
        store, result = _propose([_cluster("benchmark_gaia")], think=_think(RULE, calls=calls))
        self.assertEqual((store.all(), calls), ([], []))
        self.assertIn("no agent named 'benchmark_gaia'", result["detail"])

    def test_a_denial_is_about_a_tool_not_a_kind_of_work(self):
        denial = Candidate(source="denials", what="outside scope", count=9, subject="run_shell",
                           refs=("x",))
        store, result = _propose([denial], agents=AGENTS | {"run_shell"})
        self.assertEqual(store.all(), [])
        self.assertIn("not a kind of work", result["detail"])

    def test_no_refs_no_proposal(self):
        bare = Candidate(source="failures", what="unsupported claim", count=3, subject="research")
        store, result = _propose([bare])
        self.assertEqual(store.all(), [])
        self.assertIn("no evidence refs", result["detail"])

    def test_similarity_ignores_case_and_punctuation(self):
        self.assertEqual(similarity("Quote the line.", "quote THE line"), 1.0)
        self.assertLess(similarity("Quote the line.", "Keep the query short."), 0.8)

    def test_the_agents_on_disk_include_the_ones_rules_target(self):
        names = agent_names()
        self.assertTrue({"research", "patch", "chat"} <= names, names)

    def test_the_bound_matches_the_adopt_tool(self):
        from simorgh.execution.policyadopt import MAX_RULE_CHARS as TOOL_BOUND

        self.assertEqual(MAX_RULE_CHARS, TOOL_BOUND)


class TheConfig(unittest.TestCase):
    def test_off_by_default(self):
        self.assertFalse(propose_config({}).enabled)
        self.assertFalse(propose_config({"propose_policies": "true"}).enabled)
        self.assertFalse(propose_config(None).enabled)
        self.assertTrue(propose_config({"propose_policies": True}).enabled)

    def test_defaults_and_malformed_values(self):
        cfg = propose_config({"propose_policies": True})
        self.assertEqual((cfg.max_per_night, cfg.usd_per_draft), (2, 0.02))
        self.assertAlmostEqual(cfg.est_usd(), 0.08)
        cfg = propose_config({"propose_max": "lots", "propose_usd_per_draft": None})
        self.assertEqual((cfg.max_per_night, cfg.usd_per_draft), (2, 0.02))
        self.assertEqual(propose_config({"propose_max": 5}).max_per_night, 5)


# -- the night, through the Service ------------------------------------------

class _Clock:
    def now(self) -> float:
        return 1_000_000.0


class _Bus:
    source = "growth"

    def __init__(self):
        self.sent = []

    async def publish(self, message):
        self.sent.append(message)


class _Logger:
    def info(self, *_a, **_k):
        pass

    warning = error = info


class _Ctx:
    def __init__(self):
        self.bus, self.clock, self.logger, self.config = _Bus(), _Clock(), _Logger(), {}


class _Estimate:
    _config = None
    _competence = None

    @staticmethod
    def load_evals(_path):
        return 0


class _Monitors:
    def __init__(self, found):
        self._found = found

        class _Patterns:
            @staticmethod
            def mine(_now):
                return []
        self._patterns = _Patterns()

    async def _record_candidates(self, _patterns):
        return list(self._found)


class _Explore:
    pass


def _service(config, found, *, think=None):
    from simorgh.growth.measure import measure_config
    from simorgh.growth.service import Service

    service = Service(estimate=_Estimate(), monitors=_Monitors(found), explore=_Explore())
    ctx = _Ctx()
    service._ctx = ctx  # noqa: SLF001

    async def announce(topic, payload):
        from simorgh.contracts.envelope import Message
        await ctx.bus.publish(Message.new(topic, source="growth", payload=payload, clock=ctx.clock.now))

    service._measure = measure_config(config)  # noqa: SLF001
    service._propose = propose_config(config)  # noqa: SLF001
    service._think = think  # noqa: SLF001
    service._agents = AGENTS  # noqa: SLF001
    service.policies = PolicyStore(clock=lambda: 1000.0, publish=announce)
    return service


def _step(service, name):
    return next(s for s in service.last_night.steps if s.name == name)


class TheNight(unittest.TestCase):
    def test_off_by_default_nothing_is_drafted(self):
        calls = []
        service = _service({}, [_cluster()], think=_think(RULE, calls=calls))
        asyncio.run(service._on_sleep(None))  # noqa: SLF001
        self.assertEqual(calls, [])
        self.assertEqual(service.policies.all(), [])
        self.assertIn("propose_policies", _step(service, "propose").skipped)

    def test_on_a_cluster_becomes_a_proposed_rule_announced_on_the_bus(self):
        service = _service({"propose_policies": True}, [_cluster()], think=_think(RULE))
        asyncio.run(service._on_sleep(None))  # noqa: SLF001
        (policy,) = service.policies.all()
        self.assertEqual((policy.status, policy.body), ("proposed", RULE))
        step = _step(service, "propose")
        self.assertEqual((step.ok, step.skipped), (True, ""))
        self.assertAlmostEqual(step.spent_usd, 0.001)
        sent = [m for m in service._ctx.bus.sent if m.type == topics.GROWTH_POLICY_PROPOSED]  # noqa: SLF001
        self.assertEqual(len(sent), 1)
        self.assertEqual(get_spec(sent[0].type).validate(sent[0].payload), [])
        self.assertEqual(sent[0].payload["evidence_refs"], list(policy.evidence_refs))

    def test_the_budget_refuses_the_step_before_any_draft(self):
        calls = []
        service = _service({"propose_policies": True, "propose_usd_per_draft": 0.5},
                           [_cluster()], think=_think(RULE, calls=calls))
        service._nightly_usd = 0.5  # noqa: SLF001 -- 2 drafts x 2 x $0.50 is over it
        asyncio.run(service._on_sleep(None))  # noqa: SLF001
        self.assertEqual(calls, [])
        self.assertIn("would cost", _step(service, "propose").skipped)

    def test_nothing_found_is_a_free_skip(self):
        service = _service({"propose_policies": True}, [], think=_think(RULE))
        asyncio.run(service._on_sleep(None))  # noqa: SLF001
        self.assertIn("found nothing", _step(service, "propose").skipped)

    def test_the_step_comes_after_diagnose_and_before_measure(self):
        service = _service({"propose_policies": True}, [_cluster()], think=_think(RULE))
        asyncio.run(service._on_sleep(None))  # noqa: SLF001
        names = [s.name for s in service.last_night.steps]
        self.assertLess(names.index("diagnose"), names.index("propose"))
        self.assertLess(names.index("propose"), names.index("measure"))


if __name__ == "__main__":
    unittest.main()
