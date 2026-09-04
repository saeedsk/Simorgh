import socket
import unittest

from src.memory.long_term import InMemoryStore
from src.tools.web_fetch import FETCH_KIND, FetchRefused, WebFetchTool


class FakeResponse:
    def __init__(self, status: int, data: bytes):
        self.status = status
        self._data = data

    def read(self, n: int) -> bytes:
        return self._data[:n]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def fake_opener(response=None, exception=None, captured_requests=None):
    def opener(request, timeout=None):
        if captured_requests is not None:
            captured_requests.append(request)
        if exception is not None:
            raise exception
        return response

    return opener


def fake_resolver(ip: str):
    def resolver(host, port):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    return resolver


PUBLIC_IP = "93.184.216.34"  # a real, non-private example.com-range address


class TestWebFetchTool(unittest.TestCase):
    def _tool(self, ip=PUBLIC_IP, **kwargs):
        return WebFetchTool(
            InMemoryStore(), resolver=fake_resolver(ip), **kwargs
        )

    def test_fetch_returns_content(self):
        tool = self._tool(opener=fake_opener(response=FakeResponse(200, b"hello world")))

        result = tool.fetch("https://example.com")

        self.assertEqual(result.content, "hello world")
        self.assertEqual(result.status_code, 200)
        self.assertFalse(result.truncated)

    def test_rejects_non_http_scheme(self):
        tool = self._tool()

        with self.assertRaises(FetchRefused):
            tool.fetch("file:///etc/passwd")

    def test_rejects_ftp_scheme(self):
        tool = self._tool()

        with self.assertRaises(FetchRefused):
            tool.fetch("ftp://example.com/file")

    def test_rejects_missing_hostname(self):
        tool = self._tool()

        with self.assertRaises(FetchRefused):
            tool.fetch("https://")

    def test_rejects_loopback_address(self):
        tool = self._tool(ip="127.0.0.1")

        with self.assertRaises(FetchRefused):
            tool.fetch("https://localhost/")

    def test_rejects_private_range_address(self):
        tool = self._tool(ip="192.168.1.1")

        with self.assertRaises(FetchRefused):
            tool.fetch("https://internal.example/")

    def test_rejects_cloud_metadata_link_local_address(self):
        tool = self._tool(ip="169.254.169.254")

        with self.assertRaises(FetchRefused):
            tool.fetch("https://metadata.example/")

    def test_rejects_dns_resolution_failure(self):
        def failing_resolver(host, port):
            raise socket.gaierror("name resolution failed")

        tool = WebFetchTool(InMemoryStore(), resolver=failing_resolver)

        with self.assertRaises(FetchRefused):
            tool.fetch("https://does-not-resolve.invalid")

    def test_truncates_response_over_max_bytes(self):
        tool = self._tool(
            opener=fake_opener(response=FakeResponse(200, b"x" * 100)), max_bytes=10
        )

        result = tool.fetch("https://example.com")

        self.assertEqual(len(result.content), 10)
        self.assertTrue(result.truncated)

    def test_wraps_opener_exceptions_as_fetch_refused(self):
        tool = self._tool(opener=fake_opener(exception=TimeoutError("timed out")))

        with self.assertRaises(FetchRefused):
            tool.fetch("https://example.com")

    def test_enforces_rate_limit(self):
        store = InMemoryStore()
        tool = WebFetchTool(
            store,
            resolver=fake_resolver(PUBLIC_IP),
            opener=fake_opener(response=FakeResponse(200, b"ok")),
            max_calls=2,
        )

        tool.fetch("https://example.com/1")
        tool.fetch("https://example.com/2")

        with self.assertRaises(FetchRefused):
            tool.fetch("https://example.com/3")

    def test_logs_successful_fetch(self):
        store = InMemoryStore()
        tool = WebFetchTool(
            store,
            resolver=fake_resolver(PUBLIC_IP),
            opener=fake_opener(response=FakeResponse(200, b"ok")),
        )

        tool.fetch("https://example.com")

        records = store.query(kind=FETCH_KIND)
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0].metadata["succeeded"])

    def test_logs_failed_fetch(self):
        store = InMemoryStore()
        tool = WebFetchTool(
            store,
            resolver=fake_resolver(PUBLIC_IP),
            opener=fake_opener(exception=TimeoutError("timed out")),
        )

        with self.assertRaises(FetchRefused):
            tool.fetch("https://example.com")

        records = store.query(kind=FETCH_KIND)
        self.assertEqual(len(records), 1)
        self.assertFalse(records[0].metadata["succeeded"])

    def test_rejected_url_is_not_logged(self):
        store = InMemoryStore()
        tool = WebFetchTool(store, resolver=fake_resolver(PUBLIC_IP))

        with self.assertRaises(FetchRefused):
            tool.fetch("ftp://example.com")

        self.assertEqual(store.query(kind=FETCH_KIND), [])

    def test_sets_a_descriptive_user_agent_header(self):
        # Regression coverage: Python's default urllib User-Agent gets
        # blocked as bot traffic by major sites (Wikipedia among them) --
        # this was the actual root cause of a real 403 the creator hit.
        captured = []
        tool = self._tool(
            opener=fake_opener(response=FakeResponse(200, b"ok"), captured_requests=captured)
        )

        tool.fetch("https://example.com")

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].get_header("User-agent"), tool._user_agent)
        self.assertIn("Simorgh", tool._user_agent)
        self.assertNotIn("Mozilla", tool._user_agent)  # honest ID, not a spoofed browser

    def test_custom_user_agent_can_be_configured(self):
        captured = []
        tool = WebFetchTool(
            InMemoryStore(),
            resolver=fake_resolver(PUBLIC_IP),
            opener=fake_opener(response=FakeResponse(200, b"ok"), captured_requests=captured),
            user_agent="CustomBot/1.0",
        )

        tool.fetch("https://example.com")

        self.assertEqual(captured[0].get_header("User-agent"), "CustomBot/1.0")


if __name__ == "__main__":
    unittest.main()
