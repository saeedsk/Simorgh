"""A secret an error message tells you to set must be readable.

Live, 2026-09-20. `contracts/home/client.py` says, when Home
Assistant is not configured: "generate a long-lived access token on
your HA profile page and set HOME_ASSISTANT_TOKEN". The creator did
-- and `DEFAULT_SECRETS["execution"]` was `{"vault:*"}`, so the
scoped store handed the tool nothing and Sim answered "I can't reach
Home Assistant, it's not configured" with the token in the file,
correctly spelled.

The keys had originally been written as `vault:home_assistant:url`,
which reaches through `vault:*`. That spelling is not valid TOML --
a colon in a bare key -- so the file failed to parse and the boot
died; I renamed them to the plain names to fix that and moved them
out of scope instead. One bug traded for another, in the same file,
the same evening.

This is the assertion that would have caught either: every secret a
client NAMES as its requirement must be one the scope actually
allows.
"""

import unittest

from simorgh.kernel.registry import DEFAULT_SECRETS
from simorgh.kernel.secrets import ScopedSecretStore


class _Store:
    """A backing store that has every name, so the only thing under
    test is whether the scope lets it through."""

    @staticmethod
    def get(name: str) -> str:
        return f"value-of-{name}"


def _allowed(name: str, scope: str = "execution") -> bool:
    return bool(ScopedSecretStore(_Store(), DEFAULT_SECRETS[scope]).get(name))


class WhatTheHomeClientAsksFor(unittest.TestCase):
    def test_every_name_it_advertises_is_in_scope(self):
        from simorgh.contracts.home.client import HomeAssistantClient

        # Read off the class rather than retyped: the point is that
        # the code's own list and the scope agree, so a test that
        # spells the names itself would pass while they diverged.
        client = HomeAssistantClient.__new__(HomeAssistantClient)
        client.__init__(url="", token="")
        for name in client.needs:
            self.assertTrue(_allowed(name), f"{name} is advertised to the person and blocked by the scope")

    def test_the_vault_spelling_still_works(self):
        """The creator's file used `vault:home_assistant:token`, and a
        working setup must not break because a newer one was added."""
        self.assertTrue(_allowed("vault:home_assistant:token"))

    def test_the_scope_is_still_a_scope(self):
        """`vault:*` plus two names, not an open door: the whole point
        of a scoped store is that Execution cannot read the Telegram
        token or the API key."""
        for name in ("SIM_TELEGRAM_TOKEN", "TOGETHER_API_KEY", "SIM_API_TOKEN", "ANYTHING_ELSE"):
            self.assertFalse(_allowed(name), f"{name} should not be readable by execution")


class WhatCognitionAsksFor(unittest.TestCase):
    def test_the_provider_keys_are_in_its_scope(self):
        """The same shape, one subsystem over: a key in secrets.toml
        never reached the provider until 2026-09-19."""
        for name in ("TOGETHER_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
            self.assertTrue(_allowed(name, "cognition"), name)

    def test_cognition_cannot_read_the_house(self):
        self.assertFalse(_allowed("HOME_ASSISTANT_TOKEN", "cognition"))


if __name__ == "__main__":
    unittest.main()
