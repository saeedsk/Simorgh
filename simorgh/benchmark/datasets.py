"""Getting a benchmark's questions onto this machine.

Everything here goes through Hugging Face's datasets-server, which
answers plain JSON over HTTPS -- so this module needs no `datasets`,
`huggingface_hub` or `pyarrow`, and Sim can pull a suite on a machine
where none of them are installed. A gated dataset needs `HF_TOKEN` in
the environment, and the token must have "access public gated
repositories" enabled in its fine-grained settings: without that, the
server answers "does not exist, or is not accessible" for a dataset you
can see in a browser (diagnosed live, 2026-09-07).

Downloaded rows are cached under `~/.simorgh/benchmarks/` as JSON, so a
run is repeatable offline and a second run costs nothing. GAIA's terms
say not to reshare the set outside a gated repository; the cache is a
local file under the operator's own home, which is why the cache path
is deliberately outside the git repository and never written into it.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .api import Case, Suite

ROWS_URL = "https://datasets-server.huggingface.co/rows"
SPLITS_URL = "https://datasets-server.huggingface.co/splits"
INFO_URL = "https://huggingface.co/api/datasets/{dataset}"
DEFAULT_CACHE = Path("~/.simorgh/benchmarks").expanduser()
# The server caps a page; ask for its maximum and page through.
PAGE = 100
USER_AGENT = "Simorgh/2.0 (benchmark harness)"


class DatasetUnavailable(RuntimeError):
    """The rows could not be fetched -- with the reason a human can act on."""


@dataclass(frozen=True)
class Source:
    """Where one suite's rows live, and how to read a row as a `Case`."""

    name: str
    dataset: str
    config: str
    split: str
    description: str = ""
    gated: bool = False
    # A suite we can load but cannot yet score honestly (SWE-bench needs
    # containerised test execution). Loading it is still useful -- the
    # questions are real, and `benchmark load` proves the pipeline --
    # but `benchmark run` refuses rather than inventing a number.
    scorable: bool = True
    why_not_scorable: str = ""


SOURCES: dict[str, Source] = {
    "gaia": Source(
        name="gaia", dataset="gaia-benchmark/GAIA", config="2023_all", split="validation",
        description="General AI Assistants: tool-using questions in three difficulty levels",
        gated=True,
    ),
    "gaia-l1": Source(
        name="gaia-l1", dataset="gaia-benchmark/GAIA", config="2023_level1", split="validation",
        description="GAIA Level 1 only -- the cheapest useful signal", gated=True,
    ),
    "bfcl-parallel": Source(
        name="bfcl-parallel", dataset="OpenMLRL/BFCL-V4-Parallel-Native", config="default", split="test",
        description="Berkeley Function-Calling: pick the right functions and arguments, several per request",
    ),
    "swebench-verified": Source(
        name="swebench-verified", dataset="SWE-bench/SWE-bench_Verified", config="default", split="test",
        description="500 human-validated GitHub issues with test-verified patches",
        scorable=False,
        why_not_scorable=(
            "scoring SWE-bench means applying the patch and running FAIL_TO_PASS tests in the "
            "instance's own container; `benchmark load swebench-verified` fetches the cases, "
            "and a real evaluator is the next piece of work"
        ),
    ),
}


def _request(url: str, *, token: str = "", timeout: float = 30.0) -> dict:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 -- fixed https endpoints
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:  # noqa: BLE001
            pass
        raise DatasetUnavailable(_explain(exc.code, body)) from exc
    except Exception as exc:  # noqa: BLE001
        raise DatasetUnavailable(f"could not reach Hugging Face: {exc!r}") from exc


def _explain(code: int, body: str) -> str:
    """Turn an HTTP failure into the thing the operator must actually do."""
    if "enable access to public gated repositories" in body or (code == 403 and "gated" in body):
        return (
            "the HF token cannot read gated repositories: open "
            "https://huggingface.co/settings/tokens, edit this token, and tick "
            "'Read access to contents of all public gated repos you can access'"
        )
    if code in (401, 403) or "not accessible with the current credentials" in body:
        return (
            "no access to this dataset: set HF_TOKEN, accept the dataset's terms on its "
            "Hugging Face page, and give the token gated-repository read access"
        )
    if code == 404:
        return "no such dataset, config or split on Hugging Face"
    return f"Hugging Face answered HTTP {code}: {body}"


def revision(dataset: str, *, token: str = "") -> str:
    try:
        info = _request(INFO_URL.format(dataset=urllib.parse.quote(dataset)), token=token)
    except DatasetUnavailable:
        return "unknown"
    return str(info.get("sha") or "unknown")[:12]


def fetch_rows(source: Source, *, token: str = "", limit: int = 0, timeout: float = 30.0) -> list[dict]:
    """Every row (or the first `limit`), paged through the rows API."""
    rows: list[dict] = []
    offset = 0
    while True:
        want = PAGE if limit <= 0 else min(PAGE, limit - len(rows))
        if want <= 0:
            break
        url = (
            f"{ROWS_URL}?dataset={urllib.parse.quote(source.dataset, safe='')}"
            f"&config={urllib.parse.quote(source.config)}&split={urllib.parse.quote(source.split)}"
            f"&offset={offset}&length={want}"
        )
        payload = _request(url, token=token, timeout=timeout)
        page = [entry.get("row", {}) for entry in payload.get("rows", [])]
        rows.extend(page)
        total = int(payload.get("num_rows_total") or 0)
        offset += len(page)
        if not page or (total and offset >= total):
            break
    return rows


# ------------------------------------------------------------ row -> Case
def _gaia_case(row: dict, source: Source) -> Case:
    metadata = row.get("Annotator Metadata") or {}
    steps = metadata.get("Number of steps") if isinstance(metadata, dict) else None
    try:
        steps_hint = int(str(steps).strip())
    except (TypeError, ValueError):
        steps_hint = 0
    attachment = row.get("file_name") or ""
    if isinstance(attachment, dict):  # the rows API returns a file object for some rows
        attachment = attachment.get("path") or attachment.get("src") or ""
    return Case(
        id=str(row.get("task_id") or "")[:64],
        question=str(row.get("Question") or "").strip(),
        answer=str(row.get("Final answer") or "").strip(),
        level=str(row.get("Level") or "").strip(),
        suite=source.name,
        attachment=str(attachment),
        tools_hint=str(metadata.get("Tools") or "") if isinstance(metadata, dict) else "",
        steps_hint=steps_hint,
    )


def _swebench_case(row: dict, source: Source) -> Case:
    return Case(
        id=str(row.get("instance_id") or "")[:80],
        question=str(row.get("problem_statement") or "").strip(),
        # The "answer" is a patch verified by tests, not a string to
        # match. Kept so the case is complete; scoring it means running
        # the tests, which is why this suite is not `scorable` yet.
        answer=str(row.get("patch") or "").strip(),
        level=str(row.get("difficulty") or "").strip(),
        suite=source.name,
        tools_hint=str(row.get("repo") or ""),
    )


def _bfcl_case(row: dict, source: Source) -> Case:
    functions = row.get("function")
    ground_truth = row.get("ground_truth")
    return Case(
        id=str(row.get("id") or "")[:80],
        question=str(row.get("user_prompt") or "").strip(),
        answer=ground_truth if isinstance(ground_truth, str) else json.dumps(ground_truth),
        level=str(row.get("official_category") or "").strip(),
        suite=source.name,
        mode="bfcl",
        functions=functions if isinstance(functions, str) else json.dumps(functions),
        tools_hint=str(row.get("task_type") or ""),
    )


_PARSERS = {
    "gaia": _gaia_case, "gaia-l1": _gaia_case,
    "bfcl-parallel": _bfcl_case, "swebench-verified": _swebench_case,
}


def to_suite(source: Source, rows: list[dict], *, version: str = "unknown") -> Suite:
    parse = _PARSERS.get(source.name, _gaia_case)
    cases = tuple(case for case in (parse(row, source) for row in rows) if case.id and case.question)
    return Suite(name=source.name, cases=cases, version=version, description=source.description)


# --------------------------------------------------------------- caching
def cache_path(source: Source, cache_dir: Path | None = None) -> Path:
    root = Path(cache_dir) if cache_dir else DEFAULT_CACHE
    return root / f"{source.name}.json"


def save(suite: Suite, source: Source, rows: list[dict], cache_dir: Path | None = None) -> Path:
    path = cache_path(source, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": suite.version, "rows": rows}), encoding="utf-8")
    try:
        path.chmod(0o600)  # GAIA's terms: keep the local copy to this operator
    except OSError:  # pragma: no cover -- a filesystem without modes
        pass
    return path


def load_cached(source: Source, cache_dir: Path | None = None) -> Suite | None:
    path = cache_path(source, cache_dir)
    if not path.is_file():
        return None
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return to_suite(source, blob.get("rows") or [], version=blob.get("version", "unknown"))


def load(name: str, *, token: str | None = None, refresh: bool = False, limit: int = 0,
         cache_dir: Path | None = None, timeout: float = 30.0) -> Suite:
    """The suite named `name`, from cache when we have it.

    Raises `DatasetUnavailable` with an actionable message rather than
    returning an empty suite: a benchmark that silently scores zero
    cases is worse than one that says it could not start."""
    source = SOURCES.get(name)
    if source is None:
        raise DatasetUnavailable(f"no such benchmark {name!r}; known: {', '.join(sorted(SOURCES))}")
    if not refresh:
        cached = load_cached(source, cache_dir)
        if cached is not None and len(cached):
            return cached.sample(limit) if limit else cached
    token = os.environ.get("HF_TOKEN", "") if token is None else token
    if source.gated and not token:
        raise DatasetUnavailable(
            f"{name} is gated: set HF_TOKEN (and give the token gated-repository read access)"
        )
    rows = fetch_rows(source, token=token, limit=limit, timeout=timeout)
    if not rows:
        raise DatasetUnavailable(f"{name}: Hugging Face returned no rows")
    suite = to_suite(source, rows, version=revision(source.dataset, token=token))
    save(suite, source, rows, cache_dir)
    return suite


def known() -> list[Source]:
    return [SOURCES[name] for name in sorted(SOURCES)]


__all__ = [
    "DEFAULT_CACHE", "DatasetUnavailable", "SOURCES", "Source", "cache_path", "fetch_rows",
    "known", "load", "load_cached", "revision", "save", "to_suite",
]
