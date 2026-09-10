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
import time
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
# Statuses worth trying again: a gateway hiccup, a rate limit, a restart.
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
RETRY_BACKOFF_S = 1.0


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
    # A tool the machine needs before this suite can be scored at all,
    # named so `benchmark suites` can say it before someone starts a
    # hundred-case run that would skip every case.
    needs: str = ""


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
        needs="docker",
        # Scorable since 2026-09-10: `benchmark/swebench.py` copies the
        # instance's checkout out of its own image, lets the system edit
        # it, then applies the resulting diff in a fresh container and
        # runs the dataset's eval script there. Needs Docker; a run
        # without it is refused case by case, not silently zeroed.
    ),
}


def _request(url: str, *, token: str = "", timeout: float = 30.0, attempts: int = 4) -> dict:
    """One datasets-server call, retried through transient failures.

    A full suite is several pages, and the server answered 502 once
    mid-download (2026-09-08); losing the whole set to one gateway blip
    is not acceptable for something that then costs model calls to run.
    Only the transient statuses are retried -- a 401 or a 404 is an
    answer, and retrying it just wastes the operator's time."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    last = ""
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 -- fixed https endpoints
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")[:300]
            except Exception:  # noqa: BLE001
                pass
            if exc.code not in RETRY_STATUS or attempt == attempts - 1:
                raise DatasetUnavailable(_explain(exc.code, body)) from exc
            last = f"HTTP {exc.code}"
        except Exception as exc:  # noqa: BLE001 -- a dropped connection is worth one more try
            if attempt == attempts - 1:
                raise DatasetUnavailable(f"could not reach Hugging Face: {exc!r}") from exc
            last = repr(exc)
        time.sleep(RETRY_BACKOFF_S * (2 ** attempt))
    raise DatasetUnavailable(f"Hugging Face kept failing after {attempts} tries: {last}")


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
        # The repo-relative path the file lives at, which is not the
        # same as its name: `2023/validation/<name>`. Kept so the file
        # can actually be fetched -- without it a case knows a file
        # exists and not where, which is how 11 of 53 questions in the
        # 2026-09-10 run were skipped rather than answered.
        data=json.dumps({"file_path": str(row.get("file_path") or "")}),
        tools_hint=str(metadata.get("Tools") or "") if isinstance(metadata, dict) else "",
        steps_hint=steps_hint,
    )


def _swebench_case(row: dict, source: Source) -> Case:
    """One instance, with everything the container evaluator needs.

    The gold patch stays in `answer` for reading and comparison, and is
    NOT what the case is scored against: the score comes from running
    the instance's own tests, so a different but working fix counts."""
    return Case(
        id=str(row.get("instance_id") or "")[:80],
        question=str(row.get("problem_statement") or "").strip(),
        answer=str(row.get("patch") or "").strip(),
        level=str(row.get("difficulty") or "").strip(),
        suite=source.name,
        mode="swebench",
        tools_hint=str(row.get("repo") or ""),
        data=json.dumps({
            "instance_id": str(row.get("instance_id") or ""),
            "image": str(row.get("image") or ""),
            "eval_script": str(row.get("eval_script") or ""),
            "log_parser": str(row.get("log_parser") or ""),
            "repo": str(row.get("repo") or ""),
            "base_commit": str(row.get("base_commit") or ""),
            "FAIL_TO_PASS": row.get("FAIL_TO_PASS"),
            "PASS_TO_PASS": row.get("PASS_TO_PASS"),
        }),
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
#: Where a dataset's own files live. `resolve` serves the bytes; the
#: rows API only ever names them.
FILE_URL = "https://huggingface.co/datasets/{dataset}/resolve/main/{path}"


def fetch_attachment(source: Source, case, *, dest: Path, token: str | None = None,
                     timeout: float = 60.0) -> tuple[Path | None, str]:
    """Download the file a question is about. `(path, problem)`.

    A GAIA question like "what is the total in this spreadsheet" is
    unanswerable without the spreadsheet, and 11 of the 53 cases in the
    2026-09-10 run were skipped for exactly that reason -- a fifth of
    the suite unreachable by construction. The rows carry the path; this
    fetches it.

    Written under `dest` with mode 0600 and never inside the repository
    tree by default, for the same reason the row cache is: GAIA's terms
    forbid resharing the set.
    """
    path = ""
    payload = getattr(case, "payload", None)
    if callable(payload):
        path = str((payload() or {}).get("file_path") or "")
    if not path:
        return None, ("this case names an attached file but not where it lives -- reload the "
                      f"suite (`benchmark load {source.name}`), which now records the path")
    token = os.environ.get("HF_TOKEN", "") if token is None else token
    if source.gated and not token:
        return None, f"{source.name} is gated: set HF_TOKEN to fetch the file this question is about"

    target = Path(dest) / Path(path).name
    if target.is_file() and target.stat().st_size:
        return target, ""      # already fetched, by an earlier run or an earlier case
    url = FILE_URL.format(dataset=urllib.parse.quote(source.dataset),
                          path=urllib.parse.quote(path))
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"} if token else {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        return None, f"the attached file could not be fetched (HTTP {exc.code})"
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return None, f"the attached file could not be fetched ({exc!r})"
    if not body:
        return None, "the attached file came back empty"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        target.chmod(0o600)
    except OSError as exc:
        return None, f"the attached file could not be written ({exc!r})"
    return target, ""


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
    "DEFAULT_CACHE", "FILE_URL", "DatasetUnavailable", "SOURCES", "Source", "cache_path",
    "fetch_attachment", "fetch_rows",
    "known", "load", "load_cached", "revision", "save", "to_suite",
]
