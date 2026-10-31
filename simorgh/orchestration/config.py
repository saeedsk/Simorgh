"""`simorgh.toml [orchestration]` (16 section 3.5).

`Service.start()` adopts this section via `from_mapping` the same way
`persona.service.Service` does (observer, 2026-09-08: the config
existed, `from_mapping` existed, and nothing ever called it, so editing
`[orchestration]` changed nothing in `single` mode -- the mode `sim.sh`
actually runs).

What each field really does once adopted:

- `workers` -- genuinely applies in `single` mode. One *process* is not
  one *Worker*: `Service.start()` loops `range(config.workers)` and
  starts that many `Worker` instances sharing the `workers` consumer
  group inside this one process, so raising it gives real additional
  in-process concurrency (competing consumers of `task.available`).
  It is not meaningless just because there's a single process.
- `think_timeout_s`, `metrics_interval_s` -- read by `Service`/`Worker`
  directly (see `service.py`).
- `heartbeat_s` -- read by `Worker._heartbeat_loop` (2026-09-08 fix):
  how often a claimed task's lease is renewed with `task.
  lease_heartbeat` while a single step is still in flight, so a step
  slower than `[planning] lease_seconds` (a full `run_tests`, a stuck
  `web_fetch`, a cold-start `cognition.think`) can no longer let
  `Scheduler.scan_leases` treat the task as abandoned and hand it to a
  second worker mid-step. The Worker never waits longer than a third of
  the task's own `lease_seconds` regardless of this value, so a short
  lease (a test, a tight deployment) is never outrun by a `heartbeat_s`
  sized for the 600s default.
- `max_depth` -- read by `SessionRunner` when `delegation` is on: a
  helper task may not be delegated deeper than this.
- `max_children_concurrent` -- read since 2026-09-19: `service.py`
  passes it to the session runner and `session.py` caps the helpers one
  task may run at once with it, refusing the next with the cap in the
  message.
- There is no `needs_human_timeout_s` here any more: nothing ever read
  it -- the planner's own `needs_human` flow does any timing -- and it
  was removed on 2026-09-25 so this surface only holds fields that
  change behavior. Writing it in `[orchestration]` is reported by
  `kernel/configcheck.py` as a key that changed nothing.
- There is no `lease_seconds` here. The lease is Planning's: `[planning]
  lease_seconds` goes out on every `task.available`, and the Worker reads
  it from that payload. This section's copy was never read and was
  removed on 2026-09-19; writing it now is reported by
  `kernel/configcheck.py` as a section that changed nothing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    workers: int = 1
    # Whether Verification reviews a benchmark case's answer. On by default.
    # A benchmark wave turns it off to measure the reviewer: on 2026-09-14
    # it rejected 111 correct and 111 wrong answers alike, and on patch
    # tasks each rejection spends a revision in the same context.
    review_benchmark: bool = True
    # Re-grounding (orchestration/progress.py): every N steps a task session
    # writes a progress note and its transcript is replaced by the note and
    # the last `keep_recent_steps` steps. 0 is off, the default until its
    # benchmark arm wins (docs/plans/long-run-context-design.md).
    reground_every_steps: int = 0
    keep_recent_steps: int = 2
    # A one-line bridge before a turn that is going to be slow (stage 3
    # item 5's sibling, item 7): a `patch` or `research` session streams
    # "I'll look at X" as `session.delta` while the real reply is still
    # being written. It is never the answer and is never recorded as the
    # turn's text.
    #
    # Off by default, unlike streamed replies: this is a SECOND model
    # call on every slow turn, and the thing it buys -- knowing Sim
    # started -- the TUI already shows as the task tree the moment the
    # turn opens. Turn it on where there is no screen.
    bridge_on_slow_turns: bool = False
    #: Longest the bridge may take before the turn goes on without it.
    bridge_timeout_s: float = 2.0
    # A patch revision after a rejected answer starts from the progress note
    # and the last `keep_recent_steps` steps instead of the whole transcript.
    clean_revisions: bool = False
    # Helper tasks: the `delegate` tool, offered to patch and research sessions
    # below `max_depth`. Off until its benchmark arm wins.
    delegation: bool = False
    delegate_max_steps: int = 12
    # From this attempt on, a task's THINKs ask Cognition for the strong tier
    # ([cognition] routes.strong). 0 is off.
    escalate_from_attempt: int = 0
    # A Farsi chat turn asks Cognition for the strong tier ([cognition]
    # routes.strong). The fast chat model misread clear Farsi as "garbled"
    # and invented Hafez (live, 2026-09-27); English keeps the fast one.
    farsi_strong: bool = True
    # Escalate to the strong tier when Sim's own record at this kind of
    # work is below this, and rests on at least `escalate_min_samples`
    # outcomes (stage 6 item 2: a consumer of `self.estimate`). A flat
    # prior is 0.5 with nothing recorded, so the sample floor is what
    # stops a new task type escalating on no evidence. 0 turns it off.
    escalate_below_posterior: float = 0.45
    escalate_min_samples: int = 8
    # Read-only tools one reply asks for together run together, up to this
    # many per step (docs/plans/long-run-context-design.md, change H). 1 is off.
    parallel_read_tools: int = 1
    # Agent Skills (docs/plans/agent-skills-design.md). Off until its benchmark
    # arm: the catalog is paid on every THINK, so an unused menu is a tax on
    # every task. `skills_roots` is searched in order and the first folder with
    # a name wins; "~" is expanded.
    # On since 2026-09-16, once the catalog stopped being charged where it
    # cannot be used (`skills_channels`): a voice turn carries none of it,
    # and a typed one pays 157 tokens for the two bundled skills -- about
    # $0.008 a day at the creator's 332 calls. Until the scoping existed
    # this was off precisely because every THINK paid for it (design
    # section 5.2).
    skills_enabled: bool = True
    skills_catalog_max_chars: int = 3000
    skills_roots: tuple[str, ...] = ("skills", "~/.simorgh/skills")
    # Which channels carry the skill catalog at all. The catalog rides in
    # `task_rules` on EVERY think call, and a spoken turn will never use
    # "create new skills" or "build an MCP server" -- so voice pays
    # nothing rather than a little. The creator, 2026-09-16: "our system
    # should have the concept of being frugal where ever it is possible".
    # "" is the typed/CLI channel. Empty tuple: no catalog anywhere.
    skills_channels: tuple[str, ...] = ("", "cli", "http")
    heartbeat_s: int = 30
    # An attempt's budget beside its steps (stage 4 item 6); 0 is no limit.
    # Running out ends the attempt "budget exhausted: <which>", which --
    # unlike the step cap -- is not retried with a fresh budget.
    attempt_max_tokens: int = 0
    attempt_max_usd: float = 0.0
    attempt_max_wall_s: float = 0.0
    max_depth: int = 3
    # How many helpers one task may run at once (stage 7 item 1). Read
    # since 2026-09-19; it was declared and unread for a year, which is
    # this codebase's commonest bug.
    max_children_concurrent: int = 4
    # Agent crews (stage 18 item 2, `crew.py`; docs/plan/stage-18-agent-crews.md).
    # `max_children_concurrent` above is now each parent's cap on members
    # running at once (more wait in `starting`). Per crew: at most this many
    # members in all, this many writers (patch, skill) at once, and one
    # budget every member's is carved from -- dollars, wall-clock seconds
    # and tokens (0: no bound of that kind). Spent out, every member is
    # cancelled with reason `crew budget` and reports `partial`. A `delegate`
    # helper is outside these bounds and keeps its old ones (`Crew.bounded`).
    crew_max_members: int = 8
    crew_max_writers: int = 1
    crew_max_usd: float = 0.5
    crew_max_wall_s: float = 900.0
    crew_max_tokens: int = 0
    # Chat and voice crews (stage 18 item 3). On: a typed chat turn may
    # `spawn` read-only helpers (research, browser), and a spoken one only
    # with `background: true` -- it answers at once, and the report reaches
    # the person who asked later (a `ui.notice` for a typed turn; a spoken
    # one through Initiative, which respects quiet hours). Independent of
    # `delegation`. Off by default.
    chat_crews: bool = False
    # Above Cognition's own `Budget.max_seconds` (180s), with room to
    # spare. It used to sit BELOW it: Cognition allowed each provider
    # 180 seconds while the caller here waited 120, so a merely slow
    # primary killed the task as "no real provider" while that provider
    # was still answering, and the failover chain behind it could never
    # be reached (observer, 2026-09-10 -- a task died at 121s with one
    # `think.completed` on record and no trace of a second call).
    # Cognition bounds the whole chain now; this waits for it.
    # 320 s, not 200: Cognition SHARES a purpose's deadline between
    # candidates (`router._share_of`: `remaining / (still to try + 1)`),
    # and it never exceeds what this caller will still wait. At 200 s a
    # `draft` -- the coding call -- got a 40 s slice each, while real
    # drafting calls on SWE-bench cases measured up to 42.5 s (live,
    # 2026-09-22): Together timed out twice and Gemini answered
    # `504 DEADLINE_EXCEEDED`, on one case, minutes apart, and the case
    # fell to the floor model. This waits long enough for `draft`'s own
    # 300 s cap, so each candidate gets 60 s. It does not slow chat or
    # voice: those are bounded by `[cognition.purposes] chat.max_seconds`
    # (90 s), which is the smaller of the two and still wins.
    think_timeout_s: float = 320.0
    # A patch or skill task works in its own git worktree and lands on
    # main through `worktree_land` (execution/worktree.py) instead of
    # editing the live checkout. Needs Execution's worktree tools; a
    # session that cannot open one says so and edits the live tree.
    worktrees: bool = True
    metrics_interval_s: float = 3.0  # 0 disables the periodic `system.metrics` publish
    # Guardrails switched off for a measurement (stage 14 item 3, the
    # ablation presets in docs/plan/stage-14-toolchain-evals-and-ablation.md).
    # For the eval sandbox only: `sim.sh` and the shipped config never set
    # it. Guardian is not among them and never will be -- every proposal is
    # still gated. Names (see `ABLATABLE`):
    #   scaffold  -- `task_rules` keeps only the task, who is speaking, the
    #                turn's language and the tool list (scaffolds.render)
    #   verify    -- every profile behaves as `verify = false`
    #   revisions -- every profile behaves as `max_revisions = 0`
    #   recovery  -- a failed tool result, an unknown tool or a malformed
    #                call ends the session `failed` instead of going back
    #                to the model; the tool-error budget below is moot
    #   nudge     -- no validation before a proposal and no retry nudges
    #                (stage 16): calls go straight to Guardian as before,
    #                and the tool-error budget is off with them
    #   steps     -- no step enforcement (stage 16): the agent's
    #                required_steps / terminal_tools / prerequisites are
    #                not checked
    #   routing   -- tool routing (stage 17) as if `tool_routing = "off"`:
    #                every tool in the agent file is offered
    ablate: tuple[str, ...] = ()
    # The guardrails' budgets (stage 16, orchestration/guardrails.py; the
    # plan's Definitions). Consecutive retry nudges (unknown tool, bad
    # arguments, a text reply that looked like a failed call) before the
    # session ends `failed`; consecutive steps with a hard tool error
    # (`error_kind = "failed"`) before it ends `failed`; premature
    # finishes, and consecutive prerequisite violations, before it ends
    # `blocked`. A nudge never spends a step of `max_steps`.
    max_retries: int = 3
    max_tool_errors: int = 2
    max_premature_attempts: int = 3
    max_prereq_violations: int = 2
    # Tool routing (stage 17 items 3 and 6, `routing.py`; docs/plan/
    # stage-17-tool-routing-and-prompt-compression.md). Which tool groups
    # (`agents/groups.toml`) a chat or spoken turn is offered:
    #   off    -- every tool in the agent file, as before; the prompt is
    #             byte-identical to a build without routing
    #   shadow -- route, record what would have been offered beside what
    #             was used (`routing.shadow` telemetry event), and still
    #             offer everything
    #   on     -- offer the routed groups only, in canonical order, plus
    #             the core group (memory, `tool_more`)
    # Routing decides what is offered, never what is allowed: Guardian
    # still gates every call. Off until a shadow week says the miss rate
    # is under 3% (plan, item 3).
    tool_routing: str = "off"
    #: The tool groups closest to the turn that are offered.
    route_top_k: int = 3
    #: Groups used in this many of the conversation's last turns stay offered.
    route_sticky_turns: int = 3
    #: The conversational class must beat the best tool group by this
    #: much before a turn is offered only the core group (item 6).
    route_none_margin: float = 0.15
    #: How long a routed turn waits for Memory's embedder (`memory.embed`)
    #: before it is routed with the lexical stand-in instead. Short: it
    #: sits before the first token of every routed turn. 0 never asks.
    route_embed_timeout_s: float = 0.3
    # The facts block of a turn's prompt (`context.py::_fact_lines`, stage
    # 15). `memory_fact_lines`: facts Memory found by the query's words (8,
    # what it always showed, so a reply without graph facts renders byte for
    # byte as before). `memory_graph_lines`: on top of those, the facts it
    # reached through the entity graph -- each marked "(via <entity>)" --
    # and entity summaries, one line each, summaries first. 0 hides them.
    memory_fact_lines: int = 8
    memory_graph_lines: int = 8
    # Observation masking by age (stage 17 item 7, `pressure.py`): a tool
    # result this many steps old becomes its stub and a one-line gist made
    # by code, at any pressure; `recall_result` brings it back in full.
    # 0 is off -- the prompt is byte-identical -- until the item's
    # measurement says the tokens saved beat the cache lost (plan: 2).
    mask_after_steps: int = 0
    # Tool awareness (2026-10-27, `toolindex.py`): every tool-using turn
    # gets a one-line index of the registered tools it may load but was
    # not given; `tool_more` loads one by name (`tool`) or by a plain-words
    # search (`need`); and a chat reply that says "I can't" while a
    # matching tool exists gets those tools and one nudge before it goes
    # out. Off: prompts, offers and replies are what they were.
    tool_index: bool = False
    # Sim's supervisor (2026-10-28, `supervisor.py`): a bar raiser over a
    # job asked for in chat. At the turn's first tool call it writes the
    # job's success criteria and how each is measured; a final answer is
    # reviewed against them and Amazon's Leadership Principles (as checks,
    # `supervisor.PRINCIPLES`), and below the bar its feedback goes back as
    # an order. Off: turns are what they were.
    supervisor: bool = True
    # Stage 19 (code-first problem solving), both read only with the
    # supervisor on. `supervisor_approach`: the bar also says HOW the job is
    # done (direct, compute, parallel, decompose, background), Sim is told
    # the concrete next step, and the review checks the method. Off: the bar
    # and the review are those of 2026-10-28. `supervisor_lessons`: a
    # below-the-bar review the next one met becomes a lesson on
    # `supervisor:lessons`, recalled into the bar for a similar job.
    supervisor_approach: bool = True
    supervisor_lessons: bool = True
    # 2026-10-30, read only with the supervisor on: every crew member's
    # answer is reviewed against its own bar before it reports, and below
    # the bar the feedback goes back to that member (at most
    # `supervisor.MEMBER_REVIEW_ROUNDS` times). Off: members report as they
    # were, and only the parent's answer is reviewed.
    supervisor_members: bool = True
    #: What `from_mapping` had to ignore, logged by the service at start.
    problems: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, data: dict) -> "Config":
        known = {f for f in cls.__dataclass_fields__} - {"problems"}
        kwargs = {k: v for k, v in data.items() if k in known}
        problems: list[str] = []
        if "ablate" in kwargs:
            raw = kwargs["ablate"]
            names = [raw] if isinstance(raw, str) else list(raw or ())
            # An unknown switch is reported, not fatal: a typo here must not
            # stop a boot, and must not silently measure the wrong preset.
            problems += [f"ablate: unknown switch {n!r} ignored (known: {', '.join(sorted(ABLATABLE))})"
                         for n in names if n not in ABLATABLE]
            kwargs["ablate"] = tuple(dict.fromkeys(str(n) for n in names if n in ABLATABLE))
        if "tool_routing" in kwargs:
            mode = str(kwargs["tool_routing"]).strip().lower()
            if mode not in ROUTING_MODES:
                # Reported, and off: an unknown mode must neither stop a
                # boot nor narrow what a turn is offered by accident.
                problems.append(f"tool_routing: unknown mode {kwargs['tool_routing']!r}, using 'off' "
                                f"(known: {', '.join(ROUTING_MODES)})")
                mode = "off"
            kwargs["tool_routing"] = mode
        for key, low in (("route_top_k", 1), ("route_sticky_turns", 0), ("memory_fact_lines", 0),
                         ("memory_graph_lines", 0), ("mask_after_steps", 0)):
            if key in kwargs:
                try:
                    kwargs[key] = max(low, int(kwargs[key]))
                except (TypeError, ValueError):
                    problems.append(f"{key}: {kwargs[key]!r} is not a whole number, using the default")
                    del kwargs[key]
        for key in ("route_none_margin", "route_embed_timeout_s"):
            if key in kwargs:
                try:
                    kwargs[key] = float(kwargs[key])
                except (TypeError, ValueError):
                    problems.append(f"{key}: {kwargs[key]!r} is not a number, using the default")
                    del kwargs[key]
        if "route_embed_timeout_s" in kwargs:
            kwargs["route_embed_timeout_s"] = max(0.0, kwargs["route_embed_timeout_s"])
        return cls(**kwargs, problems=tuple(problems))


#: The guardrails `[orchestration] ablate` may switch off.
ABLATABLE = frozenset({"scaffold", "verify", "revisions", "recovery", "nudge", "steps", "routing",
                       # Stage 19 item 7b: a job whose bar is unmet goes on in the background.
                       "continue"})
#: `[orchestration] tool_routing` (stage 17); `routing.MODES`, duplicated so
#: this module stays free of imports.
ROUTING_MODES = ("off", "shadow", "on")
