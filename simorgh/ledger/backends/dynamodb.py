"""DynamoDB + S3 backend (02-ledger section 4.4), optional. Table: PK
`stream` (S), SK `seq` (N); a conditional put (`attribute_not_exists(seq)`)
is the compare-and-swap, so a lost race is a `ConflictError` exactly as
on `sqlite`. Snapshots live at SK `-1`; blobs and oversized payloads go
to S3.

The backend talks to two tiny adapter protocols (`DynamoTable`,
`BlobBucket`) rather than to boto3 directly. `Boto3Table`/`Boto3Bucket`
implement them with a *lazy* `boto3` import (no dependency in the core
-- 01 principle 4.14), and tests exercise the whole backend through
in-memory fakes of the same two protocols, so the CAS/idempotency/
snapshot logic is verified without credentials or a network.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from simorgh.contracts.envelope import Event, canonical_json

from ..api import BackendUnavailable, BlobNotFound, ConflictError, LedgerUnavailable
from ..blobs import parse_ref, sha256_hex
from ..streams import validate_stream

SNAPSHOT_SK = -1


class DynamoTable(Protocol):
    def put_if_absent(self, item: dict) -> bool: ...          # False when (stream, seq) exists

    def put(self, item: dict) -> None: ...                     # unconditional (snapshots)

    def get(self, stream: str, seq: int) -> dict | None: ...

    def latest(self, stream: str) -> dict | None: ...          # highest seq >= 1

    def range(self, stream: str, from_seq: int, limit: int | None) -> list[dict]: ...

    def find_idem(self, stream: str, key: str) -> int | None: ...

    def delete(self, stream: str, seq: int) -> None: ...

    def list_streams(self, prefix: str) -> list[str]: ...


class BlobBucket(Protocol):
    def put(self, key: str, data: bytes, *, content_type: str) -> None: ...

    def get(self, key: str) -> bytes | None: ...

    def stat(self) -> dict: ...


class DynamoBackend:
    cross_process = True

    def __init__(
        self,
        table_name: str,
        bucket_name: str,
        *,
        table: DynamoTable | None = None,
        bucket: BlobBucket | None = None,
        payload_spill_bytes: int = 350_000,
    ) -> None:
        self.table_name, self.bucket_name = table_name, bucket_name
        self._table = table
        self._bucket = bucket
        self._spill = payload_spill_bytes

    async def start(self) -> None:
        if self._table is None or self._bucket is None:
            self._table, self._bucket = _boto3_adapters(self.table_name, self.bucket_name)

    async def stop(self) -> None:
        return None

    # ------------------------------------------------------------------- core
    async def head(self, stream: str) -> int:
        item = self._table.latest(stream)  # type: ignore[union-attr]
        return int(item["seq"]) if item else 0

    def _item_from_event(self, event: Event, seq: int) -> dict:
        payload_json = canonical_json(event.payload)
        item: dict[str, Any] = {
            "stream": event.stream, "seq": seq, "type": event.type, "ts": event.ts,
            "trace_id": event.trace_id, "causation_id": event.causation_id,
            "idempotency_key": event.idempotency_key,
        }
        if len(payload_json.encode("utf-8")) > self._spill:
            key = f"payloads/{event.stream}/{seq}"
            self._bucket.put(key, payload_json.encode("utf-8"), content_type="application/json")  # type: ignore[union-attr]
            item["payload_ref"] = key
        else:
            item["payload"] = payload_json
        return item

    def _event_from_item(self, item: dict) -> Event:
        if "payload_ref" in item:
            data = self._bucket.get(item["payload_ref"])  # type: ignore[union-attr]
            if data is None:
                raise LedgerUnavailable(f"missing spilled payload {item['payload_ref']}")
            payload = json.loads(data.decode("utf-8"))
        else:
            payload = json.loads(item["payload"])
        return Event(stream=item["stream"], seq=int(item["seq"]), type=item["type"], ts=float(item["ts"]),
                     trace_id=item.get("trace_id"), causation_id=item.get("causation_id"),
                     idempotency_key=item.get("idempotency_key"), payload=payload)

    async def append(self, event: Event, *, expected_seq: int | None) -> int:
        validate_stream(event.stream)
        head = await self.head(event.stream)
        if expected_seq is not None and expected_seq != head:
            raise ConflictError(event.stream, expected_seq, head)
        seq = head + 1
        if not self._table.put_if_absent(self._item_from_event(event, seq)):  # type: ignore[union-attr]
            raise ConflictError(event.stream, expected_seq if expected_seq is not None else head, head)
        return seq

    async def find_by_idempotency(self, stream: str, key: str) -> int | None:
        return self._table.find_idem(stream, key)  # type: ignore[union-attr]

    async def read(self, stream: str, *, from_seq: int, limit: int | None) -> list[Event]:
        items = self._table.range(stream, max(from_seq, 1), limit)  # type: ignore[union-attr]
        return [self._event_from_item(i) for i in items]

    async def streams(self, prefix: str) -> list[str]:
        return sorted(self._table.list_streams(prefix))  # type: ignore[union-attr]

    # -------------------------------------------------------------- snapshots
    async def write_snapshot(self, stream: str, state: dict, at_seq: int) -> None:
        self._table.put({"stream": stream, "seq": SNAPSHOT_SK, "at_seq": at_seq, "state": json.dumps(state)})  # type: ignore[union-attr]

    async def read_snapshot(self, stream: str) -> tuple[dict, int] | None:
        item = self._table.get(stream, SNAPSHOT_SK)  # type: ignore[union-attr]
        if not item:
            return None
        try:
            return dict(json.loads(item["state"])), int(item["at_seq"])
        except (KeyError, ValueError, TypeError):
            return None

    async def delete_snapshot(self, stream: str) -> None:
        self._table.delete(stream, SNAPSHOT_SK)  # type: ignore[union-attr]

    # ------------------------------------------------------------- compaction
    async def truncate_below(self, stream: str, seq: int) -> int:
        removed = 0
        for item in self._table.range(stream, 1, None):  # type: ignore[union-attr]
            if int(item["seq"]) < seq:
                self._table.delete(stream, int(item["seq"]))  # type: ignore[union-attr]
                removed += 1
        return removed

    async def delete_stream(self, stream: str) -> None:
        for item in self._table.range(stream, 1, None):  # type: ignore[union-attr]
            self._table.delete(stream, int(item["seq"]))  # type: ignore[union-attr]
        self._table.delete(stream, SNAPSHOT_SK)  # type: ignore[union-attr]

    # ------------------------------------------------------------------ blobs
    async def put_blob(self, data: bytes, *, content_type: str) -> str:
        digest = sha256_hex(data)
        self._bucket.put(f"blobs/{digest}", data, content_type=content_type)  # type: ignore[union-attr]
        return f"blob:{digest}"

    async def get_blob(self, ref: str) -> bytes:
        digest = parse_ref(ref)
        data = self._bucket.get(f"blobs/{digest}")  # type: ignore[union-attr]
        if data is None:
            raise BlobNotFound(ref)
        return data

    async def stat(self) -> dict:
        streams = self._table.list_streams("")  # type: ignore[union-attr]
        return {"streams": len(streams), "table": self.table_name, "bucket": self.bucket_name,
                **self._bucket.stat()}  # type: ignore[union-attr]

    async def last_ts(self, stream: str) -> float | None:
        item = self._table.latest(stream)  # type: ignore[union-attr]
        return float(item["ts"]) if item else None


def _boto3_adapters(table_name: str, bucket_name: str) -> tuple[DynamoTable, BlobBucket]:
    try:
        import boto3  # type: ignore[import-not-found]
        from boto3.dynamodb.conditions import Key  # type: ignore[import-not-found]
    except ImportError:
        raise BackendUnavailable("the dynamodb ledger backend needs boto3, which is not installed") from None

    table = boto3.resource("dynamodb").Table(table_name)
    s3 = boto3.client("s3")

    class Boto3Table:
        def put_if_absent(self, item: dict) -> bool:
            try:
                table.put_item(Item=item, ConditionExpression="attribute_not_exists(seq)")
                return True
            except Exception as exc:  # noqa: BLE001 -- botocore ClientError, matched by code
                if "ConditionalCheckFailed" in type(exc).__name__ or "ConditionalCheckFailed" in str(exc):
                    return False
                raise LedgerUnavailable(str(exc)) from None

        def put(self, item: dict) -> None:
            table.put_item(Item=item)

        def get(self, stream: str, seq: int) -> dict | None:
            return table.get_item(Key={"stream": stream, "seq": seq}).get("Item")

        def latest(self, stream: str) -> dict | None:
            items = table.query(KeyConditionExpression=Key("stream").eq(stream) & Key("seq").gte(1),
                                ScanIndexForward=False, Limit=1).get("Items", [])
            return items[0] if items else None

        def range(self, stream: str, from_seq: int, limit: int | None) -> list[dict]:
            kwargs: dict[str, Any] = {"KeyConditionExpression": Key("stream").eq(stream) & Key("seq").gte(from_seq)}
            if limit is not None:
                kwargs["Limit"] = limit
            return table.query(**kwargs).get("Items", [])

        def find_idem(self, stream: str, key: str) -> int | None:
            items = table.query(IndexName="idem", KeyConditionExpression=Key("stream").eq(stream)
                                & Key("idempotency_key").eq(key)).get("Items", [])
            return int(items[0]["seq"]) if items else None

        def delete(self, stream: str, seq: int) -> None:
            table.delete_item(Key={"stream": stream, "seq": seq})

        def list_streams(self, prefix: str) -> list[str]:
            seen: set[str] = set()
            kwargs: dict[str, Any] = {"ProjectionExpression": "stream"}
            while True:
                page = table.scan(**kwargs)
                seen.update(i["stream"] for i in page.get("Items", []) if i["stream"].startswith(prefix))
                if "LastEvaluatedKey" not in page:
                    return sorted(seen)
                kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    class Boto3Bucket:
        def put(self, key: str, data: bytes, *, content_type: str) -> None:
            s3.put_object(Bucket=bucket_name, Key=key, Body=data, ContentType=content_type)

        def get(self, key: str) -> bytes | None:
            try:
                return s3.get_object(Bucket=bucket_name, Key=key)["Body"].read()
            except Exception:  # noqa: BLE001 -- NoSuchKey and friends
                return None

        def stat(self) -> dict:
            return {"blobs": None, "blob_bytes": None}

    return Boto3Table(), Boto3Bucket()


__all__ = ["BlobBucket", "DynamoBackend", "DynamoTable", "SNAPSHOT_SK"]
