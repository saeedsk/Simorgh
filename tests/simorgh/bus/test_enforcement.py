import unittest

from simorgh.bus.api import PolicyViolation
from simorgh.bus.enforcement import IdentityRegistry, ReservedTopologyPolicy
from simorgh.bus.factory import make_backend, make_client
from simorgh.bus.config import Config
from simorgh.contracts import security, topics
from simorgh.contracts.envelope import Message

from .harness import run


class TestReservedTopologyPolicy(unittest.TestCase):
    def setUp(self):
        self.policy = ReservedTopologyPolicy()

    def test_only_guardian_may_subscribe_action_proposed_even_via_wildcards(self):
        self.policy.check_subscribe("guardian", topics.ACTION_PROPOSED)
        for pattern in (topics.ACTION_PROPOSED, "action.*", "action.#", "#"):
            with self.assertRaises(PolicyViolation, msg=pattern):
                self.policy.check_subscribe("curiosity", pattern)

    def test_only_execution_may_subscribe_action_approved(self):
        self.policy.check_subscribe("execution@w1", "action.approved")
        with self.assertRaises(PolicyViolation):
            self.policy.check_subscribe("planning", "action.approved")

    def test_publish_restrictions(self):
        self.policy.check_publish("guardian", topics.ACTION_APPROVED, {})
        self.policy.check_publish("kernel", topics.ACTION_APPROVED, {})
        with self.assertRaises(PolicyViolation):
            self.policy.check_publish("orchestration", topics.ACTION_APPROVED, {})
        self.policy.check_publish("execution", topics.ACTION_DENIED, {"layer": "token"})
        with self.assertRaises(PolicyViolation):
            self.policy.check_publish("execution", topics.ACTION_DENIED, {"layer": "policy"})
        with self.assertRaises(PolicyViolation):
            self.policy.check_publish("curiosity", topics.SYSTEM_PAUSE, {})
        self.policy.check_publish("interface", topics.SYSTEM_PAUSE, {})
        with self.assertRaises(PolicyViolation):
            self.policy.check_publish("reflection", topics.SELF_MODEL_UPDATED, {})
        self.policy.check_publish("worldmodel", topics.SELF_MODEL_UPDATED, {})
        with self.assertRaises(PolicyViolation):
            self.policy.check_publish("orchestration", topics.PLAN_PROPOSED, {})

    def test_unrestricted_types_are_open(self):
        self.policy.check_subscribe("anyone", "task.#")
        self.policy.check_publish("anyone", topics.TASK_STEP, {})


class TestIdentity(unittest.TestCase):
    def test_multi_process_identity_must_authenticate_before_policy_passes(self):
        secret = security.new_run_secret()
        registry = IdentityRegistry(secret=secret, run_id="run-1")
        policy = ReservedTopologyPolicy(registry)
        token = registry.issue("guardian", "")
        with self.assertRaises(PolicyViolation):
            policy.check_subscribe("guardian", topics.ACTION_PROPOSED)  # not yet authenticated
        with self.assertRaises(PolicyViolation):
            policy.authenticate("guardian", "forged")
        policy.authenticate("guardian", token)
        policy.check_subscribe("guardian", topics.ACTION_PROPOSED)
        # a forged source name with a token issued for another name fails
        with self.assertRaises(PolicyViolation):
            policy.authenticate("execution", token)

    @run
    async def test_a_client_cannot_publish_under_another_already_authenticated_subsystems_name(self):
        # Full-stack regression for 2026-09-08: this is the local-multi
        # scenario the Kernel actually creates -- every subsystem
        # self-authenticates once at boot (`ContextFactory.build`), on the
        # SAME shared `ReservedTopologyPolicy` object. After that, curiosity's
        # own `BusClient.publish()` must still refuse to emit a message
        # claiming `source="guardian"`, even though "guardian" is a fully
        # authenticated name on this policy -- identity has to be pinned to
        # the calling client, not to whether the claimed name ever
        # authenticated at all.
        secret = security.new_run_secret()
        identities = IdentityRegistry(secret=secret, run_id="run-1")
        policy = ReservedTopologyPolicy(identities)
        backend = make_backend(Config())
        await backend.start()
        for name in ("guardian", "curiosity"):
            policy.authenticate(name, identities.issue(name))
        curiosity = make_client(backend, source="curiosity", policy=policy)
        forged = Message.new(
            topics.ACTION_DENIED, source="guardian",
            payload={"action_id": "a1", "reasons": ["forged"], "layer": "policy"},
        )
        with self.assertRaises(PolicyViolation):
            await curiosity.publish(forged)
        await backend.stop()


if __name__ == "__main__":
    unittest.main()
