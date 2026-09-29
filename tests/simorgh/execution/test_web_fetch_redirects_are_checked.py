"""Every redirect `web_fetch` follows is SSRF-checked, and a bearer token
does not follow a redirect to another host.

Confirmed live 2026-09-29: a public redirector pointed at
`http://127.0.0.1:8765/api/status` returned the running Sim's own status
-- only the first URL had been checked."""

from __future__ import annotations

import email.message
import io
import unittest
import urllib.request

from simorgh.execution.netsafety import FetchRefused
from simorgh.execution.tools import _CheckedRedirects


def _check(url: str) -> None:
    if "127.0.0.1" in url or "192.168." in url:
        raise FetchRefused(f"refusing {url!r}: resolves to a private/internal address")


class RedirectsAreChecked(unittest.TestCase):
    def _follow(self, start: str, to: str, *, token: bool = False):
        req = urllib.request.Request(start)
        if token:
            req.add_header("Authorization", "Bearer secret")
        headers = email.message.Message()
        headers["Location"] = to
        return _CheckedRedirects(_check).redirect_request(req, io.BytesIO(b""), 302, "Found", headers, to)

    def test_a_redirect_into_the_house_is_refused(self):
        with self.assertRaises(FetchRefused) as caught:
            self._follow("https://example.org/r", "http://127.0.0.1:8765/api/status")
        self.assertIn("refused a redirect", str(caught.exception))
        with self.assertRaises(FetchRefused):
            self._follow("https://example.org/r", "http://192.168.50.42/cgi-bin/api.cgi")

    def test_a_public_redirect_is_followed(self):
        new = self._follow("http://example.org/a", "https://example.org/b")
        self.assertEqual(new.full_url, "https://example.org/b")

    def test_a_token_stays_on_its_own_host(self):
        same = self._follow("https://api.github.com/a", "https://api.github.com/b", token=True)
        self.assertEqual(same.get_header("Authorization"), "Bearer secret")
        other = self._follow("https://api.github.com/a", "https://evil.example/b", token=True)
        self.assertIsNone(other.get_header("Authorization"))


if __name__ == "__main__":
    unittest.main()
