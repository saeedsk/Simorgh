"""Live 2026-09-19: "put dashboard on tv" reported success while the TV
showed Google TV's ambient screen (Glance). The remote connection had been
failing on a stale protobuf extension, and a cast loads behind the ambient
screen."""

from __future__ import annotations

import asyncio
import types
import unittest
from pathlib import Path

from simorgh.contracts.protocols import ToolContext
from simorgh.execution.config import Config
from simorgh.execution.media import androidtv
from simorgh.execution.media.cast import Device, cast_tools


class TheDebugLineCannotCloseTheConnection(unittest.TestCase):
    def test_a_formatter_that_raises_returns_a_placeholder(self):
        class _Broken:
            def MessageToString(self, message, **kw):  # noqa: N802
                raise AttributeError("'FieldDescriptor' object has no attribute 'is_repeated'")

            other = "kept"

        safe = androidtv._SafeTextFormat(_Broken())  # noqa: SLF001
        self.assertEqual(safe.MessageToString(object(), as_one_line=True), "<object>")
        self.assertEqual(safe.other, "kept")


class _Remote:
    """current_app arrives a moment after connecting, as the TV sends it."""

    app = "com.google.android.backdrop"

    def __init__(self, *args):
        self.current_app = ""

    async def async_connect(self):
        async def later():
            await asyncio.sleep(0.2)
            self.current_app = _Remote.app
        asyncio.get_running_loop().create_task(later())

    def send_key_command(self, code):
        pass

    def disconnect(self):
        pass


class _Cast:
    def devices(self):
        return [Device(name="Family Room TV", model="Chromecast", host="10.0.0.9")]

    def show_page(self, name, url):
        pass


def _ctx():
    return ToolContext(action_id="a", task_id=None, scope={}, constraints={}, data_dir=Path("."), clock=None,
                       logger=None, ledger=None, bus=None)


class TheCastIsCheckedAgainstTheScreen(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        certs = Path(self.tmp.name)
        for name in ("androidtv-cert.pem", "androidtv-key.pem", "paired-10.0.0.9"):
            (certs / name).write_text("x")
        self.tools = {t.name: t for t in cast_tools(Config(cast_page_url="http://10.0.0.5:8765/tv"), cast=_Cast(),
                                                    reachable=lambda url: True, env={"SIM_API_TOKEN": "t"})}
        for tool in self.tools.values():
            tool._remote_cls = _Remote  # noqa: SLF001
            tool._certs_dir = certs  # noqa: SLF001
            tool._WAKE_SETTLE_S = 0.0  # noqa: SLF001

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def test_current_app_waits_for_the_tv_to_say(self):
        _Remote.app = "com.google.android.backdrop"
        tv = androidtv.AndroidTv("10.0.0.9", certs_dir=Path(self.tmp.name), remote_cls=_Remote)
        self.assertEqual(await tv.current_app(), "com.google.android.backdrop")

    async def test_a_cast_behind_the_ambient_screen_is_not_reported_up(self):
        _Remote.app = "com.google.android.backdrop"
        result = await self.tools["cast_show"].run({}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("ambient screen", result.error)

    async def test_a_cast_in_front_is_up(self):
        _Remote.app = "com.google.android.apps.mediashell"
        result = await self.tools["cast_show"].run({}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)


if __name__ == "__main__":
    unittest.main()
