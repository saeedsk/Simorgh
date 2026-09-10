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

Providers. The self-hosted ones come first in `auto` order, because
"local first, cloud as a named tier" is the standing rule for a
capability (`feedback_resourcefulness`) and because a notification is
exactly the kind of thing a person may not want to route through a
third party at all:

| provider | variables | notes |
|---|---|---|
| `ntfy`   | `NTFY_URL` (+ `NTFY_TOKEN`) | a topic URL, self-hosted or ntfy.sh; the phone app is free |
| `gotify` | `GOTIFY_URL` + `GOTIFY_TOKEN` | self-hosted push server |
| `home_assistant` | `HASS_URL` + `HASS_TOKEN` (+ `HASS_NOTIFY_SERVICE`) | reaches the phones that already have the HA app |
| `matrix` | `MATRIX_HOMESERVER` + `MATRIX_TOKEN` + `MATRIX_ROOM` | a room message |
| `apprise`| `APPRISE_URLS` | a catch-all over ~100 services; needs `pip install apprise` |
| `slack`  | `SLACK_WEBHOOK_URL` | an incoming webhook; no OAuth dance |
| `email`  | `RESEND_API_KEY` + `NOTIFY_EMAIL_TO` (+ `NOTIFY_EMAIL_FROM`) | simplest keyed email API |
| `sms`    | `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` + `TWILIO_FROM` + `NOTIFY_SMS_TO` | |

**Private addresses.** `web_fetch`'s SSRF boundary refuses any URL that
resolves inside the network, and the three cloud providers keep that
rule: a Slack webhook pointing at `169.254.169.254` is either a
misconfiguration or an attack. The self-hosted four are the opposite
case -- a Gotify box or Home Assistant lives at `192.168.1.x`, and
refusing that would mean refusing the whole point of them. What makes
that safe is not the destination but the source of the URL: these come
from an operator-set environment variable, never from a tool argument,
so the model cannot aim them anywhere. `provider` is the only thing a
caller may choose, and it selects a row, not an address.

Adding a provider is a row in `PROVIDERS` and a `_send_*` function
(plus `_ALLOW_PRIVATE` if it is self-hosted, and `_READY` if it needs
a package that may not be installed).
"""

from __future__ import annotations

import base64
import json
import re
import os
import time
import urllib.parse
import urllib.request
from collections import deque
from typing import Callable

from simorgh.contracts.protocols import ToolContext, ToolResult

from .config import Config
from .netsafety import FetchRefused, validate_public_http_url

SLACK_ENV = "SLACK_WEBHOOK_URL"
RESEND_URL = "https://api.resend.com/emails"
TWILIO_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"

# provider -> the variables it needs, all required. First match wins
# when the caller does not name one, so self-hosted comes before cloud.
PROVIDERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ntfy", ("NTFY_URL",)),
    ("gotify", ("GOTIFY_URL", "GOTIFY_TOKEN")),
    ("home_assistant", ("HASS_URL", "HASS_TOKEN")),
    ("matrix", ("MATRIX_HOMESERVER", "MATRIX_TOKEN", "MATRIX_ROOM")),
    ("apprise", ("APPRISE_URLS",)),
    ("slack", (SLACK_ENV,)),
    ("email", ("RESEND_API_KEY", "NOTIFY_EMAIL_TO")),
    ("sms", ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM", "NOTIFY_SMS_TO")),
)

#: Providers whose endpoint is the operator's own machine, so a private
#: address is the normal case rather than an SSRF signal. See the module
#: docstring: what makes this safe is that the URL comes from an
#: environment variable, never from a tool argument.
_ALLOW_PRIVATE: frozenset[str] = frozenset({"ntfy", "gotify", "home_assistant", "matrix"})


def _apprise_installed() -> bool:
    import importlib.util

    return importlib.util.find_spec("apprise") is not None


#: A provider may need more than its variables. `auto` skips one that is
#: not ready, rather than picking it and failing -- but naming it
#: explicitly still gives the refusal that says what to install, which
#: is the more useful answer to "why doesn't apprise work".
#:
#: The values look up the checker through the module rather than holding
#: it, so replacing `_apprise_installed` in a test actually takes effect
#: -- binding the function object here would freeze the real one into
#: this dict at import time and quietly ignore the patch.
_READY: dict[str, "Callable[[], bool]"] = {"apprise": lambda: _apprise_installed()}


def _provider_ready(name: str) -> bool:
    check = _READY.get(name)
    return True if check is None else bool(check())


class NotifyUnavailable(Exception):
    """Nothing was sent, and this is why."""


def configured_providers(env) -> list[str]:
    """Every provider whose variables are all set, ready or not."""
    return [name for name, keys in PROVIDERS if all((env.get(k) or "").strip() for k in keys)]


def available_providers(env) -> list[str]:
    """The providers `auto` may pick: configured AND able to run here."""
    return [name for name in configured_providers(env) if _provider_ready(name)]


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
        if configured not in dict(PROVIDERS):
            raise NotifyUnavailable(
                f"unknown provider {configured!r}; known: {', '.join(n for n, _ in PROVIDERS)}")
        missing = missing_for(configured, env)
        if missing:
            raise NotifyUnavailable(f"{configured} needs {', '.join(missing)} in the environment")
        if not _provider_ready(configured):
            raise NotifyUnavailable(
                f"{configured} is configured but its package is not installed "
                f"(pip install {configured})")
        return configured
    if ready:
        return ready[0]
    raise NotifyUnavailable(
        "no notification provider is configured. Set one of: "
        + "; ".join(f"{name} ({', '.join(keys)})" for name, keys in PROVIDERS)
    )


def _post(opener, url: str, data: bytes, headers: dict, timeout: float, *,
          allow_private: bool = False, method: str | None = None) -> tuple[int, str]:
    validate_public_http_url(url, allow_private=allow_private)
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with opener(request, timeout=timeout) as response:
        return getattr(response, "status", 200), response.read(4096).decode("utf-8", "replace")


def _header_safe(text: str) -> str:
    """A value fit for an HTTP header. `urllib` encodes headers as
    latin-1, so a subject with an em-dash or an emoji in it raises
    `UnicodeEncodeError` deep inside the send -- a notification lost to
    a character. Anything that will not survive the encode is dropped
    here instead, where it costs a few characters of a title rather than
    the whole message."""
    return text.encode("latin-1", "ignore").decode("latin-1")


def _send_ntfy(opener, env, *, subject: str, body: str, timeout: float) -> tuple[int, str]:
    """ntfy: the body IS the request body, the title is a header."""
    headers = {"Content-Type": "text/plain; charset=utf-8"}
    if subject:
        headers["Title"] = _header_safe(subject)
    token = (env.get("NTFY_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return _post(opener, env["NTFY_URL"].strip(), body.encode("utf-8"), headers, timeout,
                 allow_private=True)


def _send_gotify(opener, env, *, subject: str, body: str, timeout: float) -> tuple[int, str]:
    base = env["GOTIFY_URL"].strip().rstrip("/")
    payload = {"title": subject or "Simorgh", "message": body, "priority": 5}
    return _post(opener, f"{base}/message", json.dumps(payload).encode(),
                 {"Content-Type": "application/json",
                  "X-Gotify-Key": env["GOTIFY_TOKEN"].strip()}, timeout, allow_private=True)


def _send_home_assistant(opener, env, *, subject: str, body: str, timeout: float) -> tuple[int, str]:
    """Home Assistant's own notify service -- which is how a message
    reaches the phones that already have the HA app, with no second
    account anywhere. `HASS_NOTIFY_SERVICE` names the service after the
    `notify.` prefix (`mobile_app_pixel`, `persistent_notification`);
    plain `notify` is HA's default group."""
    base = env["HASS_URL"].strip().rstrip("/")
    service = (env.get("HASS_NOTIFY_SERVICE") or "notify").strip()
    service = service.removeprefix("notify.") or "notify"
    payload = {"title": subject or "Simorgh", "message": body}
    return _post(opener, f"{base}/api/services/notify/{urllib.parse.quote(service)}",
                 json.dumps(payload).encode(),
                 {"Content-Type": "application/json",
                  "Authorization": f"Bearer {env['HASS_TOKEN'].strip()}"}, timeout, allow_private=True)


def _send_matrix(opener, env, *, subject: str, body: str, timeout: float) -> tuple[int, str]:
    """A room message. The transaction id makes the send idempotent from
    the server's side: a retried PUT with the same id is not a second
    message."""
    import uuid

    base = env["MATRIX_HOMESERVER"].strip().rstrip("/")
    room = urllib.parse.quote(env["MATRIX_ROOM"].strip(), safe="")
    txn = urllib.parse.quote(f"simorgh-{uuid.uuid4().hex}", safe="")
    text = f"{subject}\n\n{body}" if subject else body
    url = f"{base}/_matrix/client/v3/rooms/{room}/send/m.room.message/{txn}"
    return _post(opener, url, json.dumps({"msgtype": "m.text", "body": text}).encode(),
                 {"Content-Type": "application/json",
                  "Authorization": f"Bearer {env['MATRIX_TOKEN'].strip()}"}, timeout,
                 allow_private=True, method="PUT")


def _load_apprise():
    """Imported lazily and through a seam a test can replace, so nothing
    here needs the package installed to be tested. The guard is on the
    import itself -- an optional third-party import under
    `simorgh/` is only allowed that way
    (tests/simorgh/test_module_boundaries.py rule 5), and it is the
    right shape anyway: the refusal that names the pip line belongs
    next to the import that failed."""
    try:
        import apprise  # noqa: PLC0415 -- optional dependency, by design
    except ImportError as exc:
        raise NotifyUnavailable(
            "APPRISE_URLS is set but the `apprise` package is not installed "
            "(pip install apprise)"
        ) from exc
    return apprise


def _send_apprise(opener, env, *, subject: str, body: str, timeout: float) -> tuple[int, str]:
    """The catch-all: one `APPRISE_URLS` covers Telegram, Discord,
    Pushover, Signal and ~100 more, each as a URL. Apprise does its own
    I/O, so `opener` is unused here -- the injected boundary for this
    provider is `_load_apprise`.

    Its `notify()` answers a bare bool for the whole batch, so a partial
    failure reads as a failure. That is the honest mapping: a caller
    told "sent" when one of three destinations dropped the message has
    been told something untrue."""
    apprise = _load_apprise()
    urls = [u.strip() for u in re.split(r"[,\s]+", env["APPRISE_URLS"]) if u.strip()]
    client = apprise.Apprise()
    added = [u for u in urls if client.add(u)]
    if not added:
        raise NotifyUnavailable(
            f"none of the {len(urls)} APPRISE_URLS entries is a URL apprise recognises")
    ok = client.notify(title=subject or "Simorgh", body=body)
    # Never the URLs themselves: an apprise URL embeds its own token.
    return (200 if ok else 502), f"apprise delivered to {len(added)} destination(s)" if ok else \
        "apprise reported a delivery failure"


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


_SENDERS = {
    "ntfy": _send_ntfy, "gotify": _send_gotify, "home_assistant": _send_home_assistant,
    "matrix": _send_matrix, "apprise": _send_apprise,
    "slack": _send_slack, "email": _send_email, "sms": _send_sms,
}


class NotifyTool:
    name = "notify"
    description = (
        "Send a short message to the person who runs this system (ntfy, Gotify, Home "
        "Assistant, Matrix, Slack, email or SMS -- whichever is configured). "
        "Irreversible: there is no unsend."
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
        except NotifyUnavailable as exc:
            # A provider that cannot run (a missing package, a URL set
            # it cannot parse) is a refusal that names the fix, not a
            # `repr()` of an exception.
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
