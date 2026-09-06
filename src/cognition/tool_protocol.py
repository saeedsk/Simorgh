"""Shared, reviewed helpers for the marker-based tool protocol used
wherever an LLM is given bounded, single-action-per-turn tool access in
this codebase (SkillResearchAgent in src/agents/skills/research.py, and
LogicAgent in src/agents/logic/base.py).

Kept in one place specifically so every caller enforces the exact same
READ safety boundary -- confined to this repository's own tracked source,
no traversal, no credential-shaped names -- rather than each maintaining
its own copy that could drift out of sync with the others.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

_CODE_FENCE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)

_ALLOWED_READ_ROOTS = ("src", "docs", "tests")
_MAX_READ_CHARS = 20_000
_CREDENTIAL_LOOKING_NAMES = (".env", "secrets", "credentials")
# Generously above any real path in this repository -- exists purely to
# refuse an obviously-malformed "path" (a hallucinated multi-KB blob)
# before ever touching the filesystem with it.
_MAX_PATH_CHARS = 500

_DEFAULT_PREVIEW_LIMIT = 150


def preview(text: str, limit: int = _DEFAULT_PREVIEW_LIMIT) -> str:
    """A bounded, single-line-safe preview of a marker payload, for
    console narration and log display -- never the full payload used for
    the real work (safe_read_file, the audit gate, activity-log storage
    all still see the untruncated value; this is display-only).

    Caught live: a confused model emitted a "READ:" marker whose payload
    was really a 27,000-character hallucinated multi-turn transcript
    (embedding fake "READ:"/nothing-was-returned exchanges) rather than a
    real path. Every narration line printed that verbatim -- an
    unbounded, unformatted wall of text -- because nothing between
    parse_marker() and the print() call ever bounded it. Collapsing
    newlines first means even a malformed multi-line payload stays a
    single terminal line.
    """
    collapsed = text.replace("\r\n", " ").replace("\n", " ⏎ ").strip()
    if len(collapsed) > limit:
        return collapsed[:limit] + f"… (+{len(collapsed) - limit} more chars)"
    return collapsed


def first_line_argument(text: str) -> str:
    """The first non-empty line of a marker's payload, stripped -- for
    an argument that's meant to be a single bare token (a path, a URL,
    a skill name), never free-form prose.

    Guards a real, live-caught failure mode distinct from `preview()`'s
    (display-only) one: the model doesn't always stop at the marker
    itself and keeps reasoning out loud in the same response --
    "src/orchestrator/discovery.py\\nWait, the tool format is:\\nREAD:
    <path> exactly as the ENTIRE response...". `parse_marker()` has no
    way to know that wasn't part of the argument, since a code-bearing
    marker (RUN:/DRAFT:) legitimately needs everything after it kept
    intact -- this is the opposite case, a marker whose argument is
    always exactly one line. For those, only the first line was ever
    the real answer; discarding the rest turns a guaranteed-refused,
    confusing lookup (the whole rambling blob treated as one "path")
    into the working one the model actually intended, instead of
    feeding the confusion back into the next prompt and compounding it.
    """
    stripped = text.strip()
    if not stripped:
        return ""
    return stripped.splitlines()[0].strip()


def parse_marker(text: str, markers: tuple[str, ...]) -> tuple[str | None, str]:
    """If `text` (stripped) starts with one of `markers` (each given
    without a trailing colon, matched case-insensitively followed by ':'),
    returns (marker.lower(), payload). Otherwise returns (None, text) --
    the whole stripped text, meaning "no tool call, this is a final
    answer."
    """
    stripped = text.strip()
    for marker in markers:
        prefix = f"{marker}:"
        if stripped[: len(prefix)].upper() == prefix.upper():
            return marker.lower(), stripped[len(prefix) :].strip()
    return None, stripped


def extract_code(text: str) -> str | None:
    """Strip a markdown code fence if the model wrapped its answer in one;
    otherwise use the text as-is. Returns None for empty input.
    """
    match = _CODE_FENCE.search(text)
    stripped = (match.group(1) if match else text).strip()
    return stripped or None


def is_valid_python(code: str) -> bool:
    try:
        ast.parse(code)
    except SyntaxError:
        return False
    return True


def _resolve_safe_path(repo_root: Path, raw_path: str) -> tuple[Path | None, str | None]:
    """The shared validation core for safe_read_file (bounded, for the
    chat-facing READ tool) and read_file_for_patch (a much higher bound,
    for seeding a self-patch draft with a file's true current content) --
    factored out so both enforce the identical path-safety boundary
    (plain relative path inside repo_root, under src/docs/tests, no
    traversal, no credential-shaped names) rather than risking two
    copies drifting apart. Returns `(resolved_path, None)` on success or
    `(None, "refused: ...")` on any failure -- never raises.

    That "never raises" guarantee is enforced explicitly, not assumed:
    caught live, a confused model's "READ:" payload was really a huge
    (50,000+ character) hallucinated blob, and `Path.is_file()` raised a
    raw `OSError: [Errno 63] File name too long` -- nothing here used to
    catch that, and it crashed the entire CLI process mid-batch. A
    length check up front refuses the obvious case before ever touching
    the filesystem; the try/except below is the second, unconditional
    layer, since a filename can be "too long" (or otherwise invalid) in
    OS- and filesystem-specific ways this function shouldn't have to
    enumerate.
    """
    if len(raw_path) > _MAX_PATH_CHARS:
        return None, f"refused: path is {len(raw_path)} chars -- too long to be a real path"
    try:
        rel = Path(raw_path)
    except ValueError as exc:
        return None, f"refused: {raw_path!r} is not a valid path: {exc!r}"

    if rel.is_absolute() or ".." in rel.parts:
        return None, f"refused: {raw_path!r} is not a safe relative path"
    if not rel.parts or rel.parts[0] not in _ALLOWED_READ_ROOTS:
        return None, (
            f"refused: {raw_path!r} is outside the readable areas "
            f"({', '.join(_ALLOWED_READ_ROOTS)})"
        )
    if any(
        name in part.lower() or part.lower().endswith(".key")
        for part in rel.parts
        for name in _CREDENTIAL_LOOKING_NAMES
    ):
        return None, f"refused: {raw_path!r} looks like a credentials path"

    try:
        resolved_root = repo_root.resolve()
        target = (resolved_root / rel).resolve()
        if resolved_root != target and resolved_root not in target.parents:
            return None, f"refused: {raw_path!r} resolves outside the repository"
        if not target.is_file():
            return None, f"refused: {raw_path!r} is not a file"
    except OSError as exc:
        return None, f"refused: could not resolve {raw_path!r}: {exc!r}"
    return target, None


def safe_read_file(repo_root: Path, raw_path: str) -> str:
    """Read `raw_path` if -- and only if -- it resolves to a plain
    relative path inside `repo_root`, under src/, docs/, or tests/, and
    doesn't look like a credentials file. Read-only; never writes; never
    raises -- returns a "[refused: ...]" string on any problem, so a
    caller can always feed the result straight back into a prompt without
    a try/except of its own. Bounded to `_MAX_READ_CHARS`, appropriate
    for a chat-facing READ tool call -- see `read_file_for_patch` for
    self-patch's own, much higher ceiling, needed because it seeds a
    "write the complete new content of this file" prompt rather than a
    bounded conversational lookup.
    """
    target, refusal = _resolve_safe_path(repo_root, raw_path)
    if refusal is not None:
        return f"[{refusal}]"
    try:
        content = target.read_text(errors="replace")
    except OSError as exc:
        return f"[refused: could not read {raw_path!r}: {exc!r}]"

    if len(content) > _MAX_READ_CHARS:
        return content[:_MAX_READ_CHARS] + f"\n...[truncated, {len(content)} chars total]"
    return content


# Self-patching is asked to write "the COMPLETE new content" of a file,
# so silently truncating what it's shown (as safe_read_file's much
# smaller _MAX_READ_CHARS does, appropriate for a bounded chat READ)
# produces a genuinely broken draft, not just an incomplete one: caught
# live, self-patching a 62KB file fed the model only its first 20,000
# characters, and it visibly confused itself trying to ask for "more"
# (hallucinating an offset-based read protocol this system doesn't
# have) before the drafting attempt failed outright. src/main.py
# (~106KB) and src/agents/logic/base.py (~36KB) -- two of the most
# important files in the whole self-modification system -- are also
# over the old cap, meaning this was a latent correctness bug for real
# self-patch targets, not just an edge case. Generous, not unlimited:
# a file too large even for this ceiling gets an honest refusal instead
# of a silent truncation the model has to discover the hard way.
_MAX_PATCH_SEED_CHARS = 300_000


def read_file_for_patch(repo_root: Path, raw_path: str) -> tuple[str | None, str | None]:
    """Like safe_read_file, but for seeding a self-patch draft: the same
    path-safety validation, an untruncated read up to a much higher
    ceiling (`_MAX_PATCH_SEED_CHARS`), and a distinct, honest refusal for
    a file that's too large to safely draft a complete replacement for
    in one shot -- rather than silently truncating and letting the
    drafting LLM discover the gap on its own. Returns `(content, None)`
    on success or `(None, "refused: ...")` on failure; never raises.
    """
    target, refusal = _resolve_safe_path(repo_root, raw_path)
    if refusal is not None:
        return None, refusal
    try:
        content = target.read_text(errors="replace")
    except OSError as exc:
        return None, f"refused: could not read {raw_path!r}: {exc!r}"

    if len(content) > _MAX_PATCH_SEED_CHARS:
        return None, (
            f"refused: {raw_path!r} is {len(content)} chars, over the "
            f"{_MAX_PATCH_SEED_CHARS}-char self-patch limit -- too large to safely "
            "draft a complete replacement for in one shot"
        )
    return content, None


_MAX_LIST_ENTRIES = 300


def safe_list_dir(repo_root: Path, raw_path: str) -> str:
    """List the immediate entries under `raw_path`, subject to the exact
    same boundary as safe_read_file (confined to src/docs/tests, no
    traversal, never raises). An empty path or "." lists the allowed
    top-level roots themselves.

    Caught live: asked to "read your code base and point to gaps in
    your design," Sim's only way to see what files even exist was RUN
    (a sandboxed `os.listdir`) -- but SubprocessSandbox executes in an
    isolated temp directory, not the real repository, so every attempt
    saw nothing and Sim fumbled through several failed workarounds
    before answering from memory alone. READ already lets it look inside
    a file it already knows the path to; this is the missing step
    before that -- discovering the path in the first place -- without
    granting anything READ doesn't already: still read-only, still
    confined to the same three roots, still no traversal.
    """
    raw = raw_path.strip()
    if not raw or raw == ".":
        return "\n".join(f"{name}/" for name in _ALLOWED_READ_ROOTS)

    if len(raw) > _MAX_PATH_CHARS:
        return f"[refused: path is {len(raw)} chars -- too long to be a real path]"
    try:
        rel = Path(raw)
    except ValueError as exc:
        return f"[refused: {raw!r} is not a valid path: {exc!r}]"

    if rel.is_absolute() or ".." in rel.parts:
        return f"[refused: {raw!r} is not a safe relative path]"
    if not rel.parts or rel.parts[0] not in _ALLOWED_READ_ROOTS:
        return (
            f"[refused: {raw!r} is outside the readable areas "
            f"({', '.join(_ALLOWED_READ_ROOTS)})]"
        )

    try:
        resolved_root = repo_root.resolve()
        target = (resolved_root / rel).resolve()
        if resolved_root != target and resolved_root not in target.parents:
            return f"[refused: {raw!r} resolves outside the repository]"
        if not target.is_dir():
            return f"[refused: {raw!r} is not a directory]"
        entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name))
    except OSError as exc:
        return f"[refused: could not list {raw!r}: {exc!r}]"

    names: list[str] = []
    for entry in entries:
        if entry.name.startswith(".") or entry.name == "__pycache__":
            continue
        names.append(f"{entry.name}/" if entry.is_dir() else entry.name)
        if len(names) >= _MAX_LIST_ENTRIES:
            names.append(f"... (truncated at {_MAX_LIST_ENTRIES} entries)")
            break
    return "\n".join(names) if names else "[empty directory]"


@dataclass(frozen=True)
class ToolCapabilities:
    """What a provider can actually do through this protocol: which
    markers it supports and the limits that apply to each -- so
    orchestrator logic can ask "does this provider have LIST?" or "what's
    its read ceiling?" instead of assuming every provider offers the
    same fixed marker set at this module's own hardcoded limits.

    The limits default to this module's own constants (`_MAX_READ_CHARS`
    etc.) so a provider that doesn't customize anything behaves exactly
    like the pre-negotiation code that assumed those constants applied
    universally.
    """

    markers: tuple[str, ...]
    max_read_chars: int = _MAX_READ_CHARS
    max_patch_seed_chars: int = _MAX_PATCH_SEED_CHARS
    max_list_entries: int = _MAX_LIST_ENTRIES
    max_path_chars: int = _MAX_PATH_CHARS

    def supports(self, marker: str) -> bool:
        """Case-insensitive membership check, matching how parse_marker
        itself matches markers -- so a caller can gate on `supports("read")`
        regardless of the marker's declared casing.
        """
        return marker.lower() in {m.lower() for m in self.markers}


_DEFAULT_CAPABILITIES = ToolCapabilities(markers=("read", "list", "run", "draft"))

_provider_capabilities: dict[str, ToolCapabilities] = {}


def register_capabilities(provider: str, capabilities: ToolCapabilities) -> None:
    """Record what `provider` (e.g. "anthropic", "openai") supports, so
    a later get_capabilities(provider) reflects it. Overwrites any prior
    registration for the same provider name (case-insensitive) rather
    than accumulating stale entries across re-registration.
    """
    _provider_capabilities[provider.lower()] = capabilities


def get_capabilities(provider: str | None) -> ToolCapabilities:
    """The capabilities registered for `provider`, or the fixed default
    toolset (every marker this module parses, at this module's own
    limits) if `provider` is None or was never registered -- so existing
    callers that don't participate in capability negotiation keep
    working exactly as before it existed.
    """
    if provider is None:
        return _DEFAULT_CAPABILITIES
    return _provider_capabilities.get(provider.lower(), _DEFAULT_CAPABILITIES)