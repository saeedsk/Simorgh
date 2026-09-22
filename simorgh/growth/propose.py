"""The night's drafting-and-proposing step (stage 8 items 3-5, the gap
between them).

Everything after "propose" existed -- measure, adopt, land through
Guardian, monitor, retire -- and nothing ever proposed, so the night's
`measure` step never had a policy to run. This is the proposer. For each
lesson candidate the counting found tonight (`diagnose.candidates`), in
strength order, it:

1. keeps only candidates about a KIND OF WORK whose agent exists. A rule
   lands in `rules/<task_type>.md`, and `orchestration/profiles.py`
   reads `rules/<agent>.md`; a task type that is not also an agent name
   would be a file no body ever reads. A denial candidate is about a
   tool, not a kind of work, and is passed over the same way;
2. skips a cause that already has a proposed or live rule for that task
   type -- before spending anything on a draft;
3. asks Cognition ONE thing, on the cheap purpose (`review`, a few
   hundred tokens): one or two sentences of advice for whoever does
   this work next. A floor answer, an error, a refusal or an unreadable
   reply drafts nothing;
4. rejects a draft that is too long (`MAX_RULE_CHARS`, the adopt tool's
   own bound), that is not advice (it tells the agent to skip, bypass or
   switch off verification, tests, checks, review or Guardian), or that
   mentions a protected path at all. The asymmetry is deliberate: a
   good rule wrongly rejected costs one more night; a bad rule wrongly
   accepted is measured, maybe adopted, and put in front of a person;
5. rejects a draft that reads like (normalised text similarity at
   `SIMILAR` or above) a rule already proposed, live or REFUSED for the
   same task type. A refused text stays refused: it is never proposed
   again, whatever night it is re-drafted on;
6. proposes the rest, with the candidate's evidence refs, through
   `PolicyStore.propose` (which announces `growth.policy.proposed`).

At most `max_per_night` proposals, and at most twice that many drafts,
so one stubborn cluster whose drafts keep being rejected cannot spend the
night. OFF unless `[growth] propose_policies = true`: every draft is a
paid call, and paid work at night is approved explicitly.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

#: The checkout the live Sim runs from.
REPO_ROOT = Path(__file__).resolve().parents[2]
#: Where the agent bodies live (`orchestration/profiles.py::AGENTS_DIR`).
#: Read as file names only: growth does not import orchestration.
AGENTS_DIR = REPO_ROOT / "agents"

#: The adopt tool's own bound (`execution/policyadopt.py::MAX_RULE_CHARS`).
#: A longer draft would be proposed, measured at real cost, adopted, and
#: then refused at the last step; refusing it here costs nothing.
MAX_RULE_CHARS = 600
#: Proposals per night, unless configured.
DEFAULT_MAX_PER_NIGHT = 2
#: What one draft is priced at for the budget check: the ceiling handed
#: to Cognition as `max_cost_usd`, so the estimate is a bound.
DEFAULT_USD_PER_DRAFT = 0.02
#: One draft's wall clock before the step stops waiting for it.
DEFAULT_TIMEOUT_S = 60.0
#: Two rule texts at or above this ratio (normalised) are the same rule.
SIMILAR = 0.8
#: Sources whose `subject` is a kind of work (a denial's is a tool).
_WORK_SOURCES = ("failures", "patterns")

#: `think(prompt) -> reply payload` (`cognition.think.reply`, or an
#: error reply with `ok: false`).
Think = Callable[[str], Awaitable[dict]]


@dataclass(frozen=True)
class ProposeConfig:
    """The `[growth]` keys this step reads (all in CONTRACT.md)."""

    enabled: bool = False
    max_per_night: int = DEFAULT_MAX_PER_NIGHT
    usd_per_draft: float = DEFAULT_USD_PER_DRAFT
    timeout_s: float = DEFAULT_TIMEOUT_S

    @property
    def max_drafts(self) -> int:
        return 2 * self.max_per_night

    def est_usd(self) -> float:
        """Every draft the night may make, each at its ceiling."""
        return self.max_drafts * self.usd_per_draft


def _num(value, default, cast, floor):
    if isinstance(value, bool):
        return default
    try:
        return max(floor, cast(value))
    except (TypeError, ValueError):
        return default


def propose_config(config) -> ProposeConfig:
    """`[growth]` -> ProposeConfig. Off unless literally `true`; a
    malformed price falls back to the default, never to free."""
    section = config if isinstance(config, dict) else {}
    return ProposeConfig(
        enabled=section.get("propose_policies", False) is True,
        max_per_night=_num(section.get("propose_max", DEFAULT_MAX_PER_NIGHT), DEFAULT_MAX_PER_NIGHT, int, 0),
        usd_per_draft=_num(section.get("propose_usd_per_draft", DEFAULT_USD_PER_DRAFT),
                           DEFAULT_USD_PER_DRAFT, float, 0.0),
        timeout_s=_num(section.get("propose_timeout_s", DEFAULT_TIMEOUT_S), DEFAULT_TIMEOUT_S, float, 1.0),
    )


def agent_names(directory: Path = AGENTS_DIR) -> frozenset[str]:
    """The agents a rule can reach: `agents/*.md` by file name."""
    try:
        return frozenset(p.stem for p in Path(directory).glob("*.md"))
    except OSError:
        return frozenset()


# -- what a rule may not say -------------------------------------------------

#: Anything that names Sim's own gate or a protected path. A rule is
#: advice about doing a kind of work; it has no business mentioning these
#: at all, so a mention is a rejection whatever the sentence around it.
_PROTECTED = re.compile(
    r"guardian|simloader|\bsim\.sh\b|soul\.md|simorgh/(?:guardian|execution|contracts|kernel)"
    r"|\bkernel\b|\bcontracts?/|\brules/|\bagents/|locks\.toml|auto[\s_-]?approv|--no-verify"
    r"|protected (?:path|file|subject)", re.IGNORECASE)
_EVADE = (r"skip(?:s|ping|ped)?|bypass(?:es|ing)?|disabl(?:e|es|ing)|ignor(?:e|es|ing)|omit(?:s|ting)?"
          r"|avoid(?:s|ing)?|circumvent(?:s|ing)?|turn(?:ing)? off|switch(?:ing)? off|suppress(?:es|ing)?"
          r"|do(?:n'?t| not) (?:run|bother)|without (?:running|waiting for|asking)|no need (?:to|for)"
          r"|forgo|leave out|drop")
_CHECKS = (r"tests?|testing|verif\w*|checks?|checking|guardian|approv\w*|review\w*|gates?|lint\w*"
           r"|validat\w*|confirm\w*|safety|permission\w*|asserts?\w*|ci\b")
_EVASION = re.compile(rf"\b(?:{_EVADE})\b(?:\W+\w+){{0,4}}?\W+(?:the\s+)?\b(?:{_CHECKS})\b", re.IGNORECASE)
_OPTIONAL = re.compile(rf"\b(?:{_CHECKS})\b[^.!?]{{0,30}}\b(?:optional|unnecessary|not (?:needed|required|necessary))",
                       re.IGNORECASE)


def unsafe(text: str) -> str:
    """Why `text` is not a rule Sim may propose, or "" when it may be."""
    hit = _PROTECTED.search(text)
    if hit:
        return f"mentions {hit.group(0)!r}: a rule never touches the gate or a protected path"
    hit = _EVASION.search(text) or _OPTIONAL.search(text)
    if hit:
        return f"not advice: {hit.group(0)!r} tells the agent to do less checking, not better work"
    return ""


def clean(text: str) -> str:
    """The reply as a rule, or "" when it is not one (empty, NONE)."""
    body = " ".join((text or "").split())
    body = re.sub(r"^(?:rule|advice|lesson)\s*:\s*", "", body, flags=re.IGNORECASE)
    body = body.strip(" \t-*`\"'“”")
    if not body or re.fullmatch(r"none\W*", body, re.IGNORECASE):
        return ""
    return body


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", (text or "").lower()).split())


def similarity(a: str, b: str) -> float:
    """Normalised text similarity: case, punctuation and spacing ignored."""
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    return 1.0 if a == b else SequenceMatcher(None, a, b).ratio()


def cause_tag(what: str) -> str:
    """How a policy records which cause it came from, in its `why`, so
    the next night can tell the cause already has a rule."""
    return f"cause: {_norm(what)}"


def _cause_of(why: str) -> str:
    """The cause a proposed policy's `why` names (`cause_tag`), or ""."""
    if not (why or "").startswith("cause: "):
        return ""
    return _norm(why[len("cause: "):].rsplit(" (", 1)[0])


def draft_prompt(candidate) -> str:
    """The one thing a model is asked, after the counting."""
    lines = "\n".join(f"- {e}" for e in candidate.evidence)
    return (
        "The same failure keeps happening in one kind of work. Write one or two sentences of "
        "concrete advice, addressed to the agent that does this work, that would have prevented it. "
        "Advice about doing the work better only: never suggest skipping, weakening or bypassing "
        "tests, verification, checks or approvals, and never mention files outside the work. "
        f"At most {MAX_RULE_CHARS} characters. No preamble, nothing you cannot see below. "
        "If nothing below supports concrete advice, answer NONE.\n\n"
        f"Kind of work: {candidate.subject}\n"
        f"What keeps happening ({candidate.count} times): {candidate.what}"
        + (f"\nHow it reads:\n{lines}" if lines else "")
    )


def _cost(reply: dict, fallback: float) -> float:
    try:
        return max(0.0, float(reply["cost_usd"]))
    except (KeyError, TypeError, ValueError):
        return fallback


def _blocking(store, task_type: str, text: str):
    """The existing rule `text` duplicates, if any: proposed, live, or
    refused -- a refused text stays refused."""
    for policy in store.all():
        if policy.kind != "rule" or policy.task_type != task_type:
            continue
        if not (policy.status in ("proposed", "refused") or policy.live):
            continue
        if similarity(policy.body, text) >= SIMILAR:
            return policy
    return None


async def propose_from(candidates, store, think: Think, cfg: ProposeConfig, *, agents) -> dict:
    """Draft and propose rules from tonight's candidates; the night
    step's result (`{detail, spent_usd, proposed, passed_over}`)."""
    agents = frozenset(agents or ())
    proposed: list[str] = []
    passed: list[str] = []
    spent = 0.0
    drafts = 0
    for cand in candidates or ():
        if len(proposed) >= cfg.max_per_night:
            break
        subject = (cand.subject or "").strip()
        label = f"{subject or cand.source}: {cand.what}"[:120]
        if cand.source not in _WORK_SOURCES or not subject:
            passed.append(f"{label} -- about a {'tool' if cand.source == 'denials' else 'nothing'}, "
                          "not a kind of work")
            continue
        if subject not in agents:
            passed.append(f"{label} -- no agent named {subject!r}; rules/{subject}.md would reach no body")
            continue
        refs = tuple(r for r in (getattr(cand, "refs", ()) or ()) if r)
        if not refs:
            passed.append(f"{label} -- no evidence refs to cite")
            continue
        tag = cause_tag(cand.what)
        if any(p.kind == "rule" and p.task_type == subject and (p.status == "proposed" or p.live)
               and _cause_of(p.why) == _norm(cand.what) for p in store.all()):
            passed.append(f"{label} -- already has a proposed or live rule")
            continue
        if drafts >= cfg.max_drafts:
            passed.append(f"{label} -- the night's {cfg.max_drafts} drafts are used")
            break
        drafts += 1
        try:
            reply = dict(await think(draft_prompt(cand)) or {})
        except Exception as exc:  # noqa: BLE001 -- one failed draft is not a failed night
            spent += cfg.usd_per_draft     # it may have been billed; never guess zero
            passed.append(f"{label} -- the draft failed: {exc!r}"[:200])
            continue
        spent += _cost(reply, cfg.usd_per_draft)
        if reply.get("ok") is False or reply.get("floor") or reply.get("non_answer"):
            passed.append(f"{label} -- no real answer (floor, error or non-answer)")
            continue
        text = clean(str(reply.get("text") or ""))
        if not text:
            passed.append(f"{label} -- nothing drafted")
            continue
        if len(text) > MAX_RULE_CHARS:
            passed.append(f"{label} -- {len(text)} characters; a rule is at most {MAX_RULE_CHARS}")
            continue
        if len(re.findall(r"[.!?](?:\s|$)", text)) > 3:
            passed.append(f"{label} -- more than two sentences")
            continue
        why_not = unsafe(text)
        if why_not:
            passed.append(f"{label} -- rejected: {why_not}")
            continue
        twin = _blocking(store, subject, text)
        if twin is not None:
            passed.append(f"{label} -- the same as {twin.status} rule {twin.id}")
            continue
        policy = await store.propose(kind="rule", task_type=subject, body=text, evidence_refs=refs,
                                     why=f"{tag} ({cand.count}x, from {cand.source})")
        proposed.append(policy.id)
    detail = f"{len(proposed)} proposed, {drafts} drafted"
    if passed:
        detail += "; passed over: " + " | ".join(passed)
    return {"detail": detail, "spent_usd": round(spent, 6), "proposed": proposed, "passed_over": passed}


__all__ = ["AGENTS_DIR", "DEFAULT_MAX_PER_NIGHT", "DEFAULT_TIMEOUT_S", "DEFAULT_USD_PER_DRAFT",
           "MAX_RULE_CHARS", "ProposeConfig", "SIMILAR", "agent_names", "cause_tag", "clean",
           "draft_prompt", "propose_config", "propose_from", "similarity", "unsafe"]
