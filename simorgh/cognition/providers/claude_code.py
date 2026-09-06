"""Claude Code CLI provider (docs/blueprint/subsystems/04-cognition.md
section 11): body ported unchanged from v1
`src/cognition/claude_code_provider.py`, `complete()` made async via
`asyncio.to_thread`. Every claim here was verified against Claude Code's
own documentation, not assumed -- see the live-caught `--bare` lesson
below, preserved verbatim because it is the actual reason this provider
works at all on macOS.

`--bare` is deliberately NEVER passed, even though it looks like the
right minimal-footprint flag for a headless call: on macOS a normal
`claude login` session lives in the OS keychain, and `--bare` skips
keychain reads. With it passed, every call failed "Not logged in" despite
a genuinely valid subscription session in the same shell, and nothing
surfaced that as an error -- this provider silently degraded to the next
one every time. `--disallowedTools "*"` strips all tool/file/bash access
(this is a text-drafting backend only); credential env vars ranked above
the subscription in Claude Code's own precedence are stripped so a
headless call bills the subscription, not a stray key.

**Live-caught: `role: "system"` messages were being flattened into the
same `-p` prompt string as everything else, with no role distinction at
all once they reached this binary.** The underlying `claude` binary
*is* Claude Code -- the same product this file's own module lives in --
and it carries its own strong default identity/system prompt ("you are
Claude Code, an agentic coding tool"). A few paragraphs of identity text
sitting in the middle of a `-p` user turn is not remotely strong enough
to override that; asked directly, it answered honestly that it was
Claude Code, not Simorgh, because nothing had ever told it otherwise
with real system-prompt authority. Fixed by using `--system-prompt`
(full replacement, not `--append-system-prompt`, since this is a
headless drafting backend, not an interactive coding session, and the
Claude Code default identity is exactly what needs to not compete here)
for any `role: "system"` content, keeping only conversational content in
`-p`.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from typing import Callable

from simorgh.contracts.protocols import ProviderResponse

from ..api import ProviderUnavailable

_CREDENTIAL_ENV_VARS_TO_STRIP = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")

Runner = Callable[..., subprocess.CompletedProcess]


class ClaudeCodeProvider:
    name = "claude_code_cli"

    def __init__(
        self, binary: str = "claude", timeout_seconds: float = 180.0,
        env: dict[str, str] | None = None, runner: Runner | None = None,
    ) -> None:
        self._binary = binary
        self._timeout = timeout_seconds
        self._base_env = env
        self._runner: Runner = runner or subprocess.run

    def available(self) -> bool:
        return shutil.which(self._binary) is not None

    async def complete(
        self, messages: list[dict], *, tools: list[dict] | None, max_tokens: int, timeout: float | None = None,
    ) -> ProviderResponse:
        system_prompt = "\n\n".join(
            m.get("content", "") for m in messages if m.get("role") == "system" and m.get("content")
        )
        prompt = "\n\n".join(
            m.get("content", "") for m in messages if m.get("role") != "system" and m.get("content")
        )
        return await asyncio.to_thread(self._complete_sync, prompt, system_prompt, timeout or self._timeout)

    def _complete_sync(self, prompt: str, system_prompt: str, timeout: float) -> ProviderResponse:
        binary_path = shutil.which(self._binary)
        if binary_path is None:
            raise ProviderUnavailable(f"{self._binary!r} not found on PATH")

        env = self._subprocess_env()
        argv = [binary_path, "-p", prompt, "--output-format", "json", "--disallowedTools", "*"]
        if system_prompt:
            # Full replacement, not --append-system-prompt: see the module
            # docstring -- Claude Code's own default identity is exactly
            # what must not compete with Simorgh's here.
            argv += ["--system-prompt", system_prompt]
        with tempfile.TemporaryDirectory(prefix="simorgh-claude-code-") as workdir:
            try:
                completed = self._runner(
                    argv,
                    # Do NOT add "--bare": it skips keychain reads, which is
                    # where a normal macOS `claude login` session lives.
                    #
                    # stdin=DEVNULL is deliberate, not incidental: the full
                    # prompt is already on argv (-p) and --disallowedTools
                    # "*" means nothing here ever needs interactive input,
                    # so this subprocess has no legitimate reason to read
                    # stdin at all. Without it, subprocess.run leaves stdin
                    # inherited from the parent -- when the Kernel itself
                    # runs interactively (`sim.sh`), that parent stdin IS
                    # the creator's real terminal. Live-caught: a call that
                    # times out gets killed (`TimeoutExpired` below), and if
                    # the `claude` binary had put that shared terminal into
                    # raw/cbreak mode for its own use, a hard kill skips any
                    # chance for it to restore that state -- the terminal
                    # stays broken (Enter shows a literal ^M, no echo, no
                    # further input works) for the rest of the session, with
                    # no trace of why in this process's own output. Every
                    # test that verified the REPL threading fix used a pipe
                    # for stdin, never a real tty, so none of them could
                    # have caught this.
                    capture_output=True, text=True, timeout=timeout, env=env, cwd=workdir,
                    stdin=subprocess.DEVNULL,
                )
            except subprocess.TimeoutExpired as exc:
                raise ProviderUnavailable(f"claude CLI timed out after {timeout}s") from exc
            except OSError as exc:
                raise ProviderUnavailable(f"failed to spawn claude CLI: {exc!r}") from exc
            except Exception as exc:  # noqa: BLE001 -- degrade to the next provider, not just the two documented types
                raise ProviderUnavailable(f"claude CLI invocation failed: {exc!r}") from exc

        if completed.returncode != 0:
            raise ProviderUnavailable(f"claude CLI exited {completed.returncode}: {completed.stderr.strip()}")

        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ProviderUnavailable(f"claude CLI returned non-JSON output: {exc!r}") from exc

        # The CLI can exit 0 while `is_error` is true (e.g. a lapsed login)
        # -- checking only returncode lets that string through as a real reply.
        if payload.get("is_error"):
            raise ProviderUnavailable(f"claude CLI reported an error: {payload.get('result', '')!r}")

        return ProviderResponse(
            text=payload.get("result", "") or "", provider=self.name,
            input_tokens=0, output_tokens=0, cost_usd=payload.get("total_cost_usd", 0.0) or 0.0,
            metadata={"session_id": payload.get("session_id")},
        )

    def _subprocess_env(self) -> dict[str, str]:
        env = dict(self._base_env) if self._base_env is not None else dict(os.environ)
        for key in _CREDENTIAL_ENV_VARS_TO_STRIP:
            env.pop(key, None)
        return env


__all__ = ["ClaudeCodeProvider"]
