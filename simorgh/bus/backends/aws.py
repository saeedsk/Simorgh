"""AWS backend (docs/blueprint/subsystems/01-bus.md section 5.5): one SNS
topic per domain, one SQS queue per consumer group (FIFO, ordered by
`MessageGroupId = partition_key`, deduplicated by message id) and one
standard queue per broadcast subscription, a DLQ via redrive policy
plus the Ledger `dead:*` copy written by the consumer on final failure,
and a per-process temporary queue as the request/reply inbox.

Optional, never required (01 section 4.14): `boto3` is imported lazily;
if it is missing the backend raises `BackendUnavailable` at construction
so the misconfiguration surfaces at startup with a clear message, not
at the first publish. The AWS API is reached only through the injected
`session` factory, so tests drive this backend end-to-end with a fake
boto3 and never touch the network.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Callable

from simorgh.contracts.envelope import Message
from simorgh.contracts.topics import domain_of, matches

from ..api import BackendUnavailable, BusSubscription, DeadLetterHook, Delivery, Handler, SubscriptionSpec
from ..router import Registered, is_inbox, is_reply_routed

try:  # optional adapter
    import boto3  # type: ignore
except ImportError:  # pragma: no cover -- exercised via the fake in tests
    boto3 = None

Clock = Callable[[], float]


class AwsBackend:
    name = "aws"

    def __init__(
        self,
        *,
        clock: Clock,
        region: str,
        topic_prefix: str,
        queue_prefix: str,
        max_deliveries: int = 5,
        wait_time_seconds: int = 1,
        session: Any | None = None,
    ) -> None:
        if session is None:
            if boto3 is None:
                raise BackendUnavailable("bus backend 'aws' requires boto3, which is not installed")
            session = boto3.session.Session(region_name=region)
        self._sns = session.client("sns")
        self._sqs = session.client("sqs")
        self._clock = clock
        self._topic_prefix = topic_prefix
        self._queue_prefix = queue_prefix
        self._max_deliveries = max_deliveries
        self._wait = wait_time_seconds
        self._topics: dict[str, str] = {}  # domain -> topic arn
        self._registered: dict[str, Registered] = {}
        self._queues: dict[str, str] = {}  # sub id or group -> queue url
        self._pollers: dict[str, asyncio.Task] = {}
        self._state = "running"
        self._dead_hook: DeadLetterHook | None = None
        self._inflight_tasks: set[asyncio.Task] = set()
        self._receipts: dict[str, tuple[str, str]] = {}  # delivery_id -> (queue_url, receipt)
        self._active: dict[str, Delivery] = {}
        self._explicit: dict[str, tuple[str, float | None]] = {}

    # -- lifecycle -----------------------------------------------------------
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        self._state = "stopping"
        for task in self._pollers.values():
            task.cancel()
        await asyncio.gather(*self._pollers.values(), *self._inflight_tasks, return_exceptions=True)
        self._pollers.clear()

    def set_state(self, state: str) -> None:
        self._state = state

    def set_dead_letter_hook(self, hook: DeadLetterHook | None) -> None:
        self._dead_hook = hook

    # -- provisioning -----------------------------------------------------------
    def _topic_arn(self, domain: str) -> str:
        arn = self._topics.get(domain)
        if arn is None:
            arn = self._sns.create_topic(Name=f"{self._topic_prefix}-{domain}")["TopicArn"]
            self._topics[domain] = arn
        return arn

    def _ensure_queue(self, key: str, *, fifo: bool) -> str:
        url = self._queues.get(key)
        if url is not None:
            return url
        name = f"{self._queue_prefix}-{key}".replace(":", "-").replace("_", "-")
        if fifo:
            name += ".fifo"
        attrs: dict[str, str] = {"FifoQueue": "true", "ContentBasedDeduplication": "false"} if fifo else {}
        dlq_name = name.replace(".fifo", "") + "-dlq" + (".fifo" if fifo else "")
        dlq = self._sqs.create_queue(QueueName=dlq_name, Attributes={"FifoQueue": "true"} if fifo else {})
        dlq_arn = self._sqs.get_queue_attributes(QueueUrl=dlq["QueueUrl"], AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
        attrs["RedrivePolicy"] = json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": self._max_deliveries})
        url = self._sqs.create_queue(QueueName=name, Attributes=attrs)["QueueUrl"]
        self._queues[key] = url
        return url

    # -- registration ------------------------------------------------------------
    async def register(self, spec: SubscriptionSpec, handler: Handler) -> BusSubscription:
        sub_id = str(uuid.uuid4())
        reg = Registered(id=sub_id, spec=spec, handler=handler)
        self._registered[sub_id] = reg
        key = spec.group if spec.group is not None else sub_id
        fifo = spec.group is not None
        url = self._ensure_queue(key, fifo=fifo)
        if is_inbox(spec.pattern):
            # replies are published straight to the inbox queue; no SNS subscription
            pass
        else:
            for domain in self._domains_for(spec.pattern):
                self._sns.subscribe(
                    TopicArn=self._topic_arn(domain), Protocol="sqs", Endpoint=url,
                    Attributes={"FilterPolicy": json.dumps({"pattern": [spec.pattern]}), "RawMessageDelivery": "true"},
                )
        if key not in self._pollers:
            self._pollers[key] = asyncio.create_task(self._poll(key, url), name=f"bus-aws-{key}")

        async def _unsub() -> None:
            self._registered.pop(sub_id, None)
            if spec.group is None:
                task = self._pollers.pop(key, None)
                if task:
                    task.cancel()

        return BusSubscription(pattern=spec.pattern, id=sub_id, _unsubscribe=_unsub)

    @staticmethod
    def _domains_for(pattern: str) -> list[str]:
        first = pattern.split(".")[0]
        if first in ("*", "#"):
            from simorgh.contracts.topics import DOMAINS
            return list(DOMAINS)
        return [first]

    # -- enqueue -------------------------------------------------------------------
    async def enqueue(self, message: Message) -> None:
        body = message.to_json()
        if is_reply_routed(message):
            for reg in self._registered.values():
                if reg.spec.pattern == message.reply_to:
                    self._sqs.send_message(QueueUrl=self._queues[reg.id], MessageBody=body,
                                           MessageAttributes={"type": {"DataType": "String", "StringValue": message.type}})
            return
        params: dict[str, Any] = {
            "TopicArn": self._topic_arn(domain_of(message.type)),
            "Message": body,
            "MessageAttributes": {
                "type": {"DataType": "String", "StringValue": message.type},
                "priority": {"DataType": "Number", "StringValue": str(message.priority)},
            },
        }
        if message.partition_key is not None:
            params["MessageGroupId"] = message.partition_key
        params["MessageDeduplicationId"] = message.id
        self._sns.publish(**params)

    async def depth(self, group: str) -> int:
        url = self._queues.get(group)
        if url is None:
            return 0
        attrs = self._sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["ApproximateNumberOfMessages"])["Attributes"]
        return int(attrs.get("ApproximateNumberOfMessages", 0))

    # -- polling --------------------------------------------------------------------
    async def _poll(self, key: str, url: str) -> None:
        while True:
            if self._state == "stopping":
                return
            try:
                resp = await asyncio.to_thread(
                    self._sqs.receive_message, QueueUrl=url, MaxNumberOfMessages=10,
                    WaitTimeSeconds=self._wait, MessageAttributeNames=["All"], AttributeNames=["ApproximateReceiveCount"],
                )
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                await asyncio.sleep(1.0)
                continue
            for raw in resp.get("Messages", []) or []:
                message = Message.from_json(raw["Body"])
                if self._state == "paused" and key in {r.spec.group for r in self._registered.values()} and not message.type.startswith("system."):
                    continue  # leave it in the queue (visibility timeout returns it)
                regs = [r for r in self._registered.values() if (r.spec.group == key) or (r.id == key)]
                if not regs:
                    continue
                reg = next((r for r in regs if r.spec.pattern == message.reply_to), None) if is_reply_routed(message) else \
                    next((r for r in regs if matches(r.spec.pattern, message.type)), None)
                if reg is None:
                    continue
                attempt = int(raw.get("Attributes", {}).get("ApproximateReceiveCount", 1))
                delivery = Delivery(message=message, attempt=attempt, lease_until=self._clock() + 30.0,
                                    group=reg.spec.group, subscription_id=reg.id, delivery_id=raw["ReceiptHandle"])
                self._receipts[delivery.delivery_id] = (url, raw["ReceiptHandle"])
                task = asyncio.create_task(self._run(reg, delivery))
                self._inflight_tasks.add(task)
                task.add_done_callback(self._inflight_tasks.discard)
            await asyncio.sleep(0)

    async def _run(self, reg: Registered, d: Delivery) -> None:
        url, receipt = self._receipts.pop(d.delivery_id)
        self._active[d.message.id] = d
        explicit_nack: float | None | bool = False
        try:
            await reg.handler(d.message)
            explicit = self._explicit.pop(d.delivery_id, None)
            if explicit is not None and explicit[0] == "nack" and d.group is not None:
                explicit_nack = explicit[1]
                raise _ExplicitNack()
            self._sqs.delete_message(QueueUrl=url, ReceiptHandle=receipt)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001
            if d.group is None:
                self._sqs.delete_message(QueueUrl=url, ReceiptHandle=receipt)  # broadcast: dropped, not retried
            elif d.attempt < self._max_deliveries:
                backoff = explicit_nack if isinstance(explicit_nack, (int, float)) else min(60, 2 ** (d.attempt - 1))
                self._sqs.change_message_visibility(QueueUrl=url, ReceiptHandle=receipt, VisibilityTimeout=int(backoff))
            else:
                self._sqs.delete_message(QueueUrl=url, ReceiptHandle=receipt)  # redrive would also move it; we record it
                if self._dead_hook is not None:
                    await self._dead_hook(d, "max_deliveries", repr(exc))
        finally:
            if self._active.get(d.message.id) is d:
                del self._active[d.message.id]

    def _current_delivery_for(self, message: Message) -> Delivery | None:
        return self._active.get(message.id)

    async def ack(self, delivery: Delivery) -> None:
        self._explicit[delivery.delivery_id] = ("ack", None)

    async def nack(self, delivery: Delivery, *, retry_after: float | None) -> None:
        self._explicit[delivery.delivery_id] = ("nack", retry_after)


class _ExplicitNack(Exception):
    """Internal: a handler asked for a nack after returning normally."""


__all__ = ["AwsBackend", "boto3"]
