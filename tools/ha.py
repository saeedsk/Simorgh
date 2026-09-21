#!/usr/bin/env python3
"""ha: drive the Home Assistant container this machine runs for Sim.

Sim reaches Home Assistant over its REST API and nothing else: a URL
and a long-lived token, read by `simorgh/domains/home/tools.py`. That
is a small contract, and it fails in four different places -- the
Docker daemon is not running, the container is stopped, HA is running
but still booting, or the token is missing -- which from the outside
all look the same: `home_call` says "Home Assistant is not
configured" or "could not reach Home Assistant". This tool exists so
that both the creator and an agent can tell those four apart in one
command, without a browser and without reading a token out of a file.

    python3 tools/ha.py status          # daemon, container, API, token
    python3 tools/ha.py up [--create]   # start it (--create makes it the first time)
    python3 tools/ha.py down            # stop it, leaving the config volume alone
    python3 tools/ha.py logs [n]        # last n lines of HA's own log
    python3 tools/ha.py token           # how to mint a token and where to put it

`status` never raises on a machine where Docker is not running: that
is the normal state of a laptop that has just booted, and a tool that
throws a traceback at it is a tool nobody runs. It exits 0 when the
API answers, 1 when something in the chain is not ready, and says
which link it is.

No secret is ever printed. `status` reports that a token is present or
absent and nothing more -- its output goes into terminals, ledgers and
agent transcripts, and a token that appears in any of those has to be
revoked.

stdlib only, like the rest of `tools/`. See
`docs/findings/2026-09-20-home-assistant-on-the-mac.md` for why the
container was chosen over HA Core in a venv or HA OS in a VM.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

#: The container this tool drives. Overridable so a second instance
#: (a test one, say) can be driven by the same commands.
CONTAINER = os.environ.get("SIMORGH_HA_CONTAINER", "homeassistant")
IMAGE = os.environ.get("SIMORGH_HA_IMAGE", "ghcr.io/home-assistant/home-assistant:stable")
CONFIG_DIR = Path(os.environ.get("SIMORGH_HA_CONFIG", "~/.homeassistant/config")).expanduser()
PORT = int(os.environ.get("SIMORGH_HA_PORT", "8123"))
DEFAULT_URL = f"http://127.0.0.1:{PORT}"

SECRETS_FILE = Path(os.environ.get("SIMORGH_SECRETS_FILE", "~/.simorgh/secrets.toml")).expanduser()
VAULT_URL_KEY = "vault:home_assistant:url"
VAULT_TOKEN_KEY = "vault:home_assistant:token"

# Docker Desktop puts its CLI here and does not always leave it on a
# non-login shell's PATH, which is the shell an agent gets.
DOCKER_FALLBACK = "/Applications/Docker.app/Contents/Resources/bin/docker"


def docker_bin() -> str | None:
    return shutil.which("docker") or (DOCKER_FALLBACK if Path(DOCKER_FALLBACK).exists() else None)


def run(args: list[str], *, timeout: float = 20.0) -> tuple[int, str, str]:
    """Run a command and never raise. A missing binary and a timeout
    are ordinary answers here, not exceptions -- every caller below
    wants to print something about them rather than stop."""
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return 127, "", f"{args[0]}: not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"{' '.join(args[:2])}: no answer in {timeout:.0f}s"
    return done.returncode, done.stdout.strip(), done.stderr.strip()


# -- what is configured ------------------------------------------------------


def configured() -> tuple[str, bool, str]:
    """`(url, token_present, where)` exactly as Sim will see it.

    This mirrors `_HomeTool._lookup`: the secret store first (which
    resolves `vault:`-prefixed names out of `secrets.toml` and then the
    encrypted vault), then the plain environment variables. The vault
    itself is deliberately not opened -- that would touch the macOS
    keychain and prompt -- so a credential kept only in the vault is
    reported here as "not found in the file" while still working for
    Sim. Say so rather than claim it is missing.
    """
    values: dict[str, str] = {}
    where = "nowhere"
    if SECRETS_FILE.is_file():
        try:
            with SECRETS_FILE.open("rb") as fh:
                data = tomllib.load(fh)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            print(f"  warning: {SECRETS_FILE} could not be read ({exc})")
            data = {}
        for key in (VAULT_URL_KEY, VAULT_TOKEN_KEY):
            if isinstance(data.get(key), str) and data[key]:
                values[key] = data[key]
        if values:
            where = str(SECRETS_FILE)

    url = values.get(VAULT_URL_KEY) or os.environ.get("HOME_ASSISTANT_URL") or ""
    token = values.get(VAULT_TOKEN_KEY) or os.environ.get("HOME_ASSISTANT_TOKEN") or ""
    if not values and (url or token):
        where = "the environment"
    return url, bool(token), where


# -- the checks --------------------------------------------------------------


def probe_api(url: str, token: str) -> tuple[bool, str]:
    """Ask HA whether it is running. `GET /api/` needs the token;
    `GET /` does not and is what tells a stopped container apart from a
    missing token, so both are tried in that order."""
    ok, note = _get(f"{url.rstrip('/')}/api/", token)
    if ok:
        return True, note
    if token:
        return False, note
    reachable, plain = _get(url.rstrip("/") + "/", "")
    if reachable:
        return False, "HA is listening but no token is configured"
    return False, plain


def _get(target: str, token: str) -> tuple[bool, str]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = urllib.request.Request(target, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=5.0) as response:
            raw = response.read(4096)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return False, "HA refused the token (401/403): mint a new one, `ha.py token`"
        return False, f"HA answered {exc.code}"
    except urllib.error.URLError as exc:
        # `exc.reason` and never the URL: the URL is the one string
        # here that could carry a token.
        return False, f"nothing listening ({exc.reason})"
    except TimeoutError:
        return False, "no answer in 5s"
    try:
        message = str(json.loads(raw.decode("utf-8", "replace")).get("message", ""))
    except (ValueError, AttributeError):
        message = ""
    return True, message or "answered"


def cmd_status(_args) -> int:
    binary = docker_bin()
    if binary is None:
        print("docker: not installed. Docker Desktop is not on this machine.")
        print("  fix: install Docker Desktop, then `python3 tools/ha.py up --create`")
        return 1
    print(f"docker cli: {binary}")

    code, out, err = run([binary, "version", "--format", "{{.Server.Version}}"], timeout=15.0)
    if code != 0 or not out:
        print("docker daemon: NOT RUNNING")
        print(f"  ({err.splitlines()[0] if err else 'no server version'})")
        print("  fix: `open -a Docker`, wait for the whale in the menu bar, then re-run this")
        return 1
    print(f"docker daemon: running (server {out})")

    code, out, _ = run([binary, "inspect", "-f", "{{.State.Status}}", CONTAINER])
    if code != 0:
        print(f"container {CONTAINER!r}: does not exist")
        print("  fix: `python3 tools/ha.py up --create` (first run pulls about 1.5 GB)")
        return 1
    state = out or "unknown"
    print(f"container {CONTAINER!r}: {state}")
    if state != "running":
        print("  fix: `python3 tools/ha.py up`")
        return 1

    url, has_token, where = configured()
    if url:
        print(f"config: url set, token {'set' if has_token else 'MISSING'} (from {where})")
    else:
        print(f"config: nothing for Sim yet (looked in {SECRETS_FILE} and the environment)")
        print("  note: a credential kept only in the encrypted vault is not visible here")

    target = url or DEFAULT_URL
    token = os.environ.get("HOME_ASSISTANT_TOKEN", "")
    if not token and has_token:
        token = _secret(VAULT_TOKEN_KEY)
    ok, note = probe_api(target, token)
    if ok:
        print(f"api: answers at {target} ({note})")
    else:
        print(f"api: not usable at {target} -- {note}")
        if not has_token:
            print("  fix: `python3 tools/ha.py token`")
        return 1
    return 0


def _secret(name: str) -> str:
    if not SECRETS_FILE.is_file():
        return ""
    try:
        with SECRETS_FILE.open("rb") as fh:
            value = tomllib.load(fh).get(name)
    except (OSError, tomllib.TOMLDecodeError):
        return ""
    return value if isinstance(value, str) else ""


# -- the verbs ---------------------------------------------------------------


def _require_daemon(binary: str | None) -> str | None:
    if binary is None:
        print("docker is not installed on this machine")
        return None
    code, _, _ = run([binary, "version", "--format", "{{.Server.Version}}"], timeout=15.0)
    if code != 0:
        print("the Docker daemon is not running; `open -a Docker` first")
        return None
    return binary


def cmd_up(args) -> int:
    binary = _require_daemon(docker_bin())
    if binary is None:
        return 1
    code, out, _ = run([binary, "inspect", "-f", "{{.State.Status}}", CONTAINER])
    if code == 0:
        if out == "running":
            print(f"{CONTAINER} is already running at {DEFAULT_URL}")
            return 0
        code, _, err = run([binary, "start", CONTAINER], timeout=60.0)
        if code != 0:
            print(f"could not start {CONTAINER}: {err}")
            return 1
        print(f"{CONTAINER} started; HA takes 20-60s to answer at {DEFAULT_URL}")
        return 0

    create = [binary, "run", "-d", "--name", CONTAINER, "--restart", "unless-stopped",
              "-e", f"TZ={_timezone()}", "-v", f"{CONFIG_DIR}:/config",
              "-p", f"{PORT}:8123", IMAGE]
    if not args.create:
        print(f"container {CONTAINER!r} does not exist yet. To create it (pulls about 1.5 GB):")
        print("  " + " ".join(create))
        print("or run `python3 tools/ha.py up --create`, which runs exactly that.")
        return 1
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    print("creating the container; the first pull is about 1.5 GB and takes a few minutes")
    code, out, err = run(create, timeout=1800.0)
    if code != 0:
        print(f"could not create {CONTAINER}: {err or out}")
        return 1
    print(f"created. Open {DEFAULT_URL} in a browser to finish onboarding, then `ha.py token`.")
    return 0


def _timezone() -> str:
    """The machine's zone name, so HA's clock matches the household's.
    `/etc/localtime` is a symlink into the zoneinfo tree on macOS; if
    it is not, UTC is the honest answer rather than a guess."""
    try:
        target = os.readlink("/etc/localtime")
    except OSError:
        return "UTC"
    _, _, zone = target.partition("zoneinfo/")
    return zone or "UTC"


def cmd_down(_args) -> int:
    binary = _require_daemon(docker_bin())
    if binary is None:
        return 1
    code, _, err = run([binary, "stop", CONTAINER], timeout=60.0)
    if code != 0:
        print(f"could not stop {CONTAINER}: {err}")
        return 1
    print(f"{CONTAINER} stopped. The config volume ({CONFIG_DIR}) is untouched.")
    return 0


def cmd_logs(args) -> int:
    binary = _require_daemon(docker_bin())
    if binary is None:
        return 1
    code, out, err = run([binary, "logs", "--tail", str(args.lines), CONTAINER], timeout=30.0)
    if code != 0:
        print(f"no logs: {err}")
        return 1
    # HA writes most of its startup to stderr, so both streams matter.
    text = "\n".join(part for part in (out, err) if part)
    print(text or "(no output yet)")
    return 0


def cmd_token(_args) -> int:
    url, has_token, where = configured()
    print("A long-lived access token is made in the HA web UI, once, by hand:")
    print(f"  1. open {url or DEFAULT_URL} and sign in")
    print("  2. click your user name at the bottom of the sidebar")
    print("  3. Security tab -> Long-lived access tokens -> Create token")
    print("  4. name it 'simorgh' and copy the string; HA shows it exactly once")
    print()
    print(f"Then put it where Sim looks. Append to {SECRETS_FILE} (keys quoted, they contain colons):")
    print()
    print(f'  "{VAULT_URL_KEY}" = "{DEFAULT_URL}"')
    print(f'  "{VAULT_TOKEN_KEY}" = "<the token>"')
    print()
    print(f"  chmod 600 {SECRETS_FILE}   # the store refuses a group/world-readable file")
    print()
    print("`[execution] secrets` in ~/.simorgh/simorgh.toml already lists \"vault:*\", so both")
    print("names are in scope for the tools; no config change is needed. Restart Sim, then")
    print("`python3 tools/ha.py status`. HOME_ASSISTANT_URL and HOME_ASSISTANT_TOKEN in the")
    print("environment work too and are what a one-off shell should use.")
    print()
    if url and has_token:
        print(f"Right now: a url and a token are already configured, from {where}.")
    elif url:
        print(f"Right now: a url is configured from {where}, but no token.")
    else:
        print("Right now: nothing is configured.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("status", help="daemon, container, API and token, in that order")
    up = subparsers.add_parser("up", help="start the container")
    up.add_argument("--create", action="store_true", help="create it if it does not exist (pulls the image)")
    subparsers.add_parser("down", help="stop the container")
    logs = subparsers.add_parser("logs", help="tail HA's log")
    logs.add_argument("lines", nargs="?", type=int, default=50)
    subparsers.add_parser("token", help="how to mint a token and where to put it")
    args = parser.parse_args()

    handlers = {"status": cmd_status, "up": cmd_up, "down": cmd_down,
                "logs": cmd_logs, "token": cmd_token}
    handler = handlers.get(args.command or "status")
    if handler is None:
        parser.print_help()
        return 2
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
