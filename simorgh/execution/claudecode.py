"""`claude_code_task`: Claude Code as an autonomous coding worker (stage 18 item 12).

Sim already THINKS through the Claude Code CLI as a last-resort provider
(`cognition/providers`). This is different: Sim briefs Claude Code with a
feature, Claude Code implements it in the task's own worktree, and Sim
(or Verification) judges the result. Landing goes through the existing
gate (`worktree_land`: rebase, whole suite, protected paths, fast-forward);
Claude Code never pushes or lands anything by itself.

How it runs. The Claude Agent SDK (`claude-agent-sdk`, imported under
`try/except ImportError`) drives the installed `claude` CLI. Without the
SDK the tool refuses by name and nothing starts. The CLI's own
`--settings` hooks would be a second way in; it is not built, so the SDK
is the only hook path, and without one the run refuses to start.

Guardian sees every call. A `PreToolUse` hook turns each Claude Code tool
call into an `action.proposed` named `claude_code:<Tool>` (Bash, Edit,
Write, ...) whose arguments are shaped like Sim's own tools' (`command`
for a shell, `path` and `content` for a write), so ProtectedRule,
DenylistRule and the rest judge it exactly as they judge Sim's. The
proposal carries the requester and channel of the `claude_code_task`
call itself (read from its `action:<id>` record), so Guardian sees the
person who asked. The call is allowed only when Execution has verified
Guardian's `action.approved` and answered with `action.result` (the
SelfActions pattern; `service.py::_on_approved` runs nothing for a
`claude_code:` tool -- Claude Code runs it); an `action.denied`, a
timeout or a broken bus denies it with the reason. Network tools
(WebFetch, WebSearch) are refused here before Guardian unless
`[execution.claude_code] allow_network` is set.

No more reach than Sim's own tools (`local_refusal`). Guardian judges a
proposal's text and has no idea of "inside this worktree"; Sim's file
tools keep to the tree themselves (`pathsafety`) and `run_shell` has
`shell_refusals`. Claude Code's tools have neither, so the hook refuses,
before Guardian, a file path that resolves outside the worktree or names
a credential, and a Bash command `run_shell` would refuse, one that moves
a git ref or branch by hand (a worktree shares main's refs), or one that
names the live checkout. No settings file is loaded (a project
`.claude/settings.json` can carry hooks that run outside Guardian), and
Sim's other secret-shaped environment variables are blanked for the CLI.

Budget. Off by default (`enabled = false`; the tool is not even
registered). Each run has `max_turns`, a wall-clock cap `wall_s`, and
`max_usd_per_run` (passed to the SDK when it takes one, and checked on the
cost it reports), lowered by the call's own `max_usd` when it names less --
Orchestration sets that to a crew member's share of its crew's dollars,
and counts the reported `cost_usd` against the crew when the run ends; at most `max_runs_per_day` runs are started per local
day, counted on `execution:claude_code`. A run that hits a cap reports
`partial`. The first run of each day asks a person: Guardian's
`daily_human_tools` (guardian/config.py), in every posture. Every run, its
cost and every hook decision is recorded on `execution:claude_code`, so
the Claude quota is never spent silently (the 2026-09-11 lesson).

The brief is `agents/claude_code.md`'s fenced `brief` block, filled with
the feature, the acceptance test, the files in scope and the module, read
from the live repository (the task cannot have edited it: `agents/` is
protected). The repository's CLAUDE.md gives Claude Code the contract
rules, but not its lock rule: Sim is the coordinator and holds the
module locks, so the brief tells Claude Code never to claim or release a
lock, never to edit `docs/modules/locks.toml`, to stay in its worktree and
never to push -- and `local_refusal` refuses those calls before Guardian
(`COORDINATOR_FILES`, the `modlock` row of `CLAUDE_CODE_SHELL_REFUSALS`).
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import importlib
import inspect
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from simorgh.contracts import topics
from simorgh.contracts.envelope import Event, Message
from simorgh.contracts.pathnames import looks_like_credential_path
from simorgh.contracts.protocols import ToolContext, ToolResult

from .shell import DEFAULT_SHELL_REFUSALS, _is_secret_env, refusal_for

TOOL_NAME = "claude_code_task"
#: Every hook proposal's tool name starts with this. Execution's
#: `_on_approved` answers such an approval without running anything.
HOOK_PREFIX = "claude_code:"
STREAM = "execution:claude_code"
SDK_MODULE = "claude_agent_sdk"
SDK_MISSING = "needs `pip install claude-agent-sdk` (and the `claude` CLI)"
BRIEF_FILE = "agents/claude_code.md"
PROPOSED_BY = "execution"

#: Claude Code tools that reach the network.
NETWORK_TOOLS = frozenset({"WebFetch", "WebSearch"})
#: Claude Code tools that only read.
READ_TOOLS = frozenset({"Read", "Glob", "Grep", "LS", "TodoWrite", "NotebookRead", "BashOutput"})
#: Claude Code tools that write a file, and which input key names it.
WRITE_TOOLS = {"Edit": "file_path", "MultiEdit": "file_path", "Write": "file_path", "NotebookEdit": "notebook_path"}
#: The input keys a Claude Code file tool names its file or directory by.
_PATH_KEYS = ("file_path", "notebook_path", "path")

#: Bash commands refused before Guardian on top of `run_shell`'s own
#: `shell_refusals`: git commands that move a ref or a checkout OUTSIDE
#: this task's branch. A worktree shares its refs with the main checkout,
#: so `git update-ref refs/heads/main HEAD` from inside it lands with no
#: gate at all. Not a security boundary (a shell has none); the same
#: accident guard `run_shell` is.
CLAUDE_CODE_SHELL_REFUSALS: dict[str, str] = {
    r"\bgit\b[^|;&]*\b(update-ref|symbolic-ref)\b": "moves a git ref by hand; only worktree_land moves main",
    r"\bgit\b[^|;&]*\bbranch\b[^|;&]*\s(-[a-zA-Z]*[fdDmMcC][a-zA-Z]*|--force|--delete|--move|--copy)\b":
        "forces, moves or deletes a branch; commit on this task's branch only",
    r"\bgit\b[^|;&]*\bworktree\b": "manages worktrees; this task already has its own",
    r"\bgit\b[^|;&]*(--git-dir|--work-tree)\b": "points git at another repository or tree",
    r"(^|[;&|]\s*)git\s+-C\s": "runs git in another directory; stay in this task's worktree",
    # CLAUDE.md tells an agent to lock a module before editing it. Not this
    # one: Sim is the coordinator and holds the locks; a lock Claude Code
    # took would outlive its run and block everyone else.
    r"\bmodlock(\.py)?\b[^|;&]*\b(claim|release)\b": "claims or releases a module lock; Sim holds the locks",
    r"docs/modules/locks\.toml": "names the module lock file; Sim holds the locks",
}

#: Files only the coordinator (Sim, or the person running it) writes, under
#: the worktree root. A write to one is refused before Guardian.
COORDINATOR_FILES = frozenset({"docs/modules/locks.toml"})

_BRIEF_BLOCK = re.compile(r"```brief\n(.*?)\n```", re.S)


@dataclass(frozen=True)
class ClaudeCodeConfig:
    """`[execution.claude_code]` (the plan calls it `[crew.claude_code]`;
    the Kernel hands Execution only its own section)."""

    enabled: bool = False
    max_usd_per_run: float = 2.0
    max_runs_per_day: int = 3
    max_turns: int = 40
    wall_s: float = 1800.0
    # How long one Claude Code tool call waits for Guardian, a person's
    # answer included.
    hook_timeout_s: float = 600.0
    allow_network: bool = False
    model: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, object] | None) -> "ClaudeCodeConfig":
        if isinstance(data, ClaudeCodeConfig):
            return data
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in dict(data or {}).items() if k in known})


def load_sdk():
    """The Agent SDK module, or None when it is not installed."""
    try:
        return importlib.import_module(SDK_MODULE)
    except ImportError:
        return None


def _option_fields(options_cls) -> set[str]:
    if dataclasses.is_dataclass(options_cls):
        return {f.name for f in dataclasses.fields(options_cls)}
    try:
        return set(inspect.signature(options_cls).parameters)
    except (TypeError, ValueError):
        return set()


def hook_path(sdk) -> str:
    """"" when this SDK can route every tool call through a PreToolUse
    hook, else why not. No hook path, no run."""
    if sdk is None:
        return f"the Claude Agent SDK is not installed ({SDK_MISSING})"
    for name in ("ClaudeAgentOptions", "ClaudeSDKClient", "HookMatcher"):
        if not hasattr(sdk, name):
            return f"this claude-agent-sdk has no {name}, so no PreToolUse hook can be installed"
    if "hooks" not in _option_fields(sdk.ClaudeAgentOptions):
        return "this claude-agent-sdk's options take no hooks, so Guardian could not see Claude Code's calls"
    return ""


def proposal_for(tool: str, tool_input: Mapping[str, Any]) -> tuple[dict, str, list[str]]:
    """`(args, reversibility, paths)` for one Claude Code tool call, in the
    argument shapes Guardian's rules already read."""
    data = dict(tool_input or {})
    if tool == "Bash":
        return {"command": str(data.get("command") or "")}, "irreversible", []
    if tool in WRITE_TOOLS:
        path = str(data.get(WRITE_TOOLS[tool]) or "")
        if tool == "Write":
            content = str(data.get("content") or "")
        elif tool == "MultiEdit":
            content = "\n".join(str(e.get("new_string") or "") for e in data.get("edits") or () if isinstance(e, Mapping))
        elif tool == "NotebookEdit":
            content = str(data.get("new_source") or "")
        else:
            content = str(data.get("new_string") or "")
        return {"path": path, "content": content[:20000]}, "reversible", [path] if path else []
    if tool in READ_TOOLS:
        # Guardian's ProtectedRule lets a read_only proposal read a
        # protected file; where a read may reach (this worktree, no
        # credential) is `local_refusal`'s.
        path = str(data.get("file_path") or data.get("path") or data.get("notebook_path") or "")
        args = {"path": path} if path else {}
        if data.get("pattern"):
            args["pattern"] = str(data["pattern"])[:500]
        return args, "read_only", []
    if tool in NETWORK_TOOLS:
        return {"url": str(data.get("url") or ""), "query": str(data.get("query") or "")}, "irreversible", []
    # Anything else (a sub-agent, an MCP tool): its input as text, and the
    # strictest class.
    return {"input": str(data)[:4000]}, "irreversible", []


def _inside(root: Path, raw: str) -> Path | None:
    """`raw` resolved (links followed) against `root`, when it stays
    inside `root`; else None."""
    try:
        base = Path(root).resolve()
        target = Path(raw)
        target = (target if target.is_absolute() else base / target).resolve()
    except (OSError, ValueError, RuntimeError):
        return None
    return target if target == base or base in target.parents else None


def local_refusal(tool: str, tool_input: Mapping[str, Any], *, root: Path, repo_root: Path | None,
                  shell_refusals: Mapping[str, str] | None, allow_network: bool) -> str:
    """Why this Claude Code call is refused before it reaches Guardian,
    or "". Execution's own tools carry these limits themselves
    (`pathsafety`: paths stay in the tree and never name a credential;
    `run_shell`: `shell_refusals`); Claude Code's tools do not, and a
    hook "allow" lets them do whatever Guardian approved, so the same
    limits are applied here. Guardian has no notion of "inside the
    worktree" (its ScopeRule abstains), so without this an approved
    Write could edit the live checkout -- past the landing gate -- or a
    Read could hand `~/.ssh` to the model."""
    if tool in NETWORK_TOOLS and not allow_network:
        return f"{tool} reaches the network; [execution.claude_code] allow_network is off"
    data = tool_input if isinstance(tool_input, Mapping) else {}
    if tool in WRITE_TOOLS or tool in READ_TOOLS:
        for key in _PATH_KEYS:
            raw = data.get(key)
            if not raw:
                continue
            target = _inside(root, str(raw))
            if target is None:
                return f"{raw!r} is outside this task's worktree; {tool} works only inside it"
            relative = target.relative_to(Path(root).resolve())
            if looks_like_credential_path(relative.parts):
                return f"{raw!r} looks like a credentials path"
            if tool in WRITE_TOOLS and relative.as_posix() in COORDINATOR_FILES:
                return f"{raw!r} is the module lock file; Sim holds the locks, never Claude Code"
    if tool == "Bash":
        command = str(data.get("command") or "")
        reason = refusal_for(command, dict(shell_refusals or DEFAULT_SHELL_REFUSALS))
        reason = reason or refusal_for(command, CLAUDE_CODE_SHELL_REFUSALS)
        if reason:
            return f"that command {reason}"
        if repo_root is not None:
            live = {str(repo_root), str(Path(repo_root).resolve())}
            tree = str(Path(root).resolve())
            if any(p and p in command and not tree.startswith(p) for p in live):
                return "that command names the live checkout; work stays in this task's worktree"
    return ""


#: The credentials the `claude` CLI itself signs in with; every other
#: secret-shaped variable is blanked for it (`claude_code_env`).
CLI_CREDENTIALS = frozenset({"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"})


def claude_code_env(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """`{name: ""}` for every secret-shaped variable (`run_shell`'s own
    test, `shell._is_secret_env`) but the CLI's own credential."""
    source = os.environ if environ is None else environ
    return {name: "" for name in source if _is_secret_env(name) and name.upper() not in CLI_CREDENTIALS}


def render_brief(template: str, *, feature: str, acceptance: str, files: list[str], module: str) -> str:
    return (template.replace("{feature}", feature.strip() or "(none given)")
            .replace("{acceptance}", acceptance.strip() or "(none given: write one test that proves the feature)")
            .replace("{files}", "\n".join(f"- {f}" for f in files) or "- (not named: find them)")
            .replace("{module}", module.strip() or "<module>"))


def brief_template(repo_root: Path) -> str:
    text = (Path(repo_root) / BRIEF_FILE).read_text(encoding="utf-8")
    match = _BRIEF_BLOCK.search(text)
    if not match:
        raise ValueError(f"{BRIEF_FILE} has no ```brief block")
    return match.group(1)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60,
                          stdin=subprocess.DEVNULL)


ProgressFn = Callable[[ToolContext, dict], Awaitable[None]]


class _Run:
    def __init__(self) -> None:
        self.id = uuid.uuid4().hex[:10]
        self.calls = 0
        self.decisions: list[dict] = []
        self.text: list[str] = []
        self.result: Any = None
        self.root: Path = Path(".")


class ClaudeCodeTaskTool:
    name = TOOL_NAME
    description = (
        "Hand a coding task to Claude Code, which implements it in this task's own worktree with a test, "
        "every one of its tool calls approved by Guardian. Arguments: feature (what to build), acceptance "
        "(the test that proves it), files (paths in scope), module (the module to test with "
        "tools/modtest.py). Never touches protected paths, never pushes or lands: land with worktree_land. "
        "Costs real money; the first run of the day asks a person."
    )
    read_only = False
    reversibility = "irreversible"
    args_schema = {
        "type": "object", "required": ["feature"],
        "properties": {
            "feature": {"type": "string"}, "acceptance": {"type": "string"},
            "files": {"type": "array", "items": {"type": "string"}}, "module": {"type": "string"},
            # A crew member's share of its crew's dollars (Orchestration
            # sets it; stage 18): the run is capped at the lower of this and
            # `max_usd_per_run`.
            "max_usd": {"type": "number"},
        },
    }

    def __init__(self, config, *, sdk_loader: Callable[[], Any] = load_sdk,
                 progress: ProgressFn | None = None, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._config = config
        self._cc = ClaudeCodeConfig.from_mapping(getattr(config, "claude_code", None))
        self._sdk_loader = sdk_loader
        self._progress = progress or self._log_progress
        self._monotonic = monotonic
        self._start_lock = asyncio.Lock()

    @property
    def timeout_s(self) -> float:
        """The wall cap, plus room to collect the diff and report."""
        return float(self._cc.wall_s) + 60.0

    # -- the call --------------------------------------------------------------------------------

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        cc = self._cc
        if not cc.enabled:
            return ToolResult.unconfigured(f"{TOOL_NAME} is off ([execution.claude_code] enabled = false)")
        feature = str(args.get("feature") or "").strip()
        if not feature:
            return ToolResult.refused("give the feature to build")
        cap = self._dollar_cap(args.get("max_usd"))
        if cap <= 0:
            return ToolResult.refused(f"{TOOL_NAME}: no dollars left to spend (max_usd {args.get('max_usd')!r})")
        root = getattr(ctx, "root", None)
        if root is None or not (Path(root) / ".git").is_file():
            return ToolResult.refused(f"{TOOL_NAME} runs only in this task's own worktree (worktree_open), "
                                      "never in the live checkout")
        if getattr(ctx, "bus", None) is None:
            return ToolResult.refused(f"{TOOL_NAME} needs the bus: without it Guardian cannot see Claude Code's calls")
        sdk = self._sdk_loader()
        why = hook_path(sdk)
        if why:
            return ToolResult.unconfigured(f"{TOOL_NAME} refuses to start: {why}")
        try:
            template = brief_template(Path(self._config.repo_root))
        except (OSError, ValueError) as exc:
            return ToolResult.unconfigured(f"{TOOL_NAME}: no brief template: {exc}")
        files = [str(f) for f in (args.get("files") or ()) if str(f).strip()]
        brief = render_brief(template, feature=feature, acceptance=str(args.get("acceptance") or ""),
                             files=files, module=str(args.get("module") or ""))
        found = await self._requester(ctx)
        if found is None:
            # Unknown is not "nobody": proposing Claude Code's calls with
            # no requester would act for Sim itself, which may be more
            # than the person who asked may do.
            return ToolResult.refused(f"{TOOL_NAME}: could not read who asked for this call "
                                      f"(action:{ctx.action_id}), so its calls cannot be proposed for them")
        requester, channel = found
        root = Path(root)
        start_head = _git(root, "rev-parse", "HEAD").stdout.strip()

        run = _Run()
        run.root = root
        # The count and the `started` that it counts under one lock: two
        # calls at once both read "0 today" and both ran past the cap.
        async with self._start_lock:
            runs_today = await self._runs_today(ctx)
            if runs_today >= cc.max_runs_per_day:
                return ToolResult.refused(f"{TOOL_NAME}: {runs_today} run(s) today already, the cap is "
                                          f"{cc.max_runs_per_day} ([execution.claude_code] max_runs_per_day)")
            await self._append(ctx, "started", {"run": run.id, "feature": feature[:500], "files": files,
                                                "requester": requester, "max_usd": cap,
                                                "max_turns": cc.max_turns, "wall_s": cc.wall_s})
        started = self._monotonic()
        status, reason = "ok", ""
        try:
            await asyncio.wait_for(self._drive(sdk, ctx, run, brief, root, requester, channel, max_usd=cap),
                                   timeout=cc.wall_s)
        except asyncio.TimeoutError:
            status, reason = "partial", f"stopped at the wall-clock cap ({cc.wall_s:.0f}s)"
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- an SDK or CLI failure is a report, never a crash
            status, reason = "failed", f"Claude Code failed: {exc!r}"[:600]
        wall = self._monotonic() - started

        result = run.result
        cost = float(getattr(result, "total_cost_usd", 0.0) or 0.0)
        turns = int(getattr(result, "num_turns", 0) or 0)
        subtype = str(getattr(result, "subtype", "") or "")
        if status == "ok":
            if result is None:
                status, reason = "failed", "Claude Code ended without a result"
            elif "max_turns" in subtype:
                status, reason = "partial", f"stopped at the turn cap ({cc.max_turns})"
            elif "budget" in subtype or cost > cap:
                status, reason = "partial", f"stopped at the cost cap (${cost:.2f} of ${cap:.2f})"
            elif getattr(result, "is_error", False) or (subtype and subtype != "success"):
                status, reason = "failed", f"Claude Code reported {subtype or 'an error'}"

        commits, diff_ref, dirty = await self._artifacts(ctx, root, start_head)
        denied = [d for d in run.decisions if not d["allowed"]]
        summary = (str(getattr(result, "result", "") or "") or "\n".join(run.text[-3:])).strip()[:1200]
        report = {
            "status": status, "summary": summary or reason, "reason": reason,
            "artifacts": ([diff_ref] if diff_ref else []) + [f"commit:{sha}" for sha, _ in commits],
            "commits": [{"sha": sha, "subject": subject} for sha, subject in commits],
            "diff_ref": diff_ref, "uncommitted": dirty,
            "steps": turns, "cost_usd": round(cost, 4), "wall_s": round(wall, 1),
            "tool_calls": run.calls, "denied_calls": len(denied),
            "decisions": run.decisions[-50:], "run": run.id,
        }
        await self._append(ctx, "finished", {k: v for k, v in report.items() if k != "decisions"})
        lines = [f"Claude Code {status}" + (f": {reason}" if reason else ""),
                 f"{len(commits)} commit(s), {run.calls} tool call(s) ({len(denied)} denied by Guardian), "
                 f"{turns} turn(s), ${cost:.2f}, {wall:.0f}s"]
        lines += [f"  {sha[:12]} {subject}" for sha, subject in commits[:10]]
        if dirty:
            lines.append(f"uncommitted: {', '.join(dirty[:10])} -- commit or discard before worktree_land")
        if summary:
            lines.append(summary)
        effects = tuple(f"git_commit:{sha}" for sha, _ in commits)
        if status in ("ok", "partial"):
            return ToolResult(ok=True, output="\n".join(lines), side_effects=effects, metadata=report)
        return ToolResult(ok=False, error=reason, output="\n".join(lines), side_effects=effects,
                          metadata=report, error_kind="failed")

    def _dollar_cap(self, asked) -> float:
        """This run's dollar cap: `max_usd_per_run`, or less when the call
        names less (`max_usd`: a crew member's share of its crew's dollars,
        which Orchestration sets). Never more than the config allows; 0 or
        below when the call has nothing left to spend."""
        cap = float(self._cc.max_usd_per_run)
        if asked in (None, ""):
            return cap
        try:
            asked = float(asked)
        except (TypeError, ValueError):
            return cap
        return min(cap, asked)

    async def _drive(self, sdk, ctx, run: _Run, brief: str, root: Path, requester: str, channel: str,
                     *, max_usd: float | None = None) -> None:
        cc = self._cc

        async def pre_tool_use(input_data, tool_use_id=None, context=None):
            tool = str((input_data or {}).get("tool_name") or "")
            tool_input = (input_data or {}).get("tool_input") or {}
            allowed, why = await self._decide(ctx, run, tool, tool_input, requester, channel)
            return {"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow" if allowed else "deny",
                "permissionDecisionReason": why,
            }}

        fields = _option_fields(sdk.ClaudeAgentOptions)
        wanted: dict[str, Any] = {
            "cwd": str(root),
            "max_turns": int(cc.max_turns),
            # The most restrictive mode that still lets the hook decide:
            # nothing is pre-approved, and a call the hook did not allow
            # would need a prompt that headless mode cannot show.
            "permission_mode": "default",
            "hooks": {"PreToolUse": [sdk.HookMatcher(matcher=None, hooks=[pre_tool_use])]},
            "max_budget_usd": float(cc.max_usd_per_run if max_usd is None else max_usd),
            # No settings files at all. A project `.claude/settings.json`
            # can carry hooks (commands run outside PreToolUse, so
            # outside Guardian), MCP servers and allow rules, and the
            # worktree is reused by a retry: one approved Write there
            # would arm the next run. CLAUDE.md is read through the
            # brief ("Read CLAUDE.md ... first"), a gated Read.
            "setting_sources": [],
            # The SDK hands the CLI this process's environment with
            # `env` laid over it, and Claude Code's Bash inherits it:
            # one approved `printenv` and every provider key Sim holds
            # is in Anthropic's context. `run_shell` strips them
            # (`shell._child_env`); here they are blanked, all but the
            # CLI's own credential.
            "env": claude_code_env(),
        }
        if not cc.allow_network:
            wanted["disallowed_tools"] = sorted(NETWORK_TOOLS)
        if cc.model:
            wanted["model"] = cc.model
        options = sdk.ClaudeAgentOptions(**{k: v for k, v in wanted.items() if k in fields})
        async with sdk.ClaudeSDKClient(options=options) as client:
            await client.query(brief)
            async for message in client.receive_response():
                await self._on_message(ctx, run, message)

    async def _on_message(self, ctx, run: _Run, message) -> None:
        if hasattr(message, "total_cost_usd") or type(message).__name__ == "ResultMessage":
            run.result = message
            return
        for block in getattr(message, "content", None) or ():
            if isinstance(block, str):
                continue
            name, text = getattr(block, "name", None), getattr(block, "text", None)
            if name and hasattr(block, "input"):
                event = {"run": run.id, "kind": "tool", "tool": str(name)}
            elif isinstance(text, str) and text.strip():
                run.text.append(text.strip())
                event = {"run": run.id, "kind": "text", "text": text.strip()[:500]}
            else:
                continue
            try:
                await self._progress(ctx, event)
            except Exception as exc:  # noqa: BLE001 -- progress is a report, never the run
                with contextlib.suppress(Exception):
                    ctx.logger.warning("claude_code_progress_failed", error=repr(exc))

    # -- the hook --------------------------------------------------------------------------------

    async def _decide(self, ctx, run: _Run, tool: str, tool_input, requester: str, channel: str) -> tuple[bool, str]:
        run.calls += 1
        action_id = f"claude-code-{run.id}-{run.calls}"
        record = {"action_id": action_id, "tool": tool}
        refused = local_refusal(tool, tool_input, root=run.root, repo_root=getattr(self._config, "repo_root", None),
                                shell_refusals=getattr(self._config, "shell_refusals", None),
                                allow_network=self._cc.allow_network)
        if refused:
            allowed, why = False, refused
        else:
            allowed, why = await self._ask_guardian(ctx, action_id, tool, tool_input, requester, channel)
        record.update({"allowed": allowed, "why": why[:300]})
        run.decisions.append(record)
        with contextlib.suppress(Exception):
            await self._append(ctx, "decision", {"run": run.id, **record})
        return allowed, why

    async def _ask_guardian(self, ctx, action_id: str, tool: str, tool_input, requester: str,
                            channel: str) -> tuple[bool, str]:
        args, reversibility, paths = proposal_for(tool, tool_input if isinstance(tool_input, Mapping) else {})
        loop = asyncio.get_running_loop()
        done: asyncio.Future = loop.create_future()

        async def _on(message: Message) -> None:
            if not done.done() and (message.payload or {}).get("action_id") == action_id:
                done.set_result(message)

        subs: list = []
        try:
            # Subscribed before the proposal, as SelfActions does: the
            # answer can arrive before a later subscription exists.
            for topic in (topics.ACTION_RESULT, topics.ACTION_DENIED):
                subs.append(await ctx.bus.subscribe(topic, _on))
            payload = {
                "action_id": action_id, "tool": HOOK_PREFIX + tool, "args": args,
                "scope": {"paths": paths, "network": tool in NETWORK_TOOLS},
                "reversibility": reversibility, "proposed_by": PROPOSED_BY,
                "rationale": f"Claude Code ({TOOL_NAME} {ctx.action_id}) wants to use {tool}",
                "requester": requester or None, "requester_channel": channel or None,
            }
            if ctx.task_id:
                payload["task_id"] = ctx.task_id
            await ctx.bus.publish(Message.new(topics.ACTION_PROPOSED, source=PROPOSED_BY, payload=payload))
            try:
                message = await asyncio.wait_for(done, timeout=self._cc.hook_timeout_s)
            except asyncio.TimeoutError:
                return False, f"Guardian did not answer within {self._cc.hook_timeout_s:.0f}s; denied"
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- a broken bus denies; it never allows
            return False, f"could not ask Guardian: {exc!r}"[:300]
        finally:
            for sub in subs:
                with contextlib.suppress(Exception):
                    await sub.unsubscribe()
        body = message.payload or {}
        if message.type == topics.ACTION_DENIED:
            reasons = "; ".join(str(r) for r in body.get("reasons") or ()) or "no reason given"
            return False, f"Guardian denied {tool} ({body.get('layer', 'policy')}): {reasons}"
        if not body.get("ok"):
            return False, f"Guardian's approval of {tool} did not verify: {body.get('error') or 'unknown'}"
        return True, "approved by Guardian"

    # -- records ---------------------------------------------------------------------------------

    async def _requester(self, ctx) -> tuple[str, str] | None:
        """Who asked for this run, from Guardian's record of the proposal:
        every Claude Code call is proposed on their behalf, never more.
        None when that record cannot be read: the caller refuses."""
        ledger = getattr(ctx, "ledger", None)
        if ledger is None or not getattr(ctx, "action_id", ""):
            return None
        try:
            events = await ledger.read(f"action:{ctx.action_id}")
        except Exception:  # noqa: BLE001 -- unreadable is unknown, never "nobody"
            return None
        for event in events:
            if event.type == "received":
                proposal = (event.payload or {}).get("proposal") or {}
                return str(proposal.get("requester") or ""), str(proposal.get("requester_channel") or "")
        return None

    async def _runs_today(self, ctx) -> int:
        ledger = getattr(ctx, "ledger", None)
        if ledger is None:
            return 0
        today = time.strftime("%Y-%m-%d", time.localtime(ctx.clock.now()))
        try:
            events = await ledger.read(STREAM)
        except Exception:  # noqa: BLE001 -- an unreadable count must not allow an unbounded day
            return self._cc.max_runs_per_day
        return sum(1 for e in events if e.type == "started"
                   and time.strftime("%Y-%m-%d", time.localtime(float(e.ts or 0))) == today)

    async def _artifacts(self, ctx, root: Path, start: str) -> tuple[list[tuple[str, str]], str, list[str]]:
        def collect():
            commits: list[tuple[str, str]] = []
            if start:
                log = _git(root, "log", "--format=%H %s", f"{start}..HEAD")
                for line in log.stdout.splitlines():
                    sha, _, subject = line.partition(" ")
                    if sha:
                        commits.append((sha, subject))
            diff = _git(root, "diff", start or "HEAD").stdout if start else ""
            status = _git(root, "status", "--porcelain").stdout
            dirty = [line[3:] for line in status.splitlines() if line.strip()]
            return commits, diff, dirty

        commits, diff, dirty = await asyncio.to_thread(collect)
        ref = ""
        if diff and getattr(ctx, "ledger", None) is not None:
            with contextlib.suppress(Exception):
                ref = await ctx.ledger.put_blob(diff.encode("utf-8"))
        return commits, ref, dirty

    async def _log_progress(self, ctx, event: dict) -> None:
        await self._append(ctx, "progress", event)

    @staticmethod
    async def _append(ctx, type_: str, payload: dict) -> None:
        if ctx is None or getattr(ctx, "ledger", None) is None:
            return
        await ctx.ledger.append(STREAM, Event(
            stream=STREAM, type=type_, ts=ctx.clock.now(), trace_id="", causation_id=None,
            payload={"action_id": ctx.action_id, "task": ctx.task_id, **payload}))


def claude_code_tools(config) -> list:
    """`claude_code_task` only when a person turned it on."""
    cc = ClaudeCodeConfig.from_mapping(getattr(config, "claude_code", None))
    return [ClaudeCodeTaskTool(config)] if cc.enabled else []


__all__ = ["BRIEF_FILE", "CLAUDE_CODE_SHELL_REFUSALS", "CLI_CREDENTIALS", "COORDINATOR_FILES", "ClaudeCodeConfig", "claude_code_env", "ClaudeCodeTaskTool", "HOOK_PREFIX", "NETWORK_TOOLS", "SDK_MISSING",
           "STREAM", "TOOL_NAME", "brief_template", "claude_code_tools", "hook_path", "load_sdk", "local_refusal", "proposal_for",
           "render_brief"]
