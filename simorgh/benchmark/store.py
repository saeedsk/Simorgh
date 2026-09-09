"""Where benchmark runs are kept, so today's number can be compared to
last week's.

The Ledger, not a file: a run is an event that happened, the Ledger is
this system's record of events that happened, and putting it anywhere
else would mean a second answer to "what has Sim done". One stream,
`benchmark:runs`, append-only.

Each run is stored twice over: a compact summary inline (the numbers the
history graph plots -- small enough to stay under the Ledger's inline
limit however many cases ran) and the full per-case detail as a blob.
The history view reads only the summaries, so plotting a year of runs
costs one stream read; `compare` fetches the two blobs it actually
needs.
"""

from __future__ import annotations

import json
from collections import deque

from simorgh.contracts.envelope import Event

from .api import RunRecord

STREAM = "benchmark:runs"


class RunStore:
    def __init__(self, ledger, clock=None) -> None:
        self._ledger = ledger
        self._clock = clock

    def _now(self) -> float:
        if self._clock is None:
            import time

            return time.time()
        return self._clock() if callable(self._clock) else self._clock.now()

    async def append(self, record: RunRecord) -> str:
        """Store `record`; returns the blob ref for its case detail."""
        detail_ref = ""
        try:
            detail_ref = await self._ledger.put_blob(
                json.dumps(record.to_payload(with_cases=True)).encode("utf-8"),
                content_type="application/json",
            )
        except Exception:  # noqa: BLE001 -- detail is a nicety; the summary is the record
            detail_ref = ""
        payload = record.to_payload(with_cases=False)
        payload["detail_ref"] = detail_ref
        await self._ledger.append(STREAM, Event(
            stream=STREAM, type="benchmark.run", ts=self._now(), trace_id=record.run_id,
            causation_id=None, payload=payload, idempotency_key=record.run_id,
        ))
        return detail_ref

    async def history(self, *, suite: str = "", model: str = "", limit: int = 100) -> list[RunRecord]:
        """Runs, oldest first, most recent `limit` after filtering.

        The filter is applied while streaming: only the last `limit`
        matching records are kept, so a long stream is not fully
        materialized when only recent runs are needed.
        """
        try:
            events = await self._ledger.read(STREAM)
        except Exception:  # noqa: BLE001 -- no stream yet is an empty history, not an error
            return []
        if limit > 0:
            kept: deque[RunRecord] = deque(maxlen=limit)
            for event in events:
                if event.type != "benchmark.run":
                    continue
                payload = event.payload
                if suite and payload.get("suite") != suite:
                    continue
                if model and payload.get("model") != model:
                    continue
                kept.append(RunRecord.from_payload(payload))
            return list(kept)
        records = []
        for event in events:
            if event.type != "benchmark.run":
                continue
            payload = event.payload
            if suite and payload.get("suite") != suite:
                continue
            if model and payload.get("model") != model:
                continue
            records.append(RunRecord.from_payload(payload))
        return records

    async def latest(self, *, suite: str = "", model: str = "") -> RunRecord | None:
        records = await self.history(suite=suite, model=model, limit=1)
        return records[-1] if records else None

    async def detail(self, run_id: str) -> RunRecord | None:
        """One run with its per-case results, read back from its blob."""
        try:
            events = await self._ledger.read(STREAM)
        except Exception:  # noqa: BLE001
            return None
        for event in reversed(events):
            if event.type == "benchmark.run" and event.payload.get("run_id") == run_id:
                ref = event.payload.get("detail_ref") or ""
                if not ref:
                    return RunRecord.from_payload(event.payload)
                try:
                    blob = await self._ledger.get_blob(ref)
                    return RunRecord.from_payload(json.loads(blob.decode("utf-8")))
                except Exception:  # noqa: BLE001 -- fall back to the summary
                    return RunRecord.from_payload(event.payload)
        return None


__all__ = ["STREAM", "RunStore"]
