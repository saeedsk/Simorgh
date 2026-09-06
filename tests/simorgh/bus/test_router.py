import unittest

from simorgh.bus.api import SubscriptionSpec
from simorgh.bus.router import Registered, groups_for, is_reply_routed, route
from simorgh.contracts import topics

from tests.simorgh.helpers import make_message


def _reg(pattern, group=None, rid=None):
    async def h(m):
        return None

    return Registered(id=rid or pattern + str(group), spec=SubscriptionSpec(pattern, group, False, "t"), handler=h)


class TestRoute(unittest.TestCase):
    def test_broadcast_each_subscription_gets_a_copy(self):
        regs = [_reg("task.*", rid="a"), _reg("task.*", rid="b"), _reg("action.#", rid="c")]
        out = route(make_message(topics.TASK_STARTED), regs)
        self.assertEqual([r.id for r in out], ["a", "b"])

    def test_competing_group_collapses_to_one_delivery(self):
        regs = [_reg("task.*", "workers", "w1"), _reg("task.*", "workers", "w2"), _reg("task.*", rid="listener")]
        out = route(make_message(topics.TASK_AVAILABLE), regs)
        self.assertEqual({r.id for r in out}, {"w1", "listener"})

    def test_hash_matches_rest_and_star_exactly_one_segment(self):
        self.assertTrue(topics.matches("task.*", "task.claim"))
        self.assertFalse(topics.matches("task.*", "task.claim.reply"))
        self.assertTrue(topics.matches("task.#", "task.claim.reply"))
        self.assertTrue(topics.matches("#", "anything.at.all"))

    def test_reply_goes_only_to_its_inbox(self):
        inbox = _reg("_inbox.orchestration.abc", rid="inbox")
        regs = [inbox, _reg("task.#", rid="eavesdropper")]
        req = make_message(topics.TASK_CLAIM, reply_to="_inbox.orchestration.abc")
        reply = req.reply(topics.TASK_CLAIM_REPLY, {"granted": True, "lease_until": 1.0, "task": {}}, source="planning")
        reply = reply.with_(reply_to=req.reply_to)
        self.assertTrue(is_reply_routed(reply))
        self.assertEqual([r.id for r in route(reply, regs)], ["inbox"])

    def test_inboxes_never_receive_ordinary_messages(self):
        regs = [_reg("_inbox.x.y", rid="inbox")]
        self.assertEqual(route(make_message(topics.TASK_STARTED), regs), [])

    def test_groups_for(self):
        regs = [_reg("task.*", "workers"), _reg("task.*", "audit"), _reg("task.*")]
        self.assertEqual(groups_for(make_message(topics.TASK_STARTED), regs), {"workers", "audit"})


if __name__ == "__main__":
    unittest.main()
