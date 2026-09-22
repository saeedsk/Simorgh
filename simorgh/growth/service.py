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

from simorgh.contracts import topics
from simorgh.contracts.protocols import Context, Health

from .measure import MeasureConfig, measure_config
from .night import DEFAULT_NIGHTLY_USD
from .propose import ProposeConfig, propose_config

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


def nightly_usd(config) -> float:
    """`[growth] nightly_usd`, or the default (stage 8 item 8).

    Anything unreadable falls back to the default rather than to no
    cap: a malformed number in a config file must never be the reason
    a night spends without limit.
    """
    try:
        return max(0.0, float((config or {}).get("nightly_usd", DEFAULT_NIGHTLY_USD)))
    except (AttributeError, TypeError, ValueError):
        return DEFAULT_NIGHTLY_USD


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
    consumes: tuple[str, ...] = _union("consumes") + (topics.SYSTEM_TICK_SLEEP,)
    produces: tuple[str, ...] = _union("produces") + (
        # The subsystem's own, not any part's: what was decided
        # (stage 8 item 4).
        topics.GROWTH_LESSON_FOUND, topics.GROWTH_POLICY_PROPOSED,
        topics.GROWTH_POLICY_ADOPTED, topics.GROWTH_POLICY_RETIRED,
    )

    def __init__(self, **parts) -> None:
        """`Service(estimate=..., monitors=..., explore=...)` replaces a
        part, which is how a test drives one of them in isolation
        without booting the other two."""
        self._parts: dict[str, object] = {}
        for key, factory in PARTS:
            self._parts[key] = parts.get(key) or factory()
        self._started: list[str] = []
        #: What Sim decided to do differently (stage 8 item 4); built in
        #: `start` because it needs the ledger and the bus.
        self.policies = None
        self._subs: list = []
        #: Policies retired since boot, for `health()`.
        self.retired = 0
        #: What the night may spend, and what today already has
        #: (stage 8 item 8).
        self._nightly_usd = DEFAULT_NIGHTLY_USD
        self._spent_today = 0.0
        #: Which day `_spent_today` belongs to (days since the epoch by
        #: the Context clock), so the cap is a cap on the DAY.
        self._spent_day = None
        #: Measuring proposed rules (stage 8 item 5): OFF unless
        #: `[growth] measure_policies = true`, because it costs money.
        self._measure = MeasureConfig()
        #: The seam a test replaces: `(suite, task_type, cfg) -> run_cases`.
        self._cases_for = None
        #: Drafting and proposing rules from what diagnose found: OFF
        #: unless `[growth] propose_policies = true`, because every
        #: draft is a paid call.
        self._propose = ProposeConfig()
        #: Seams a test replaces: `think(prompt) -> reply payload`, and
        #: the agent names a rule can reach (None: read `agents/`).
        self._think = None
        self._agents = None
        #: What tonight's `diagnose` step found, for the `propose` step.
        self._candidates: list = []
        #: The last night's report, for `health()` and the tests.
        self.last_night = None
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
        # The policy store belongs to the whole subsystem rather than
        # to any one part: a lesson can come from any of them, and what
        # was decided is one record (stage 8 item 4).
        from simorgh.contracts.envelope import Message

        from .policies import PolicyStore

        async def _announce(topic: str, payload: dict) -> None:
            await ctx.bus.publish(Message.new(topic, source=ctx.bus.source, payload=payload,
                                              clock=ctx.clock.now))

        # What a night may spend (stage 8 item 8). Read here, because a
        # setting nothing reads is the bug this codebase keeps finding.
        self._nightly_usd = nightly_usd(ctx.config)
        self._measure = measure_config(ctx.config)
        self._propose = propose_config(ctx.config)
        self.policies = PolicyStore(ctx.ledger, clock=ctx.clock, publish=_announce)
        try:
            await self.policies.sync()
        except Exception as exc:  # noqa: BLE001 -- an unreadable stream is not a failed start
            ctx.logger.warning("growth.policies_unreadable", error=repr(exc))
        # The subsystem's own tick: watch what was adopted (stage 8
        # item 6). It runs here rather than in a part because it reads
        # one part's numbers to judge another part's decision, which is
        # the whole reason these three stopped being separate.
        self._subs = [await ctx.bus.subscribe(topics.SYSTEM_TICK_SLEEP, self._on_sleep)]
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
                ctx.logger.error("growth.part_failed", part=key, error=repr(exc))
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

    async def _on_sleep(self, _message) -> None:
        """The night (stage 8 item 8): a fixed list of steps, each run
        once, cheapest first, against one budget."""
        from .night import run_night

        day = int(self._now() // 86400)
        if day != self._spent_day:
            self._spent_day, self._spent_today = day, 0.0
        report = await run_night(self._night_steps(), budget_usd=self._nightly_usd,
                                 spent_so_far=self._spent_today)
        self._spent_today += report.spent_usd
        self.last_night = report
        if self._ctx is not None:
            self._ctx.logger.info("growth.night", ran=report.ran, failed=report.failed,
                                  stopped_at=report.stopped_at, spent_usd=round(report.spent_usd, 4))

    def _night_steps(self) -> list:
        """What a night does, cheapest first.

        Ordered so that stopping early loses the least: the evals every
        other judgement rests on are free, retiring a policy is free and
        can only ever REMOVE one, and the counting is free. Measuring a
        proposed rule costs money, and is last for that reason: one step
        per policy, each priced at its worst case, so the night's cap
        refuses the ones it cannot cover before anything is spent.
        """
        from .night import Step

        return [
            Step("evals", self._step_evals, est_usd=0.0),
            Step("review", self._step_review, est_usd=0.0),
            Step("diagnose", self._step_diagnose, est_usd=0.0),
            self._propose_step(),
            *self._measure_steps(),
        ]

    def _propose_step(self):
        """Draft a rule for what diagnose found and propose it (the gap
        between items 3 and 5): one step, priced at every draft the
        night may make, or one free step that says why it is off.

        Measuring is built before the night runs, so a rule proposed
        tonight is measured on the NEXT night -- after its
        `growth.policy.proposed` has been announced to the household.
        """
        from .night import Step

        cfg = self._propose
        if not cfg.enabled:
            async def _off() -> dict:
                return {"skipped": "off: [growth] propose_policies is not true (every draft is a paid call)",
                        "spent_usd": 0.0}
            return Step("propose", _off, est_usd=0.0)
        return Step("propose", self._step_propose, est_usd=cfg.est_usd())

    async def _step_propose(self) -> dict:
        from .propose import agent_names, propose_from

        if self.policies is None:
            return {"skipped": "no policy store", "spent_usd": 0.0}
        if not self._candidates:
            return {"skipped": "diagnose found nothing tonight", "spent_usd": 0.0}
        agents = self._agents if self._agents is not None else agent_names()
        return await propose_from(self._candidates, self.policies, self._think or self._think_draft,
                                  self._propose, agents=agents)

    async def _think_draft(self, prompt: str) -> dict:
        """One `cognition.think` on the cheap purpose (`review`), capped
        at `propose_usd_per_draft`; the reply payload, or an error
        reply (`ok: false`) on a timeout."""
        from simorgh.contracts.envelope import Message

        ctx = self._ctx
        if ctx is None:
            return {"ok": False, "text": ""}
        request = Message.new(topics.COGNITION_THINK, source=ctx.bus.source, clock=ctx.clock.now, payload={
            "purpose": "review", "messages": [{"role": "user", "content": prompt}],
            "budget": {"max_tokens": 200, "max_cost_usd": self._propose.usd_per_draft},
            "require_real_provider": False})
        reply = await ctx.bus.request_or_error(request, timeout=self._propose.timeout_s)
        return dict(reply.payload or {})

    def _measure_steps(self) -> list:
        """One step per PROPOSED rule (stage 8 item 5), or one free step
        that says why nothing was measured."""
        from .night import Step

        cfg = self._measure

        def _declined(why: str):
            async def _run() -> dict:
                return {"skipped": why, "spent_usd": 0.0}
            return [Step("measure", _run, est_usd=0.0)]

        if not cfg.enabled:
            return _declined("off: [growth] measure_policies is not true (it runs paid suites)")
        if self.policies is None:
            return _declined("no policy store")
        proposed = [p for p in self.policies.all() if p.status == "proposed"]
        if not proposed:
            return _declined("nothing proposed")
        steps = []
        for policy in proposed:
            if policy.kind != "rule":
                steps.extend(_declined(f"{policy.id}: only a rule can be measured today, not a {policy.kind}"))
                continue
            # Free when there is no suite to run: the step only says so.
            priced = cfg.est_usd() if cfg.held_out.get(policy.task_type) else 0.0
            steps.append(Step(f"measure:{policy.id}", self._measure_step(policy), est_usd=priced))
        return steps

    def _measure_step(self, policy):
        from .measure import measure_one

        async def _run() -> dict:
            return await measure_one(self.policies, policy, self._measure, land=self._land,
                                     samples_now=self._samples_of(policy.task_type),
                                     cases_for=self._cases_for)
        return _run

    def _samples_of(self, task_type: str) -> int:
        try:
            return self._posterior_of(task_type)[1]
        except Exception:  # noqa: BLE001 -- no estimate is a count of nothing
            return 0

    async def _land(self, payload: dict) -> None:
        """An adopted rule becomes `action.proposed(policy_adopt)`.
        Only Guardian subscribes to it; it asks a person before
        `rules/` changes (`guardian/config.py::ask_subjects`)."""
        from simorgh.contracts.envelope import Message

        ctx = self._ctx
        if ctx is None:
            raise RuntimeError("growth is not started; there is no bus to land a rule on")
        await ctx.bus.publish(Message.new(topics.ACTION_PROPOSED, source=ctx.bus.source, payload=payload,
                                          clock=ctx.clock.now))

    async def _step_evals(self) -> dict:
        """Re-read the eval record, so the morning's estimates rest on
        the latest run rather than on whatever was there at boot."""
        loaded = self.estimate.load_evals(self._evals_record())
        return {"detail": f"{loaded} suite(s) read", "spent_usd": 0.0}

    def _evals_record(self):
        from pathlib import Path

        config = getattr(self.estimate, "_config", None)  # noqa: SLF001 -- one subsystem, two parts
        return Path(getattr(config, "evals_record", ".simorgh_loader/evals.jsonl"))

    async def _step_review(self) -> dict:
        """Retire what has run out or stopped working (stage 8 item 6).

        A policy is a claim that Sim is better at something for having
        it, checked against the same measure that justified adopting
        it. Reversible, recorded, announced -- never a panic rollback.
        """
        if self.policies is None:
            return {"detail": "no policy store", "spent_usd": 0.0}
        gone = list(await self.policies.retire_expired())
        gone += await self.policies.review(self._posterior_of)
        self.retired += len(gone)
        return {"detail": f"{len(gone)} retired", "spent_usd": 0.0}

    async def _step_diagnose(self) -> dict:
        """What keeps going wrong, counted (stage 8 item 3). Free: the
        model is only ever asked to phrase what counting found, and
        that is the `propose` step, which costs money and comes next.
        """
        monitors = self.monitors
        found = await monitors._record_candidates(  # noqa: SLF001 -- one subsystem, two parts
            monitors._patterns.mine(self._now()))    # noqa: SLF001
        self._candidates = list(found or ())
        return {"detail": f"{len(found)} candidate(s)", "spent_usd": 0.0}

    def _now(self) -> float:
        return float(self._ctx.clock.now()) if self._ctx is not None else 0.0

    def _posterior_of(self, task_type: str) -> tuple[float, int]:
        """`(mean, samples)` for a task type, from the estimate part."""
        table = getattr(self.estimate, "_competence", None)  # noqa: SLF001 -- one subsystem, two parts
        if table is None:
            raise LookupError("no competence table")
        estimate = table.estimate(task_type)
        # Rounded: `samples` is an effective count under exponential
        # forgetting, and truncating loses a whole one at every
        # boundary (stage 6 item 1).
        return float(estimate["mean"]), int(round(float(estimate["samples"])))

    async def stop(self) -> None:
        for sub in self._subs:
            await sub.unsubscribe()
        self._subs.clear()
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


__all__ = ["NAME", "PARTS", "Service", "VERSION", "nightly_usd"]
