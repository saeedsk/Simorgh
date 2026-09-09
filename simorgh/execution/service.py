"""Execution's Service (08-execution.md section 5): the only subsystem
the Kernel/Bus enforcement lets subscribe to `action.approved`. Verifies
every approval independently (verifier.py) before running anything,
dispatches to the tool registry, and reports `action.result`. Registry
and dispatch are kept in this one module for this build (the spec's
`registry.py`/`runner.py` split is a natural follow-up once the tool
count grows past what fits in one screenful).

Skill acquisition as procedural memory (Phase 4 roadmap item 4.7): per
08-execution.md's own dependency line ("Depends on ... learn.skill.
acquired") and section 5.2 ("`learn.skill.acquired` -> load the skill
module in a sandbox-backed SkillTool, register it, emit tool.registered"),
this Service subscribes to `learn.skill.acquired` and loads exactly the
one newly-acquired skill -- never a directory scan of every skill ever
acquired at boot, which is what makes this "on demand." `_load_skill`
also best-effort enriches the tool's `description` via a
`memory.retrieve{kinds:[procedural]}` request against the procedural
record Learning writes on acquisition (learning/pipeline.py) -- the
"discoverable by description" half of the same roadmap item. A second,
independent on-demand path lives in `_on_approved`: an approved action
naming an as-yet-unregistered `skill:<name>` tool (e.g. after a restart,
when no fresh `learn.skill.acquired` fired this process) triggers the
same `_load_skill` lazily, reconstructing the skill's path from the
`skill_dir/<name>.py` convention `ApplySkillTool` and `SkillPipeline`
both already use.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import time
from pathlib import Path

from simorgh.contracts import topics
from simorgh.contracts.envelope import Event, Message
from simorgh.contracts.protocols import Health, ToolContext

from . import pathsafety
from .config import Config

# The Ledger's blob-ref shape, matched here by shape rather than by
# importing the Ledger's helper (the module-boundary rule).
_BLOB_REF = re.compile(r"^blob:[0-9a-f]{64}$")
from .external import load_external_tools
from .mcp import McpClient, McpServerConfig, McpToolProxy, mcp_single_arg_key
from .tools import SkillTool, builtin_tools
from .verifier import ApprovalVerifier

INFLIGHT_STREAM = "execution:inflight"
TOOLS_STREAM = "execution:tools"


class Service:
    name = "execution"
    version = "0.1.0"
    consumes = (topics.ACTION_APPROVED, topics.SYSTEM_STATE_CHANGED, topics.LEARN_SKILL_ACQUIRED)
    produces = (topics.ACTION_RESULT, topics.ACTION_DENIED, topics.TOOL_REGISTERED, topics.PERCEPT_WEB_FETCHED, topics.SYSTEM_METRICS,)

    def __init__(self, *, config: Config | None = None, extra_tools: list | None = None) -> None:
        self._config = config or Config()
        self._extra_tools = extra_tools or []
        self._registry: dict[str, object] = {}
        self._subs: list = []
        self._paused = False
        self._semaphore: asyncio.Semaphore | None = None
        self._degraded_detail = ""
        self._mcp_clients: list[McpClient] = []
        self._mcp_errors: list[str] = []

    async def start(self, ctx) -> None:
        self._ctx = ctx
        secret = ctx.secrets.get("__hmac__")
        if not secret:
            raise RuntimeError("execution: no guardian_hmac secret in Context -- refusing to start")
        self._secret = bytes.fromhex(secret) if isinstance(secret, str) else secret
        self._verifier = ApprovalVerifier(self._secret)
        self._semaphore = asyncio.Semaphore(self._config.max_concurrent_actions)

        # External adapters (external.py) load last so a hand-built tool of
        # the same name is never shadowed by an optional package's.
        external = load_external_tools(self._config.external_tools, logger=ctx.logger)
        for tool in builtin_tools(self._config) + self._extra_tools + external:
            if tool.name in self._registry:
                ctx.logger.warning("tool_name_collision", name=tool.name, provider=getattr(tool, "provider", "builtin"))
                continue
            self._registry[tool.name] = tool
            await ctx.bus.publish(Message.new(
                topics.TOOL_REGISTERED, source="execution",
                payload={"name": tool.name, "version": "1", "description": tool.description,
                         "read_only": tool.read_only, "reversibility": tool.reversibility,
                         "schema_ref": "", "provider": getattr(tool, "provider", "builtin")},
            ))
            await ctx.ledger.append(TOOLS_STREAM, self._event(TOOLS_STREAM, "registered", {
                "name": tool.name, "provider": getattr(tool, "provider", "builtin"),
                "reversibility": tool.reversibility, "read_only": tool.read_only,
            }))

        # Skills already on disk get ANNOUNCED, not loaded. Loading stays
        # on demand by design (see
        # tests/simorgh/integration/test_skill_acquisition_procedural_memory.py:
        # "never a directory scan of every skill ever acquired at boot").
        # The gap the audit found was different: nothing ever told the
        # model a skill existed, so it could never name one, so the lazy
        # load in `_on_approved` could never fire. A skill Sim wrote was
        # a committed file and nothing else (2026-09-08). Announcing the
        # name costs a directory listing and no source read.
        await self._announce_skills_on_disk()

        for server in self._config.mcp_servers:
            await self._start_mcp_server(server)

        await self._replay_inflight()

        self._subs.append(await ctx.bus.subscribe(topics.ACTION_APPROVED, self._on_approved, group="execution"))
        self._subs.append(await ctx.bus.subscribe(topics.SYSTEM_STATE_CHANGED, self._on_state_changed))
        self._subs.append(await ctx.bus.subscribe(topics.LEARN_SKILL_ACQUIRED, self._on_skill_acquired))

    async def stop(self) -> None:
        for sub in self._subs:
            await sub.unsubscribe()
        self._subs.clear()
        for client in self._mcp_clients:
            await client.close()
        self._mcp_clients.clear()

    async def health(self) -> Health:
        if self._degraded_detail:
            return Health.degraded(self._degraded_detail)
        if self._mcp_errors:
            return Health.degraded("; ".join(self._mcp_errors))
        return Health.ok(f"{len(self._registry)} tools registered")

    # -- MCP servers (mcp.py's own module docstring: a human-configured,
    # static list -- never autonomously expanded) ---------------------------
    async def _start_mcp_server(self, server: McpServerConfig) -> None:
        """Start one configured MCP server and register every tool it
        declares. Never raises: a server that fails to launch, times out,
        or speaks a broken protocol is logged and skipped -- one
        misconfigured server must not stop the rest of Execution (and
        therefore the whole Kernel) from booting."""
        client = McpClient(server)
        try:
            await asyncio.wait_for(client.start(), timeout=server.timeout_s)
            specs = await asyncio.wait_for(client.list_tools(), timeout=server.timeout_s)
        except Exception as exc:  # noqa: BLE001 -- a bad server degrades, never crashes Execution's boot
            detail = f"mcp server {server.name!r} failed to start: {exc!r}"
            self._mcp_errors.append(detail)
            self._ctx.logger.warning("mcp_server_start_failed", server=server.name, detail=repr(exc))
            with contextlib.suppress(Exception):
                await client.close()
            return

        self._mcp_clients.append(client)
        for spec in specs:
            tool = McpToolProxy(client, server, spec)
            self._registry[tool.name] = tool
            await self._ctx.bus.publish(Message.new(
                topics.TOOL_REGISTERED, source="execution",
                payload={"name": tool.name, "version": "1", "description": tool.description,
                         "read_only": tool.read_only, "reversibility": tool.reversibility,
                         "schema_ref": "", "provider": "mcp",
                         "marker_arg_key": mcp_single_arg_key(tool.args_schema)},
            ))
            await self._ctx.ledger.append(TOOLS_STREAM, self._event(TOOLS_STREAM, "registered", {
                "name": tool.name, "provider": "mcp", "reversibility": tool.reversibility,
                "read_only": tool.read_only, "marker_arg_key": mcp_single_arg_key(tool.args_schema),
            }))

    async def _on_state_changed(self, message: Message) -> None:
        self._paused = message.payload["state"] in ("paused", "stopping")

    # -- skill acquisition as procedural memory (roadmap 4.7) --------------------
    async def _on_skill_acquired(self, message: Message) -> None:
        name, path = message.payload.get("name", ""), message.payload.get("path", "")
        if name and path:
            await self._load_skill(name, path=path)

    def skill_files(self) -> list[Path]:
        directory = self._config.repo_root / self._config.skill_dir
        if not directory.is_dir():
            return []
        return [p for p in sorted(directory.glob("*.py")) if not p.name.startswith("_")]

    async def _announce_skills_on_disk(self) -> int:
        """Say which skills exist, without reading or loading any.

        `tool.registered` is how Orchestration learns a tool's name, and
        a name is all the model needs to ask for one; the source and the
        real description are read by `_load_skill` when an approved
        action first names it. A skill already in the registry (acquired
        this process) is left alone -- its announcement was the real one.
        """
        announced = 0
        for path in self.skill_files():
            name = f"skill:{path.stem}"
            if name in self._registry:
                continue
            await self._ctx.bus.publish(Message.new(
                topics.TOOL_REGISTERED, source="execution",
                payload={"name": name, "version": "1",
                         "description": f"skill {path.stem!r} from an earlier session (loaded on first use)",
                         "read_only": False, "reversibility": "reversible",
                         "schema_ref": "", "provider": "skill"},
            ))
            announced += 1
        if announced:
            self._ctx.logger.info("skills_announced", count=announced, directory=self._config.skill_dir)
        # `status` read a counter `learning.skills_acquired` that nothing
        # ever published, so it showed "skills: 0" forever (observer,
        # 2026-09-08). Execution is what actually knows.
        await self._ctx.bus.publish(Message.new(
            topics.SYSTEM_METRICS, source=self._ctx.source,
            payload={"subsystem": "execution", "counters": {},
                     "gauges": {"skills": len(self.skill_files())}},
        ))
        return announced

    async def _load_skill(self, name: str, *, path: str) -> object | None:
        """Register the one named skill as a `skill:<name>` tool, reading
        its source from `path` (readable-roots bounded) and its
        description from Memory's procedural record if one answers in
        time. Never raises; a load that cannot complete just leaves the
        tool unregistered for the caller to report as `unknown tool`.

        Always re-reads the file rather than trusting an already-registered
        tool's captured source: `apply_skill` rewrites a skill's file in
        place and then calls right back in here (`_on_approved`'s
        `LEARN_SKILL_ACQUIRED` re-publish, same process, same registry) to
        make the fix live immediately. An early return here used to hand
        back the pre-fix `SkillTool` -- whose `_source` was captured once
        at construction and never looked at the file again -- so a
        self-applied bugfix was silently invisible until the next kernel
        restart (live-caught, 2026-09-08: a skill fixed via `apply_skill`
        kept running its old, broken code in the very same process that
        just "fixed" it). Only the no-op case -- source on disk is
        unchanged from what is already registered -- is still short-
        circuited, so a genuinely repeated acquisition does not spam a
        second `tool.registered`/ledger entry (see
        `test_a_second_acquisition_of_the_same_name_does_not_re_register`)."""
        existing = self._registry.get(f"skill:{name}")
        # `safe_read_file` caps at `_MAX_READ_CHARS` and appends a
        # human-readable "...[truncated at N of M chars; read the rest
        # with ...]" hint -- correct for a `read_file` tool result shown
        # to the model, wrong here: that hint text was landing verbatim
        # inside the *executable* source this loads, silently corrupting
        # any skill whose source exceeded the cap (live-caught by an
        # observer probe, 2026-09-09: a 500KB generated skill wrote to
        # disk intact but failed with a SyntaxError from the injected
        # truncation notice the moment it ran). `read_source` returns the
        # file's real, uncapped content -- capping belongs to the
        # tool-output path, not to what actually gets executed.
        source, refusal = pathsafety.read_source(self._config.repo_root, path, readable_roots=self._config.readable_roots)
        if refusal:
            self._ctx.logger.warning("skill_load_refused", name=name, path=path, detail=refusal)
            return existing
        if existing is not None and getattr(existing, "_source", None) == source:
            return existing
        description = await self._skill_description(name) or f"On-demand skill {name!r} acquired at {path}"
        tool = SkillTool(self._config, skill_name=name, source=source, description=description)
        self._registry[tool.name] = tool
        await self._ctx.bus.publish(Message.new(
            topics.TOOL_REGISTERED, source="execution",
            payload={"name": tool.name, "version": "1", "description": tool.description,
                     "read_only": tool.read_only, "reversibility": tool.reversibility,
                     "schema_ref": "", "provider": "skill", "marker_arg_key": tool.marker_arg_key},
        ))
        await self._ctx.ledger.append(TOOLS_STREAM, self._event(TOOLS_STREAM, "registered", {
            "name": tool.name, "provider": "skill", "reversibility": tool.reversibility,
            "read_only": tool.read_only, "marker_arg_key": tool.marker_arg_key,
        }))
        return tool

    async def _skill_description(self, name: str) -> str | None:
        """Best-effort `memory.retrieve{kinds:[procedural]}` for the
        description Learning stored on acquisition (learning/pipeline.py)
        -- the "discoverable by description" half of roadmap item 4.7.
        Absence (timeout, no Memory booted, nothing stored yet) degrades
        to a synthesized description rather than blocking the load."""
        try:
            reply = await self._ctx.bus.request(
                Message.new(
                    topics.MEMORY_RETRIEVE, source="execution",
                    payload={"query": name, "kinds": ["procedural"], "k": 3,
                             "filters": {"tags": ["skill", name]}},
                ),
                timeout=self._config.skill_lookup_timeout_s,
            )
        except Exception:  # noqa: BLE001 -- a description lookup failure must never block loading the skill
            return None
        items = reply.payload.get("items") or []
        if not items:
            return None
        # `memory.retrieve` ranks by similarity*confidence plus a recency
        # term, not by recency alone -- right for open-ended semantic
        # search, wrong here: `filters` already narrows the pool to
        # records tagged for exactly this one skill, so what's left to
        # pick among them is which is CURRENT, not which reads most like
        # the query. A skill re-applied via `apply_skill` appends a new
        # procedural record (append-only) rather than replacing the old
        # one, and a stale first-draft description that happens to repeat
        # the skill's own name in its text can out-score a fresh, accurate
        # one on lexical similarity alone (live-caught, 2026-09-08: a
        # skill's fixed v2 behavior still reported its v1 description).
        # Taking the newest of the (already skill-scoped) candidates
        # instead keeps the announced description in step with the code.
        return max(items, key=lambda i: i.get("ts", 0.0))["content"]

    async def _replay_inflight(self) -> None:
        events = await self._ctx.ledger.read(INFLIGHT_STREAM)
        started = {e.payload["action_id"] for e in events if e.type == "started"}
        finished = {e.payload["action_id"] for e in events if e.type == "finished"}
        for action_id in started - finished:
            await self._ctx.bus.publish(Message.new(
                topics.ACTION_RESULT, source="execution",
                payload={"action_id": action_id, "ok": False, "output_ref": "", "stdout_preview": "",
                         "duration_ms": 0, "side_effects": [], "error": "interrupted by restart"},
            ))
            await self._ctx.ledger.append(INFLIGHT_STREAM, self._event(INFLIGHT_STREAM, "finished", {"action_id": action_id, "ok": False}))

    async def _fetch_proposed_args(self, action_id: str) -> dict | None:
        events = await self._ctx.ledger.read(f"action:{action_id}")
        for event in events:
            if event.type == "received":
                return await self._resolve_arg_refs(event.payload["proposal"].get("args"))
        return None

    async def _resolve_arg_refs(self, args: dict | None) -> dict | None:
        """Guardian records an oversized argument (a patch's whole file
        body) as a blob ref, since the Ledger refuses it inline. The
        verifier hashes the real arguments, so they are read back here."""
        if not isinstance(args, dict):
            return args
        resolved: dict = {}
        for key, value in args.items():
            # `blob:<sha256>` is the Ledger's ref shape (02 section 4.2).
            # Matched here by shape rather than by importing the Ledger's
            # own helper, which the module-boundary rule forbids.
            if isinstance(value, str) and _BLOB_REF.match(value):
                resolved[key] = (await self._ctx.ledger.get_blob(value)).decode("utf-8")
            else:
                resolved[key] = value
        return resolved

    async def _on_approved(self, message: Message) -> None:
        approved = message.payload
        action_id = approved["action_id"]
        now = self._ctx.clock.now()
        args = await self._fetch_proposed_args(action_id)
        outcome = self._verifier.verify(approved, args, now=now)

        await self._ctx.ledger.append(f"action:{action_id}", self._event(
            f"action:{action_id}", "verified", {"outcome": outcome.ok, "reason": outcome.reason},
        ))

        if not outcome.ok:
            await self._ctx.bus.publish(message.caused(
                topics.ACTION_DENIED,
                {"action_id": action_id, "reasons": [f"signature {outcome.reason}"], "layer": "token"},
                source="execution",
            ))
            self._degraded_detail = f"token verification failed: {outcome.reason}"
            return
        self._degraded_detail = ""

        if self._paused:
            await self._publish_result(message, action_id, ok=False, error="paused")
            return

        tool = self._registry.get(approved["tool"])
        if tool is None and approved["tool"].startswith("skill:"):
            # Lazy on-demand load: this process never saw this skill's own
            # `learn.skill.acquired` (e.g. it was acquired before this
            # restart), so resolve it from the `skill_dir/<name>.py`
            # convention `ApplySkillTool`/`SkillPipeline` both use, rather
            # than reporting a false "unknown tool" for a skill that is
            # really just not loaded *yet*.
            skill_name = approved["tool"][len("skill:"):]
            tool = await self._load_skill(skill_name, path=f"{self._config.skill_dir}/{skill_name}.py")
        if tool is None:
            await self._publish_result(message, action_id, ok=False, error="unknown tool")
            return

        async with self._semaphore:
            await self._ctx.ledger.append(INFLIGHT_STREAM, self._event(INFLIGHT_STREAM, "started", {"action_id": action_id, "tool": tool.name}))
            start = time.monotonic()
            timeout = approved.get("constraints", {}).get("timeout_s") or self._config.default_timeout_s
            ctx = ToolContext(
                action_id=action_id, task_id=None, scope={}, constraints=approved.get("constraints") or {},
                data_dir=self._config.repo_root, clock=self._ctx.clock, logger=self._ctx.logger,
                ledger=self._ctx.ledger, bus=self._ctx.bus,
            )
            try:
                result = await asyncio.wait_for(tool.run(args or {}, ctx=ctx), timeout=timeout)
            except asyncio.TimeoutError:
                await self._finish(action_id)
                await self._publish_result(message, action_id, ok=False, error="timeout",
                                            duration_ms=int((time.monotonic() - start) * 1000))
                return
            except Exception as exc:  # noqa: BLE001 -- a tool crash must become a result, never take Execution down
                await self._finish(action_id)
                await self._publish_result(message, action_id, ok=False, error=repr(exc),
                                            duration_ms=int((time.monotonic() - start) * 1000))
                return

            await self._finish(action_id)
            duration_ms = int((time.monotonic() - start) * 1000)
            output = result.output if isinstance(result.output, str) else result.output.decode("utf-8", "replace")
            # A tool that fetched real data hands the rows back as a
            # file, and says so in its own output. Before this, the
            # rows existed only inside the tool's process: the model saw
            # a rendered summary of the first N and there was no way to
            # analyse the rest, which is the whole point of fetching
            # them (2026-09-09 -- the comparables analysis another agent
            # ran on 95120 listings needs the data, not a summary).
            output = self._store_rows(action_id, result, output)
            output_ref = ""
            preview = output
            if len(output.encode("utf-8")) > self._config.blob_inline_threshold_bytes:
                output_ref = await self._ctx.ledger.put_blob(output.encode("utf-8"))
                preview = output[: self._config.max_output_bytes]
            # Everything a tool reported ABOUT its result, kept whole.
            # `_publish_result` only ever forwarded a hand-picked few
            # fields (web_fetch's url/sha, propose_mcp_server's name), so
            # a caller downstream could not see, say, whether a search
            # was flagged low-confidence, and the Ledger recorded none of
            # it.
            metadata_ref = ""
            if result.metadata:
                metadata_ref = await self._ctx.ledger.put_blob(
                    json.dumps(result.metadata, default=str).encode("utf-8"),
                    content_type="application/json",
                )
            await self._publish_result(
                message, action_id, ok=result.ok, error=result.error, output_ref=output_ref,
                stdout_preview=preview[: self._config.max_output_bytes], duration_ms=duration_ms,
                side_effects=list(result.side_effects),
                stderr=str((result.metadata or {}).get("stderr") or ""),
                metadata_ref=metadata_ref,
            )
            await self._ctx.bus.publish(Message.new(
                topics.TOOL_INVOKED, source="execution",
                payload={"name": tool.name, "action_id": action_id, "duration_ms": duration_ms, "ok": result.ok},
            ))
            if tool.name == "apply_skill" and result.ok:
                # A skill becomes callable the moment it is written, not
                # only at the next boot. Until 2026-09-08 nothing ever
                # registered one, so a skill Sim wrote was a file and
                # nothing more (audit).
                # `args`, the arguments this call actually ran with --
                # NOT `approved["args"]`, which does not exist: the
                # `action.approved` contract carries `args_sha256` and
                # no arguments at all (contracts/messages/action.py).
                # So `subject` was always "", the branch never fired,
                # and the fix above never worked: after two successful
                # apply_skill calls the registry still held zero skills
                # (observer, 2026-09-08). `learn.skill.acquired` has two
                # publishers and this was one of them, so WorldModel,
                # Curiosity and Reflection were all subscribed to an
                # event that could never fire.
                subject = str((args or {}).get("subject") or "")
                if subject.endswith(".py"):
                    name = Path(subject).stem
                    await self._load_skill(name, path=subject)
                    await self._ctx.bus.publish(Message.new(
                        # The contract (`contracts/messages/learn.py`)
                        # names this field `tests`, not `tests_passed`.
                        # Every publish here raised ContractError and
                        # never delivered -- silently, until the bus
                        # stopped swallowing handler errors earlier
                        # today, at which point it became a traceback on
                        # every single skill apply instead (observer,
                        # 2026-09-08). `apply_skill` runs its own
                        # sandbox smoke test before this point, but that
                        # count is not threaded through to here, so `0`
                        # is honest -- it says a real test count was not
                        # measured at this call site, not that zero
                        # tests exist.
                        topics.LEARN_SKILL_ACQUIRED, source="execution",
                        payload={"name": name, "path": subject, "tests": 0,
                                 "description": f"skill {name!r} written by a skill task"},
                    ))
            if tool.name == "web_fetch" and result.ok:
                # 08-execution.md section 4.2's `percept.web.fetched` row
                # ("after web_fetch -- memory, curiosity"): the contract
                # (`contracts/messages/percept.py`) requires a `content_ref`
                # unconditionally, not the size-gated inline preview above,
                # so a small fetch still gets its own blob rather than
                # reusing `output_ref` (which stays "" under the inline
                # threshold).
                content_ref = output_ref or await self._ctx.ledger.put_blob(output.encode("utf-8"), content_type="text/plain")
                await self._ctx.bus.publish(Message.new(
                    topics.PERCEPT_WEB_FETCHED, source="execution",
                    payload={
                        "url": result.metadata.get("url", ""),
                        "status": int(result.metadata.get("status") or 0),
                        "content_ref": content_ref,
                        "sha256": result.metadata.get("sha256", ""),
                        "fetched_at": float(result.metadata.get("fetched_at") or 0.0),
                    },
                ))
            if tool.name == "propose_mcp_server" and result.ok:
                # `ProposeMcpServerTool`'s own docstring: it only records
                # a proposal, so the human learns about it the same way
                # any other notice reaches them -- `ui.notice`, printed
                # live by Interface -- rather than needing to think to
                # go check a Ledger stream nobody looks at unprompted.
                await self._ctx.bus.publish(Message.new(
                    topics.UI_NOTICE, source="execution",
                    payload={
                        "level": "info",
                        "text": (
                            f"Sim proposed an MCP server: {result.metadata.get('name', '')} "
                            f"({result.metadata.get('proposal_id', '')}) -- {result.metadata.get('reason', '')} "
                            "Review with `mcp`."
                        ),
                        "source": "execution",
                    },
                ))

    async def _finish(self, action_id: str) -> None:
        await self._ctx.ledger.append(INFLIGHT_STREAM, self._event(INFLIGHT_STREAM, "finished", {"action_id": action_id}))

    def _store_rows(self, action_id: str, result, output: str) -> str:
        """Write a tool's structured rows to a real file and name it in
        the output. Returns the output, unchanged when there is nothing
        to store.

        The file lands under `results/` -- a readable root that is NOT a
        write scope, so Sim can read back what it fetched and cannot
        commit it. Failure to write is never fatal: the rendered output
        is still a real answer, and a data tool must not fail because a
        directory was not writable.
        """
        rows = (result.metadata or {}).get("rows")
        if not isinstance(rows, list) or not rows:
            return output
        capped = rows[: self._config.results_max_rows]
        directory = self._config.repo_root / self._config.results_dir
        path = directory / f"{action_id}.json"
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(capped, default=str, indent=1))
            self._prune_results(directory)
        except OSError as exc:
            self._ctx.logger.warning("results_write_failed", action_id=action_id, error=repr(exc))
            return output
        rel = f"{self._config.results_dir}/{path.name}"
        note = f"\n\nfull data: {rel} ({len(capped)} of {len(rows)} rows)"
        if len(capped) == len(rows):
            note = f"\n\nfull data: {rel} ({len(rows)} rows)"
        return output + note

    def _prune_results(self, directory: Path) -> None:
        files = sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for stale in files[self._config.results_keep_files:]:
            with contextlib.suppress(OSError):
                stale.unlink()

    async def _publish_result(self, message: Message, action_id: str, *, ok: bool, error: str | None = None,
                               output_ref: str = "", stdout_preview: str = "", duration_ms: int = 0,
                               side_effects: list | None = None, stderr: str = "",
                               metadata_ref: str = "") -> None:
        payload = {
            "action_id": action_id, "ok": ok, "output_ref": output_ref, "stdout_preview": stdout_preview,
            "duration_ms": duration_ms, "side_effects": side_effects or [], "metadata_ref": metadata_ref,
        }
        if error is not None:
            # A failing tool's reason usually lives on stderr, and the
            # metadata carrying it was dropped here, so the model saw
            # "exit_code=1" and nothing else. Found by trial 2026-09-07:
            # the sandbox failed with a real SyntaxError and the model's
            # entire observation was the string "exit_code=1". It
            # recovered by luck, not by reading the traceback.
            tail = (stderr or "").strip()[-1500:]
            payload["error"] = f"{error}\n{tail}" if tail else error
        await self._ctx.bus.publish(message.caused(topics.ACTION_RESULT, payload, source="execution"))

    def _event(self, stream: str, type: str, payload: dict) -> Event:
        return Event(stream=stream, type=type, ts=self._ctx.clock.now(), trace_id="", causation_id=None, payload=payload)
