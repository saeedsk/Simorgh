"""Stage 10 item 3: the companion classes. A consented adult, alone in the
kitchen in the evening, with a strong posterior, gets a spoken check-in;
at night, or with somebody else in the room, it goes to the phone; a
child, a guest, an unknown voice or an adult who has not said yes never
gets one, whatever the posterior; the model may say NOTHING and a line
that names a condition never becomes a proposal."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from simorgh.contracts import topics, validate
from simorgh.contracts.envelope import Message
from simorgh.contracts.people import Person
from simorgh.contracts.protocols import Context
from simorgh.initiative.api import (
    COOLDOWN,
    Notice,
    Situation,
    acceptable_line,
    alone,
    companion_gate,
    compose_prompt,
    cooldown_key,
    decide,
    matches_interest,
)
from simorgh.initiative.service import Service

from tests.simorgh.helpers import FakeClock

EVENING_ALONE = Situation(people={"Soodeh": "kitchen"})
EVENING_TOGETHER = Situation(people={"Soodeh": "kitchen", "Saeed": "kitchen"})
EVENING_APART = Situation(people={"Soodeh": "kitchen", "Saeed": "office"})
NIGHT_ALONE = Situation(quiet_hours=True, someone_asleep=True, people={"Soodeh": "kitchen"})

STRONG = Notice("check_in", "Soodeh seems quieter than usual", person="Soodeh", weight=0.75)
WEAK = Notice("check_in", "Soodeh seems quieter than usual", person="Soodeh", weight=0.4)


class WhetherAndWhere(unittest.TestCase):
    def test_a_strong_reading_alone_in_the_evening_is_spoken(self):
        delivery = decide(STRONG, EVENING_ALONE)
        self.assertIsNotNone(delivery)
        self.assertEqual(delivery.channel, "speaker")
        self.assertEqual(delivery.tool, "speak")

    def test_at_night_it_goes_to_the_phone(self):
        delivery = decide(STRONG, NIGHT_ALONE)
        self.assertIsNotNone(delivery)
        self.assertEqual(delivery.channel, "phone")
        self.assertEqual(delivery.to, "Soodeh")

    def test_with_somebody_else_in_the_room_it_is_not_said_aloud(self):
        delivery = decide(STRONG, EVENING_TOGETHER)
        self.assertIsNotNone(delivery)
        self.assertNotEqual(delivery.channel, "speaker", "a private word is not said in front of somebody else")

    def test_somebody_in_another_room_leaves_her_alone(self):
        self.assertTrue(alone("Soodeh", EVENING_APART))
        self.assertFalse(alone("Soodeh", EVENING_TOGETHER))
        self.assertFalse(alone("Soodeh", Situation()), "unplaced is not alone")
        self.assertEqual(decide(STRONG, EVENING_APART).channel, "speaker")

    def test_a_weak_reading_stays_quiet(self):
        self.assertIsNone(decide(WEAK, EVENING_ALONE))

    def test_somebody_not_home_gets_nothing_spoken_and_little_else(self):
        delivery = decide(STRONG, Situation(people={"Saeed": "office"}))
        self.assertTrue(delivery is None or delivery.channel != "speaker")

    def test_the_cooldown_is_per_person(self):
        now = 1_790_000_000.0
        recent = {cooldown_key(STRONG): now - 3600}
        self.assertIsNone(decide(STRONG, EVENING_ALONE, now=now, last_by_kind=recent))
        for_saeed = Notice("check_in", "Saeed seems quieter", person="Saeed", weight=0.75)
        self.assertIsNotNone(decide(for_saeed, Situation(people={"Saeed": "office"}), now=now, last_by_kind=recent))
        self.assertIsNotNone(decide(STRONG, EVENING_ALONE, now=now,
                                    last_by_kind={cooldown_key(STRONG): now - COOLDOWN["check_in"] - 1}))

    def test_an_interest_share_is_light_and_private_too(self):
        share = Notice("interest_share", "a new Lego robotics kit", person="Aran")
        self.assertEqual(decide(share, Situation(people={"Aran": "playroom"})).channel, "speaker")
        with_ira = decide(share, Situation(people={"Aran": "playroom", "Ira": "playroom"}))
        self.assertTrue(with_ira is None or with_ira.channel != "speaker", "not in front of his sister; it can wait")
        self.assertIsNone(decide(share, Situation(quiet_hours=True, someone_asleep=True,
                                                  people={"Aran": "playroom"})), "not at night")


class TheGates(unittest.TestCase):
    def _person(self, role, *permissions):
        person = Person("p", "P", role)
        for permission in permissions:
            person = person.with_permission(permission)
        return person

    def test_a_check_in_is_only_for_an_adult_who_said_yes(self):
        notice = Notice("check_in", "note", person="P", weight=0.9)
        self.assertEqual(companion_gate(notice, self._person("adult", "wellbeing_checkins")), "")
        self.assertEqual(companion_gate(notice, self._person("owner", "wellbeing_checkins")), "")
        for role in ("child", "guest", "unknown"):
            with self.subTest(role=role):
                why = companion_gate(notice, self._person(role, "wellbeing_checkins"))
                self.assertIn(role, why)
        self.assertIn("not said yes", companion_gate(notice, self._person("adult")))
        self.assertIn("nobody", companion_gate(notice, None))
        self.assertIn("needs a person", companion_gate(Notice("check_in", "note"), None))

    def test_a_share_admits_a_child_with_a_parents_grant_and_refuses_a_guest(self):
        notice = Notice("interest_share", "lego", person="P")
        self.assertEqual(companion_gate(notice, self._person("child", "interest_shares")), "")
        self.assertIn("guest", companion_gate(notice, self._person("guest", "interest_shares")))
        self.assertIn("not said yes", companion_gate(notice, self._person("child")))

    def test_the_gate_does_not_touch_the_household_classes(self):
        self.assertEqual(companion_gate(Notice("event_fyi", "a car"), None), "")
        self.assertEqual(companion_gate(Notice("reminder", "dentist", person="Ira"), None), "")


class TheWords(unittest.TestCase):
    def test_the_model_may_decline(self):
        self.assertEqual(acceptable_line("NOTHING"), ("", "the model had nothing worth saying"))
        self.assertEqual(acceptable_line("  nothing. ")[0], "")
        self.assertEqual(acceptable_line("")[0], "")

    def test_a_line_that_names_a_condition_is_refused(self):
        line, why = acceptable_line("You seem a bit depressed lately, Soodeh.")
        self.assertEqual(line, "")
        self.assertIn("condition", why)
        self.assertEqual(acceptable_line("Have you thought about therapy?")[0], "")

    def test_a_warm_opening_passes_and_a_speech_does_not(self):
        line, why = acceptable_line('"Hey Soodeh -- quiet day? I\'m around if you want company."')
        self.assertEqual(why, "")
        self.assertTrue(line.startswith("Hey Soodeh"))
        self.assertIn("ran long", acceptable_line("word " * 80)[1])

    def test_the_prompt_asks_and_does_not_tell(self):
        prompt = compose_prompt(STRONG, Person("s", "Soodeh", "adult"))
        for must in ("Soodeh", "Ask, do not tell", "Never name a condition", "NOTHING", "percentages"):
            self.assertIn(must, prompt)
        share = compose_prompt(Notice("interest_share", "a new Lego kit", person="Aran"), Person("a", "Aran", "child"))
        self.assertIn("Lego kit", share)
        self.assertIn("child", share)

    def test_matching_an_interest_is_plain(self):
        self.assertEqual(matches_interest("A new Lego robotics kit was announced", ("chess", "lego robotics")),
                         "lego robotics")
        self.assertEqual(matches_interest("Markets fell today", ("lego robotics",)), "")
        self.assertEqual(matches_interest("", ("lego",)), "")


# -- the service, over a fake bus ------------------------------------------------------------
class _Sub:
    def __init__(self, bus, topic):
        self.bus, self.topic = bus, topic

    async def unsubscribe(self):
        self.bus.handlers.pop(self.topic, None)


class _Bus:
    """Records what Initiative publishes (validated against the catalogue)
    and answers its requests from canned replies."""

    source = "initiative"

    def __init__(self):
        self.handlers = {}
        self.published = []
        self.requests = []
        self.replies = {}      # topic -> callable(message) -> payload

    async def subscribe(self, topic, handler):
        self.handlers[topic] = handler
        return _Sub(self, topic)

    async def publish(self, message):
        validate(message)
        self.published.append(message)

    async def request(self, message, *, timeout):
        validate(message)
        self.requests.append(message)
        answer = self.replies.get(message.type)
        if answer is None:
            raise TimeoutError(message.type)
        payload = answer(message) if callable(answer) else dict(answer)
        return Message.new(topics.reply_type_for(message.type), source="test", payload=payload)

    def deliver(self, topic, payload):
        return self.handlers[topic](Message.new(topic, source="test", payload=payload))

    def of(self, topic):
        return [m.payload for m in self.published if m.type == topic]


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


def _people_reply(people):
    by_name = {p.name.lower(): p for p in people}

    def answer(message):
        args = message.payload.get("args") or {}
        name = str(args.get("name") or "").lower()
        if name:
            person = by_name.get(name)
            return {"ok": True, "facet": "people", "as_of": 0.0, "person": person.to_dict() if person else None,
                    "role": person.role if person else "unknown"}
        return {"ok": True, "facet": "people", "as_of": 0.0, "people": [p.to_dict() for p in people]}
    return answer


def _home_reply(situation: Situation):
    return {"ok": True, "facet": "home", "as_of": 0.0, "entities": [], "presence": {},
            "situation": {"quiet_hours": situation.quiet_hours, "someone_asleep": situation.someone_asleep,
                          "child_alone": situation.child_alone, "tv_playing": situation.tv_playing,
                          "nobody_home": not situation.people, "people": dict(situation.people)}}


SOODEH = Person("soodeh", "Soodeh", "adult").with_permission("wellbeing_checkins")
SAEED = Person("saeed", "Saeed", "owner")
IRA = Person("ira", "Ira", "child").with_permission("wellbeing_checkins")     # a flag a parent should not have set
BOBBY = Person("bobby", "Bobby", "guest").with_permission("wellbeing_checkins")
ARAN = Person("aran", "Aran", "child").with_permission("interest_shares").with_interest("lego robotics")
LINE = "Hey Soodeh -- quiet day? I'm around if you fancy a chat."


class TheService(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bus = _Bus()
        self.clock = FakeClock(1_790_000_000.0)
        self.ctx = Context(name="initiative", instance_id="", run_id="t", mode="single", bus=self.bus, ledger=None,
                           config={}, secrets={}, clock=self.clock, logger=_Logger(), data_dir=Path(self.tmp.name))
        self.service = Service()
        await self.service.start(self.ctx)
        self.people = [SOODEH, SAEED, IRA, BOBBY, ARAN]
        self.situation = EVENING_ALONE
        self.model_says = LINE
        self.bus.replies[topics.WORLD_ENV_QUERY] = self._world
        self.bus.replies[topics.COGNITION_THINK] = lambda m: {
            "text": self.model_says, "tool_calls": [], "provider": "fake", "cost_usd": 0.0, "tokens": 12,
            "floor": False, "non_answer": False}

    def _world(self, message):
        what = message.payload["what"]
        if what == "people":
            return _people_reply(self.people)(message)
        return _home_reply(self.situation)

    async def asyncTearDown(self):
        await self.service.stop()

    async def _low(self, person, mean=0.75):
        await self.bus.deliver(topics.WORLD_WELLBEING_CHANGED,
                               {"person": person, "state": "low", "mean": mean, "evidence": 5.0, "since": 1.0})

    async def test_a_consented_adult_alone_in_the_evening_is_asked_aloud_in_the_models_words(self):
        await self._low("Soodeh")
        proposals = self.bus.of(topics.ACTION_PROPOSED)
        self.assertEqual(len(proposals), 1, self.bus.of(topics.INITIATIVE_SUPPRESSED))
        self.assertEqual(proposals[0]["tool"], "speak")
        self.assertEqual(proposals[0]["args"]["text"], LINE)
        self.assertEqual(proposals[0]["requester_channel"], "initiative")
        self.assertIn("check_in", proposals[0]["rationale"])
        think = [m for m in self.bus.requests if m.type == topics.COGNITION_THINK]
        self.assertEqual(len(think), 1)
        self.assertIn("Soodeh", think[0].payload["messages"][0]["content"])
        self.assertNotIn("0.75", think[0].payload["messages"][0]["content"], "the note carries no raw numbers")

    async def test_at_night_it_goes_to_her_phone(self):
        self.situation = NIGHT_ALONE
        await self._low("Soodeh")
        proposals = self.bus.of(topics.ACTION_PROPOSED)
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0]["tool"], "notify")
        # `notify` takes `body` and has no recipient field -- it reaches
        # the person who runs Sim. Asserting `args["to"]` passed while
        # every real notification was denied for a missing `body`
        # (2026-09-20); who it is for rides in the subject.
        self.assertEqual(proposals[0]["args"]["body"], LINE)
        self.assertIn("Soodeh", proposals[0]["args"]["subject"])

    async def test_with_saeed_in_the_kitchen_it_is_not_said_aloud(self):
        self.situation = EVENING_TOGETHER
        await self._low("Soodeh")
        proposals = self.bus.of(topics.ACTION_PROPOSED)
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0]["tool"], "notify")

    async def test_a_child_a_guest_an_unknown_voice_and_an_ungranted_adult_never_get_a_check_in(self):
        for person, expect in (("Ira", "child"), ("Bobby", "guest"), ("Nobody", "nobody"), ("Saeed", "not said yes")):
            with self.subTest(person=person):
                self.bus.published.clear()
                self.bus.requests.clear()
                self.situation = Situation(people={person: "kitchen"})
                await self._low(person, mean=0.99)
                self.assertEqual(self.bus.of(topics.ACTION_PROPOSED), [])
                suppressed = self.bus.of(topics.INITIATIVE_SUPPRESSED)
                self.assertEqual(len(suppressed), 1)
                self.assertEqual(suppressed[0]["kind"], "check_in")
                self.assertIn(expect, suppressed[0]["why"])
                self.assertEqual([m for m in self.bus.requests if m.type == topics.COGNITION_THINK], [],
                                 "the model is not even asked")

    async def test_a_state_that_is_not_low_is_not_a_reason(self):
        for state in ("usual", "high", "unknown"):
            await self.bus.deliver(topics.WORLD_WELLBEING_CHANGED,
                                   {"person": "Soodeh", "state": state, "mean": 0.9, "evidence": 5.0})
        self.assertEqual(self.bus.published, [])

    async def test_the_model_may_say_nothing(self):
        self.model_says = "NOTHING"
        await self._low("Soodeh")
        self.assertEqual(self.bus.of(topics.ACTION_PROPOSED), [])
        self.assertIn("nothing worth saying", self.bus.of(topics.INITIATIVE_SUPPRESSED)[0]["why"])

    async def test_a_line_naming_a_condition_never_becomes_a_proposal(self):
        self.model_says = "Soodeh, you seem depressed. Have you considered therapy?"
        await self._low("Soodeh")
        self.assertEqual(self.bus.of(topics.ACTION_PROPOSED), [])
        self.assertIn("condition", self.bus.of(topics.INITIATIVE_SUPPRESSED)[0]["why"])

    async def test_no_model_means_no_words(self):
        del self.bus.replies[topics.COGNITION_THINK]
        await self._low("Soodeh")
        self.assertEqual(self.bus.of(topics.ACTION_PROPOSED), [])
        self.assertIn("did not answer", self.bus.of(topics.INITIATIVE_SUPPRESSED)[0]["why"])

    async def test_one_check_in_per_person_per_day(self):
        await self._low("Soodeh")
        self.clock.advance(3600)
        await self._low("Soodeh", mean=0.9)
        self.assertEqual(len(self.bus.of(topics.ACTION_PROPOSED)), 1)
        self.assertEqual(len(self.bus.of(topics.INITIATIVE_SUPPRESSED)), 1)

    async def test_a_share_about_what_aran_cares_about_goes_to_aran(self):
        self.situation = Situation(people={"Aran": "playroom"})
        self.model_says = "Aran, a new Lego robotics kit just came out -- want to have a look later?"
        await self.bus.deliver(topics.CURIOSITY_SHARE_PROPOSED,
                               {"kind": "news", "content_ref": "news:1", "summary": "A new Lego robotics kit was announced"})
        proposals = self.bus.of(topics.ACTION_PROPOSED)
        self.assertEqual(len(proposals), 1)
        self.assertIn("interest_share", proposals[0]["rationale"])
        self.assertEqual(proposals[0]["tool"], "speak")

    async def test_a_share_about_nothing_anybody_cares_about_stays_news(self):
        self.situation = Situation(people={"Aran": "playroom"})
        await self.bus.deliver(topics.CURIOSITY_SHARE_PROPOSED,
                               {"kind": "news", "content_ref": "news:2", "summary": "Markets fell today"})
        self.assertEqual(self.bus.of(topics.ACTION_PROPOSED), [])
        self.assertEqual(self.bus.of(topics.INITIATIVE_SUPPRESSED)[0]["kind"], "news")

    async def test_a_share_with_no_summary_says_so(self):
        await self.bus.deliver(topics.CURIOSITY_SHARE_PROPOSED, {"kind": "news", "content_ref": "news:3"})
        suppressed = self.bus.of(topics.INITIATIVE_SUPPRESSED)
        self.assertEqual(len(suppressed), 1)
        self.assertIn("no summary", suppressed[0]["why"])


if __name__ == "__main__":
    unittest.main()


class TheDeliveryPathsExist(unittest.IsolatedAsyncioTestCase):
    """2026-09-20, from the creator's own log: `notify` denied with
    "$.body: required property missing", twice in one evening, and
    `speak` was never a registered tool at all.

    So Initiative decided, proposed, and nothing ever arrived -- both
    of its channels had been dead since stage 6 item 6. A decision
    machinery whose delivery does not exist is worse than none: it
    looks like restraint.
    """

    def _tools(self):
        from simorgh.domains import domain_tools
        from simorgh.execution.config import Config
        from simorgh.execution.tools import builtin_tools

        config = Config()
        return {t.name: t for t in builtin_tools(config) + domain_tools(config, secrets=None)}

    def test_every_tool_initiative_can_propose_is_registered(self):
        """`Delivery.tool` is the mapping; every value it can take has
        to be a tool that exists."""
        from simorgh.initiative.api import CHANNELS, Delivery, Notice

        registered = self._tools()
        notice = Notice(kind="check_in", text="a word", person="Soodeh")
        for channel in CHANNELS:
            tool = Delivery(notice=notice, channel=channel, to="Soodeh", utility=1.0, why="").tool
            with self.subTest(channel=channel, tool=tool):
                self.assertIn(tool, registered, f"Initiative proposes {tool!r} and nothing answers to it")

    def test_what_initiative_sends_satisfies_the_tools_own_schema(self):
        from simorgh.contracts import schema as schema_mod  # noqa: F401 -- presence, not use

        tools = self._tools()
        for tool_name, args in (("speak", {"text": "a word"}),
                                ("notify", {"body": "a word", "subject": "for Soodeh"})):
            with self.subTest(tool=tool_name):
                required = set(tools[tool_name].args_schema.get("required") or ())
                self.assertTrue(required <= set(args),
                                f"{tool_name} requires {sorted(required - set(args))} and Initiative sends none")


class ACameraDoesNotSpeakForItself(unittest.IsolatedAsyncioTestCase):
    """The vision model's words go through the same gate as everything else.

    `execution/vision.py` used to publish `voice.speak.request` with
    its description, so a camera talked in the room at any hour --
    past Guardian, and past the one module that knows who is asleep,
    who is present and which channel reaches them. At 02:00 that is
    the exact failure stage 6 item 6's acceptance names.
    """

    async def test_at_two_in_the_morning_it_goes_to_the_phone(self):
        from simorgh.initiative.api import Notice, Situation, decide

        # 02:00, a child asleep in the living room.
        night = Situation(quiet_hours=True, someone_asleep=True, child_alone=True,
                          people={"Otto": "living room"})
        delivery = decide(Notice(kind="event_fyi", text="Front Door: a delivery van has pulled up",
                                 ref="camera:Front Door"),
                          night, owner="Mara", now=0.0, last_by_kind={}, delivered_today=0,
                          do_not_disturb=())
        if delivery is not None:
            self.assertEqual(delivery.tool, "notify",
                             "a camera at 02:00 with a child asleep must not use the speaker")


class BeingToldToLeaveIt(unittest.IsolatedAsyncioTestCase):
    """A companion that cannot be told to stop is a process.

    Two answers, treated differently on purpose. "Not now" is a hold
    Sim applies itself -- they answered, they just do not want to
    talk about it, and asking again tomorrow is the whole complaint.
    "Stop asking me" is consent being withdrawn, and Sim withdraws
    consent on nobody's behalf: it proposes the revoke at tier 3 and
    the person confirms, exactly as they did to grant it.
    """

    def test_what_counts_as_which(self):
        from simorgh.initiative.api import pushback

        for said in ("not now", "I'm fine, thanks", "nothing's wrong", "leave it"):
            self.assertEqual(pushback(said), "not now", said)
        for said in ("stop asking me that", "please stop checking on me", "don't ask me that again"):
            self.assertEqual(pushback(said), "stop", said)
        for said in ("yeah, it was a long week", "fine by me", "I'm going to the shop"):
            self.assertEqual(pushback(said), "", said)

    def test_a_long_week_is_not_pushback(self):
        """The words that matter are narrow; an ordinary answer to
        "how are you" must not read as a refusal, or the one time
        somebody actually talks is the time Sim stops listening."""
        from simorgh.initiative.api import pushback

        self.assertEqual(pushback("It's been a lot, honestly"), "")
        self.assertEqual(pushback("Work is fine, home is the problem"), "")


class AnInterestIsAskedForNotAssumed(unittest.IsolatedAsyncioTestCase):
    """Stage 10 item 7: knowing what somebody likes, and being allowed
    to bring it up, are different things.

    Consolidation records `interest` facts like any other fact. That
    is memory. Putting one on `Person.interests` is what lets Sim
    start a conversation about it unprompted, and that is the
    person's to grant: a tier-3 `people add_interest` with the
    sentence Sim heard in the rationale, so whoever confirms it can
    see what it is confirming.
    """

    def _service(self, person):
        import types

        from simorgh.initiative.service import Service

        service = Service.__new__(Service)
        published = []

        class _Bus:
            source = "initiative"

            async def publish(self, message):
                published.append(message)

        service._ctx = types.SimpleNamespace(bus=_Bus(), clock=types.SimpleNamespace(now=lambda: 0.0))
        service._published = published

        async def _person(_name):
            return person

        service._person = _person
        return service, published

    def _fact(self, **over):
        from simorgh.contracts.envelope import Message
        from simorgh.contracts import topics

        payload = {"id": "f1", "subject": "Aran", "predicate": "interest", "object": "lego robotics",
                   "person_scope": "Aran", "valid_from": 0.0, "confidence": 0.9,
                   "source_refs": ["I've been really into lego robotics lately"]}
        payload.update(over)
        return Message.new(topics.MEMORY_FACT_STORED, source="memory", payload=payload)

    def _person(self, **over):
        from simorgh.contracts.people import Person

        fields = {"person_id": "aran", "name": "Aran", "role": "child", "interests": ()}
        fields.update(over)
        return Person(**fields)

    async def test_it_proposes_rather_than_writing(self):
        service, published = self._service(self._person())
        await service._on_fact_stored(self._fact())
        self.assertEqual(len(published), 1)
        payload = published[0].payload
        self.assertEqual(payload["tool"], "people")
        self.assertEqual(payload["args"], {"action": "add_interest", "name": "Aran", "interest": "lego robotics"})
        self.assertIn("lego robotics", payload["rationale"])
        self.assertIn("really into lego robotics", payload["rationale"],
                      "the quote belongs in the rationale: whoever says yes should see what Sim heard")

    async def test_an_interest_already_held_is_not_proposed_again(self):
        service, published = self._service(self._person(interests=("lego robotics",)))
        await service._on_fact_stored(self._fact())
        self.assertEqual(published, [])

    async def test_a_fact_about_nobody_sim_knows_is_left_alone(self):
        service, published = self._service(None)
        await service._on_fact_stored(self._fact())
        self.assertEqual(published, [])

    async def test_an_ordinary_fact_is_not_an_interest(self):
        service, published = self._service(self._person())
        await service._on_fact_stored(self._fact(predicate="lives_in", object="the blue room"))
        self.assertEqual(published, [])
