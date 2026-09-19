"""The token boundary (2026-09-18 evaluation, S15/V2).

Two rules, pinned: the cameras are never open (`/api/dash/streams`,
`/cameras/snap/`, `/tv/hls/` need the token like any gated route), and a
server bound to anything but this machine serves only the open routes
until a token is configured.
"""

import http.client
import asyncio
import unittest

import pytest

from simorgh.interface.httpapi import HttpApi

from .test_httpapi import _FakeBus

pytestmark = pytest.mark.contract


class _Base(unittest.IsolatedAsyncioTestCase):
    async def _start(self, *, host: str, token: str = "") -> HttpApi:
        api = HttpApi(_FakeBus({}), host=host, port=0, token=token)
        await api.start()
        self.addAsyncCleanup(api.stop)
        return api

    async def _get(self, api: HttpApi, path: str, *, bearer: str = "") -> http.client.HTTPResponse:
        def _do():
            conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=5)
            conn.request("GET", path, headers={"Authorization": f"Bearer {bearer}"} if bearer else {})
            resp = conn.getresponse()
            resp.body = resp.read()
            conn.close()
            return resp

        return await asyncio.to_thread(_do)


class TheCamerasAreNeverOpen(_Base):
    async def test_streams_stills_and_live_video_need_the_token(self):
        api = await self._start(host="127.0.0.1", token="secret")
        for path in ("/api/dash/streams", "/cameras/snap/driveway.jpg", "/tv/hls/1/index.m3u8"):
            resp = await self._get(api, path)
            self.assertEqual(resp.status, 401, path)
        # ...and the page's own `?token=` form still works for the video element.
        resp = await self._get(api, "/tv/hls/1/index.m3u8?token=secret")
        self.assertNotEqual(resp.status, 401)
        resp = await self._get(api, "/api/dash/streams", bearer="secret")
        self.assertNotEqual(resp.status, 401)

    async def test_wallpapers_and_the_pages_stay_open(self):
        api = await self._start(host="127.0.0.1", token="secret")
        for path in ("/", "/dash?token=secret", "/api/status", "/wallpapers/none.jpg"):
            resp = await self._get(api, path)
            self.assertNotEqual(resp.status, 401, path)


class ALanBindWithoutATokenServesOnlyTheOpenRoutes(_Base):
    async def test_gated_routes_are_refused_on_a_lan_bind_with_no_token(self):
        api = await self._start(host="0.0.0.0", token="")
        self.assertFalse(api.loopback_bind)
        self.assertEqual((await self._get(api, "/api/status")).status, 200)
        self.assertEqual((await self._get(api, "/api/dash/streams")).status, 401)
        self.assertEqual((await self._get(api, "/cameras/snap/driveway.jpg")).status, 401)

    async def test_on_this_machine_no_token_means_open(self):
        api = await self._start(host="127.0.0.1", token="")
        self.assertTrue(api.loopback_bind)
        self.assertNotEqual((await self._get(api, "/api/dash/streams")).status, 401)


class TheDashDataRouteWithholdsTheHouse(_Base):
    async def test_without_the_token_no_camera_is_listed(self):
        class _Feeds:
            async def start(self, *a, **k):
                return None

            async def stop(self, *a, **k):
                return None

            def snapshot(self):
                return {"news": {"top": ["x"]}, "cameras": [{"name": "Front"}], "streams": [{"url": "/tv/hls/1/"}],
                        "ring_cameras": [{"name": "Porch"}], "events": [{"camera": "Porch"}]}

        import json

        api = HttpApi(_FakeBus({}), host="127.0.0.1", port=0, token="secret", feeds=_Feeds())
        await api.start()
        self.addAsyncCleanup(api.stop)
        open_body = json.loads((await self._get(api, "/api/dash/data")).body)
        self.assertEqual(open_body["news"], {"top": ["x"]}, "the news tiles stay open")
        for key in ("cameras", "streams", "ring_cameras", "events"):
            self.assertNotIn(key, open_body)
        full = json.loads((await self._get(api, "/api/dash/data?token=secret")).body)
        self.assertEqual(full["cameras"], [{"name": "Front"}])
