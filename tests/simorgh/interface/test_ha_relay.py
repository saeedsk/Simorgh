"""Home Assistant relayed onto the tailnet for the phone away from home.

2026-09-27, the creator: "while I was outside home using the Sim app on
the iPhone over Tailscale, HA was not working". The app's HA tab opens HA's
LAN address; only the Mac is on the tailnet."""

import asyncio
import unittest

from simorgh.interface.harelay import HomeAssistantRelay, on_tailnet


class HomeAssistantRelayTest(unittest.IsolatedAsyncioTestCase):
    async def test_bytes_go_both_ways(self):
        async def fake_ha(reader, writer):
            line = await reader.readline()
            writer.write(b"HA saw " + line)
            await writer.drain()
            writer.close()

        ha = await asyncio.start_server(fake_ha, "127.0.0.1", 0)
        ha_port = ha.sockets[0].getsockname()[1]
        relay = HomeAssistantRelay(f"http://127.0.0.1:{ha_port}", "127.0.0.1", port=0)
        relay.port = 0
        self.assertTrue(await relay.start())
        port = relay._server.sockets[0].getsockname()[1]            # noqa: SLF001
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"GET /\n")
        await writer.drain()
        self.assertEqual(await asyncio.wait_for(reader.read(100), 5), b"HA saw GET /\n")
        writer.close()
        await relay.stop()
        ha.close()

    def test_only_a_tailnet_host_gets_the_relay(self):
        self.assertEqual(on_tailnet("saeeds-macbook-pro.taila5bf90.ts.net:8765"), "saeeds-macbook-pro.taila5bf90.ts.net")
        self.assertEqual(on_tailnet("100.71.125.30:8765"), "100.71.125.30")
        self.assertEqual(on_tailnet("192.168.50.33:8765"), "")
        self.assertEqual(on_tailnet(""), "")

    def test_the_url_uses_the_host_the_phone_came_by(self):
        relay = HomeAssistantRelay("http://192.168.50.208:8123", "100.71.125.30")
        self.assertEqual(relay.url_for("100.71.125.30"), "http://100.71.125.30:8124")

    async def test_nothing_to_relay_is_said(self):
        relay = HomeAssistantRelay("", "100.71.125.30")
        self.assertFalse(await relay.start())
        self.assertIn("not relayed", relay.detail)


if __name__ == "__main__":
    unittest.main()
