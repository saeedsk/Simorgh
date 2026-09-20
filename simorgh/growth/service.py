"""Growth as one Subsystem (stage 8 item 1).

Learning, Reflection and Curiosity were three subsystems that all
answered the same question -- *how should Sim be different tomorrow?* --
and answered it separately. Learning kept competence posteriors from
task outcomes. Reflection watched for drift and wrote critiques.
Curiosity went and found things out. Three services, three configs,
three places a lesson could be recorded and none of them aware of the
others, which is why a failure cluster Reflection found never reached
the estimate Learning kept.

This is the merge. One Subsystem the Kernel registers, three parts
inside it:

    estimate/   what Sim is good at, from outcomes         (was learning)
    monitors/   what is going wrong, watched               (was reflection)
    explore/    what is worth finding out                  (was curiosity)
    diagnose.py what keeps going wrong, by counting
    policies.py what was decided, with the evidence

**Every topic is preserved.** `learn.*`, `reflect.*` and `curiosity.*`
are all still published and subscribed exactly as before, because the
point of the merge is one owner, not a migration every consumer has to
follow. The one visible change is the `source` on the wire: these
events now come from `growth`.

The parts stay separable on purpose. Each is still an ordinary Service
underneath with its own `start(ctx)`, its own config dataclass and its
own tests; this class fans out to them and unions their manifests. A
part that fails to start is logged and skipped rather than taking the
other two down with it -- growth is the layer Sim can live without for
an afternoon, and none of it is on the path of answering a person.
"""

from __future__ import annotations

from dataclasses import replace

from simorgh.contracts.protocols import Context, Health

from .estimate.service import Service as EstimateService
from .explore.service import Service as ExploreService
from .monitors.service import Service as MonitorsService

NAME = "growth"
VERSION = "0.1.0"

#: The parts, in start order: estimates first (the monitors read them),
#: then the monitors, then exploring, which is the least load-bearing.
#: Each is `(config key under [growth], factory)`.
PARTS: tuple[tuple[str, type], ...] = (
    ("estimate", EstimateService),
    ("monitors", MonitorsService),
    ("explore", ExploreService),
)


def _union(attr: str) -> tuple[str, ...]:
    """The three parts' manifests, deduplicated, in declaration order."""
    seen: dict[str, None] = {}
    for _key, factory in PARTS:
        for topic in getattr(factory, attr, ()) or ():
            seen.setdefault(topic, None)
    return tuple(seen)


class Service:
    """One Subsystem over the three parts."""

    name = NAME
    version = VERSION
    consumes: tuple[str, ...] = _union("consumes")
    produces: tuple[str, ...] = _union("produces")

    def __init__(self, **parts) -> None:
        """`Service(estimate=..., monitors=..., explore=...)` replaces a
        part, which is how a test drives one of them in isolation
        without booting the other two."""
        self._parts: dict[str, object] = {}
        for key, factory in PARTS:
            self._parts[key] = parts.get(key) or factory()
        self._started: list[str] = []
        self._failed: dict[str, str] = {}
        self._ctx: Context | None = None

    # -- the parts, by name, so a test or a tool can reach one ----------------
    @property
    def estimate(self):
        return self._parts["estimate"]

    @property
    def monitors(self):
        return self._parts["monitors"]

    @property
    def explore(self):
        return self._parts["explore"]

    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        for key, _factory in PARTS:
            part = self._parts[key]
            try:
                await part.start(self._context_for(ctx, key))
            except Exception as exc:  # noqa: BLE001 -- one part is not the subsystem
                # Growth is what Sim can live without for an afternoon.
                # A part that cannot start says so and the rest run;
                # taking the whole subsystem down would stop the
                # estimates a running task reads.
                self._failed[key] = repr(exc)
                ctx.logger.log("error", "growth.part_failed", part=key, error=repr(exc))
            else:
                self._started.append(key)

    @staticmethod
    def _context_for(ctx: Context, key: str) -> Context:
        """The part's own Context: its `[growth.<part>]` section, and a
        name that says which part a log line came from.

        Everything else -- the bus client, the ledger, the clock -- is
        shared, so the parts publish as `growth` and their events are
        one subsystem's events, which is the point of the merge.
        """
        section = ctx.config.get(key) if hasattr(ctx.config, "get") else None
        return replace(ctx, name=f"{NAME}.{key}",
                       config=dict(section) if isinstance(section, dict) else {})

    async def stop(self) -> None:
        for key in reversed(self._started):
            try:
                await self._parts[key].stop()
            except Exception:  # noqa: BLE001 -- a stubborn part is not a failed stop
                pass
        self._started.clear()

    async def health(self) -> Health:
        notes: list[str] = []
        degraded = list(self._failed)
        for key, _factory in PARTS:
            if key in self._failed:
                notes.append(f"{key}: did not start")
                continue
            try:
                health = await self._parts[key].health()
            except Exception as exc:  # noqa: BLE001 -- an unhealthy part is a note, not a crash
                degraded.append(key)
                notes.append(f"{key}: {exc!r}")
                continue
            detail = getattr(health, "detail", "") or ""
            if getattr(health, "status", "ok") != "ok":
                degraded.append(key)
            notes.append(f"{key}: {detail}" if detail else key)
        summary = "; ".join(notes)
        return Health.ok(summary) if not degraded else Health.degraded(summary)


__all__ = ["NAME", "PARTS", "Service", "VERSION"]
