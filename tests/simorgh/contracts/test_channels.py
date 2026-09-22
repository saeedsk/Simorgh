"""Sim can be reached from outside the house, and only by the family.

The creator, 2026-09-16: "CHANGE THE CONTRACT AND INTRODUCE EXTERNAL
VOICE/TEXT CHANNELS LIKE WHATSAPP AND TELEGRAM", after describing the
use for it by voice -- talking to Sim from the car instead of carrying
the MacBook out to it.

Two things are under test, and the second matters more than the first.

The enum and the registry must not drift. `percept.text.received`'s
`channel` is closed on purpose: a live bug published `"dashboard"`, a
value the enum never had, and every publish 500'd on validation. Closing
it caught that. Building the enum from `channels.ALL` keeps one truth,
and this asserts the two really are the same set rather than trusting
that they are.

And an external channel is a remote control of this house. `cli` and
`voice` need a person in the room; WhatsApp needs only the number. So
the gate in front of it is deny-by-default, and these tests hold that
line -- including the quiet way it could fail open, which is not a
missing check but a check that compares `+1 (415) 555-0123` against
`14155550123` and never matches.
"""

from __future__ import annotations

import unittest

from simorgh.contracts import channels


class TheRegistryAndTheEnumAgreeTestCase(unittest.TestCase):
    def test_the_percept_enum_is_exactly_the_registry(self):
        """Built from `channels.ALL`, so the two cannot drift -- and
        read back through the registry rather than trusted."""
        import simorgh.contracts.messages.percept  # noqa: F401 -- registers the type
        from simorgh.contracts import topics
        from simorgh.contracts.registry import get_spec

        spec = get_spec(topics.PERCEPT_TEXT_RECEIVED)
        field = next(f for f in spec.fields if f.name == "channel")
        self.assertEqual(set(field.node.enum), set(channels.ALL))

    def test_a_whatsapp_percept_really_validates(self):
        """The bug this enum exists to catch published an unlisted
        channel and every publish 500'd. The proof is a payload through
        the real validator, not a set comparison."""
        for channel in channels.EXTERNAL:
            with self.subTest(channel=channel):
                self.assertEqual(
                    self._spec().validate(
                        {"channel": channel, "text": "what time is dinner", "session_id": "s1"}),
                    [])

    def test_an_unlisted_channel_is_still_refused(self):
        """Widening must not have opened the door to everything: the
        value that caused the original outage still fails."""
        errors = self._spec().validate(
            {"channel": "dashboard", "text": "hi", "session_id": "s1"})
        self.assertNotEqual(errors, [], "an unlisted channel must not validate")

    @staticmethod
    def _spec():
        import simorgh.contracts.messages.percept  # noqa: F401 -- registers the type
        from simorgh.contracts import topics
        from simorgh.contracts.registry import get_spec

        return get_spec(topics.PERCEPT_TEXT_RECEIVED)

    def test_the_new_channels_are_in_it(self):
        self.assertIn(channels.WHATSAPP, channels.ALL)
        self.assertIn(channels.TELEGRAM, channels.ALL)

    def test_the_old_channels_are_untouched(self):
        """Widening must not quietly drop one that is in use."""
        for name in ("cli", "api", "chat", "command", "voice"):
            self.assertIn(name, channels.ALL)

    def test_local_and_external_do_not_overlap(self):
        self.assertEqual(set(channels.LOCAL) & set(channels.EXTERNAL), set())

    def test_external_is_about_trust_not_transport(self):
        """`api` is HTTP and still local: the dashboard is on this
        machine. The question is whether the house admitted them."""
        self.assertFalse(channels.is_external("api"))
        self.assertFalse(channels.is_external("voice"))
        self.assertTrue(channels.is_external("whatsapp"))
        self.assertTrue(channels.is_external("telegram"))

    def test_an_unknown_channel_is_not_known(self):
        self.assertFalse(channels.is_known("dashboard"))  # the value that 500'd
        self.assertFalse(channels.is_known(""))

    def test_a_channel_is_named_for_a_person_never_as_a_slug(self):
        self.assertEqual(channels.display("whatsapp"), "WhatsApp")
        self.assertEqual(channels.display("telegram"), "Telegram")

    def test_an_unnameable_channel_is_described_not_invented(self):
        self.assertEqual(channels.display("carrier_pigeon"), "another channel")


class TheGateDeniesByDefaultTestCase(unittest.TestCase):
    def test_no_allow_list_admits_nobody(self):
        """The failure this exists to prevent: an empty list meaning
        "anyone", handing the house to whoever finds the number."""
        self.assertFalse(channels.allowed("14155550123", []))

    def test_a_listed_sender_is_admitted(self):
        self.assertTrue(channels.allowed("14155550123", ["14155550123"]))

    def test_a_stranger_is_refused(self):
        self.assertFalse(channels.allowed("19995550000", ["14155550123"]))

    def test_an_empty_sender_is_refused(self):
        """A vendor payload with no sender must not sail through."""
        self.assertFalse(channels.allowed("", ["14155550123"]))
        self.assertFalse(channels.allowed("   ", ["14155550123"]))

    def test_a_blank_entry_in_the_list_admits_nobody(self):
        """A trailing comma in settings must not become a wildcard."""
        self.assertFalse(channels.allowed("14155550123", ["", "  "]))


class ThePunctuationDoesNotLockTheFamilyOutTestCase(unittest.TestCase):
    """The quiet failure: a gate that is present, correct-looking, and
    matches nothing, because two APIs spell one number differently."""

    def test_a_phone_number_matches_however_it_is_written(self):
        for written in ("+1 (415) 555-0123", "1-415-555-0123", "+14155550123",
                        "1.415.555.0123", " 14155550123 "):
            with self.subTest(written=written):
                self.assertTrue(channels.allowed(written, ["14155550123"]),
                                f"{written!r} should be the same person")

    def test_the_allow_list_side_is_normalised_too(self):
        """The creator types the number into settings the way a person
        writes one."""
        self.assertTrue(channels.allowed("14155550123", ["+1 (415) 555-0123"]))

    def test_a_telegram_handle_matches_with_or_without_the_at(self):
        self.assertTrue(channels.allowed("@Saeed", ["saeed"]))
        self.assertTrue(channels.allowed("saeed", ["@Saeed"]))

    def test_a_handle_is_not_reduced_to_its_digits(self):
        """`normalise_sender` strips punctuation from phone-shaped
        values only: a handle with a digit in it stays itself, or two
        different people could collide."""
        self.assertEqual(channels.normalise_sender("saeed2"), "saeed2")
        self.assertNotEqual(channels.normalise_sender("saeed2"), "2")

    def test_two_different_handles_do_not_collide(self):
        self.assertFalse(channels.allowed("@aran", ["@ira"]))


if __name__ == "__main__":
    unittest.main()


class TheConsoleIsOneAnswer(unittest.TestCase):
    """`CONSOLE_CHANNELS` (2026-09-22): Guardian's `role_of`, Persona's
    attribution and World Model's People store used to carry three copies
    of `("", "cli")`; they now read this one (their own tests check they
    agree with it)."""

    def test_the_console_is_the_keyboard_and_nothing_else(self):
        self.assertEqual(channels.CONSOLE_CHANNELS, ("", "cli"))
        self.assertTrue(channels.is_console("cli"))
        self.assertTrue(channels.is_console(""))
        for other in ("voice", "api", "chat", "command", "telegram", "whatsapp", "initiative"):
            self.assertFalse(channels.is_console(other), other)

    def test_it_never_widens(self):
        """A message that does not say, or a spelling a caller did not
        normalise, is not the owner's keyboard."""
        self.assertFalse(channels.is_console(None))
        self.assertFalse(channels.is_console("CLI"))
        self.assertFalse(channels.is_console(" cli"))
