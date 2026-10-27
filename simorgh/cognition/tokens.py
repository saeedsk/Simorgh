"""A stdlib token estimator (docs/blueprint/subsystems/04-cognition.md
section 7, "Token estimation without a tokenizer dependency"): chars/4,
which keeps enough headroom in every threshold that a real tokenizer
dependency isn't needed for budgeting purposes (principle 4.14).

`split_messages` uses the same estimate to say where a think's input
tokens go (stage 17 item 1). It estimates shares, not counts: the
provider's own `tokens_in` is the count, and a reader scales the shares
to it."""

from __future__ import annotations

import json

_CHARS_PER_TOKEN = 4

#: What the estimator is, recorded beside every split so a reader knows
#: these are not a provider's tokenizer.
ESTIMATOR = "chars/4"

#: The blocks of a think's input, in the order they reach the provider
#: (the system prefix, then the tool block, then the user turn).
BLOCKS = ("prefix", "tools", "memory", "question", "window", "results")

# How Orchestration heads a tool result it hands back in a user turn
# (`orchestration/session.py`); a typed transcript uses `role: "tool"`.
_RESULT_HEADS = ("Result of ", "Results of ")


def estimate_tokens(text: str) -> int:
    return max(0, (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN)


def _content(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        text = content
    else:
        text = json.dumps(content, default=str) if content else ""
    if message.get("tool_calls"):
        text += json.dumps(message["tool_calls"], default=str)
    return text


def _is_result(message: dict) -> bool:
    role = message.get("role", "user")
    return role == "tool" or (role == "user" and str(message.get("content") or "").startswith(_RESULT_HEADS))


def split_messages(messages: list[dict]) -> dict[str, int]:
    """The caller's messages of one think, estimated per block:

    - `memory`: every `role: "system"` message the caller sends (the
      memory and facts blocks, the house, the speaker's preferences);
    - `results`: `role: "tool"` messages and user turns that start
      "Result of" / "Results of";
    - `question`: the turn marked `protected`, else the first user turn
      that is not a result;
    - `window`: everything else (earlier turns, the model's own replies).
    """
    out = {"memory": 0, "question": 0, "window": 0, "results": 0}
    question_at = next((i for i, m in enumerate(messages) if m.get("protected")), None)
    if question_at is None:
        question_at = next((i for i, m in enumerate(messages)
                            if m.get("role", "user") == "user" and not _is_result(m)), None)
    for i, m in enumerate(messages):
        tokens = estimate_tokens(_content(m))
        if i == question_at:
            out["question"] += tokens
        elif m.get("role") == "system":
            out["memory"] += tokens
        elif _is_result(m):
            out["results"] += tokens
        else:
            out["window"] += tokens
    return out


__all__ = ["BLOCKS", "ESTIMATOR", "estimate_tokens", "split_messages"]
