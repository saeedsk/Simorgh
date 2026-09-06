"""Snapshot + replay for `Projection`s (02-ledger section 4.5). A
derived view is loaded from its last snapshot (if any), then every event
after that seq is folded in, in order. Replay is deterministic because
events are immutable and totally ordered per stream -- which is exactly
why a projection's state is never *stored* as truth: it can always be
recomputed, so it can never silently drift from what actually happened
(01 principle 4.4; v1's own `tasks.py::_fold`, generalized).
"""

from __future__ import annotations

from .api import LedgerBackend, Projection


async def rebuild(backend: LedgerBackend, projection: Projection, stream: str) -> int:
    """Load the snapshot, replay the tail, return the stream head. A
    corrupt or unloadable snapshot is ignored (with a full replay from
    seq 1) rather than trusted -- the log is the truth, the snapshot is
    an optimization."""
    from_seq = 1
    snapshot = await backend.read_snapshot(stream)
    if snapshot is not None:
        state, at_seq = snapshot
        try:
            projection.load(state)
            projection.applied_seq = at_seq
            projection.snapshot_seq = at_seq
            from_seq = at_seq + 1
        except Exception:  # noqa: BLE001 -- a bad snapshot must never brick a rebuild
            projection.applied_seq = 0
            projection.snapshot_seq = 0
            from_seq = 1
    head = from_seq - 1
    for event in await backend.read(stream, from_seq=from_seq, limit=None):
        projection.fold(event)
        head = event.seq
    return max(head, await backend.head(stream))


async def materialize(backend: LedgerBackend, projection: Projection, stream: str) -> int:
    """`rebuild`, then snapshot if the view has moved `snapshot_every`
    events past its last snapshot."""
    head = await rebuild(backend, projection, stream)
    if projection.applied_seq - projection.snapshot_seq >= max(1, projection.snapshot_every):
        await backend.write_snapshot(stream, projection.state(), projection.applied_seq)
        projection.snapshot_seq = projection.applied_seq
    return head


__all__ = ["materialize", "rebuild"]
