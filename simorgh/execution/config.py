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


@dataclass(frozen=True)
class Config:
    max_concurrent_actions: int = 4
    default_timeout_s: float = 60.0
    max_output_bytes: int = 65536
    blob_inline_threshold_bytes: int = 4096
    approval_max_age_s: float = 120.0
    repo_root: Path = field(default_factory=Path.cwd)
    readable_roots: tuple[str, ...] = ("src", "docs", "tests", "simorgh", "simorgh_skills")
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
    write_scopes_source: tuple[str, ...] = (
        "src/", "simorgh/", "simorgh_skills/", "tests/", "tools/", "docs/",
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
    # `run_shell`. Off by default: it is the one tool whose blast
    # radius is not bounded by its own arguments, so turning it on is
    # a decision someone makes on purpose, in `[execution] shell = true`.
    shell: bool = False
    shell_timeout_s: float = 120.0
    # Commands refused outright, pattern -> the reason the model is
    # given. Not a security boundary (a shell has none, and any of
    # these is trivially rewritten); a guard against the specific
    # accidents a small model makes.
    shell_refusals: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_SHELL_REFUSALS))
    web_fetch_max_bytes: int = 200_000
    web_fetch_max_calls: int = 30
    web_fetch_window_s: float = 3600.0
    web_fetch_allow_private_networks: bool = False
    web_fetch_user_agent: str = "Simorgh/2.0 (personal AI assistant; +https://github.com/saeedsk/Simorgh)"
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
