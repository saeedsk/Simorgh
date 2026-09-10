"""`notify`: how autonomous work reaches a person who is not watching.

Sim can already do a great deal without supervision. What it could not
do was tell anyone -- a task that finished at 3am, a benchmark that
regressed, a Guardian denial worth a human's attention, all of it sat in
a ledger nobody was reading. `ui.notice` reaches a REPL that may not be
open.

Built before any credential exists, on purpose (the creator,
2026-09-09: build it so that "when the skill will be needed, user will
provide account or api key ... but still the sim infra needs to be
ready"). Every provider is switched on by an environment variable and
switched off by its absence, exactly like `web_search`'s Brave/Tavily/
Serper backends. With nothing configured the tool refuses and names the
variables that would make it work -- it never silently does nothing,
which for a notification is the worst possible failure.

Sending is `irreversible` and always will be: there is no unsend. That
is the property that makes this safe to hand to an autonomous system --
Guardian sees every call, and with `irreversible_requires_human` set,
every message waits for a person. A deployment that auto-approves has
made that choice knowingly.

Providers, best-supported first:

| provider | variables | notes |
|---|---|---|
| `slack`  | `SLACK_WEBHOOK_URL` | an incoming webhook; no OAuth dance |
| `email`  | `RESEND_API_KEY` + `NOTIFY_EMAIL_TO` (+ `NOTIFY_EMAIL_FROM`) | simplest keyed email API |
| `sms`    | `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` + `TWILIO_FROM` + `NOTIFY_SMS_TO` | |

Adding a provider is a row in `PROVIDERS` and a `_send_*` function.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.parse
import urllib.request
from collections import deque

from simorgh.contracts.protocols import ToolContext, ToolResult

from .config import Config
from .netsafety import FetchRefused, validate_public_http_url

SLACK_ENV = "SLACK_WEBHOOK_URL"
RESEND_URL = "https://api.resend.com/emails"
TWILIO_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"

# provider -> the variables it needs, all required. First match wins
# when the caller does not name one.
PROVIDERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("slack", (SLACK_ENV,)),
    ("email", ("RESEND_API_KEY", "NOTIFY_EMAIL_TO")),
    ("sms", ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM", "NOTIFY_SMS_TO")),
)


class NotifyUnavailable(Exception):
    """Nothing was sent, and this is why."""


def available_providers(env) -> list[str]:
    return [name for name, keys in PROVIDERS if all((env.get(k) or "").strip() for k in keys)]


def missing_for(provider: str, env) -> list[str]:
    keys = dict(PROVIDERS).get(provider, ())
    return [k for k in keys if not (env.get(k) or "").strip()]


def choose_provider(configured: str, env) -> str:
    """The provider to use. `auto` takes the first one fully configured.

    Raises rather than guessing: a notification that quietly goes
    nowhere is worse than one that fails loudly, because the whole point
    is that somebody finds out.
    """
    configured = (configured or "auto").strip().lower()
    ready = available_providers(env)
    if configured != "auto":
        missing = missing_for(configured, env)
        if configured not in dict(PROVIDERS):
            raise NotifyUnavailable(
                f"unknown provider {configured!r}; known: {', '.join(n for n, _ in PROVIDERS)}")
        if missing:
            raise NotifyUnavailable(f"{configured} needs {', '.join(missing)} in the environment")
        return configured
    if ready:
        return ready[0]
    raise NotifyUnavailable(
        "no notification provider is configured. Set one of: "
        + "; ".join(f"{name} ({', '.join(keys)})" for name, keys in PROVIDERS)
    )


def _post(opener, url: str, data: bytes, headers: dict, timeout: float) -> tuple[int, str]:
    validate_public_http_url(url, allow_private=False)
    request = urllib.request.Request(url, data=data, headers=headers)
    with opener(request, timeout=timeout) as response:
        return getattr(response, "status", 200), response.read(4096).decode("utf-8", "replace")


def _send_slack(opener, env, *, subject: str, body: str, timeout: float) -> tuple[int, str]:
    text = f"*{subject}*\n{body}" if subject else body
    return _post(opener, env[SLACK_ENV].strip(), json.dumps({"text": text}).encode(),
                 {"Content-Type": "application/json"}, timeout)


def _send_email(opener, env, *, subject: str, body: str, timeout: float) -> tuple[int, str]:
    payload = {
        "from": (env.get("NOTIFY_EMAIL_FROM") or "simorgh@localhost").strip(),
        "to": [t.strip() for t in env["NOTIFY_EMAIL_TO"].split(",") if t.strip()],
        "subject": subject or "Simorgh",
        "text": body,
    }
    return _post(opener, RESEND_URL, json.dumps(payload).encode(),
                 {"Content-Type": "application/json",
                  "Authorization": f"Bearer {env['RESEND_API_KEY'].strip()}"}, timeout)


def _send_sms(opener, env, *, subject: str, body: str, timeout: float) -> tuple[int, str]:
    sid, token = env["TWILIO_ACCOUNT_SID"].strip(), env["TWILIO_AUTH_TOKEN"].strip()
    text = f"{subject}: {body}" if subject else body
    form = urllib.parse.urlencode({
        "From": env["TWILIO_FROM"].strip(), "To": env["NOTIFY_SMS_TO"].strip(), "Body": text[:1500],
    }).encode()
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
    return _post(opener, TWILIO_URL.format(sid=urllib.parse.quote(sid)), form,
                 {"Content-Type": "application/x-www-form-urlencoded",
                  "Authorization": f"Basic {auth}"}, timeout)


_SENDERS = {"slack": _send_slack, "email": _send_email, "sms": _send_sms}


class NotifyTool:
    name = "notify"
    description = (
        "Send a short message to the person who runs this system (Slack, email or SMS, "
        "whichever is configured). Irreversible: there is no unsend."
    )
    read_only = False
    reversibility = "irreversible"
    args_schema = {
        "type": "object", "required": ["body"],
        "properties": {"body": {"type": "string"}, "subject": {"type": "string"},
                       "provider": {"type": "string"}},
    }

    def __init__(self, config: Config, *, opener=None, env=None) -> None:
        self._config = config
        self._opener = opener or urllib.request.urlopen
        self._env = env if env is not None else os.environ
        self._recent: deque[float] = deque()

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        import asyncio

        body = str(args.get("body") or "").strip()
        if not body:
            return ToolResult(ok=False, error="refused: an empty message")
        subject = " ".join(str(args.get("subject") or "").split())[:200]
        try:
            self._enforce_rate_limit(ctx)
            provider = choose_provider(str(args.get("provider") or self._config.notify_provider), self._env)
        except NotifyUnavailable as exc:
            return ToolResult(ok=False, error=f"refused: {exc}")

        body = body[: self._config.notify_max_chars]
        try:
            status, reply = await asyncio.wait_for(
                asyncio.to_thread(_SENDERS[provider], self._opener, self._env,
                                  subject=subject, body=body, timeout=self._config.notify_timeout_s),
                timeout=self._config.notify_timeout_s + 5.0,
            )
        except asyncio.TimeoutError:
            return ToolResult(ok=False, error=f"timeout sending via {provider}")
        except FetchRefused as exc:
            return ToolResult(ok=False, error=f"refused: {exc}")
        except Exception as exc:  # noqa: BLE001 -- a delivery failure is a result, never a crash
            return ToolResult(ok=False, error=f"sending via {provider} failed: {exc!r}")

        ok = 200 <= int(status) < 300
        return ToolResult(
            ok=ok,
            output=(f"sent via {provider}" if ok else f"{provider} answered {status}"),
            error=None if ok else f"{provider} answered {status}: {reply[:300]}",
            # Never the message body, and never a credential: a notice
            # that echoed its own contents into the ledger would put
            # whatever Sim was told to pass on into a second place
            # nobody chose.
            metadata={"provider": provider, "status": int(status), "chars": len(body)},
        )

    def _enforce_rate_limit(self, ctx: ToolContext) -> None:
        now = ctx.clock.now() if ctx.clock else time.monotonic()
        cutoff = now - self._config.notify_window_s
        while self._recent and self._recent[0] < cutoff:
            self._recent.popleft()
        if len(self._recent) >= self._config.notify_max_calls:
            raise NotifyUnavailable(
                f"rate limit: {len(self._recent)}/{self._config.notify_max_calls} messages already sent "
                f"in the last {self._config.notify_window_s:.0f}s -- a notifier that can spam is a notifier "
                "nobody reads"
            )
        self._recent.append(now)
