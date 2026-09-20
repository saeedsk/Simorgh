"""media/androidtv.py: the TV's own apps over the remote protocol (2026-09-13)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simorgh.domains.media import androidtv
from simorgh.domains.media.androidtv import AndroidTv, app_link, key_code


class InvalidAuth(Exception):
    pass


class FakeRemote:
    """The library's AndroidTVRemote, remembered."""

    instances: list = []
    pin = "ABC123"

    def __init__(self, client_name, certfile, keyfile, host, **_kw) -> None:
        self.client_name, self.certfile, self.keyfile, self.host = client_name, certfile, keyfile, host
        self.calls: list = []
        self.current_app = "com.google.android.youtube.tv"
        FakeRemote.instances.append(self)

    async def async_generate_cert_if_missing(self):
        Path(self.certfile).write_text("cert"); Path(self.keyfile).write_text("key")
        self.calls.append("cert")

    async def async_start_pairing(self):
        self.calls.append("start_pairing")

    async def async_finish_pairing(self, pin):
        self.calls.append(("finish_pairing", pin))
        if pin != FakeRemote.pin:
            raise InvalidAuth("wrong")

    async def async_connect(self):
        self.calls.append("connect")

    def send_launch_app_command(self, link):
        self.calls.append(("launch", link))

    def send_key_command(self, key):
        self.calls.append(("key", key))

    def disconnect(self):
        self.calls.append("disconnect")


class AndroidTvTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        FakeRemote.instances = []
        androidtv._PENDING.clear()

    def _tv(self) -> AndroidTv:
        return AndroidTv("10.0.0.9", certs_dir=Path(self.tmp.name), remote_cls=FakeRemote)

    async def test_pairing_is_the_persons_two_steps_and_a_wrong_code_says_so(self):
        tv = self._tv()
        self.assertFalse(tv.paired())
        self.assertIn("not paired", await tv.launch("https://www.youtube.com/watch?v=x"), "nothing before pairing")
        self.assertEqual(await tv.pair_start(), "")
        self.assertEqual(FakeRemote.instances[-1].calls, ["cert", "start_pairing"])
        self.assertFalse(tv.paired(), "a code on the TV is not a pairing yet")
        self.assertIn("did not match", await tv.pair_finish("000000"))
        self.assertEqual(await tv.pair_finish("abc 123"), "", "the code, however it was typed")
        self.assertTrue(tv.paired())
        self.assertIn("no pairing is under way", await AndroidTv("10.0.0.9", certs_dir=Path(self.tmp.name),
                                                                remote_cls=FakeRemote).pair_finish("ABC123")
                      if False else await tv.pair_finish("ABC123"))

    async def test_a_link_opens_the_app_and_a_key_is_pressed_over_a_fresh_connection(self):
        tv = self._tv()
        await tv.pair_start(); await tv.pair_finish(FakeRemote.pin)
        self.assertEqual(await tv.launch("https://www.youtube.com/watch?v=RqfZ3UTC14c"), "")
        remote = FakeRemote.instances[-1]
        self.assertEqual(remote.calls, ["connect", ("launch", "https://www.youtube.com/watch?v=RqfZ3UTC14c"), "disconnect"])
        self.assertEqual(await tv.key("volume up"), "")
        self.assertEqual(FakeRemote.instances[-1].calls[1], ("key", "VOLUME_UP"))
        self.assertEqual(await tv.current_app(), "com.google.android.youtube.tv")

    def test_apps_and_keys_are_named_the_way_people_say_them(self):
        self.assertEqual(app_link("YouTube"), "https://www.youtube.com/")
        self.assertEqual(app_link("https://www.netflix.com/title/80057281"), "https://www.netflix.com/title/80057281")
        self.assertEqual(app_link("solitaire"), "")
        self.assertEqual(key_code("Play Pause"), "MEDIA_PLAY_PAUSE")
        self.assertEqual(key_code("ok"), "DPAD_CENTER")
        self.assertEqual(key_code("DPAD_UP"), "DPAD_UP")
        self.assertEqual(key_code(""), "")
