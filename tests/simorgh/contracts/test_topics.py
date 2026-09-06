import unittest

from simorgh.contracts import topics
from simorgh.contracts.topics import matches, may_publish, may_subscribe, reply_type_for


class TestPatternMatching(unittest.TestCase):
    def test_exact(self):
        self.assertTrue(matches("task.step", "task.step"))
        self.assertFalse(matches("task.step", "task.started"))

    def test_star_matches_exactly_one_segment(self):
        self.assertTrue(matches("task.*", "task.step"))
        self.assertFalse(matches("task.*", "task.dependency.satisfied"))
        self.assertTrue(matches("task.*.satisfied", "task.dependency.satisfied"))
        self.assertFalse(matches("*.step", "task.dependency.satisfied"))

    def test_hash_matches_the_rest_including_nothing(self):
        self.assertTrue(matches("action.#", "action.proposed"))
        self.assertTrue(matches("task.#", "task.dependency.satisfied"))
        self.assertTrue(matches("#", "anything.at.all"))
        self.assertFalse(matches("action.#", "task.step"))

    def test_hash_only_matches_when_prefix_matches(self):
        self.assertTrue(matches("task.dependency.#", "task.dependency.satisfied"))
        self.assertFalse(matches("task.dependency.#", "task.step"))


class TestReplyNaming(unittest.TestCase):
    def test_plain_request_reply(self):
        self.assertEqual(reply_type_for("task.claim"), "task.claim.reply")

    def test_dot_request_becomes_dot_reply(self):
        self.assertEqual(reply_type_for("task.list.request"), "task.list.reply")

    def test_reply_is_idempotent(self):
        self.assertEqual(reply_type_for("task.claim.reply"), "task.claim.reply")


class TestReservedTopology(unittest.TestCase):
    def test_only_guardian_may_subscribe_to_proposed(self):
        self.assertTrue(may_subscribe("guardian", topics.ACTION_PROPOSED))
        self.assertFalse(may_subscribe("orchestration@w1", topics.ACTION_PROPOSED))

    def test_only_execution_may_subscribe_to_approved(self):
        self.assertTrue(may_subscribe("execution@e2", topics.ACTION_APPROVED))
        self.assertFalse(may_subscribe("guardian", topics.ACTION_APPROVED))

    def test_unreserved_topics_are_open(self):
        self.assertTrue(may_subscribe("curiosity", topics.TASK_COMPLETED))
        self.assertTrue(may_publish("curiosity", topics.TASK_COMPLETED))

    def test_only_guardian_or_kernel_may_publish_approved(self):
        self.assertTrue(may_publish("guardian", topics.ACTION_APPROVED))
        self.assertTrue(may_publish("kernel", topics.ACTION_APPROVED))
        self.assertFalse(may_publish("execution", topics.ACTION_APPROVED))
        self.assertFalse(may_publish("orchestration", topics.ACTION_APPROVED))

    def test_execution_may_publish_denied_only_with_layer_token(self):
        self.assertTrue(may_publish("execution", topics.ACTION_DENIED, {"layer": "token"}))
        self.assertFalse(may_publish("execution", topics.ACTION_DENIED, {"layer": "policy"}))
        self.assertTrue(may_publish("guardian", topics.ACTION_DENIED, {"layer": "policy"}))

    def test_control_messages_are_interface_or_kernel_only(self):
        for t in (topics.SYSTEM_PAUSE, topics.SYSTEM_STOP, topics.SYSTEM_RESUME):
            self.assertTrue(may_publish("interface", t))
            self.assertFalse(may_publish("planning", t))
        self.assertTrue(may_publish("execution", topics.SYSTEM_RESTART))
        self.assertFalse(may_publish("execution", topics.SYSTEM_PAUSE))

    def test_single_writer_streams(self):
        self.assertTrue(may_publish("worldmodel", topics.SELF_MODEL_UPDATED))
        self.assertFalse(may_publish("reflection", topics.SELF_MODEL_UPDATED))
        self.assertTrue(may_publish("planning", topics.PLAN_PROPOSED))
        self.assertFalse(may_publish("orchestration", topics.PLAN_PROPOSED))

    def test_source_instance_suffix_is_ignored_for_identity(self):
        self.assertEqual(topics.source_name("orchestration@w3"), "orchestration")


if __name__ == "__main__":
    unittest.main()
