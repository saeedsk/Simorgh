"""GAIA's scorer, and the answer extraction it depends on.

GAIA is scored by quasi-exact match, not by a judge model: an answer is
"a number OR as few words as possible OR a comma separated list of
numbers and/or strings", and the official scorer normalises each type
before comparing. That is worth reimplementing faithfully rather than
approximating with a fuzzy match -- a benchmark whose scorer is looser
than the published one produces a number that cannot be compared to
anybody else's, which defeats the purpose of running a standard
benchmark at all.

The rules, from the GAIA scorer:

- a number: strip $ , % and spaces, compare as float
- a string: lowercase, strip punctuation and articles, collapse spaces
- a list: split on commas, apply the number/string rule per element,
  and compare element-wise in order

The one addition is `final_answer`: our answering system replies in
prose, so the scorer needs the answer pulled out of it first. GAIA's
own prompt asks for a `FINAL ANSWER:` line, and that is what we ask for
and read.
"""

from __future__ import annotations

import json
import re
import string

FINAL_ANSWER_PREFIX = "FINAL ANSWER:"
# The instruction handed to the answering system. Verbatim in spirit
# from the GAIA prompt: the format is part of the benchmark, and a
# system that answers correctly in the wrong shape scores zero on the
# real leaderboard too, so we must not be kinder here.
ANSWER_FORMAT = (
    "Finish your reply with a line of exactly this form:\n"
    "FINAL ANSWER: <answer>\n"
    "where <answer> is a number, or as few words as possible, or a comma "
    "separated list of numbers and/or strings. Do not use units, commas in "
    "numbers, or the % sign unless the question asks for them. Write digits "
    "for numbers unless the question says otherwise."
)

_ARTICLES = {"a", "an", "the"}
_NUMBER = re.compile(r"^[-+]?\d{1,3}(,\d{3})*(\.\d+)?$|^[-+]?\d*\.?\d+$")


def final_answer(text: str) -> str:
    """The answer out of a prose reply.

    The last `FINAL ANSWER:` line wins -- a model that restates the
    format instruction before answering would otherwise have its own
    example scored. With no such line, the last non-empty line is used:
    a right answer stated plainly should not score zero because of a
    missing prefix, though the prompt does ask for one."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    for line in reversed(lines):
        upper = line.upper()
        if FINAL_ANSWER_PREFIX in upper:
            index = upper.rindex(FINAL_ANSWER_PREFIX) + len(FINAL_ANSWER_PREFIX)
            return line[index:].strip().strip("*` ")
    return lines[-1].strip().strip("*` ") if lines else ""


def _is_number(text: str) -> bool:
    return bool(_NUMBER.match(text.strip().replace("$", "").replace("%", "").replace(" ", "")))


def _as_number(text: str) -> float:
    return float(text.strip().replace("$", "").replace("%", "").replace(",", "").replace(" ", ""))


def normalise_string(text: str) -> str:
    text = (text or "").lower().strip()
    text = text.replace("’", "'")
    text = "".join(ch for ch in text if ch not in string.punctuation)
    words = [w for w in text.split() if w not in _ARTICLES]
    return " ".join(words)


def normalise(value: str) -> str:
    """One scalar, normalised to a comparable form."""
    value = (value or "").strip()
    if _is_number(value):
        number = _as_number(value)
        # 3 and 3.0 are the same answer; 3.14159 and 3.1416 are not.
        return str(int(number)) if number == int(number) else repr(round(number, 6))
    return normalise_string(value)


def _split_list(value: str) -> list[str]:
    return [part.strip() for part in value.split(",")]


def matches(given: str, expected: str) -> bool:
    """GAIA quasi-exact match, applied element-wise for lists."""
    given, expected = (given or "").strip(), (expected or "").strip()
    if not expected:
        return False
    expected_parts, given_parts = _split_list(expected), _split_list(given)
    if len(expected_parts) > 1:
        if len(given_parts) != len(expected_parts):
            return False
        return all(normalise(g) == normalise(e) for g, e in zip(given_parts, expected_parts))
    return normalise(given) == normalise(expected)


def score(reply: str, expected: str) -> tuple[bool, str]:
    """`(correct, the answer we extracted)` for one prose reply."""
    answer = final_answer(reply)
    return matches(answer, expected), answer


# ------------------------------------------------------------- BFCL
# Berkeley Function-Calling Leaderboard: the answer is a set of calls,
# not a string. BFCL's own AST scorer compares the chosen function names
# and each argument's value, ignoring order for parallel calls -- two
# calls that must both happen have no defined order, so requiring one
# would score presentation rather than routing.
BFCL_ANSWER_FORMAT = (
    "Reply with ONLY a JSON array of the calls to make, in this shape:\n"
    '[{"name": "function_name", "arguments": {"arg": "value"}}]\n'
    "Use only the functions given, and include every call the request needs."
)


def parse_calls(text: str) -> list[tuple[str, dict]]:
    """`(name, arguments)` pairs out of a reply, JSON array or not.

    Accepts the several shapes a small model actually produces: a bare
    array, an array inside a fenced block, and BFCL's own ground-truth
    form `{"func": {"arg": [value]}}` where each argument's value is a
    list of acceptable values."""
    blob = _json_blob(text)
    if blob is None:
        return []
    return _as_calls(blob)


def _json_blob(text: str):
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start = min((i for i in (text.find("["), text.find("{")) if i >= 0), default=-1)
    if start < 0:
        return None
    for end in range(len(text), start, -1):
        try:
            return json.loads(text[start:end])
        except ValueError:
            continue
    return None


def _as_calls(blob) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []
    entries = blob if isinstance(blob, list) else [blob]
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if "name" in entry and isinstance(entry.get("arguments", entry.get("parameters")), dict):
            calls.append((str(entry["name"]), dict(entry.get("arguments") or entry.get("parameters") or {})))
            continue
        # ground-truth form: exactly one key, the function name
        for name, args in entry.items():
            if isinstance(args, dict):
                calls.append((str(name), dict(args)))
    return calls


def _argument_matches(given, expected) -> bool:
    """BFCL ground truth gives a *list* of acceptable values per
    argument, and an empty string in that list means the argument may be
    omitted entirely."""
    options = expected if isinstance(expected, list) else [expected]
    if given is None:
        return any(option in ("", None) for option in options)
    for option in options:
        if given == option:
            return True
        if isinstance(given, str) and isinstance(option, str) and normalise(given) == normalise(option):
            return True
        if isinstance(given, (int, float)) and isinstance(option, (int, float)) and float(given) == float(option):
            return True
    return False


def _call_matches(given: tuple[str, dict], expected: tuple[str, dict]) -> bool:
    if given[0] != expected[0]:
        return False
    for arg, want in expected[1].items():
        if not _argument_matches(given[1].get(arg), want):
            return False
    # An argument the expectation never mentions and that is not in the
    # function's optional set would be a hallucinated one; BFCL treats
    # extra arguments as wrong.
    return not set(given[1]) - set(expected[1])


def score_calls(reply: str, expected_json: str) -> tuple[bool, str]:
    """True when the reply's calls match the expected set, order-free."""
    try:
        expected = _as_calls(json.loads(expected_json))
    except ValueError:
        expected = parse_calls(expected_json)
    given = parse_calls(reply)
    rendered = json.dumps([{"name": n, "arguments": a} for n, a in given])[:500]
    if not expected or len(given) != len(expected):
        return False, rendered
    remaining = list(given)
    for want in expected:
        for index, got in enumerate(remaining):
            if _call_matches(got, want):
                remaining.pop(index)
                break
        else:
            return False, rendered
    return True, rendered


def score_case(reply: str, expected: str, *, mode: str = "gaia") -> tuple[bool, str]:
    """Score one reply the way its suite says to."""
    if mode == "bfcl":
        return score_calls(reply, expected)
    return score(reply, expected)


def answer_format(mode: str = "gaia") -> str:
    return BFCL_ANSWER_FORMAT if mode == "bfcl" else ANSWER_FORMAT


__all__ = [
    "ANSWER_FORMAT", "BFCL_ANSWER_FORMAT", "FINAL_ANSWER_PREFIX", "answer_format", "final_answer",
    "matches", "normalise", "normalise_string", "parse_calls", "score", "score_calls", "score_case",
]
