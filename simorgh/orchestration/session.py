"""The session state machine (16 section 5): CLAIMED -> GATHER -> THINK ->
(final -> VERIFY -> COMPLETED | tool_calls -> PROPOSE -> GATHER) with a
bounded evaluator-optimizer revision loop. One action is proposed per
step and awaited before the next THINK (section 7: "simpler resume and
exact trajectories; cost: no parallel tool calls inside a step").

Deliberately scoped down from the full spec this build: no Plan Mode
artifact assembly, no delegation (fresh/fork), no steer injection, no
reground-every-N-steps restatement. See the package README.
"""

from __future__ import annotations

import asyncio
import json
import uuid

from simorgh.contracts import topics
from simorgh.contracts.envelope import Event, Message

from . import scaffolds
from .api import Outcome, Session, Step
from .context import DEFAULT_TIMEOUT_S, Assembler
from .tools import marker_hint, offered_tools, to_action_payload

ACTION_TIMEOUT_S = 30.0
# The reason an attempt gives when it spends its whole step budget with
# a tool call still pending. Planning matches it by prefix to re-offer
# the task soon (`planning/service.py::CONTINUATION_REASON`, same text;
# the packages may not import each other).
CONTINUATION_REASON = "step budget exhausted"
# Ledger-only record type: which uncommitted edits an exhausted attempt
# left in the tree for the next one.
EDITS_KEPT = topics.TASK_EDITS_KEPT
# Tools that *end* an attempt's work rather than extend it, so the last
# step may still run one when there is an uncommitted edit waiting.
FINISHING_TOOLS = ("git_commit", "git_discard")
# An attempt below this number may leave its edits for the next; the
# one at it discards. Planning gives up after nine blocks, so the chain
# always ends with a clean-up before that.
KEEP_EDITS_UNTIL_ATTEMPT = 6
# How long to wait for a given tool, when 30s is not the right answer.
#
# Live-caught 2026-09-07, watching a real patch task: `run_tests`
# reported "no response (timed out)" twice, and the session -- doing
# exactly what its scaffold says, not committing on a failing suite --
# left the edit applied and uncommitted. Execution allows a test run
# `test_timeout_s` (300s) and every tool `default_timeout_s` (60s),
# while this caller gave *everything* 5 seconds. A test suite cannot
# finish in 5s, so `run_tests` could never once have succeeded, and
# Sim could never verify its own work.
#
# Kept a little above Execution's own limits so the tool's timeout is
# what fires, with its real error, rather than this one guessing. When
# `test_timeout_s` went 120 -> 300 this stayed at 180, so a suite that
# ran long under load (a repeat trial with a full pytest in the next
# process, 2026-09-07) timed out *here* first: the session moved on
# while the tests were still running, and the task sat in_progress.
_ACTION_TIMEOUTS: dict[str, float] = {
    "run_tests": 330.0,
    "run_python_sandboxed": 45.0,
    "web_fetch": 45.0,
    "apply_source_patch": 60.0,
    "apply_skill": 60.0,
}
# Found by a watched trial, 2026-09-07, and the third stale 5-second
# timeout in this file. Verification at LIGHT rigor makes two sequential
# provider round trips (generate a checklist, then evaluate it) plus the
# mechanical checks, so 5s could never cover it: in 2 of 2 runs the real
# verdict landed 14ms to 3s *after* the session had already given up and
# accepted the task with `verification_ref=None`. Money spent on the
# review, verdict discarded -- and the `blocked` path for a failing
# verdict was unreachable, so verification could never stop a bad patch.
# Matches `learning/config.py::verify_timeout_seconds`.
VERIFY_TIMEOUT_S = 300.0


class _EventWaiter:
    """Waits for the first event of any of `types` whose payload[`key`]
    equals `value` -- the action.proposed -> {result|denied|needs_human}
    and verify.requested -> verify.result correlations, neither of which
    rides the bus's reply_to inbox (they're events, not request/reply;
    03 section 1's own table).
    """

    def __init__(self, bus) -> None:
        self._bus = bus

    async def wait(self, types: tuple[str, ...], *, key: str, value: str, timeout: float) -> Message | None:
        fut: asyncio.Future = asyncio.get_running_loop().create_future()

        async def _on(message: Message) -> None:
            if message.payload.get(key) == value and not fut.done():
                fut.set_result(message)

        subs = [await self._bus.subscribe(t, _on) for t in types]
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            for s in subs:
                await s.unsubscribe()


class SessionRunner:
    def __init__(
        self, bus, ledger, *, clock=None, worker_id: str = "w1", is_paused=None,
        think_timeout_s: float = 5.0, action_timeout_s: float = ACTION_TIMEOUT_S,
        verify_timeout_s: float = VERIFY_TIMEOUT_S, assemble_timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._bus = bus
        self._ledger = ledger
        self._clock = clock
        self._worker_id = worker_id
        self._assembler = Assembler(bus, clock=clock, timeout_s=assemble_timeout_s)
        self._waiter = _EventWaiter(bus)
        self._is_paused = is_paused or (lambda: False)
        self._think_timeout_s = think_timeout_s
        self._action_timeout_s = action_timeout_s
        self._verify_timeout_s = verify_timeout_s

    async def run(self, session: Session, *, user_text: str = "") -> Outcome:
        """Run the session, and never leave a change behind that nobody
        committed.

        Live-caught 2026-09-07 by a trial designed to fail: asked to make
        a change that breaks the suite, Sim applied it, ran the tests, saw
        red, and correctly refused to commit -- and then left the modified
        file sitting in the working tree. Its instructions do say to put
        the tree back, and it had `git_discard` to do it with, but it
        spent its remaining steps investigating the failure instead.

        Which is a reasonable thing for it to do. "Never leave a broken
        change in the tree" is a property the system should hold, not a
        request the model has to remember, so the cleanup happens here
        whichever way the session ended.
        """
        outcome = await self._run(session, user_text=user_text)
        if session.uncommitted and outcome.kind != "paused":
            if self._continues(session, outcome):
                await self._keep_uncommitted(session)
            else:
                await self._discard_uncommitted(session)
        return outcome

    @staticmethod
    def _continues(session: Session, outcome: Outcome) -> bool:
        """Whether this attempt's uncommitted edits stay in the tree for
        the next one. Only when the attempt ran out of steps mid-work
        (Planning re-offers such a task within seconds, see
        `resume.py`) and only for the first few attempts: watched trial,
        2026-09-07 -- with the edit discarded every time, each attempt
        re-applied the same patch and none ever reached the commit. The
        last allowed attempt discards as before, so the "never leave a
        broken change" property still holds for the chain as a whole."""
        return (
            outcome.kind == "blocked"
            and (outcome.reason or "").startswith(CONTINUATION_REASON)
            and session.attempt < KEEP_EDITS_UNTIL_ATTEMPT
        )

    async def _keep_uncommitted(self, session: Session) -> None:
        kept = sorted(session.uncommitted)
        created = sorted(p for p in session.created if p in session.uncommitted)
        step = Step(
            session.next_step_no(), "act",
            f"kept {len(kept)} uncommitted edit(s) in the tree for the next attempt: {', '.join(kept)}",
            ok=True,
        )
        session.record(step)
        await self._record_step(session, step)
        # Ledger only: the next attempt reads this back (`resume.py`) to
        # inherit the paths, so *its* end cleans them up if it does not
        # commit. Nothing on the bus needs it.
        await self._append(session, EDITS_KEPT, {"task_id": session.task_id, "paths": kept, "created": created})

    async def _discard_uncommitted(self, session: Session) -> None:
        left = sorted(session.uncommitted)
        for path in left:
            call = {"tool": "git_discard", "args": {"path": path, "created": path in session.created}}
            ok, summary, _detail = await self._propose_and_await(session, call, session.next_step_no())
            step = Step(
                session.next_step_no(), "act",
                f"put {path} back: {summary}" if ok else f"could not put {path} back: {summary}",
                tool="git_discard", ok=ok,
            )
            session.record(step)
            await self._record_step(session, step)
        session.uncommitted.clear()

    async def _run(self, session: Session, *, user_text: str = "") -> Outcome:
        await self._append(session, topics.TASK_STARTED, {"task_id": session.task_id, "worker_id": self._worker_id})
        await self._publish(session, topics.TASK_STARTED, {"task_id": session.task_id, "worker_id": self._worker_id})

        pending_user_text = user_text
        while True:
            if self._paused():
                return await self._pause(session)

            step_no = session.next_step_no()
            is_last = session.budget.is_last_step
            # Live-caught (the creator: "not informative ... what do you
            # mean thinking"): every narration event before this one fired
            # *after* `_think()` already had its reply -- during the real
            # wait (the slow part, seconds to well over a minute for a
            # real model call) nothing was published at all. This is a
            # bus-only heads-up (no Ledger append, no `session.record()`
            # -- it isn't a completed step, just an announcement of intent)
            # so a live narrator has something concrete to say *while*
            # waiting, not just after.
            await self._publish(session, topics.TASK_STEP, {
                "task_id": session.task_id, "step_no": step_no, "phase": "gather",
                "summary": f"asking the model (purpose={'chat' if session.profile.name == 'chat' else 'draft'})",
            })
            think_reply = await self._think(session, pending_user_text, last_step=is_last)
            pending_user_text = ""

            if think_reply is None:  # provider unavailable / timeout -- honest floor
                if session.profile.name == "chat":
                    return Outcome("completed", result_summary="", floor=True)
                return Outcome("blocked", reason="no real provider")

            session.budget.steps_used += 1
            tool_calls = think_reply.payload.get("tool_calls") or []
            floor = think_reply.payload.get("floor", False)

            if tool_calls and is_last and tool_calls[0].get("tool") in FINISHING_TOOLS and session.uncommitted:
                # The last step may still *finish*: refusing a git_commit
                # here threw away the whole attempt's work and reported
                # "step budget exhausted" over an applied, tested change
                # (watched trial, 2026-09-07). A finishing tool ends the
                # work rather than extending it, so it costs no further
                # step -- the model answers straight after.
                call = tool_calls[0]
                ok, summary, detail = await self._propose_and_await(session, call, step_no)
                step = Step(step_no, "act", detail, tool=call.get("tool"), ok=ok)
                session.record(step)
                await self._record_step(session, step)
                if ok:
                    # A successful finishing action leaves nothing for
                    # cleanup to undo. The `file_write`/`git_commit` side
                    # effects normally say so; clearing here as well means
                    # a tool that reports success without them can never
                    # have its own commit discarded a moment later.
                    session.uncommitted.clear()
                    session.created.clear()
                text = f"{'Committed' if ok else 'Could not commit'} the change: {summary}"
                session.messages.append({"role": "assistant", "content": text})
                if not session.profile.verify:
                    return Outcome("completed", result_summary=text, floor=False)
                return await self._verify_then_finish(session, text, floor=False)

            if tool_calls and not is_last:
                call = tool_calls[0]  # one action per step (section 7)
                ok, summary, detail = await self._propose_and_await(session, call, step_no)
                # `detail` (narration/Ledger, generously bounded) vs `summary`
                # (the model's own next-turn context, tightly bounded) are
                # deliberately different lengths -- see `_propose_and_await`.
                step = Step(step_no, "act", detail, tool=call.get("tool"), ok=ok)
                session.record(step)
                await self._record_step(session, step)
                # Two turns, not one. This used to append a single
                # *assistant* message reading "[tool_call read_file] ->
                # <the file>", so the model was asked to continue a
                # conversation whose last turn was its own, with the tool
                # output attributed to itself rather than returned to it.
                #
                # Live-caught 2026-09-07, monitoring whether Sim ever
                # edits its own source: it never has -- 246 tool runs,
                # every one read-only, zero `apply_source_patch`. Asked to
                # add a docstring, it searched, read the exact file, and
                # then answered "It looks like your message came through
                # as just a step marker with no actual content." It was
                # looking for a turn addressed to it and finding a
                # fragment it thought it had written, so it lost the
                # thread and wrote prose instead of applying anything.
                #
                # The request stays the assistant's; the result comes back
                # as a turn addressed to it, which is the shape every
                # tool-using model is trained on.
                tool_name = call.get("tool")
                session.messages.append({
                    "role": "assistant", "content": f"[tool_call {tool_name}]",
                })
                # "Continue the task." here was read literally: after a
                # successful git_commit the model re-read the file, ran the
                # tests again, re-applied the same content, and burned the
                # whole step budget without ever answering (watched trial,
                # 2026-09-07). Say what finishing looks like every time.
                session.messages.append({
                    "role": "user",
                    "content": (
                        f"Result of {tool_name}:\n{summary}\n\n"
                        "If the task is now finished, reply with your final answer in plain text, "
                        "with no tool marker. Otherwise take the next step."
                    ),
                })
                if self._paused():
                    return await self._pause(session)
                continue

            text = think_reply.payload.get("text", "")
            if tool_calls and is_last:
                # The budget ran out while the model was still asking for
                # a tool. That is not a finished task, and recording it as
                # `completed` -- with the raw tool marker as the answer --
                # taught Learning that doing nothing is a win, and showed
                # the human "READ_FILE: simorgh/cognition/parser.py" as a
                # result. Found by two watched trials 2026-09-07.
                step = Step(step_no, "act", "step budget exhausted with work still pending", ok=False)
                session.record(step)
                await self._record_step(session, step)
                return Outcome("blocked", reason=f"{CONTINUATION_REASON} before the task was finished")
            step = Step(step_no, "gather" if step_no == 1 else "act", "final answer", ok=True)
            session.record(step)
            await self._record_step(session, step)
            session.messages.append({"role": "assistant", "content": text})

            if not session.profile.verify:
                return Outcome("completed", result_summary=text, floor=floor)

            return await self._verify_then_finish(session, text, floor=floor)

    # -- phases -----------------------------------------------------------------------------

    async def _think(self, session: Session, user_text: str, *, last_step: bool) -> Message | None:
        offered = offered_tools(session.profile.tools)
        messages = await self._assembler.assemble(session, session.profile.scaffold, user_text=user_text)
        is_chat = session.profile.name == "chat"
        req = Message.new(
            topics.COGNITION_THINK, source=self._bus.source,
            payload={
                "purpose": "chat" if is_chat else "draft",
                "messages": messages, "tools": list(offered),
                # `Profile.scaffold` reached `assemble()` and was dropped;
                # Cognition's protected `task_rules` block (04 section 5.4)
                # was implemented and never filled by anyone. So a patch
                # session was told what it *could* call and never what
                # finishing means -- live 2026-09-07, a run applied its
                # edit and stopped without committing it. See scaffolds.py.
                "task_rules": scaffolds.render(
                    session.profile, subject=session.subject, task=session.user_text,
                ),
                # Live-caught: this request never actually asked Cognition
                # to parse tool calls -- `expected` was never set, so
                # `cognition/service.py::_expected_spec` always fell
                # through to `{"kind": "final"}` and every model reply was
                # treated as a plain answer, no matter what it wrote. The
                # GATHER -> THINK -> (tool_calls -> PROPOSE | final ->
                # VERIFY) loop this module's own docstring describes was
                # real code with no way to ever reach its tool_calls
                # branch from a real chat turn. `expected: "tool_calls"`
                # only when this profile actually has tools to offer --
                # an empty list would ask Cognition to scan for zero
                # markers, indistinguishable from asking for `final`
                # except for the wasted round-trip.
                "expected": "tool_calls" if offered else "text",
                # Live-caught: the general "here's the marker syntax"
                # instruction (cognition/service.py) never told the model
                # a tool's own argument *shape* -- a model asked to use
                # propose_mcp_server invented a JSON format with a made-up
                # field instead of the real key:value one. Only tools with
                # real internal structure need an entry (orchestration/
                # tools.py::_MARKER_ARG_HINT); most don't.
                "tool_hints": {t: h for t in offered if (h := marker_hint(t))},
                "budget": {"max_tokens": session.profile.max_output_tokens, "max_cost_usd": 0.5},
                "require_real_provider": False, "last_step": last_step,
                # Live-caught (v2 live trial, 2026-09-06): a chat turn
                # whose assembled memory-retrieval block happens to be
                # large (large migrated records, a broad query) could
                # exceed budget even after layers 1-4 -- `allow_summarize`
                # (04-cognition.md section 5's own layer 5, "last resort")
                # exists precisely for this and was simply never opted
                # into here. Scoped to chat only, never draft -- summarizing
                # a patch/skill draft's own code context could silently
                # lose the exact content a real code change needs.
                "allow_summarize": is_chat,
            },
            clock=self._clock,
        )
        reply = await self._bus.request_or_error(req, timeout=self._think_timeout_s)
        if reply.payload.get("ok") is False:
            # Live-caught (v2 live trial, 2026-09-06): this used to just
            # return None, and every caller collapsed that into a silent,
            # empty `Outcome(floor=True, result_summary="")` -- no error
            # code anywhere, not on the Ledger, not in the HTTP response,
            # not even printed (the real process's stdout is buffered when
            # not a tty). Diagnosing a real intermittent failure this way
            # took far longer than it should have. A `task.step` record
            # with `ok=False` costs nothing and makes the actual Cognition
            # error code/detail visible on this task's own Ledger stream
            # (queryable via `/api/logs?stream=task:<id>`) instead of
            # vanishing -- callers still get `None` and are unaffected.
            error = reply.payload.get("error") or {}
            # `phase` is `gather|act|verify` in the contract (TaskStep); the
            # failed think happened while gathering the answer, so "gather"
            # -- a first version wrote "think", which only the schema-blind
            # Ledger path accepted (post-cutover review caught it).
            step_payload = {
                "task_id": session.task_id, "step_no": session.next_step_no(),
                "phase": "gather", "ok": False,
                "summary": f"cognition error: {error.get('code', 'unknown')} -- {error.get('detail', '')}",
            }
            await self._append(session, topics.TASK_STEP, step_payload)
            # Published too (not just appended) so a live surface -- the
            # REPL's narration, the dashboard feed -- sees the failure as
            # it happens, not only in the Ledger afterwards.
            await self._publish(session, topics.TASK_STEP, step_payload)
            return None
        return reply

    # Live-caught (the creator: "I'd like ... code diffs ... similar UI
    # experience as claude code cli" -- 07-post-cutover-review.md §3.11):
    # a real diff (`execution/tools.py::_write_scoped_file`) now travels
    # through `output`/`stdout_preview`, but the old 200-char cap here
    # existed for the *model's own next-turn context* (`session.messages`
    # -- keeping tool output small is deliberate, this session's own
    # context_too_large work), not for what a human watching narration
    # gets to see. Returns both: `summary` (200 chars, unchanged, goes to
    # the model) and `detail` (2000 chars, goes only to the published
    # `task.step` -- the Ledger, the CLI narration, the dashboard feed --
    # never back into the model's own context).
    _DETAIL_CHARS = 2000
    # What the *model* is shown of a tool result.
    #
    # This was 200 characters. Live-caught 2026-09-07, tracing why
    # Sim had never once edited its own source across 246 tool runs:
    # asked to add a docstring to a 5,457-character file, it read the
    # file, was handed the first 200 characters of it, and read it
    # again -- eight times in a row, replying with nothing but
    # "READ_FILE: simorgh/interface/vitals.py" each time. It could not
    # patch a file it had never been allowed to see, and `list_dir` of
    # the repo root came back so clipped that it concluded it was
    # working in "an empty temp directory".
    #
    # 8000 characters is about 2000 tokens, which is exactly the size
    # Cognition already budgets per tool result
    # (`cognition/config.py::tool_result_max_tokens`) and compacts
    # from layer 1 onward. Bounding it to a fiftieth of that here,
    # before compaction ever saw it, was not caution -- it removed
    # the only channel the model had for looking at anything.
    _MODEL_RESULT_CHARS = 8000

    @classmethod
    def _bound_for_model(cls, text: str) -> str:
        # A silent cut taught the model that the file *ended* there
        # (observer round, 2026-09-07: it rewrote a module from the
        # first 8000 chars and lost the rest). Say it was cut, say how
        # long the whole thing is, and say how to get the remainder.
        if len(text) <= cls._MODEL_RESULT_CHARS:
            return text
        return (
            text[: cls._MODEL_RESULT_CHARS]
            + f"\n...[cut at {cls._MODEL_RESULT_CHARS} of {len(text)} chars;"
            " for a file, READ_FILE: path:START-END returns just those lines]"
        )

    async def _propose_and_await(self, session: Session, call: dict, step_no: int) -> tuple[bool, str, str]:
        action_id = uuid.uuid4().hex[:12]
        payload = to_action_payload(
            action_id=action_id, task_id=session.task_id, call=call,
            rationale=f"step {step_no} of {session.profile.name} session",
            proposed_by=self._bus.source,
        )
        msg = Message.new(
            topics.ACTION_PROPOSED, source=self._bus.source,
            payload=payload, partition_key=f"task:{session.task_id}", clock=self._clock,
        )
        await self._bus.publish(msg)
        result = await self._waiter.wait(
            (topics.ACTION_RESULT, topics.ACTION_DENIED, topics.ACTION_NEEDS_HUMAN),
            key="action_id", value=action_id,
            timeout=_ACTION_TIMEOUTS.get(call.get("tool"), self._action_timeout_s),
        )
        if result is None:
            text = f"{call.get('tool')}: no response (timed out)"
            return False, text, text
        if result.type == topics.ACTION_RESULT:
            ok = result.payload.get("ok", False)
            if ok:
                for effect in result.payload.get("side_effects") or ():
                    kind, _, path = str(effect).partition(":")
                    if kind == "file_write" and path:
                        session.uncommitted.add(path)
                    elif kind == "file_create" and path:
                        # A file this session brought into existence. If it
                        # is never committed, cleanup removes it outright:
                        # `git_discard` rightly refuses an untracked path,
                        # which used to leave every abandoned new file
                        # behind as a dirty tree (watched trials, 2026-09-07).
                        session.uncommitted.add(path)
                        session.created.add(path)
                    elif kind in ("git_commit", "git_discard") and path:
                        session.uncommitted.discard(path)
                        session.created.discard(path)
            full = result.payload.get("stdout_preview", "")
            error = result.payload.get("error") or ""
            if not ok:
                # A failing tool puts its reason in `error`, not in
                # `stdout_preview`, and only the preview was ever read --
                # so a refusal reached the model as an *empty* result. It
                # was told "that failed" and nothing else.
                #
                # Live-caught 2026-09-07: `apply_source_patch` was refused
                # and the step recorded an empty summary, leaving the
                # model to guess. The same silence sat behind every failed
                # `run_tests` and `git_commit` in the earlier trials.
                full = f"{error}\n\n{full}".strip() if full else error
            return ok, self._bound_for_model(full), full[: self._DETAIL_CHARS]
        if result.type == topics.ACTION_DENIED:
            reasons = "; ".join(result.payload.get("reasons", [])) or result.payload.get("layer", "denied")
            text = f"denied: {reasons}"
            return False, text, text
        text = f"needs human: {result.payload.get('question', '')}"
        return False, text, text

    async def _verify_then_finish(self, session: Session, text: str, *, floor: bool) -> Outcome:
        while True:
            # A fresh verification_id per attempt (not just per session): a
            # real Verification service treats a *repeated* id on
            # `verify:<id>` as a redelivery and replays the recorded verdict
            # instead of re-running checks (10 section 8, "duplicate
            # request") -- reusing one id across revisions would silently
            # replay the first (failing) verdict forever and never see the
            # revised text (harness-06 gap #5: iterative verification).
            verification_id = uuid.uuid4().hex[:12]
            subject_ref = await self._put_verify_subject(session, text)
            msg = Message.new(
                topics.VERIFY_REQUESTED, source=self._bus.source,
                payload={
                    "verification_id": verification_id, "task_id": session.task_id,
                    "kind": "task", "subject_ref": subject_ref,
                },
                partition_key=f"task:{session.task_id}", clock=self._clock,
            )
            await self._bus.publish(msg)
            result = await self._waiter.wait(
                (topics.VERIFY_RESULT,), key="verification_id", value=verification_id, timeout=self._verify_timeout_s,
            )
            if result is None:
                # No verdict in time. Accept rather than block forever, but
                # say so: "verification never answered" used to be
                # indistinguishable from "verification passed".
                step = Step(session.next_step_no(), "act",
                            f"verification did not answer within {self._verify_timeout_s:.0f}s; accepted unverified",
                            ok=False)
                session.record(step)
                await self._record_step(session, step)
                return Outcome("completed", result_summary=text, floor=floor, verification_ref=None)

            verdict = result.payload.get("verdict")
            if verdict in ("pass", "insufficient_evidence"):
                return Outcome("completed", result_summary=text, floor=floor, verification_ref=verification_id)

            # The objection, on the record. A failed verdict used to leave
            # nothing on the task's own stream or on screen: the trial saw
            # "blocked: verification failed after max revisions" after a
            # search, a patch, a green suite and a commit, and nobody could
            # say what the reviewer had objected to (2026-09-07).
            feedback = result.payload.get("feedback", {}).get("items", [])
            note = "; ".join(
                f"{f.get('what')}" + (f" -- {f.get('why')}" if f.get('why') else "")
                + (f" (fix: {f.get('suggested_fix')})" if f.get('suggested_fix') else "")
                for f in feedback
            ) or "revise and try again"
            step = Step(session.next_step_no(), "verify", f"verification {verdict}: {note}", ok=False)
            session.record(step)
            await self._record_step(session, step)

            if session.budget.revisions_used >= session.profile.max_revisions:
                # The answer travels with the refusal. Otherwise nobody
                # downstream can tell whether verification rejected
                # something wrong or something right.
                return Outcome("blocked", reason="verification failed after max revisions",
                               result_summary=text, verification_ref=verification_id)

            session.budget.revisions_used += 1
            session.messages.append({"role": "user", "content": f"Verification feedback: {note}"})
            think_reply = await self._think(session, "", last_step=session.budget.is_last_step)
            if think_reply is None:
                return Outcome("blocked", reason="no real provider during revision", verification_ref=verification_id)
            text = think_reply.payload.get("text", text)
            session.messages.append({"role": "assistant", "content": text})

    async def _put_verify_subject(self, session: Session, text: str) -> str:
        """`verify.requested.subject_ref` is a blob ref, not raw text --
        Verification's `_resolve_subject` reads it with `ledger.get_blob`
        and expects a JSON object with `description`/`result` (the shape
        every other producer, e.g. `learning/pipeline.py`'s
        `candidate_ref`, already sends). Sending truncated raw text there
        silently resolves to an empty subject and the semantic checklist
        loses its signal.
        """
        # The steps travel too. The reviewer used to see only the task
        # and the final answer, generate questions about the change, and
        # answer them from the answer's *prose* -- so a correct patch with
        # a green suite and a commit failed on "does the new code have a
        # test?" it was never asked to write, and a research answer failed
        # on whatever its two paragraphs did not happen to mention
        # (watched trials, 2026-09-07). Now it sees what was actually done.
        steps = [
            {
                "tool": step.tool, "ok": step.ok, "phase": step.phase,
                "summary": (step.summary or "")[: 1500 if step.tool in ("apply_source_patch", "apply_skill") else 300],
            }
            for step in session.steps
        ]
        payload = json.dumps({
            "description": session.user_text, "result": text[:2000], "kind": session.kind, "steps": steps,
        }).encode("utf-8")
        return await self._ledger.put_blob(payload, content_type="application/json")

    # -- pause/resume -------------------------------------------------------------------------

    def _paused(self) -> bool:
        return self._is_paused()

    async def _pause(self, session: Session) -> Outcome:
        resume_from = len(session.steps)
        await self._append(session, topics.TASK_PAUSED, {
            "task_id": session.task_id, "reason": "system paused", "resume_from_step": resume_from,
        })
        await self._publish(session, topics.TASK_PAUSED, {
            "task_id": session.task_id, "reason": "system paused", "resume_from_step": resume_from,
        })
        return Outcome("paused", reason="system paused")

    # -- ledger + bus plumbing -----------------------------------------------------------------

    async def _record_step(self, session: Session, step: Step) -> None:
        payload = {
            "task_id": session.task_id, "step_no": step.no, "phase": step.phase, "summary": step.summary,
        }
        if step.tool is not None:
            payload["tool"] = step.tool
        if step.ok is not None:
            payload["ok"] = step.ok
        await self._append(session, topics.TASK_STEP, payload)
        await self._publish(session, topics.TASK_STEP, payload)

    async def _append(self, session: Session, type_: str, payload: dict) -> None:
        msg = Message.new(type_, source=self._bus.source, payload=payload,
                          partition_key=f"task:{session.task_id}", clock=self._clock)
        await self._ledger.append(f"task:{session.task_id}", Event.from_message(msg, f"task:{session.task_id}"))

    async def _publish(self, session: Session, type_: str, payload: dict) -> None:
        msg = Message.new(type_, source=self._bus.source, payload=payload,
                          partition_key=f"task:{session.task_id}", clock=self._clock)
        await self._bus.publish(msg)
