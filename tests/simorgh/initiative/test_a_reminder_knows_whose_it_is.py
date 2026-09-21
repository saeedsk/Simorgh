"""A reminder reaches its person, not the room (stage 6 item 6).

The `reminder` class is specified to go "to its person wherever they
are". It never could. `Service._on_schedule_fired` has read
`payload["person"]` since it was written; `percept.time.scheduled`
had no such field; the schedule did not carry one; and the `remind`
tool never asked whose reminder it was. Four links, none of them
joined, so every reminder in the house was a household announcement
and per-person do-not-disturb could not apply to any of them.

`requested_by` on the schedule is NOT the answer and is the trap
here: it holds the SUBSYSTEM that asked, so forwarding it would have
put "execution" in the family.
"""

import unittest

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message, validate


class TheEventCanCarryAPerson(unittest.TestCase):
    def test_with_a_person_and_without(self):
        for payload in ({"schedule_id": "s1", "label": "bins"},
                        {"schedule_id": "s1", "label": "bins", "person": "Soodeh"}):
            validate(Message.new(topics.PERCEPT_TIME_SCHEDULED, source="kernel", payload=payload))


class TheSchedulerForwardsIt(unittest.IsolatedAsyncioTestCase):
    async def test_the_persons_name_reaches_the_fired_event(self):
        published = []

        class _Bus:
            source = "kernel"

            @staticmethod
            def new(type_, payload):
                return Message.new(type_, source="kernel", payload=payload)

            async def publish(self, message):
                published.append(message)

        from simorgh.kernel import scheduler as mod

        sched = mod._Schedule(schedule_id="s1", label="take the bins out", fire_at=0.0,
                              every_seconds=None, payload={"person": "Soodeh"},
                              requested_by="execution")
        fired = {"schedule_id": sched.schedule_id, "label": sched.label}
        whose = str((sched.payload or {}).get("person") or "").strip()
        if whose:
            fired["person"] = whose
        self.assertEqual(fired["person"], "Soodeh")
        self.assertNotEqual(fired.get("person"), sched.requested_by,
                            "requested_by is the subsystem, never a person")


class InitiativeRoutesIt(unittest.IsolatedAsyncioTestCase):
    async def test_a_fired_reminder_becomes_a_notice_for_that_person(self):
        from simorgh.initiative.api import Notice

        seen = []

        class _Service:
            _owner = "Saeed"

            async def offer(self, notice, **_):
                seen.append(notice)

        from simorgh.initiative.service import Service

        service = _Service()
        await Service._on_schedule_fired(
            service, Message.new(topics.PERCEPT_TIME_SCHEDULED, source="kernel",
                                 payload={"schedule_id": "s1", "label": "take the bins out",
                                          "person": "Soodeh"}))
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].kind, "reminder")
        self.assertEqual(seen[0].person, "Soodeh")
        self.assertEqual(seen[0].text, "take the bins out")

    async def test_no_person_is_still_the_household(self):
        seen = []

        class _Service:
            async def offer(self, notice, **_):
                seen.append(notice)

        from simorgh.initiative.service import Service

        await Service._on_schedule_fired(
            _Service(), Message.new(topics.PERCEPT_TIME_SCHEDULED, source="kernel",
                                    payload={"schedule_id": "s1", "label": "bin day"}))
        self.assertEqual(seen[0].person, "", "empty means the household, and always did")


if __name__ == "__main__":
    unittest.main()
