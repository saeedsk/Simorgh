"""Internal types verification's own modules share -- never imported by
another subsystem (docs/blueprint/subsystems/10-verification.md section
3.4). `Check` is the plugin shape every mechanical check implements;
`CheckContext` is what a check is given to reach the outside world
(propose an action and await its result, ask cognition a question, ask
guardian to review code) without importing anything but this package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Literal, Protocol


class Rigor(Enum):
    NONE = "none"
    LIGHT = "light"
    STANDARD = "standard"
    FULL = "full"

    def __ge__(self, other: "Rigor") -> bool:  # NONE < LIGHT < STANDARD < FULL
        order = [Rigor.NONE, Rigor.LIGHT, Rigor.STANDARD, Rigor.FULL]
        return order.index(self) >= order.index(other)

    def __lt__(self, other: "Rigor") -> bool:
        return not self.__ge__(other)


@dataclass(frozen=True)
class VerifyRequest:
    """The resolved form of a `verify.requested` message: `subject_ref`
    has already been read from the blob store into `subject` (an
    arbitrary dict a check looks up keys from -- e.g. `path`, `original`,
    `candidate`/`code`, `result`, `description`) so a check never touches
    the Ledger directly.
    """

    verification_id: str
    task_id: str
    kind: str  # task | plan | self_patch | skill  (the wire enum, contracts/schema/verify.requested.v1.json)
    subject: dict[str, Any]
    checklist_hint: str | None = None
    reversibility: str = "reversible"  # read_only | reversible | irreversible


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    output: str = ""
    output_ref: str = ""
    error: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ReviewReply:
    approved: bool
    reasons: tuple[str, ...] = ()
    layers_run: tuple[str, ...] = ()
    ok: bool = True  # False = guardian never answered (floor)


@dataclass(frozen=True)
class ThinkReply:
    text: str
    floor: bool = False
    non_answer: bool = False
    ok: bool = True


@dataclass(frozen=True)
class FailedItem:
    question: str
    evidence: str
    suggestion: str


@dataclass(frozen=True)
class Feedback:
    failed_items: tuple[FailedItem, ...] = ()
    mechanical_errors: tuple[str, ...] = ()
    revise_hint: str = ""
    retryable: bool = True

    def to_payload(self) -> dict:
        return {
            "failed_items": [
                {"question": i.question, "evidence": i.evidence, "suggestion": i.suggestion}
                for i in self.failed_items
            ],
            "mechanical_errors": list(self.mechanical_errors),
            "revise_hint": self.revise_hint,
            "retryable": self.retryable,
        }


@dataclass(frozen=True)
class CheckResult:
    status: Literal["passed", "failed", "skipped", "insufficient"]
    detail: str = ""
    evidence: dict = field(default_factory=dict)
    feedback: Feedback | None = None


@dataclass(frozen=True)
class CheckContext:
    act: Callable[..., Awaitable[ActionResult]]
    think: Callable[..., Awaitable[ThinkReply]]
    review: Callable[[str, str, str], Awaitable[ReviewReply]]  # subject, code, kind
    clock: Any
    config: "VerificationConfig"  # noqa: F821 -- forward ref, defined in config.py


class Check(Protocol):
    name: str
    cost: Literal["free", "cheap", "expensive"]

    def applies(self, req: VerifyRequest) -> bool: ...

    async def run(self, req: VerifyRequest, ctx: CheckContext) -> CheckResult: ...
