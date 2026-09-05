"""Claude Code CLI provider: drafts text via a spawned `claude -p` process,
billed against the caller's Claude subscription (Pro/Max/Team/Enterprise)
rather than the pay-per-token API.

Every claim below was verified against Claude Code's own documentation
before writing this, not assumed from training data:

- `claude -p "<prompt>" --output-format json` runs one-shot, exits 0 on
  success and non-zero on failure, and returns a JSON object with
  `result` (the text), `total_cost_usd` (a real, CLI-computed figure --
  not an estimate), and `session_id`.
- Credential precedence in Claude Code ranks ANTHROPIC_AUTH_TOKEN and
  CLAUDE_CODE_OAUTH_TOKEN, as well as ANTHROPIC_API_KEY, above the
  subscription OAuth session -- all three are stripped from the
  subprocess environment so a headless call is actually billed against
  the logged-in subscription, not a stray key/token.
- `--disallowedTools "*"` removes every tool from Claude's context
  entirely -- this provider is used purely as a text-drafting backend,
  with no file/bash access. `--dangerously-skip-permissions` does the
  opposite (auto-approves everything) and is never passed here, by
  design. Claude Code has no documented built-in flag to scope the
  working directory, so each call additionally runs from a fresh, empty
  temp directory as a second, independent layer of containment -- the
  same defense-in-depth posture as SubprocessSandbox: don't rely on one
  control alone.
- `/usage`'s output in headless mode isn't documented as structured or
  reliably parseable, so this provider doesn't attempt to parse it.
  `total_cost_usd` from each response feeds the same BudgetGuard every
  other provider uses instead. If the CLI itself refuses because the
  plan's rolling quota is exhausted, that surfaces as a non-zero exit,
  which becomes ProviderUnavailable here -- CognitionRouter's existing
  fallback handles the rest; no separate sleep/backoff loop is needed.
- `--bare` is deliberately NOT passed, even though it sounds like the
  right minimal-footprint flag for a headless drafting call (it skips
  hooks/LSP/plugin sync/attribution/auto-memory/background prefetches/
  CLAUDE.md discovery). Live-caught: on macOS, a normal `claude login`
  session is stored in the OS keychain, not a plain credentials file --
  and `--bare`'s help text says it also skips "keychain reads." With it
  passed, every single call failed with "Not logged in · Please run
  /login" despite `claude auth status` confirming a genuinely valid
  Pro-subscription session in the same shell -- this provider silently
  degraded to the next one (Gemini) every time, for this session's
  entire history, and nothing surfaced that as an error anywhere. Every
  one of `--bare`'s other effects is already covered by the isolation
  this provider builds itself (`cwd` is a fresh, empty temp directory,
  so there's no CLAUDE.md/project hooks to discover in the first place;
  `--disallowedTools "*"` already removes every tool a hook could act
  through) -- keychain reads were the one thing actually needed and the
  one thing this flag can't be told to keep.

This provider must always be wrapped in src/cognition/budget.BudgetGuard
before being registered in a CognitionRouter, exactly like every other
real provider in this codebase.

Requires the user to already be authenticated via `claude login`,
interactively, once, outside this codebase -- this provider does not
handle login.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from typing import Any, Callable

from src.cognition.provider import LLMProvider, LLMResponse, ProviderUnavailable

# Ranked above the subscription OAuth session in Claude Code's own
# credential precedence -- stripped so a headless call is billed against
# the logged-in subscription, not a stray key/token in the environment.
_CREDENTIAL_ENV_VARS_TO_STRIP = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
)

DEFAULT_TIMEOUT_SECONDS = 180.0

Runner = Callable[..., subprocess.CompletedProcess]


class ClaudeCodeProvider(LLMProvider):
    """Calls a locally installed `claude` CLI in headless mode.

    `runner` (default `subprocess.run`) and `env` (default `os.environ`)
    are injectable so this can be tested without spawning a real process
    or requiring `claude` to be installed.
    """

    name = "claude_code_cli"

    def __init__(
        self,
        binary: str = "claude",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        env: dict[str, str] | None = None,
        runner: Runner | None = None,
    ) -> None:
        self._binary = binary
        self._timeout = timeout_seconds
        self._base_env = env
        self._runner: Runner = runner or subprocess.run

    def available(self) -> bool:
        return shutil.which(self._binary) is not None

    def complete(self, prompt: str, **kwargs: Any) -> LLMResponse:
        binary_path = shutil.which(self._binary)
        if binary_path is None:
            raise ProviderUnavailable(f"{self._binary!r} not found on PATH")

        env = self._subprocess_env()
        with tempfile.TemporaryDirectory(prefix="simorgh-claude-code-") as workdir:
            try:
                completed = self._runner(
                    [
                        binary_path,
                        "-p",
                        prompt,
                        "--output-format",
                        "json",
                        "--disallowedTools",
                        "*",
                        # Do NOT add "--bare" here: it skips keychain reads,
                        # which is where a normal macOS `claude login`
                        # session lives -- see the module docstring.
                    ],
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                    env=env,
                    cwd=workdir,
                )
            except subprocess.TimeoutExpired as exc:
                raise ProviderUnavailable(
                    f"claude CLI timed out after {self._timeout}s"
                ) from exc
            except OSError as exc:
                raise ProviderUnavailable(f"failed to spawn claude CLI: {exc!r}") from exc
            except Exception as exc:  # noqa: BLE001 -- any other failure
                # spawning/running the CLI must degrade to the next
                # provider too, not just the two documented exception types
                raise ProviderUnavailable(f"claude CLI invocation failed: {exc!r}") from exc

        if completed.returncode != 0:
            raise ProviderUnavailable(
                f"claude CLI exited {completed.returncode}: {completed.stderr.strip()}"
            )

        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ProviderUnavailable(
                f"claude CLI returned non-JSON output: {exc!r}"
            ) from exc

        # A real, live gap: the CLI can exit 0 while `is_error` is true in
        # the payload -- e.g. "Not logged in · Please run /login" when no
        # subscription session is active. Checking only returncode let
        # that string through as if it were an actual drafted reply,
        # which CognitionRouter would then hand straight to the user as
        # Sim's own words. Caught live: `claude -p ... --bare` returned
        # exit 0 with exactly this payload once a session's Claude Code
        # login had lapsed.
        if payload.get("is_error"):
            raise ProviderUnavailable(
                f"claude CLI reported an error: {payload.get('result', '')!r}"
            )

        return LLMResponse(
            text=payload.get("result", "") or "",
            provider_name=self.name,
            metadata={
                "cost_usd": payload.get("total_cost_usd", 0.0) or 0.0,
                "session_id": payload.get("session_id"),
            },
        )

    def _subprocess_env(self) -> dict[str, str]:
        env = dict(self._base_env) if self._base_env is not None else dict(os.environ)
        for key in _CREDENTIAL_ENV_VARS_TO_STRIP:
            env.pop(key, None)
        return env
