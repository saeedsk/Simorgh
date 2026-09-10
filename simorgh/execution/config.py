"""Execution configuration (08-execution.md section 3.5) -- a working
subset: the knobs the tools built this phase actually read. Shell,
relaunch, hot_swap, and isolated_test_suite (and their config keys) are
still deferred -- see simorgh/execution/README.md. Skill tools
(`apply_skill`, `SkillTool`, on-demand `learn.skill.acquired`
loading -- Phase 4 roadmap item 4.7) and `web_fetch` are built this pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .external import ExternalToolSpec
from .shell import DEFAULT_SHELL_REFUSALS
from .mcp import McpServerConfig


def _looks_like_the_repo(candidate: Path) -> bool:
    """A deep path, so a case-insensitive filesystem cannot match a
    parent directory that merely shares the package's name."""
    return (candidate / "simorgh" / "kernel" / "service.py").is_file()


def find_repo_root(start: Path | None = None) -> Path:
    """Where Sim's own source lives.

    Was `Path.cwd()` alone. Launched from anywhere else, every readable
    root pointed at nothing, and Sim answered questions about itself
    from imagination: it invented five subsystems, denied having a
    Guardian while `status` printed `guardian ok`, and denied having a
    step budget it was actively enforcing -- with no error, ever
    (observer, 2026-09-08).

    The running package's own location is checked first and is right by
    construction; `start` (normally the cwd) only wins when it is a
    different, genuine checkout -- which is what a sandboxed trial or a
    rolled-back loader boot actually is.
    """
    here = Path(__file__).resolve().parents[2]
    base = (start or Path.cwd()).resolve()
    for candidate in (base, *base.parents):
        if _looks_like_the_repo(candidate):
            return candidate
    return here if _looks_like_the_repo(here) else base


@dataclass(frozen=True)
class Config:
    max_concurrent_actions: int = 4
    default_timeout_s: float = 60.0
    max_output_bytes: int = 65536
    blob_inline_threshold_bytes: int = 4096
    approval_max_age_s: float = 120.0
    repo_root: Path = field(default_factory=lambda: find_repo_root())
    # `papers/` is here because the creator put papers on self-learning
    # AI there for Sim to read (2026-09-08); without the root they were
    # reachable by no tool at all.
    # `tools` is here because it was WRITABLE and not readable: Sim
    # could patch a file it was forbidden to open, and a task to fix a
    # bug in tools/trial.py spent 464 seconds failing on
    # "[refused: outside the readable areas]" before giving up
    # (observer, 2026-09-08).
    readable_roots: tuple[str, ...] = (
        "src", "docs", "tests", "simorgh", "simorgh_skills", "papers", "tools",
        # Where a large tool result is written (`results_dir` below).
        # Readable, never writable by a patch: `write_scopes_source` does
        # not list it, so Sim can read the data it fetched and cannot
        # commit it.
        "results",
    )
    # Files at the repo root. `readable_roots` holds directories only, so
    # README.md, requirements.txt, simloader.py and sim.sh were readable
    # by nothing -- Sim could not read its own bootloader, and a chat
    # session burned its whole budget hunting for a README it was
    # standing on. Reading them is safe; writing them is a separate
    # question that `write_scopes_source` and Guardian answer.
    readable_root_files: tuple[str, ...] = (
        "README.md", "CLAUDE.md", "requirements.txt", "simorgh.toml", "simloader.py", "sim.sh",
    )
    # The creator, 2026-09-07: "give sim file system write access".
    # Every directory of the repository, rather than the two packages
    # it started with -- docs, tests, tools and the rest are all
    # things a self-improving system has real reason to edit. Paths
    # are still repo-relative and `..` is still refused, so this is
    # "anywhere in the project", not "anywhere on the machine".
    #
    # `run_shell` (execution/shell.py) is not bounded by this and
    # cannot be: a shell writes wherever the user can. Once that tool
    # is enabled these scopes describe the *file* tools, and Guardian
    # is what stands behind the shell.
    # `src/` is READABLE but not writable. It is the retired v1 tree
    # (docs/architecture.md: "retired but not yet deleted -- that's the
    # plan's Stage C"), so anything written there is work scheduled for
    # deletion. Found 2026-09-08: a Sim run had left an uncommitted
    # docstring in `src/cognition/__init__.py` in the real repo, which
    # is effort spent on a tree nobody will ever run again.
    write_scopes_source: tuple[str, ...] = (
        "simorgh/", "simorgh_skills/", "tests/", "tools/", "docs/",
    )
    sandbox_cpu_seconds: int = 5
    sandbox_memory_mb: int = 256
    sandbox_timeout_s: float = 10.0
    # -- search_code (grep across `readable_roots`; the gap `read_file`+
    # `list_dir` alone can't close -- finding *where* something lives
    # without already knowing the file). Read-only, so these caps exist
    # to bound one query's own cost, not as a Guardian-relevant limit.
    search_max_files_scanned: int = 2000
    search_max_matches: int = 200
    search_max_file_bytes: int = 1_000_000
    # -- run_tests (the `isolated_test_suite` gap named deferred in
    # execution/README.md, built here as its own standalone tool rather
    # than as part of the full draft/verify Cognition loop that gap was
    # originally scoped for): pytest against a throwaway copy of the
    # repo, never the real working tree. Separate limits from the code
    # sandbox above -- a real test run legitimately needs more time/
    # memory than a short isolated script.
    # The full suite takes ~180s on this repo, so 120s sat right on top
    # of it and flaked under load: one timeout burned half a trial's
    # budget and the session ran out of steps before it could commit.
    # Found by the repeat-run trial, 2026-09-07.
    test_timeout_s: float = 300.0
    test_cpu_seconds: int = 240
    test_memory_mb: int = 1024
    test_output_max_chars: int = 8000
    # -- skills (11-learning.md's `skill_dir`; 08-execution.md's
    # `write_scopes.skills`) -- where `apply_skill` writes and
    # `learn.skill.acquired`/on-demand loading reads back from.
    skill_dir: str = "simorgh_skills"
    write_scopes_skills: tuple[str, ...] = ("simorgh_skills/",)
    skill_lookup_timeout_s: float = 2.0
    # -- web_fetch (08-execution.md section 5.2/3.5; the one reviewed path
    # for real outbound network access -- see WebFetchTool's own docstring)
    web_fetch_timeout_s: float = 10.0
    # (host suffix, environment variable) -- `web_fetch` sends
    # `Authorization: Bearer <value>` only to these hosts, and only when
    # the variable is set. Hugging Face is here because the creator put
    # an HF_TOKEN in the environment on 2026-09-07 and the datasets
    # worth reading (SWE-bench, BFCL, GAIA) are hosted there; a public
    # dataset needs no token, a gated one does. Adding a host here is a
    # decision to trust it with that credential.
    web_fetch_bearers: tuple[tuple[str, str], ...] = (
        ("huggingface.co", "HF_TOKEN"),
        ("cdn-lfs.huggingface.co", "HF_TOKEN"),
    )
    # `run_shell`. On by default since 2026-09-07 -- the creator: "give
    # sim file system write access and shell access". It is the one tool
    # whose blast radius is not bounded by its own arguments, so it is
    # declared irreversible (Guardian's ReversibilityRule sees every
    # call), refuses the catastrophic outright (`shell_refusals`), and
    # `[execution] shell = false` turns it off.
    shell: bool = True
    # -- run_remote (execution/remote.py). OFF by default, one step
    # stricter than `run_shell` above: the blast radius is a machine
    # this code cannot inspect, snapshot or roll back. The host, user
    # and key come from SIMORGH_REMOTE_HOST/_USER/_KEY -- never from the
    # model, which supplies only the command. There is deliberately no
    # `host` argument; adding one would make this a general way to send
    # anything here to any machine on the internet.
    remote: bool = False
    remote_timeout_s: float = 300.0
    remote_connect_timeout_s: float = 15.0
    remote_output_max_chars: int = 8000
    # Setting this False accepts an unknown or CHANGED host key without
    # complaint, which is exactly the signal that someone is between you
    # and the host. Only for a throwaway box you would not mind losing.
    remote_strict_host_key: bool = True
    # Prefixed to every command as `cd <dir> && ...`; "" runs in the
    # login directory.
    remote_working_dir: str = ""
    shell_timeout_s: float = 120.0
    # Commands refused outright, pattern -> the reason the model is
    # given. Not a security boundary (a shell has none, and any of
    # these is trivially rewritten); a guard against the specific
    # accidents a small model makes.
    shell_refusals: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_SHELL_REFUSALS))
    # -- web_search (execution/websearch.py). The creator, 2026-09-08:
    # "add web search engine tool ability to sim". `auto` uses whichever
    # provider key is actually set, else DuckDuckGo, which needs none;
    # naming one explicitly means that one or an error, since silently
    # falling back to a weaker engine would look like a mysterious drop
    # in benchmark scores rather than a misconfiguration.
    web_search_provider: str = "auto"
    web_search_max_results: int = 8
    web_search_timeout_s: float = 15.0
    web_search_max_bytes: int = 400_000
    # Its own budget: a search is one call where a fetch is many, so a
    # burst of reading must not starve the searching that found it.
    # The keyless endpoint throttles back-to-back requests by answering
    # 200 with an empty page, so leave a gap and try again rather than
    # reporting "no results" for something it refused.
    web_search_min_interval_s: float = 2.0
    web_search_attempts: int = 3
    web_search_max_calls: int = 60
    web_search_window_s: float = 3600.0
    # Turn a fetched HTML page into readable text before the model sees
    # it. Off would mean handing it 87% markup again; the switch exists
    # because a caller that genuinely wants the source should be able to
    # say so.
    web_fetch_extract_text: bool = True
    web_fetch_max_bytes: int = 200_000
    web_fetch_max_calls: int = 30
    web_fetch_window_s: float = 3600.0
    web_fetch_allow_private_networks: bool = False
    web_fetch_user_agent: str = "Simorgh/2.0 (personal AI assistant; +https://github.com/saeedsk/Simorgh)"
    # -- large tool results (service.py::_store_rows). A data tool can
    # return far more than a model should read inline -- one
    # `search_listings` call fetches hundreds of rows -- and the useful
    # thing to do with them is analysis, not reading. Rows are written
    # to a real file under `results/` (a readable root, gitignored) and
    # the tool's own output names the path, so `read_file` can open it
    # and a script with repo access can load it with pandas. Live-driven
    # (2026-09-09): the KNN-comparables analysis another agent ran on
    # 95120 listings needs the rows, not a rendered summary.
    results_dir: str = "results"
    results_max_rows: int = 500
    results_keep_files: int = 50

    # -- find_package / install_package (packages.py). The tools that
    # turn "no capability for this" into "there is a library for this".
    # `run_shell` could always pip-install; these are the narrow,
    # checked, audited version, and the install leaves a line in
    # `package_log` so a human can see what Sim added and why.
    package_lookup_timeout_s: float = 10.0
    package_install_timeout_s: float = 300.0
    package_min_age_days: int = 30
    max_installs_per_day: int = 10
    package_log: str = "simorgh_packages.txt"
    # Crude, overridable, and aimed at the accident rather than the
    # attacker -- same bargain as DEFAULT_SHELL_REFUSALS.
    package_denylist: tuple[str, ...] = (r"(?i)^sudo", r"(?i)^setuptools$", r"(?i)^pip$")
    # -- run_script (script.py): real Python, repo importable, network
    # reachable -- for USING an installed library. Guardian still reads
    # the payload as `code`, so hand-written network calls are refused
    # here exactly as they are in the sandbox.
    script_dir: str = ".simorgh_scripts"
    script_timeout_s: float = 180.0
    script_cpu_seconds: int = 120
    script_memory_mb: int = 1024
    script_output_max_chars: int = 8000
    script_keep_files: int = 50
    # Not os.environ wholesale: a subprocess should not inherit every
    # credential in the session just to reach the network.
    script_env_passthrough: tuple[str, ...] = (
        "PATH", "HOME", "LANG", "LC_ALL", "TMPDIR",
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
    )

    # -- notify (notify.py): how autonomous work reaches a person who is
    # not watching the REPL. Every provider is switched on by an
    # environment variable and off by its absence, so the tool exists and
    # is registered before any credential does -- it refuses cleanly and
    # names the variable to set, rather than being absent when needed.
    # "auto" picks the first fully-configured provider in notify.PROVIDERS.
    notify_provider: str = "auto"  # auto | slack | email | sms
    notify_timeout_s: float = 15.0
    notify_max_chars: int = 4000
    # A notifier that can spam is a notifier nobody reads -- and an
    # autonomous loop that discovers `notify` is exactly the thing that
    # would send four hundred of them.
    notify_max_calls: int = 20
    notify_window_s: float = 3600.0

    # -- render_page (render.py's own module docstring): a real headless-
    # Chromium render via Puppeteer, so Sim can see a page the way a
    # browser actually executes it (JS-driven layout, a runtime error a
    # syntax check can't catch) instead of only reading the source and
    # guessing. Same SSRF guard as web_fetch for a remote URL; a local
    # path is read through the same readable_roots/pathsafety boundary
    # every other file-reading tool already uses.
    render_page_timeout_s: float = 20.0
    render_page_max_chars: int = 20_000
    render_page_allow_private_networks: bool = False
    render_page_node_path: str = ""  # "" -> resolved once via `npm root -g`
    # `browse_page` writes screenshots here (a readable root, gitignored).
    render_screenshot_dir: str = "results/screenshots"
    # -- run_container (container.py). The one tool whose isolation runs
    # the other way: the container cannot see the repository at all.
    # Files go in by being copied into a scratch dir mounted at /work,
    # never a bind mount of the repo -- a container that could write
    # back into the tree would make every write-scope rule advisory.
    container_docker_path: str = ""
    container_image_prefixes: tuple[str, ...] = (
        "python:", "node:", "ubuntu:", "debian:", "alpine:", "golang:", "rust:",
    )
    container_scratch_dir: str = "results/containers"
    container_timeout_s: float = 300.0
    container_memory_mb: int = 1024
    container_cpus: float = 1.0
    container_output_max_chars: int = 8000
    # -- geocode (geocode.py): turns a free-text address into lat/lng
    # using the free, keyless Nominatim (OpenStreetMap) API -- no
    # account or credential needed, unlike every commercial geocoder.
    # Nominatim's usage policy caps unauthenticated use at ~1 req/s and
    # requires an identifying User-Agent, both honored below.
    geocode_timeout_s: float = 10.0
    geocode_min_interval_s: float = 1.0
    geocode_user_agent: str = "Simorgh/2.0 (personal AI assistant; +https://github.com/saeedsk/Simorgh)"
    # -- search_listings (realestate.py): real, current for-sale property
    # data via the `homeharvest` package -- an actively-maintained open-
    # source library that reads Realtor.com's own site backend, not a
    # licensed data API. Unofficial and rate-limited hard here on purpose:
    # a single query can return 1000+ rows city-wide (live-tested,
    # 2026-09-09), so this caps what comes back and how often it can be
    # called at all, on top of homeharvest's own request pacing.
    # Which source answers `search_listings`. "auto" prefers a licensed
    # API when its key is set (see listingsources.PROVIDERS) and falls
    # back to the keyless homeharvest scraper otherwise, so the tool
    # works with no account and improves the day somebody adds one.
    # Naming a provider whose key is missing is an error, not a silent
    # fallback: data from a source the operator did not choose would
    # arrive wearing the wrong disclaimer.
    real_estate_provider: str = "auto"  # auto | rentcast | attom | homeharvest
    real_estate_max_results: int = 20
    real_estate_timeout_s: float = 30.0
    real_estate_max_calls: int = 20
    real_estate_window_s: float = 3600.0
    # -- MCP (mcp.py's own module docstring): a human-configured, static
    # list of external tool servers. Empty by default -- Sim never adds
    # to this itself; each entry is a deliberate capability grant, same
    # spirit as `web_fetch_allow_private_networks` defaulting False.
    mcp_servers: tuple[McpServerConfig, ...] = ()
    # -- open-source toolset adapters (external.py's module docstring):
    # LangChain tools, pydantic_ai toolsets, Composio, plain callables --
    # each an optional import, wrapped behind the Tool protocol so
    # Guardian still gates every call.
    external_tools: tuple[ExternalToolSpec, ...] = ()

    @classmethod
    def from_mapping(cls, data: Mapping[str, object] | None) -> "Config":
        if not data:
            return cls()
        kwargs = dict(data)
        if "external_tools" in kwargs:
            kwargs["external_tools"] = tuple(
                spec if isinstance(spec, ExternalToolSpec) else ExternalToolSpec.from_mapping(spec)
                for spec in kwargs["external_tools"]
            )
        if "repo_root" in kwargs:
            kwargs["repo_root"] = Path(kwargs["repo_root"])
        for key in ("readable_roots", "write_scopes_source", "write_scopes_skills"):
            if key in kwargs:
                kwargs[key] = tuple(kwargs[key])
        if "mcp_servers" in kwargs:
            kwargs["mcp_servers"] = tuple(
                server if isinstance(server, McpServerConfig) else McpServerConfig(
                    name=server["name"], command=server["command"],
                    args=tuple(server.get("args", ())), env=dict(server.get("env", {})),
                    read_only_tools=frozenset(server.get("read_only_tools", ())),
                    timeout_s=float(server.get("timeout_s", 15.0)),
                )
                for server in kwargs["mcp_servers"]
            )
        kwargs = {k: v for k, v in kwargs.items() if k in cls.__dataclass_fields__}
        return cls(**kwargs)
