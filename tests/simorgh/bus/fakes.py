"""Bus-test fakes: an in-memory `Ledger` (the bus may not import
`simorgh.ledger`, so it never sees the real one), a fake boto3 session
that models SNS fan-out + SQS FIFO/DLQ well enough to drive the aws
backend end-to-end offline, and small async helpers."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from simorgh.contracts.envelope import Event


class FakeLedger:
    """Records appends per stream; can be told to fail to model an outage."""

    def __init__(self) -> None:
        self.streams: dict[str, list[Event]] = defaultdict(list)
        self.blobs: dict[str, bytes] = {}
        self.fail = False

    async def append(self, stream: str, event: Event, *, expected_seq: int | None = None) -> int:
        if self.fail:
            raise OSError("ledger down")
        seq = len(self.streams[stream]) + 1
        self.streams[stream].append(event.with_seq(seq) if hasattr(event, "with_seq") else Event(**{**event.to_dict(), "seq": seq}))
        return seq

    async def read(self, stream: str, *, from_seq: int = 0, limit: int | None = None) -> list[Event]:
        out = [e for e in self.streams.get(stream, []) if e.seq > from_seq]
        return out[:limit] if limit else out

    async def tail(self, stream: str, handler):  # pragma: no cover - unused by the bus
        raise NotImplementedError

    async def snapshot(self, stream: str, state: dict, at_seq: int) -> None:  # pragma: no cover
        return None

    async def load_snapshot(self, stream: str):  # pragma: no cover
        return None

    async def streams_(self, prefix: str) -> list[str]:  # pragma: no cover
        return [s for s in self.streams if s.startswith(prefix)]

    streams_list = streams_

    async def put_blob(self, data: bytes, *, content_type: str) -> str:
        if self.fail:
            raise OSError("ledger down")
        ref = "blob:" + hashlib.sha256(data).hexdigest()
        self.blobs[ref] = data
        return ref

    async def get_blob(self, ref: str) -> bytes:
        return self.blobs[ref]

    async def compact(self, stream: str, *, before_seq: int, keep_snapshot: bool = True) -> int:  # pragma: no cover
        return 0

    def types(self, stream: str) -> list[str]:
        return [e.type for e in self.streams.get(stream, [])]


async def pump(seconds: float = 0.05, *, step: float = 0.005) -> None:
    """Let the event loop run backend dispatchers for a little real time."""
    end = asyncio.get_running_loop().time() + seconds
    while asyncio.get_running_loop().time() < end:
        await asyncio.sleep(step)


async def wait_until(predicate, *, timeout: float = 2.0, step: float = 0.005) -> None:
    end = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > end:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(step)


# --------------------------------------------------------------------------- fake boto3
@dataclass
class _Queue:
    url: str
    arn: str
    fifo: bool
    messages: deque = field(default_factory=deque)  # (body, attributes, receive_count, invisible_until, group_id)
    attributes: dict = field(default_factory=dict)
    dedupe: set = field(default_factory=set)


class FakeSNS:
    def __init__(self, sqs: "FakeSQS") -> None:
        self._sqs = sqs
        self.topics: dict[str, str] = {}  # name -> arn
        self.subscriptions: list[tuple[str, str, dict]] = []  # (topic_arn, queue_url, filter)

    def create_topic(self, Name: str) -> dict:
        arn = self.topics.setdefault(Name, f"arn:aws:sns:fake:000:{Name}")
        return {"TopicArn": arn}

    def subscribe(self, TopicArn: str, Protocol: str, Endpoint: str, Attributes: dict | None = None) -> dict:
        filt = json.loads((Attributes or {}).get("FilterPolicy", "{}"))
        self.subscriptions.append((TopicArn, Endpoint, filt))
        return {"SubscriptionArn": f"{TopicArn}:{uuid.uuid4()}"}

    def publish(self, TopicArn: str, Message: str, MessageAttributes: dict | None = None, **kw: Any) -> dict:
        from simorgh.contracts.topics import matches

        mtype = (MessageAttributes or {}).get("type", {}).get("StringValue", "")
        for arn, url, filt in self.subscriptions:
            if arn != TopicArn:
                continue
            patterns = filt.get("pattern", [])
            if patterns and not any(matches(p, mtype) for p in patterns):
                continue
            self._sqs._deliver(url, Message, MessageAttributes or {}, kw.get("MessageGroupId"), kw.get("MessageDeduplicationId"))
        return {"MessageId": str(uuid.uuid4())}


class FakeSQS:
    def __init__(self, clock) -> None:
        self._clock = clock
        self.queues: dict[str, _Queue] = {}
        self.deleted: list[str] = []
        self.visibility_changes: list[tuple[str, int]] = []

    def create_queue(self, QueueName: str, Attributes: dict | None = None) -> dict:
        url = f"https://sqs.fake/{QueueName}"
        if url not in self.queues:
            self.queues[url] = _Queue(url=url, arn=f"arn:aws:sqs:fake:000:{QueueName}",
                                      fifo=QueueName.endswith(".fifo"), attributes=dict(Attributes or {}))
        return {"QueueUrl": url}

    def get_queue_attributes(self, QueueUrl: str, AttributeNames: list) -> dict:
        q = self.queues[QueueUrl]
        visible = sum(1 for m in q.messages if m[3] <= self._clock())
        return {"Attributes": {"QueueArn": q.arn, "ApproximateNumberOfMessages": str(visible), **q.attributes}}

    def _deliver(self, url: str, body: str, attrs: dict, group_id: str | None, dedupe_id: str | None) -> None:
        q = self.queues[url]
        if q.fifo and dedupe_id:
            if dedupe_id in q.dedupe:
                return
            q.dedupe.add(dedupe_id)
        q.messages.append([body, attrs, 0, 0.0, group_id])

    def send_message(self, QueueUrl: str, MessageBody: str, MessageAttributes: dict | None = None, **kw: Any) -> dict:
        self._deliver(QueueUrl, MessageBody, MessageAttributes or {}, kw.get("MessageGroupId"), kw.get("MessageDeduplicationId"))
        return {"MessageId": str(uuid.uuid4())}

    def receive_message(self, QueueUrl: str, MaxNumberOfMessages: int = 1, WaitTimeSeconds: int = 0, **kw: Any) -> dict:
        q = self.queues[QueueUrl]
        now = self._clock()
        out = []
        held_groups: set = set()
        for entry in q.messages:
            body, attrs, count, invisible_until, group_id = entry
            if invisible_until > now:
                if group_id:
                    held_groups.add(group_id)
                continue
            if q.fifo and group_id in held_groups:
                continue
            entry[2] = count + 1
            entry[3] = now + 30.0
            if group_id:
                held_groups.add(group_id)
            receipt = f"{QueueUrl}#{id(entry)}"
            out.append({"Body": body, "ReceiptHandle": receipt, "MessageAttributes": attrs,
                        "Attributes": {"ApproximateReceiveCount": str(entry[2])}})
            if len(out) >= MaxNumberOfMessages:
                break
        return {"Messages": out} if out else {}

    def _find(self, QueueUrl: str, receipt: str):
        q = self.queues[QueueUrl]
        for entry in q.messages:
            if f"{QueueUrl}#{id(entry)}" == receipt:
                return q, entry
        return q, None

    def delete_message(self, QueueUrl: str, ReceiptHandle: str) -> dict:
        q, entry = self._find(QueueUrl, ReceiptHandle)
        if entry is not None:
            q.messages.remove(entry)
            self.deleted.append(ReceiptHandle)
        return {}

    def change_message_visibility(self, QueueUrl: str, ReceiptHandle: str, VisibilityTimeout: int) -> dict:
        q, entry = self._find(QueueUrl, ReceiptHandle)
        if entry is not None:
            entry[3] = self._clock() + VisibilityTimeout
        self.visibility_changes.append((ReceiptHandle, VisibilityTimeout))
        return {}


class FakeBoto3Session:
    def __init__(self, clock) -> None:
        self.sqs = FakeSQS(clock)
        self.sns = FakeSNS(self.sqs)

    def client(self, name: str):
        return {"sns": self.sns, "sqs": self.sqs}[name]
