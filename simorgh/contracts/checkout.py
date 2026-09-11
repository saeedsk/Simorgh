"""A checkout whose tests live in a container, described where every
subsystem can read it.

The SWE-bench runner copies an instance's `/testbed` out of its Docker
image into `workspace/swebench/<id>/` and asks Sim to fix the bug there.
That tree's dependencies -- compiled extensions, pinned packages, the
conda env -- exist only inside the image. So `run_tests` on a path in
it could never work on the host, and in the first real run Sim burned
step after step on `refused: '...test_connect.py' does not exist` (the
tool resolved the path against Simorgh's own repo) and
`git_commit: nothing_to_commit` (`workspace/` is gitignored, so from
Simorgh's repo the checkout's changes are invisible) before working
around both with `run_shell` (2026-09-10).

This file is the wire between the two sides. Benchmark writes a
manifest into the checkout when it materialises it; Execution's
`run_tests` finds the manifest above the target and runs the project's
own test command inside the project's own container, and its git tools
operate on the nested repository the path actually belongs to. Neither
package may import the other, and both may import here.

Stdlib only, like the rest of Contracts.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

#: Sits at the checkout's root. Dot-prefixed so it is not source, and
#: named for its owner so nothing mistakes it for the project's own.
MANIFEST_NAME = ".simorgh-checkout.json"

#: How `run_tests` should turn a path into what the test command wants.
TARGET_PATH = "path"            # pytest: hand the path over as-is
TARGET_DJANGO_LABEL = "django_label"  # runtests.py: `tests/a/b.py` -> `a.b`


@dataclass(frozen=True)
class ContainerCheckout:
    """Everything needed to run this checkout's tests where they can run.

    `setup` is the shell prelude that makes the project importable
    inside the container (activate the env, `cd` to the tree, whatever
    the image's own eval script does before it tests). `test_command`
    is that script's test line with its targets removed, so a caller
    appends its own.
    """

    image: str
    platform: str
    workdir: str
    base_commit: str
    setup: str
    test_command: str
    target_style: str = TARGET_PATH
    #: The commit that IS the tree Sim was handed (`record_pristine`),
    #: or "" for a manifest written before it existed. An image's tree
    #: is not its base commit: SWE-bench's environment setup edits files
    #: (astropy's `pyproject.toml`), and a diff against the base commit
    #: carries those edits as if Sim had made them -- in the second live
    #: run the scorer's `git apply` refused that hunk and `patch --fuzz`
    #: then "Assuming -R" silently REVERSED the image's own change
    #: (2026-09-10). Every diff of what Sim did is taken against this.
    pristine: str = ""

    @property
    def diff_base(self) -> str:
        return self.pristine or self.base_commit

    def write(self, checkout: Path) -> None:
        (checkout / MANIFEST_NAME).write_text(json.dumps(asdict(self), indent=2) + "\n")

    @classmethod
    def read(cls, checkout: Path) -> "ContainerCheckout | None":
        """The manifest at `checkout`, or None when there is none or it
        cannot be read -- a checkout without one is an ordinary
        directory, and a broken one must not become a crash in a tool."""
        try:
            data = json.loads((checkout / MANIFEST_NAME).read_text())
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        try:
            return cls(
                image=str(data["image"]), platform=str(data.get("platform", "")),
                workdir=str(data["workdir"]), base_commit=str(data.get("base_commit", "")),
                setup=str(data.get("setup", "")), test_command=str(data["test_command"]),
                target_style=str(data.get("target_style", TARGET_PATH)),
                pristine=str(data.get("pristine", "")),
            )
        except (KeyError, TypeError):
            return None


def find_enclosing(root: Path, relative: str) -> tuple[Path, str] | None:
    """`(checkout, path relative to it)` for the nearest manifest-bearing
    ancestor of `root/relative`, strictly below `root`; else None.

    The root itself is never a checkout: Simorgh's own repository has
    no manifest and must never be treated as somebody else's tree.
    """
    root = root.resolve()
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    for candidate in [target, *target.parents]:
        if candidate == root:
            return None
        if (candidate / MANIFEST_NAME).is_file():
            return candidate, target.relative_to(candidate).as_posix()
    return None


#: The first line of `run_tests`' output when it ran inside a checkout's
#: container. `verification/checks/fullsuiteran.py` reads it back: a
#: change that lives in somebody else's project is checked by that
#: project's tests, and Simorgh's own suite has nothing to say about it.
_CONTAINER_RUN = re.compile(r"\[ran '(?P<target>.+?)' inside image (?P<image>\S+)\]")


def container_run_line(target: str, image: str) -> str:
    return f"[ran {target!r} inside image {image}]"


def container_run(summary: str) -> tuple[str, str] | None:
    """`(target, image)` when `summary` records a run inside a container."""
    match = _CONTAINER_RUN.search(summary or "")
    return (match.group("target"), match.group("image")) if match else None


def django_label(relative: str) -> str:
    """`tests/test_utils/tests.py` -> `test_utils.tests`, the shape
    Django's `runtests.py` takes, and `tests/a/tests.py::Cls::test_x`
    -> `a.tests.Cls.test_x` -- a pytest node id was handed through with
    its `::` intact and runtests.py could make nothing of it (measured
    against the real django image, 2026-09-10). A label that is already
    a label is returned unchanged."""
    text = relative.strip().replace("\\", "/")
    path, _, rest = text.partition("::")
    if path.startswith("tests/"):
        path = path[len("tests/"):]
    if path.endswith(".py"):
        path = path[:-3]
    label = path.strip("/").replace("/", ".")
    if rest:
        label = ".".join([label, *[part for part in rest.split("::") if part]])
    return label



def staged_diff(checkout: Path, base: str = "", *, exclude: tuple[str, ...] = (),
                timeout: float = 120.0) -> tuple[str, str]:
    """`(patch, problem)`: everything `checkout` differs from `base` by --
    committed or not, tracked or untracked -- with `exclude` pathspecs
    left out. Against `base` when the checkout carries that commit, else
    against HEAD.

    Read through a PRIVATE index (`GIT_INDEX_FILE`), never the
    checkout's own. Both readers of this diff used to `git add -A` in
    the real index first, and two of them at once -- two `run_tests`
    in flight on one checkout, measured 2026-09-10 -- collided on
    `.git/index.lock`: one came back "could not stage the checkout" for
    a tree that was fine. A private index has no lock to fight over and
    leaves the checkout's staging area exactly as Sim left it.

    `core.fileMode=false` throughout: a materialised tree can be 777
    against an index of 644 (astropy-14995's image is), and a mode
    flip on every file is not a change.
    """
    git = shutil.which("git")
    if not git:
        return "", "git is not installed"
    with tempfile.TemporaryDirectory(prefix="simorgh-index-") as tmp:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(tmp) / "index"))

        def run(*cmd: str) -> subprocess.CompletedProcess:
            return subprocess.run([git, "-C", str(checkout), "-c", "core.fileMode=false", *cmd],
                                  capture_output=True, text=True, timeout=timeout,
                                  stdin=subprocess.DEVNULL, env=env)

        try:
            # Seed the private index from HEAD FIRST. An empty index plus
            # `core.fileMode=false` re-adds every file as 644 -- there
            # is no existing entry whose mode git could keep -- and the
            # patch then strips the executable bit from everything that
            # had one. Measured against the real django image before
            # this line existed: `tests/runtests.py` arrived as 100644
            # and every in-container run died `Permission denied`,
            # exit 126 (2026-09-10). With HEAD's modes in the index,
            # `add -A` keeps them and only content changes remain.
            run("read-tree", "HEAD")
            if run("add", "-A").returncode != 0:
                return "", "could not stage the checkout"
            against = []
            if base and run("rev-parse", "--verify", "--quiet", f"{base}^{{commit}}").returncode == 0:
                against = [base]
            diff = run("diff", "--cached", "--binary", *against, "--", ".",
                       *[f":(exclude){pattern}" for pattern in exclude])
        except (OSError, subprocess.SubprocessError) as exc:
            return "", f"could not read the checkout's diff: {exc!r}"
    if diff.returncode != 0:
        return "", f"could not read the checkout's diff: {(diff.stderr or '').strip()[:300]}"
    return diff.stdout, ""


def record_pristine(checkout: Path, base: str = "", *, timeout: float = 120.0) -> str:
    """Commit the checkout's working tree as it stands -- on no branch,
    under `refs/simorgh/pristine`, through a private index -- and return
    the commit id, or "" when git cannot. Called by the benchmark right
    after it copies an image's tree out, BEFORE the manifest is written,
    so the commit is exactly the tree Sim is handed and every later diff
    of "what did Sim change" has an honest zero to start from."""
    git = shutil.which("git")
    if not git or not (checkout / ".git").exists():
        return ""
    with tempfile.TemporaryDirectory(prefix="simorgh-index-") as tmp:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(tmp) / "index"),
                   GIT_AUTHOR_NAME="simorgh", GIT_AUTHOR_EMAIL="simorgh@localhost",
                   GIT_COMMITTER_NAME="simorgh", GIT_COMMITTER_EMAIL="simorgh@localhost")

        def run(*cmd: str) -> subprocess.CompletedProcess:
            return subprocess.run([git, "-C", str(checkout), "-c", "core.fileMode=false", *cmd],
                                  capture_output=True, text=True, timeout=timeout,
                                  stdin=subprocess.DEVNULL, env=env)

        try:
            run("read-tree", "HEAD")
            if run("add", "-A").returncode != 0:
                return ""
            tree = run("write-tree")
            if tree.returncode != 0:
                return ""
            parents: list[str] = []
            if base and run("rev-parse", "--verify", "--quiet", f"{base}^{{commit}}").returncode == 0:
                parents = ["-p", base]
            commit = run("commit-tree", tree.stdout.strip(), *parents, "-m", "simorgh: the tree as materialised")
            if commit.returncode != 0:
                return ""
            sha = commit.stdout.strip()
            run("update-ref", "refs/simorgh/pristine", sha)
        except (OSError, subprocess.SubprocessError):
            return ""
    return sha

# -- What a container run has to cover -----------------------------------
#
# `verification/checks/fullsuiteran.py` used to accept ANY passing run
# inside the checkout's image as proof of the change. Live, 2026-09-10:
# Sim changed one module, ran an unrelated test file, that file passed,
# and a change that broke 28 tests in the module it had edited was
# accepted and committed. "The project's own tests ran and passed" was
# true and said nothing about the change.
#
# What changed is read from the checkout's own git against the
# manifest's base commit -- exactly what the scorer will diff -- and not
# from the session's `written_paths`: an edit made with `run_shell` and
# `sed -i` never reports a `file_write` side effect, and a change the
# scorer will see is one the verifier must see too.

_TEST_DIRS = frozenset({"tests", "test", "testing"})
_SOURCE_ROOTS = frozenset({"src", "lib"})


def is_test_path(relative: str) -> bool:
    """A test file, or anything under a tests directory. Excluded from
    "what changed" for the same reason `swebench.diff_of` drops it: the
    scorer restores the tests before it runs, so a test edit is not part
    of the answer and cannot be what a test run was meant to cover."""
    parts = [p for p in relative.replace("\\", "/").split("/") if p]
    if not parts:
        return False
    name = parts[-1]
    return (
        any(p in _TEST_DIRS for p in parts[:-1])
        or name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"
    )


def changed_sources(checkout: Path, base: str = "", *, timeout: float = 60.0) -> tuple[str, ...] | None:
    """Checkout-relative paths of the Python source files the checkout
    differs from `base` by -- committed or not, staged or not, new or
    edited -- with tests and the manifest left out.

    None means "no opinion": no git, not a repository, or git would not
    answer. A caller treats that as "cannot tell", never as "nothing
    changed"."""
    git = shutil.which("git")
    if not git or not (checkout / ".git").exists():
        return None

    def run(*cmd: str) -> subprocess.CompletedProcess:
        # `core.fileMode=false`: a materialised tree is 755 against an
        # index of 644, and a mode flip is not a change to cover.
        return subprocess.run([git, "-C", str(checkout), "-c", "core.fileMode=false", *cmd],
                              capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)

    try:
        against = "HEAD"
        if base and run("rev-parse", "--verify", "--quiet", f"{base}^{{commit}}").returncode == 0:
            against = base
        tracked = run("diff", "--name-only", against, "--", ".")
        untracked = run("ls-files", "--others", "--exclude-standard")
    except (OSError, subprocess.SubprocessError):
        return None
    if tracked.returncode != 0 or untracked.returncode != 0:
        return None
    found: list[str] = []
    for line in tracked.stdout.splitlines() + untracked.stdout.splitlines():
        name = line.strip()
        if not name or name == MANIFEST_NAME or not name.endswith(".py") or is_test_path(name):
            continue
        if name not in found:
            found.append(name)
    return tuple(sorted(found))


def _dotted(relative: str) -> tuple[str, ...]:
    """The module names a source path can be imported as: `pkg/a/b.py`
    is `pkg.a.b`, `pkg/a/__init__.py` is `pkg.a`, and a `src/` layout
    is offered both with and without the root."""
    parts = [p for p in relative.replace("\\", "/").split("/") if p]
    if parts and parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    if parts and parts[-1] == "__init__":
        parts.pop()
    names = [".".join(parts)] if parts else []
    if len(parts) > 1 and parts[0] in _SOURCE_ROOTS:
        names.append(".".join(parts[1:]))
    return tuple(n for n in names if n)


def _owning_package(tests_dir: str) -> str | None:
    """The package a tests directory belongs to: `pkg/a/tests` -> `pkg/a`,
    `pkg/a/tests/sub` -> `pkg/a`. None when the path has no tests
    component at all."""
    parts = [p for p in tests_dir.split("/") if p and p != "."]
    for index, part in enumerate(parts):
        if part in _TEST_DIRS:
            return "/".join(parts[:index])
    return None


def _imports_of(path: Path, package: str) -> set[str]:
    """Every dotted name `path` imports, absolute; a relative import is
    resolved against `package` (the dotted package the file sits in)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".")
                anchor = anchor[: max(0, len(anchor) - (node.level - 1))]
                base = ".".join(p for p in [*anchor, base] if p)
            if base:
                names.add(base)
            for alias in node.names:
                names.add(f"{base}.{alias.name}" if base else alias.name)
    return names


def covers(target: str, changed: str, *, checkout: Path | None = None) -> bool:
    """Whether a test run of `target` (checkout-relative, a pytest path
    or node id) could have exercised the changed source file `changed`.

    True when the target is the checkout itself, a directory above the
    file, the tests directory of the file's own package or of a package
    above it (`pkg/a/tests/...` for `pkg/a/b.py`, `pkg/tests/...` too),
    or a test file that imports the changed module or the package it
    sits in. A tests directory at the checkout's root counts on its own
    or one file deep -- deeper than that (`tests/forms/...`) it is one
    app's tests among many, and only its imports can say which.

    Deliberately not "imports the top-level package": `import astropy`
    at the head of every test file would make every file cover every
    change, which is the hole this exists to close."""
    changed = changed.replace("\\", "/").strip("/")
    text = target.split("::", 1)[0].strip().replace("\\", "/").strip("/")
    if text in ("", "."):
        return True
    is_file = text.endswith(".py")
    if not is_file and (changed == text or changed.startswith(text + "/")):
        return True
    changed_dir = changed.rpartition("/")[0]
    tests_dir = text.rpartition("/")[0] if is_file else text
    owner = _owning_package(tests_dir)
    if owner is not None:
        if owner:
            if changed_dir == owner or changed_dir.startswith(owner + "/"):
                return True
        elif len([p for p in tests_dir.split("/") if p]) == 1:
            return True
    if checkout is not None and is_file:
        wanted = set()
        for name in _dotted(changed):
            wanted.add(name)
            package = name.rpartition(".")[0]
            if package:
                wanted.add(package)
        package_of_test = ".".join(p for p in tests_dir.split("/") if p)
        if wanted & _imports_of(checkout / text, package_of_test):
            return True
    return False


def suggest_target(checkout: Path, changed: str) -> str:
    """The checkout-relative test target nearest to `changed` that
    exists on disk: the closest `tests/` directory walking up from the
    file, else the file's own directory."""
    parts = [p for p in changed.replace("\\", "/").split("/") if p][:-1]
    while parts:
        for name in ("tests", "test"):
            candidate = "/".join([*parts, name])
            if (checkout / candidate).is_dir():
                return candidate
        parts.pop()
    if (checkout / "tests").is_dir():
        return "tests"
    return changed.rpartition("/")[0] or "."


__all__ = ["MANIFEST_NAME", "TARGET_DJANGO_LABEL", "TARGET_PATH", "ContainerCheckout",
           "changed_sources", "container_run", "container_run_line", "covers", "django_label",
           "find_enclosing", "is_test_path", "record_pristine", "staged_diff", "suggest_target"]
