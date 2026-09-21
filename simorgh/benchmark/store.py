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
#: A mark on the stream: history reads forward from the last one.
CLEARED = "benchmark.cleared"


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

    async def clear(self, *, model: str = "", everything: bool = False) -> int:
        """Forget recorded runs, for one model or for all of them.

        Not a deletion. The Ledger is append-only on purpose -- a log
        that can be rewritten cannot be evidence of anything -- so a
        clear appends a MARK, and `history` reads forward from it.
        What happened is still on the stream for anyone who goes
        looking; what the history SHOWS starts again from here.

        Returns how many runs the history will stop showing, which is
        the number a person actually wants back ("cleared 14 runs"),
        not the number of events written.
        """
        before = len(await self.history(model="" if everything else model, limit=0))
        await self._ledger.append(STREAM, Event(
            stream=STREAM, type=CLEARED, ts=self._now(), trace_id=STREAM, causation_id=None,
            payload={"model": "" if everything else model, "all": bool(everything)},
        ))
        return before

    async def _cleared_at(self, events) -> tuple[float, dict]:
        """`(when everything was last cleared, per-model marks)`."""
        everything, per_model = 0.0, {}
        for event in events:
            if event.type != CLEARED:
                continue
            payload = event.payload or {}
            if payload.get("all") or not payload.get("model"):
                everything = max(everything, float(event.ts or 0.0))
            else:
                name = str(payload["model"])
                per_model[name] = max(per_model.get(name, 0.0), float(event.ts or 0.0))
        return everything, per_model

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
        # A run recorded before the last clear is not shown. Per model
        # and globally, whichever mark is later (`benchmark clear`).
        everything, per_model = await self._cleared_at(events)

        def _kept(event) -> bool:
            at = float(event.ts or 0.0)
            since = max(everything, per_model.get(str((event.payload or {}).get("model") or ""), 0.0))
            return at > since

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
                if not _kept(event):
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
            if not _kept(event):
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
