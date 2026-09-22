"""`policy_adopt`: write an adopted lesson into `rules/<task_type>.md`
and commit it (stage 8 item 5).

The growth loop measures a proposed rule (`growth/evaluate.py`) and, when
it fixed a held-out case and broke none, proposes this. `rules/` is a
protected subject that Guardian ASKS about rather than refuses
(`guardian/config.py::ask_subjects`, the creator's choice on 2026-09-22),
so this runs only after a person has said yes -- and `orchestration/
profiles.py` then puts the file after that agent's body.

One file, appended to, committed on its own: the live checkout must stay
committed (an uncommitted edit blocks the loader's rollback), and a rule
that turns out wrong is one `git revert` away. Never pushes.
"""

from __future__ import annotations

import asyncio
import re
import subprocess
import time
from pathlib import Path

from simorgh.contracts.protocols import ToolContext, ToolResult

from .config import Config

_TASK_TYPE = re.compile(r"^[a-z][a-z0-9_-]{0,40}$")
#: A rule is a line or two of advice, not a document.
MAX_RULE_CHARS = 600


class PolicyAdoptTool:
    name = "policy_adopt"
    description = ("Write an adopted lesson into rules/<task_type>.md and commit it. Only after the growth "
                   "loop measured it; a person always says yes first.")
    read_only = False
    reversibility = "irreversible"
    args_schema = {
        "type": "object", "required": ["task_type", "rule", "policy_id", "path"],
        "properties": {
            "task_type": {"type": "string"}, "rule": {"type": "string"}, "policy_id": {"type": "string"},
            # Redundant with task_type on purpose: Guardian reads the path
            # argument to see that this touches `rules/`.
            "path": {"type": "string"},
            "why": {"type": "string"},
        },
    }

    def __init__(self, config: Config) -> None:
        self._config = config

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        task_type = str(args.get("task_type") or "").strip().lower()
        if not _TASK_TYPE.match(task_type):
            return ToolResult.refused(f"refused: {task_type!r} is not a task type name")
        expected = f"rules/{task_type}.md"
        if str(args.get("path") or "") != expected:
            return ToolResult.refused(f"refused: the path must be {expected!r}, the file for that task type")
        rule = " ".join(str(args.get("rule") or "").split())
        if not rule:
            return ToolResult.refused("refused: an empty rule changes nothing")
        if len(rule) > MAX_RULE_CHARS:
            return ToolResult.refused(f"refused: a rule is at most {MAX_RULE_CHARS} characters, not {len(rule)}")
        policy_id = re.sub(r"[^A-Za-z0-9_-]", "", str(args.get("policy_id") or ""))[:40]
        root = Path(self._config.repo_root)
        path = root / expected
        stamp = time.strftime("%Y-%m-%d", time.localtime())
        why = " ".join(str(args.get("why") or "").split())[:200]
        line = f"- {rule}\n<!-- policy {policy_id}, adopted {stamp}{': ' + why if why else ''} -->\n"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
            if f"- {rule}\n" in existing:
                return ToolResult(ok=True, output=f"{expected} already has this rule; nothing written",
                                  metadata={"path": expected, "unchanged": True})
            path.write_text(existing + ("" if not existing or existing.endswith("\n") else "\n") + line,
                            encoding="utf-8")
        except OSError as exc:
            return ToolResult(ok=False, error=f"could not write {expected}: {exc!r}")

        def git(*cmd):
            return subprocess.run(["git", *cmd], cwd=root, capture_output=True, text=True, timeout=30,
                                  stdin=subprocess.DEVNULL)

        added = await asyncio.to_thread(git, "add", "--", expected)
        committed = await asyncio.to_thread(
            git, "commit", "-m", f"growth: adopt policy {policy_id} into {expected}", "--", expected)
        if added.returncode != 0 or committed.returncode != 0:
            return ToolResult(ok=False, error=f"{expected} written but not committed: "
                                              f"{(committed.stderr or added.stderr).strip()[:300]}",
                              metadata={"path": expected, "written": True})
        head = await asyncio.to_thread(git, "rev-parse", "HEAD")
        return ToolResult(ok=True, output=f"adopted into {expected} and committed ({head.stdout.strip()[:12]})",
                          metadata={"path": expected, "commit": head.stdout.strip()})


__all__ = ["PolicyAdoptTool"]
