"""The crew's data model as A2A's (stage 18 item 8), both ways, pure.

Inside one Sim, crew members talk over the in-process Bus. The shapes
they exchange are A2A's, so a member can be a remote A2A agent and a Sim
agent can be served to a remote caller without glue
(docs/plan/stage-18-agent-crews.md, "Interoperability"):

- a member's status is an A2A task state (`waiting` = `input-required`);
- a `crew.message` is an A2A `Message` with parts (text; data; a ref as
  a file part's url);
- a member with its `Report` is an A2A `Task` whose one artifact,
  `report`, holds the summary as a text part, the rest of the report as
  a data part, and each artifact ref as a file part.

Everything Sim knows that A2A has no field for rides in `metadata.simorgh`,
so a round trip through either version is exact. A Task or Message from
an agent that is not Sim has no such metadata; it is read by its A2A
fields alone (see `from_a2a_task`).

The readers trust `metadata.simorgh` only when the caller says
`trusted=True`. Anything that came over the wire -- a remote agent's
Task, a remote caller's Message, another Sim's -- is read untrusted,
because the remote side writes that metadata too: trusted, it could
name itself `patch`, give itself a budget, claim a parent, or send a
`steer` from the root to a sibling. Untrusted, the member's agent,
parent, depth, budget, policy and isolation are the caller's, the
report is held to its caps, and a message's sender and recipient come
from its role and the `handle` the caller holds for that remote member.

Two wire versions, pinned by the vendored schemas in
`tests/simorgh/contracts/fixtures/a2a/`: `1.0` (v1.0.1, the default:
`TASK_STATE_*` and `ROLE_*` enums, parts told apart by which field is
set) and `0.3` (v0.3.0: `kind` discriminators, `input-required`). The
readers accept both without being told which.

No IO, no SDK: the official `a2a-sdk` speaks these same dicts, and the
transport (stage 18 items 9-10) lives in execution and interface.
"""

from __future__ import annotations

import json
from typing import Any

from .messages.crew import (
    FINDINGS_MAX,
    MEMBER_STATUS,
    MESSAGE_KIND,
    REPORT_STATUS,
    SUMMARY_MAX,
    CrewMessage,
    Member,
    MemberBudget,
    Report,
)

A2A_VERSIONS = ("1.0", "0.3")
A2A_DEFAULT_VERSION = "1.0"
#: The metadata key every Sim-written Task, Message and Part carries.
META_KEY = "simorgh"
REPORT_ARTIFACT = "report"

#: Member status -> A2A v0.3 task state. v1.0 is the same word as
#: `TASK_STATE_<UPPER_SNAKE>`. `blocked` (Sim cannot go on: a missing
#: SDK, a refused scheme) is A2A's `rejected`; reading back, `rejected`
#: and `auth-required` are both `blocked`.
_STATE_OF: dict[str, str] = {
    "starting": "submitted",
    "running": "working",
    "waiting": "input-required",
    "done": "completed",
    "failed": "failed",
    "blocked": "rejected",
    "cancelled": "canceled",
}
_STATUS_OF: dict[str, str] = {
    **{state: status for status, state in _STATE_OF.items()},
    "auth-required": "blocked",
    "unknown": "running",
    "unspecified": "running",
}
#: v1.0's proto enum numbers, which its schema also admits on the wire.
_STATE_NUMBERS = ("unspecified", "submitted", "working", "completed", "failed", "canceled",
                  "input-required", "rejected", "auth-required")
#: A foreign Task's report status, from its state alone.
_REPORT_STATUS_OF = {"completed": "ok", "failed": "failed", "canceled": "cancelled",
                     "rejected": "blocked", "auth-required": "blocked"}
#: Message kinds the working member says (A2A role `agent`); the rest are
#: said TO a working member (role `user`).
_AGENT_KINDS = frozenset({"progress", "milestone", "question", "report"})


def _check_version(version: str) -> str:
    if version not in A2A_VERSIONS:
        raise ValueError(f"A2A version {version!r} is not one of {', '.join(A2A_VERSIONS)}")
    return version


# --- states -------------------------------------------------------------------


def task_state(status: str, version: str = A2A_DEFAULT_VERSION) -> str:
    """A member status as an A2A task state in `version`'s spelling."""
    _check_version(version)
    try:
        state = _STATE_OF[status]
    except KeyError:
        raise ValueError(f"member status {status!r} is not one of {', '.join(MEMBER_STATUS)}") from None
    return state if version == "0.3" else "TASK_STATE_" + state.upper().replace("-", "_")


def _plain_state(state: Any) -> str:
    """Any A2A spelling of a state -> the v0.3 word (`input-required`)."""
    if isinstance(state, bool):
        return "unknown"
    if isinstance(state, int):
        return _STATE_NUMBERS[state] if 0 <= state < len(_STATE_NUMBERS) else "unknown"
    text = str(state or "").strip()
    if text.upper().startswith("TASK_STATE_"):
        text = text[len("TASK_STATE_"):]
    return text.lower().replace("_", "-") or "unknown"


def member_status(state: Any) -> str:
    """An A2A task state, in either version (or as v1.0's enum number), as
    a member status. A state this does not know reads as `running`."""
    return _STATUS_OF.get(_plain_state(state), "running")


# --- parts --------------------------------------------------------------------


def _text_part(text: str, version: str) -> dict:
    return {"kind": "text", "text": text} if version == "0.3" else {"text": text}


def _data_part(data: dict, version: str, tag: str = "") -> dict:
    meta = {"metadata": {META_KEY: tag}} if tag else {}
    if version == "0.3":
        return {"kind": "data", "data": data, **meta}
    return {"data": data, "mediaType": "application/json", **meta}


def _file_part(ref: str, version: str) -> dict:
    return {"kind": "file", "file": {"uri": ref}} if version == "0.3" else {"url": ref}


def _read_part(part: Any) -> tuple[str, Any, str]:
    """(`text` | `data` | `file` | `other`, the value, the part's Sim tag)."""
    if not isinstance(part, dict):
        return "other", None, ""
    meta = part.get("metadata")
    tag = meta.get(META_KEY, "") if isinstance(meta, dict) else ""
    kind = part.get("kind")
    if kind == "text" or (kind is None and "text" in part):
        return "text", str(part.get("text", "")), tag
    if kind == "data" or (kind is None and "data" in part):
        return "data", part.get("data"), tag
    if kind == "file":
        f = part.get("file") if isinstance(part.get("file"), dict) else {}
        return ("file", str(f["uri"]), tag) if f.get("uri") else ("other", None, tag)
    if kind is None and part.get("url"):
        return "file", str(part["url"]), tag
    return "other", None, tag


def _meta(obj: dict) -> dict:
    meta = obj.get("metadata")
    sim = meta.get(META_KEY) if isinstance(meta, dict) else None
    return sim if isinstance(sim, dict) else {}


def _payload(value: Any) -> dict:
    return value.to_payload() if hasattr(value, "to_payload") else dict(value)


def _clip(text: str) -> str:
    """A foreign summary cut to the Report's cap. The rest is not lost on
    purpose: the caller has the whole Task and may store it as a blob."""
    return text if len(text) <= SUMMARY_MAX else text[: SUMMARY_MAX - 1] + "…"


def _bounded(report: Report, state_status: str) -> Report:
    """An untrusted report held to the Report's own rules: the summary
    cut to its cap, at most FINDINGS_MAX findings, and a status the
    vocabulary knows (else the one the task's state implies)."""
    return Report(
        status=report.status if report.status in REPORT_STATUS else state_status,
        summary=_clip(report.summary), findings=report.findings[:FINDINGS_MAX],
        artifacts=report.artifacts, steps=report.steps, tokens=report.tokens,
        cost_usd=report.cost_usd, wall_s=report.wall_s,
        questions_unanswered=report.questions_unanswered)


# --- Task <-> member + report ---------------------------------------------------


def to_a2a_task(member: Member | dict, report: Report | dict | None = None, *,
                version: str = A2A_DEFAULT_VERSION) -> dict:
    """A crew member, and its report when it has one, as an A2A `Task`."""
    _check_version(version)
    m = member if isinstance(member, Member) else Member.from_dict(member)
    sim = m.to_dict()
    for key in ("handle", "crew_id"):
        sim.pop(key)
    task: dict = {
        "id": m.handle,
        "contextId": m.crew_id,
        "status": {"state": task_state(m.status, version)},
        "metadata": {META_KEY: sim},
    }
    if report is not None:
        r = report if isinstance(report, Report) else Report.from_dict(report)
        rest = r.to_dict()
        rest.pop("summary")
        refs = rest.pop("artifacts")
        parts = [_text_part(r.summary, version), _data_part(rest, version, tag=REPORT_ARTIFACT)]
        parts += [_file_part(ref, version) for ref in refs]
        task["artifacts"] = [{"artifactId": f"{m.handle}:{REPORT_ARTIFACT}", "name": REPORT_ARTIFACT,
                              "parts": parts}]
    if version == "0.3":
        task["kind"] = "task"
    return task


def from_a2a_task(task: dict, *, crew_id: str = "", parent: str = "", handle: str = "",
                  trusted: bool = False) -> tuple[Member, Report | None]:
    """An A2A `Task` as a member and its report.

    With `trusted=True`, a Task Sim wrote reads back exactly. Otherwise
    `metadata.simorgh` decides nothing about the member (module
    docstring): the handle is `handle` (else the task id), the crew is
    `crew_id` (else the contextId), and the report Sim's artifact carries
    is held to its caps. A foreign Task: the agent is
    `a2a`, the parent is `parent`, the status comes from the state, and
    the report -- present once the task is terminal or has artifacts --
    has the state's report status, every text part of every artifact as
    its summary (cut to the cap; the status message's text when there are
    no artifacts), and every file part as an artifact ref.
    """
    sim = _meta(task)
    state = (task.get("status") or {}).get("state")
    plain = _plain_state(state)
    status = member_status(state)
    if sim.get("status") in MEMBER_STATUS and _STATE_OF[sim["status"]] == _STATE_OF[status]:
        status = sim["status"]          # e.g. `blocked` that went out as `rejected`
    if trusted:
        member = Member(
            handle=str(task.get("id", "")),
            agent=str(sim.get("agent") or "a2a"),
            parent=str(sim.get("parent", parent)),
            depth=int(sim.get("depth", 1) or 0),
            status=status,
            budget=MemberBudget.from_dict(sim.get("budget")),
            report_policy=str(sim.get("report_policy", "end")),
            isolation=str(sim.get("isolation", "fresh")),
            crew_id=str(task.get("contextId") or crew_id),
        )
    else:
        member = Member(handle=str(handle or task.get("id", "")), agent="a2a", parent=parent,
                        status=status, crew_id=str(crew_id or task.get("contextId") or ""))
    artifacts = [a for a in task.get("artifacts") or () if isinstance(a, dict)]
    ours = next((a for a in artifacts
                 if any(_read_part(p)[2] == REPORT_ARTIFACT for p in a.get("parts") or ())), None)
    if ours is not None:
        texts, data, refs = [], {}, []
        for p in ours.get("parts") or ():
            kind, value, tag = _read_part(p)
            if kind == "text":
                texts.append(value)
            elif kind == "data" and tag == REPORT_ARTIFACT and isinstance(value, dict):
                data = value
            elif kind == "file":
                refs.append(value)
        report = Report.from_dict({**data, "summary": "\n".join(texts), "artifacts": refs})
        return member, (report if trusted else _bounded(report, _REPORT_STATUS_OF.get(plain, "partial")))
    if not artifacts and plain not in _REPORT_STATUS_OF:
        return member, None
    texts, refs = [], []
    for a in artifacts:
        for p in a.get("parts") or ():
            kind, value, _ = _read_part(p)
            if kind == "text" and value:
                texts.append(value)
            elif kind == "file":
                refs.append(value)
    if not artifacts:
        message = (task.get("status") or {}).get("message") or {}
        texts = [v for k, v, _ in map(_read_part, message.get("parts") or ()) if k == "text" and v]
    report = Report(status=_REPORT_STATUS_OF.get(plain, "partial"), summary=_clip("\n".join(texts)),
                    artifacts=tuple(refs))
    return member, report


# --- Message <-> crew.message ----------------------------------------------------


def to_a2a_message(crew_message: CrewMessage | dict, *, version: str = A2A_DEFAULT_VERSION) -> dict:
    """A `crew.message` (the dataclass or its payload) as an A2A `Message`.

    The role is the working member's side: what a member says about its
    own work (progress, milestone, question, report) is role `agent` on
    the sender's task; what is said to a member (steer, answer, note) is
    role `user` on the recipient's task.
    """
    _check_version(version)
    p = _payload(crew_message)
    kind = p["kind"]
    if kind not in MESSAGE_KIND:
        raise ValueError(f"message kind {kind!r} is not one of {', '.join(MESSAGE_KIND)}")
    agent_side = kind in _AGENT_KINDS
    sim = {"from": p["from"], "to": p["to"], "kind": kind, "seq": p["seq"]}
    if p.get("reply_to") is not None:
        sim["reply_to"] = p["reply_to"]
    parts = [_text_part(p.get("body", ""), version)] + [_file_part(r, version) for r in p.get("refs") or ()]
    role = ("agent" if agent_side else "user") if version == "0.3" else ("ROLE_AGENT" if agent_side else "ROLE_USER")
    message = {
        "messageId": f"{p['crew_id']}:{p['seq']}",
        "contextId": p["crew_id"],
        "taskId": p["from"] if agent_side else p["to"],
        "role": role,
        "parts": parts,
        "metadata": {META_KEY: sim},
    }
    if version == "0.3":
        message["kind"] = "message"
    return message


def from_a2a_message(message: dict, *, crew_id: str = "", parent: str = "", handle: str = "",
                     kind: str | None = None, seq: int = 0, trusted: bool = False) -> CrewMessage:
    """An A2A `Message` as a `crew.message` dataclass.

    With `trusted=True`, one Sim wrote reads back exactly. Otherwise its
    `metadata.simorgh` is ignored (module docstring) and it reads as a
    foreign one, in crew `crew_id` (else its contextId), its task being
    `handle` (else its taskId): role `agent` is from
    its task to `parent`, kind `progress`; role `user` is from `parent`
    to its task, kind `steer`; `kind` overrides either (an
    `input-required` status message is a `question`). Text parts are the
    body, a data part is appended as compact JSON, file parts are refs,
    and `seq` is the caller's, since only the crew knows its sequence.
    """
    sim = _meta(message)
    texts, refs = [], []
    for part in message.get("parts") or ():
        k, value, _ = _read_part(part)
        if k == "text":
            texts.append(value)
        elif k == "data":
            texts.append(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        elif k == "file":
            refs.append(value)
    if trusted and sim.get("kind") in MESSAGE_KIND and "from" in sim and "to" in sim:
        sender, recipient, kind_ = str(sim["from"]), str(sim["to"]), str(sim["kind"])
        seq_ = int(sim.get("seq", seq) or 0)
        reply_to = sim.get("reply_to")
    else:
        role = str(message.get("role", "")).lower().removeprefix("role_")
        task_id = str(handle or message.get("taskId", ""))
        agent_side = role != "user"
        sender, recipient = (task_id, parent) if agent_side else (parent, task_id)
        kind_ = "progress" if agent_side else "steer"
        seq_, reply_to = seq, None
    if kind is not None:
        if kind not in MESSAGE_KIND:
            raise ValueError(f"message kind {kind!r} is not one of {', '.join(MESSAGE_KIND)}")
        kind_ = kind
    crew = (message.get("contextId") or crew_id) if trusted else (crew_id or message.get("contextId"))
    return CrewMessage.from_payload({
        "crew_id": str(crew or ""),
        "from": sender, "to": recipient, "kind": kind_, "body": "\n".join(texts), "seq": seq_,
        **({"refs": refs} if refs else {}),
        **({"reply_to": int(reply_to)} if reply_to is not None else {}),
    })


__all__ = [
    "A2A_DEFAULT_VERSION", "A2A_VERSIONS", "META_KEY", "REPORT_ARTIFACT",
    "from_a2a_message", "from_a2a_task", "member_status", "task_state",
    "to_a2a_message", "to_a2a_task",
]
