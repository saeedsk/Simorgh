"""SQLite backend (docs/blueprint/subsystems/01-bus.md section 5.4): one
WAL-mode database shared by every process on the host, so `local-multi`
mode is a config change, not a code change (02 section 6).

`enqueue` inserts the message and fans out one `deliveries` row per
matching durable-or-live subscription (broadcast) or per competing
group. A poller per process leases the highest-priority pending rows
for its own subscriptions inside one `BEGIN IMMEDIATE` transaction,
inserting `partition_locks` so a key is held by at most one in-flight
delivery across *all* processes. Ack deletes the lock; nack schedules a
retry; a reaper returns expired leases to `pending` (attempt+1) --
that is what makes a Worker's death recoverable (Flow 7). Durable
subscriptions are rows, so a process that starts later still receives
what was enqueued while it was down; a non-durable subscription only
sees messages enqueued after it registered.

DB calls are synchronous on the event loop: every statement here is
sub-millisecond on tiny tables and WAL never blocks readers; the cost
of threading a connection through `to_thread` is not worth it at this
throughput (the bottleneck is LLM calls, not messages).
"""

from __future__ import annotations

import asyncio
import heapq
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Callable

from simorgh.contracts.envelope import Message
from simorgh.contracts.topics import matches

from ..api import BusSubscription, BusUnavailable, DeadLetterHook, Delivery, Handler, SubscriptionSpec
from ..router import INBOX_PREFIX, Registered, is_inbox, is_reply_routed

Clock = Callable[[], float]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages(
  id TEXT PRIMARY KEY, type TEXT NOT NULL, schema_version INTEGER, ts REAL, source TEXT,
  trace_id TEXT, causation_id TEXT, correlation_id TEXT, partition_key TEXT, priority INTEGER,
  expires_at REAL, reply_to TEXT, idempotency_key TEXT, payload TEXT NOT NULL,
  enqueued_seq INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS subscriptions(
  sub_id TEXT PRIMARY KEY, source TEXT, pattern TEXT NOT NULL, grp TEXT, durable INTEGER,
  created_at REAL, last_seen REAL, live INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS deliveries(
  delivery_id TEXT PRIMARY KEY, message_id TEXT NOT NULL, sub_id TEXT, grp TEXT,
  attempt INTEGER NOT NULL DEFAULT 1, state TEXT NOT NULL, lease_until REAL, retry_after REAL,
  partition_key TEXT, priority INTEGER, enqueued_seq INTEGER, last_error TEXT);
CREATE TABLE IF NOT EXISTS partition_locks(
  grp TEXT NOT NULL, partition_key TEXT NOT NULL, delivery_id TEXT, lease_until REAL,
  PRIMARY KEY(grp, partition_key));
CREATE TABLE IF NOT EXISTS acked(id TEXT PRIMARY KEY, grp TEXT, ts REAL);
CREATE INDEX IF NOT EXISTS ix_deliv ON deliveries(grp, state, priority DESC, enqueued_seq);
CREATE INDEX IF NOT EXISTS ix_lease ON deliveries(lease_until);
CREATE INDEX IF NOT EXISTS ix_sub ON deliveries(sub_id, state);
"""


class SqliteBackend:
    name = "sqlite"

    def __init__(
        self,
        path: str | Path,
        *,
        clock: Clock,
        max_deliveries: int = 5,
        lease_seconds: float = 30.0,
        poll_interval_ms: int = 50,
        busy_timeout_ms: int = 5000,
        dedupe_window: int = 5000,
        on_expired: Callable[[Message], None] | None = None,
        on_handler_error: Callable[[Message, BaseException], None] | None = None,
    ) -> None:
        self._path = str(path)
        self._clock = clock
        self._max_deliveries = max_deliveries
        self._lease = lease_seconds
        self._poll = poll_interval_ms / 1000.0
        self._busy = busy_timeout_ms
        self._dedupe_window = dedupe_window
        self._on_expired = on_expired
        self._on_handler_error = on_handler_error
        self._db: sqlite3.Connection | None = None
        self._registered: dict[str, Registered] = {}
        self._state = "running"
        self._dead_hook: DeadLetterHook | None = None
        self._poller: asyncio.Task | None = None
        self._inflight: dict[str, int] = {}
        self._inflight_tasks: set[asyncio.Task] = set()
        self._max_inflight: dict[str, int] = {}
        self._active: dict[str, Delivery] = {}  # message id -> in-flight delivery
        self._explicit: dict[str, tuple[str, float | None]] = {}

    # -- lifecycle -----------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self._path, timeout=self._busy / 1000.0, isolation_level=None)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        db.execute(f"PRAGMA busy_timeout={self._busy}")
        db.executescript(_SCHEMA)
        return db

    async def start(self) -> None:
        if self._db is None:
            self._db = self._connect()
        if self._poller is None:
            self._poller = asyncio.create_task(self._poll_loop(), name="bus-sqlite-poller")

    async def stop(self) -> None:
        self._state = "stopping"
        if self._poller is not None:
            self._poller.cancel()
            try:
                await self._poller
            except asyncio.CancelledError:
                pass
            self._poller = None
        for t in list(self._inflight_tasks):
            t.cancel()
        await asyncio.gather(*self._inflight_tasks, return_exceptions=True)
        if self._db is not None:
            # release our leases so another process can pick them up immediately
            try:
                for sub_id in self._registered:
                    self._db.execute(
                        "UPDATE deliveries SET state='pending', lease_until=NULL WHERE sub_id=? AND state='leased'",
                        (sub_id,),
                    )
                    self._db.execute("DELETE FROM partition_locks WHERE delivery_id IN (SELECT delivery_id FROM deliveries WHERE sub_id=?)", (sub_id,))
                    self._db.execute("UPDATE subscriptions SET live=0 WHERE sub_id=? AND durable=0", (sub_id,))
            except sqlite3.Error:
                pass
            self._db.close()
            self._db = None

    def set_state(self, state: str) -> None:
        self._state = state

    def set_dead_letter_hook(self, hook: DeadLetterHook | None) -> None:
        self._dead_hook = hook

    def _run(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        assert self._db is not None
        try:
            return self._db.execute(sql, params)
        except sqlite3.OperationalError as exc:
            raise BusUnavailable(f"sqlite: {exc}") from exc

    # -- registration -----------------------------------------------------------
    async def register(self, spec: SubscriptionSpec, handler: Handler) -> BusSubscription:
        assert self._db is not None
        sub_id = str(uuid.uuid4())
        now = self._clock()
        if spec.durable and spec.group is not None:
            # a durable competing member reuses the group's persisted identity, so pending rows
            # enqueued while every member was down are still delivered
            self._run(
                "INSERT OR IGNORE INTO subscriptions(sub_id, source, pattern, grp, durable, created_at, last_seen, live) "
                "VALUES(?,?,?,?,1,?,?,1)",
                (f"group:{spec.group}:{spec.pattern}", spec.source, spec.pattern, spec.group, now, now),
            )
        self._run(
            "INSERT INTO subscriptions(sub_id, source, pattern, grp, durable, created_at, last_seen, live) VALUES(?,?,?,?,?,?,?,1)",
            (sub_id, spec.source, spec.pattern, spec.group, 1 if spec.durable else 0, now, now),
        )
        reg = Registered(id=sub_id, spec=spec, handler=handler)
        self._registered[sub_id] = reg
        self._max_inflight[sub_id] = spec.max_inflight

        async def _unsub() -> None:
            self._registered.pop(sub_id, None)
            if self._db is not None:
                self._run("UPDATE subscriptions SET live=0 WHERE sub_id=?", (sub_id,))

        return BusSubscription(pattern=spec.pattern, id=sub_id, _unsubscribe=_unsub)

    # -- enqueue ----------------------------------------------------------------
    async def enqueue(self, message: Message) -> None:
        assert self._db is not None
        m = message
        expires_at = (m.ts + m.ttl_seconds) if m.ttl_seconds is not None else None
        self._run("BEGIN IMMEDIATE")
        try:
            seq = self._run("SELECT COALESCE(MAX(enqueued_seq),0)+1 FROM messages").fetchone()[0]
            self._run(
                "INSERT OR IGNORE INTO messages VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (m.id, m.type, m.schema_version, m.ts, m.source, m.trace_id, m.causation_id, m.correlation_id,
                 m.partition_key, m.priority, expires_at, m.reply_to, m.idempotency_key, m.to_json(), seq),
            )
            rows = self._run(
                "SELECT sub_id, pattern, grp, durable, live FROM subscriptions WHERE live=1 OR durable=1"
            ).fetchall()
            targets: list[tuple[str, str | None]] = []
            seen_groups: set[str] = set()
            for sub_id, pattern, grp, durable, live in rows:
                if is_reply_routed(m):
                    if pattern != m.reply_to:
                        continue
                elif is_inbox(pattern) or not matches(pattern, m.type):
                    continue
                if grp is not None:
                    if grp in seen_groups:
                        continue
                    seen_groups.add(grp)
                    targets.append((f"group:{grp}:{pattern}" if sub_id.startswith("group:") or durable else grp, grp))
                else:
                    targets.append((sub_id, None))
            for target_sub, grp in targets:
                self._run(
                    "INSERT INTO deliveries(delivery_id, message_id, sub_id, grp, attempt, state, lease_until, retry_after, "
                    "partition_key, priority, enqueued_seq) VALUES(?,?,?,?,1,'pending',NULL,NULL,?,?,?)",
                    (str(uuid.uuid4()), m.id, target_sub, grp, m.partition_key, m.priority, seq),
                )
            self._run("COMMIT")
        except Exception:
            self._run("ROLLBACK")
            raise

    async def depth(self, group: str) -> int:
        if self._db is None:
            return 0
        return self._run("SELECT COUNT(*) FROM deliveries WHERE grp=? AND state='pending'", (group,)).fetchone()[0]

    def inflight(self) -> dict[str, int]:
        return dict(self._inflight)

    # -- polling / leasing ----------------------------------------------------------
    async def _poll_loop(self) -> None:
        while True:
            try:
                self._reap()
                if self._state != "stopping":
                    self._lease_ready()
            except BusUnavailable:
                pass
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 -- the poller must survive anything a handler does
                pass
            await asyncio.sleep(self._poll)

    def _reap(self) -> None:
        now = self._clock()
        expired = self._run(
            "SELECT delivery_id, grp, partition_key, attempt FROM deliveries WHERE state='leased' AND lease_until < ?",
            (now,),
        ).fetchall()
        for delivery_id, grp, pkey, attempt in expired:
            self._run("UPDATE deliveries SET state='pending', attempt=attempt+1, lease_until=NULL WHERE delivery_id=?", (delivery_id,))
            if pkey is not None and grp is not None:
                # (grp, partition_key) is partition_locks' own primary key --
                # freeing by that alone is correct and sufficient once this
                # delivery's lease has expired; also matching delivery_id
                # would wrongly leave a stuck lock if the two ever disagree
                # (e.g. bookkeeping drift, or a lock recorded by an older
                # process generation), which defeats the whole point of
                # reaping a dead process's lease.
                self._run("DELETE FROM partition_locks WHERE grp=? AND partition_key=?", (grp, pkey))

    def _my_subscription_ids(self) -> dict[str, Registered]:
        ids: dict[str, Registered] = {}
        for reg in self._registered.values():
            ids[reg.id] = reg
            if reg.spec.group is not None:
                ids[reg.spec.group] = reg
                ids[f"group:{reg.spec.group}:{reg.spec.pattern}"] = reg
        return ids

    def _lease_ready(self) -> None:
        mine = self._my_subscription_ids()
        if not mine:
            return
        now = self._clock()
        placeholders = ",".join("?" for _ in mine)
        self._run("BEGIN IMMEDIATE")
        try:
            rows = self._run(
                f"SELECT d.delivery_id, d.message_id, d.sub_id, d.grp, d.attempt, d.partition_key, m.type, m.payload, m.expires_at "
                f"FROM deliveries d JOIN messages m ON m.id=d.message_id "
                f"WHERE d.state='pending' AND d.sub_id IN ({placeholders}) "
                f"AND (d.retry_after IS NULL OR d.retry_after <= ?) "
                f"ORDER BY d.priority DESC, d.enqueued_seq ASC LIMIT 64",
                (*mine.keys(), now),
            ).fetchall()
            leased: list[tuple[Registered, Delivery]] = []
            for delivery_id, message_id, sub_id, grp, attempt, pkey, mtype, payload, expires_at in rows:
                reg = mine[sub_id]
                if self._state == "paused" and grp is not None and not mtype.startswith("system."):
                    continue
                if self._inflight.get(reg.id, 0) >= self._max_inflight.get(reg.id, 16):
                    continue
                if expires_at is not None and now > expires_at:
                    self._run("UPDATE deliveries SET state='expired' WHERE delivery_id=?", (delivery_id,))
                    if self._on_expired:
                        self._on_expired(Message.from_json(payload))
                    continue
                if grp is not None and self._run("SELECT 1 FROM acked WHERE id=? AND grp=?", (message_id, grp)).fetchone():
                    self._run("UPDATE deliveries SET state='acked' WHERE delivery_id=?", (delivery_id,))
                    continue
                if pkey is not None and grp is not None:
                    held = self._run("SELECT 1 FROM partition_locks WHERE grp=? AND partition_key=?", (grp, pkey)).fetchone()
                    if held:
                        continue
                    self._run("INSERT INTO partition_locks(grp, partition_key, delivery_id, lease_until) VALUES(?,?,?,?)",
                              (grp, pkey, delivery_id, now + self._lease))
                self._run("UPDATE deliveries SET state='leased', lease_until=? WHERE delivery_id=?", (now + self._lease, delivery_id))
                message = Message.from_json(payload)
                delivery = Delivery(message=message, attempt=attempt, lease_until=now + self._lease, group=grp,
                                    subscription_id=reg.id, delivery_id=delivery_id)
                leased.append((reg, delivery))
                self._inflight[reg.id] = self._inflight.get(reg.id, 0) + 1
            self._run("COMMIT")
        except Exception:
            self._run("ROLLBACK")
            raise
        for reg, delivery in leased:
            task = asyncio.create_task(self._run_handler(reg, delivery))
            self._inflight_tasks.add(task)
            task.add_done_callback(self._inflight_tasks.discard)

    async def _run_handler(self, reg: Registered, delivery: Delivery) -> None:
        m = delivery.message
        self._active[m.id] = delivery
        try:
            timeout = reg.spec.max_handler_seconds or self._lease
            await asyncio.wait_for(reg.handler(m), timeout=timeout)
            explicit = self._explicit.pop(delivery.delivery_id, None)
            if explicit is None or explicit[0] == "ack" or delivery.group is None:
                self._ack_row(delivery)
            else:
                await self._nack_or_dead(delivery, explicit[1], None)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001
            self._explicit.pop(delivery.delivery_id, None)
            if self._on_handler_error:
                self._on_handler_error(m, exc)
            if delivery.group is None:
                self._ack_row(delivery)  # broadcast: dropped, not retried
            else:
                await self._nack_or_dead(delivery, None, exc)
        finally:
            self._inflight[reg.id] = max(0, self._inflight.get(reg.id, 0) - 1)
            if self._active.get(m.id) is delivery:
                del self._active[m.id]

    def _ack_row(self, d: Delivery) -> None:
        if self._db is None:
            return
        self._run("UPDATE deliveries SET state='acked' WHERE delivery_id=?", (d.delivery_id,))
        if d.group is not None:
            self._run("INSERT OR IGNORE INTO acked(id, grp, ts) VALUES(?,?,?)", (d.message.id, d.group, self._clock()))
            self._run("DELETE FROM acked WHERE id NOT IN (SELECT id FROM acked ORDER BY ts DESC LIMIT ?)", (self._dedupe_window,))
        self._unlock(d)

    def _unlock(self, d: Delivery) -> None:
        if d.message.partition_key is not None and d.group is not None:
            self._run("DELETE FROM partition_locks WHERE grp=? AND partition_key=? AND delivery_id=?",
                      (d.group, d.message.partition_key, d.delivery_id))

    def _nack_row(self, d: Delivery, retry_after: float | None, error: BaseException | None) -> None:
        backoff = retry_after if retry_after is not None else min(60.0, 2.0 ** (d.attempt - 1))
        self._run(
            "UPDATE deliveries SET state='pending', attempt=attempt+1, lease_until=NULL, retry_after=?, last_error=? WHERE delivery_id=?",
            (self._clock() + backoff, repr(error) if error else None, d.delivery_id),
        )
        self._unlock(d)

    async def _nack_or_dead(self, d: Delivery, retry_after: float | None, error: BaseException | None) -> None:
        if d.attempt >= self._max_deliveries:
            self._run("UPDATE deliveries SET state='dead', last_error=? WHERE delivery_id=?", (repr(error) if error else "nack", d.delivery_id))
            self._unlock(d)
            if self._dead_hook is not None:
                await self._dead_hook(d, "max_deliveries", repr(error) if error else "nack")
            return
        self._nack_row(d, retry_after, error)

    def _current_delivery_for(self, message: Message) -> Delivery | None:
        return self._active.get(message.id)

    async def ack(self, delivery: Delivery) -> None:
        self._explicit[delivery.delivery_id] = ("ack", None)

    async def nack(self, delivery: Delivery, *, retry_after: float | None) -> None:
        self._explicit[delivery.delivery_id] = ("nack", retry_after)

    # -- inspection (tests, `simorgh status`) ------------------------------------------
    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for state, n in self._run("SELECT state, COUNT(*) FROM deliveries GROUP BY state").fetchall():
            out[state] = n
        return out


__all__ = ["SqliteBackend", "INBOX_PREFIX"]
