"""Sliding-window conversation history pruner constrained by character budget.

Provides flexible pruning of message histories to stay within character limits
while preserving leading system instructions and maintaining conversation coherence.
"""

from __future__ import annotations

import copy
from collections import deque
from typing import Any, Callable, List, Optional, Sequence, Tuple

__all__ = [
    "prune_conversation_history",
    "calculate_message_chars",
    "ConversationPruner",
]


def _extract_role_and_content(msg: Any) -> Tuple[str, str]:
    """Extract role and string content from various message representations."""
    if isinstance(msg, dict):
        role = str(msg.get("role", "") or "")
        raw_content = msg.get("content")
        if raw_content is None:
            raw_content = msg.get("text", "") or ""
        if isinstance(raw_content, str):
            content = raw_content
        elif isinstance(raw_content, (list, tuple)):
            parts = []
            for item in raw_content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(str(item.get("text", "") or ""))
                else:
                    parts.append(str(item))
            content = "".join(parts)
        else:
            content = str(raw_content)
        return role, content
    elif isinstance(msg, tuple) and len(msg) == 2:
        return str(msg[0]), str(msg[1])
    elif isinstance(msg, str):
        return "", msg
    else:
        role = str(getattr(msg, "role", "") or "")
        raw_content = getattr(msg, "content", None)
        if raw_content is None:
            raw_content = getattr(msg, "text", "") or ""
        if isinstance(raw_content, str):
            content = raw_content
        elif isinstance(raw_content, (list, tuple)):
            parts = []
            for item in raw_content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(str(item.get("text", "") or ""))
                else:
                    parts.append(str(item))
            content = "".join(parts)
        else:
            content = str(raw_content)
        return role, content


def calculate_message_chars(
    msg: Any,
    include_role: bool = True,
    char_counter: Optional[Callable[[Any], int]] = None,
) -> int:
    """Calculate the character length of a single message.

    Args:
        msg: Message object, dict, tuple, or string.
        include_role: If True, include role name length in the character count.
        char_counter: Optional custom counting callable.

    Returns:
        Integer character count.
    """
    if char_counter is not None:
        return char_counter(msg)

    role, content = _extract_role_and_content(msg)
    chars = len(content)
    if include_role and role:
        chars += len(role)
    return chars


def _truncate_message(msg: Any, max_content_chars: int) -> Any:
    """Create a copy of msg with content truncated to max_content_chars."""
    max_content_chars = max(0, max_content_chars)
    if isinstance(msg, dict):
        new_msg = copy.deepcopy(msg)
        if "content" in new_msg:
            raw = new_msg["content"]
            if isinstance(raw, str):
                new_msg["content"] = raw[:max_content_chars]
            elif isinstance(raw, list):
                remaining = max_content_chars
                new_list = []
                for item in raw:
                    if remaining <= 0:
                        break
                    if isinstance(item, str):
                        truncated = item[:remaining]
                        new_list.append(truncated)
                        remaining -= len(truncated)
                    elif isinstance(item, dict) and "text" in item:
                        item_copy = copy.deepcopy(item)
                        text = str(item.get("text", ""))
                        truncated = text[:remaining]
                        item_copy["text"] = truncated
                        new_list.append(item_copy)
                        remaining -= len(truncated)
                    else:
                        new_list.append(copy.deepcopy(item))
                new_msg["content"] = new_list
            else:
                new_msg["content"] = str(raw)[:max_content_chars]
        elif "text" in new_msg:
            new_msg["text"] = str(new_msg["text"])[:max_content_chars]
        return new_msg
    elif isinstance(msg, tuple) and len(msg) == 2:
        return (msg[0], str(msg[1])[:max_content_chars])
    elif isinstance(msg, str):
        return msg[:max_content_chars]
    else:
        try:
            new_obj = copy.deepcopy(msg)
            if hasattr(new_obj, "content"):
                setattr(new_obj, "content", str(getattr(new_obj, "content"))[:max_content_chars])
            elif hasattr(new_obj, "text"):
                setattr(new_obj, "text", str(getattr(new_obj, "text"))[:max_content_chars])
            return new_obj
        except Exception:
            return msg


def prune_conversation_history(
    messages: Sequence[Any],
    max_chars: int,
    *,
    preserve_system: bool = True,
    system_role: str = "system",
    include_role: bool = True,
    truncate_oversized: bool = False,
    ensure_start_role: Optional[str] = None,
    char_counter: Optional[Callable[[Any], int]] = None,
) -> List[Any]:
    """Prune conversation history using a sliding-window constrained by character budget.

    Args:
        messages: Sequence of messages (dicts, tuples, objects, or strings).
        max_chars: Maximum character budget. Must be non-negative.
        preserve_system: If True, leading system messages are anchored and preserved.
        system_role: Role name identifying system messages (default: 'system').
        include_role: If True, role length is included in character budgeting.
        truncate_oversized: If True, partially truncate a message that exceeds remaining budget
            instead of dropping it completely.
        ensure_start_role: If specified (e.g. 'user'), drops messages from the beginning of
            the non-system window until a message with this role is found.
        char_counter: Custom function to count characters in a message.

    Returns:
        A list of pruned messages fitting within max_chars.

    Raises:
        ValueError: If max_chars is negative or preserved system messages exceed max_chars
            (when truncate_oversized is False).
    """
    if max_chars < 0:
        raise ValueError(f"max_chars must be non-negative, got {max_chars}")

    msg_list = list(messages)
    if not msg_list or max_chars == 0:
        return []

    # 1. Identify leading system messages
    leading_system: List[Any] = []
    rest_messages: List[Any] = msg_list

    if preserve_system:
        idx = 0
        while idx < len(msg_list):
            role, _ = _extract_role_and_content(msg_list[idx])
            if role == system_role:
                leading_system.append(msg_list[idx])
                idx += 1
            else:
                break
        rest_messages = msg_list[idx:]

    # 2. Budget system messages
    sys_chars = sum(
        calculate_message_chars(m, include_role=include_role, char_counter=char_counter)
        for m in leading_system
    )

    if sys_chars > max_chars:
        if not truncate_oversized:
            raise ValueError(
                f"Preserved system messages require {sys_chars} characters, "
                f"which exceeds the budget of {max_chars} characters."
            )
        truncated_system: List[Any] = []
        budget_left = max_chars
        for sys_msg in leading_system:
            c = calculate_message_chars(sys_msg, include_role=include_role, char_counter=char_counter)
            if c <= budget_left:
                truncated_system.append(sys_msg)
                budget_left -= c
            else:
                role, _ = _extract_role_and_content(sys_msg)
                role_len = len(role) if include_role and role else 0
                avail = budget_left - role_len
                if avail > 0:
                    truncated_system.append(_truncate_message(sys_msg, avail))
                break
        return truncated_system

    budget_left = max_chars - sys_chars

    # 3. Slide window from the end backwards over remaining messages
    window: deque[Any] = deque()
    for msg in reversed(rest_messages):
        c = calculate_message_chars(msg, include_role=include_role, char_counter=char_counter)
        if c <= budget_left:
            window.appendleft(msg)
            budget_left -= c
        else:
            if truncate_oversized and budget_left > 0:
                role, _ = _extract_role_and_content(msg)
                role_len = len(role) if include_role and role else 0
                avail = budget_left - role_len
                if avail > 0:
                    truncated_msg = _truncate_message(msg, avail)
                    window.appendleft(truncated_msg)
                    budget_left = 0
            break

    # 4. Optional: ensure starting role for window
    if ensure_start_role is not None and window:
        while window:
            role, _ = _extract_role_and_content(window[0])
            if role == ensure_start_role:
                break
            window.popleft()

    return leading_system + list(window)


class ConversationPruner:
    """Configurable sliding-window conversation pruner."""

    def __init__(
        self,
        max_chars: int,
        *,
        preserve_system: bool = True,
        system_role: str = "system",
        include_role: bool = True,
        truncate_oversized: bool = False,
        ensure_start_role: Optional[str] = None,
        char_counter: Optional[Callable[[Any], int]] = None,
    ) -> None:
        if max_chars < 0:
            raise ValueError(f"max_chars must be non-negative, got {max_chars}")
        self.max_chars = max_chars
        self.preserve_system = preserve_system
        self.system_role = system_role
        self.include_role = include_role
        self.truncate_oversized = truncate_oversized
        self.ensure_start_role = ensure_start_role
        self.char_counter = char_counter

    def count_chars(self, messages: Sequence[Any]) -> int:
        """Calculate total characters for a sequence of messages."""
        return sum(
            calculate_message_chars(
                m,
                include_role=self.include_role,
                char_counter=self.char_counter,
            )
            for m in messages
        )

    def prune(self, messages: Sequence[Any]) -> List[Any]:
        """Prune conversation messages to fit within configured budget."""
        return prune_conversation_history(
            messages,
            max_chars=self.max_chars,
            preserve_system=self.preserve_system,
            system_role=self.system_role,
            include_role=self.include_role,
            truncate_oversized=self.truncate_oversized,
            ensure_start_role=self.ensure_start_role,
            char_counter=self.char_counter,
        )

    def is_within_budget(self, messages: Sequence[Any]) -> bool:
        """Check if message sequence is within the character budget."""
        return self.count_chars(messages) <= self.max_chars