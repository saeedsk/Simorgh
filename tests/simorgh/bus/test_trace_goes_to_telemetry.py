"""Stage 1 item 3: a traced message is a span, not a ledger stream."""

import unittest

from simorgh.bus.trace import TraceWriter
from simorgh.contracts.envelope import Message


class _Telemetry:
    def __init__(self):
        self.events = []

    def event(self, name, **kw):
        self.events.append((name, kw))


class _Ledger:
    def __init__(self):
        self.appends = []

    async def append(self, stream, event):
        self.appends.append(stream)

    async def put_blob(self, body, content_type=""):
        return "blob:x"


class ATracedMessageIsASpan(unittest.IsolatedAsyncioTestCase):
    async def test_the_span_carries_id_parent_and_source_and_no_stream_is_written(self):
        telemetry, ledger = _Telemetry(), _Ledger()
        writer = TraceWriter(ledger, telemetry=telemetry)
        cause = Message.new("percept.text.received", source="interface", payload={"text": "hi"})
        effect = cause.caused("cognition.think", {"purpose": "chat"}, source="orchestration")
        for m in (cause, effect):
            writer.write(m)
        await writer.stop()
        self.assertEqual(ledger.appends, [])
        (n1, a), (n2, b) = telemetry.events
        self.assertEqual((n1, a["span_id"], a["trace_id"]), ("percept.text.received", cause.id, cause.trace_id))
        self.assertEqual((n2, b["parent_id"], b["attrs"]["source"]), ("cognition.think", cause.id, "orchestration"))
        self.assertIsNone(await writer.write_blob_body(Message.new("percept.text.received", source="s", payload={"text": "y" * 10_000})))

    async def test_the_ledger_backend_is_kept_behind_the_switch(self):
        telemetry, ledger = _Telemetry(), _Ledger()
        writer = TraceWriter(ledger, telemetry=telemetry, backend="ledger")
        m = Message.new("percept.text.received", source="interface", payload={})
        writer.write(m)
        await writer.flush()
        await writer.stop()
        self.assertEqual(telemetry.events, [])
        self.assertEqual(ledger.appends, [f"trace:{m.trace_id}"])


if __name__ == "__main__":
    unittest.main()
