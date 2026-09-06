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
        prompt = "\n\n".join(m.get("content", "") for m in messages if m.get("content"))
        return await asyncio.to_thread(self._complete_sync, prompt, timeout or self._timeout)

    def _complete_sync(self, prompt: str, timeout: float) -> ProviderResponse:
        binary_path = shutil.which(self._binary)
        if binary_path is None:
            raise ProviderUnavailable(f"{self._binary!r} not found on PATH")

        env = self._subprocess_env()
        with tempfile.TemporaryDirectory(prefix="simorgh-claude-code-") as workdir:
            try:
                completed = self._runner(
                    [binary_path, "-p", prompt, "--output-format", "json", "--disallowedTools", "*"],
                    # Do NOT add "--bare": it skips keychain reads, which is
                    # where a normal macOS `claude login` session lives.
                    capture_output=True, text=True, timeout=timeout, env=env, cwd=workdir,
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
