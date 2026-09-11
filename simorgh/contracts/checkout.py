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

import json
import re
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
    Django's `runtests.py` takes. A label that is already a label is
    returned unchanged."""
    text = relative.strip().replace("\\", "/")
    if text.startswith("tests/"):
        text = text[len("tests/"):]
    if text.endswith(".py"):
        text = text[:-3]
    return text.strip("/").replace("/", ".")


__all__ = ["MANIFEST_NAME", "TARGET_DJANGO_LABEL", "TARGET_PATH", "ContainerCheckout",
           "container_run", "container_run_line", "django_label", "find_enclosing"]
