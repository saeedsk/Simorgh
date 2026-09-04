"""Cycle and infinite-loop detection in agent action history."""

from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple
import dataclasses
import json

DEFAULT_IGNORE_KEYS = frozenset({
    "id",
    "call_id",
    "tool_call_id",
    "timestamp",
    "created_at",
    "updated_at",
    "request_id",
    "execution_time",
    "duration",
    "elapsed",
})


def _normalize_obj(obj: Any, ignore_keys: Set[str]) -> Any:
    """Recursively convert an action or data object into a normalized, JSON-serializable structure."""
    if obj is None or isinstance(obj, (int, bool, str)):
        return obj
    if isinstance(obj, float):
        if obj != obj:  # NaN
            return "__NaN__"
        return round(obj, 10)
    if isinstance(obj, (list, tuple)):
        return [_normalize_obj(x, ignore_keys) for x in obj]
    if isinstance(obj, (set, frozenset)):
        normalized_items = [_normalize_obj(x, ignore_keys) for x in obj]
        try:
            return sorted(normalized_items)
        except TypeError:
            return sorted(normalized_items, key=str)
    if isinstance(obj, dict):
        return {
            str(k): _normalize_obj(v, ignore_keys)
            for k, v in sorted(obj.items(), key=lambda item: str(item[0]))
            if str(k) not in ignore_keys
        }
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return _normalize_obj(dataclasses.asdict(obj), ignore_keys)
    if hasattr(obj, "model_dump") and callable(obj.model_dump):
        try:
            return _normalize_obj(obj.model_dump(), ignore_keys)
        except Exception:
            pass
    if hasattr(obj, "dict") and callable(obj.dict):
        try:
            return _normalize_obj(obj.dict(), ignore_keys)
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        return _normalize_obj(
            {k: v for k, v in obj.__dict__.items() if not k.startswith("_")},
            ignore_keys,
        )
    return str(obj)


def canonicalize_action(action: Any, ignore_keys: Optional[Iterable[str]] = None) -> str:
    """Return a deterministic string token representing an action for cycle comparison."""
    keys_to_ignore = set(DEFAULT_IGNORE_KEYS) if ignore_keys is None else set(ignore_keys)
    normalized = _normalize_obj(action, keys_to_ignore)
    return json.dumps(normalized, sort_keys=True, ensure_ascii=False)


def is_primitive(pattern: Tuple[Any, ...]) -> bool:
    """Return True if pattern cannot be expressed as a repetition of a shorter pattern."""
    L = len(pattern)
    if L <= 1:
        return True
    for d in range(1, L // 2 + 1):
        if L % d == 0:
            if pattern == pattern[:d] * (L // d):
                return False
    return True


@dataclasses.dataclass(frozen=True)
class CycleRecord:
    """Details of a detected action repetition cycle."""

    cycle_length: int
    repetitions: int
    fractional_repetitions: float
    pattern: Tuple[Any, ...]
    start_index: int
    end_index: int
    is_tail: bool

    def to_dict(self) -> Dict[str, Any]:
        """Convert the record into a JSON-serializable dictionary."""
        pattern_serialized = []
        for item in self.pattern:
            if isinstance(item, (dict, list, str, int, float, bool)) or item is None:
                pattern_serialized.append(item)
            elif dataclasses.is_dataclass(item) and not isinstance(item, type):
                pattern_serialized.append(dataclasses.asdict(item))
            elif hasattr(item, "__dict__"):
                pattern_serialized.append(
                    {k: v for k, v in item.__dict__.items() if not k.startswith("_")}
                )
            else:
                pattern_serialized.append(str(item))

        return {
            "cycle_length": self.cycle_length,
            "repetitions": self.repetitions,
            "fractional_repetitions": round(self.fractional_repetitions, 3),
            "pattern": pattern_serialized,
            "start_index": self.start_index,
            "end_index": self.end_index,
            "is_tail": self.is_tail,
            "summary": self.summary,
        }

    @property
    def summary(self) -> str:
        """Human-readable description of the cycle."""
        tail_str = " at history tail" if self.is_tail else ""
        return (
            f"Cycle of length {self.cycle_length} repeated {self.fractional_repetitions:.2f}x "
            f"from index {self.start_index} to {self.end_index}{tail_str}"
        )

    def format_mitigation_prompt(self) -> str:
        """Generate a prompt message suitable for injecting into an agent to break the loop."""
        items_desc = []
        for i, action in enumerate(self.pattern, 1):
            if isinstance(action, dict):
                act_str = json.dumps(action, ensure_ascii=False)
            else:
                act_str = str(action)
            items_desc.append(f"  {i}. {act_str}")
        pattern_str = "\n".join(items_desc)
        return (
            f"SYSTEM INTERVENTION: Repetitive action loop detected!\n"
            f"The following sequence of {self.cycle_length} action(s) has been repeated "
            f"{self.fractional_repetitions:.1f} times consecutively:\n"
            f"{pattern_str}\n"
            f"Please break out of this loop immediately. Try an alternative tool or strategy, "
            f"or explain why the task cannot proceed."
        )


def _get_tokens(
    history: Sequence[Any],
    ignore_keys: Optional[Iterable[str]] = None,
    key_fn: Optional[Callable[[Any], Any]] = None,
) -> List[str]:
    if key_fn is not None:
        return [canonicalize_action(key_fn(a), ignore_keys) for a in history]
    return [canonicalize_action(a, ignore_keys) for a in history]


def detect_tail_cycle(
    history: Sequence[Any],
    min_cycle_length: int = 1,
    max_cycle_length: Optional[int] = None,
    min_repetitions: int = 2,
    ignore_keys: Optional[Iterable[str]] = None,
    key_fn: Optional[Callable[[Any], Any]] = None,
) -> Optional[CycleRecord]:
    """Detect if the most recent actions in history form an ongoing repeating cycle."""
    if min_cycle_length < 1:
        raise ValueError("min_cycle_length must be at least 1")
    if min_repetitions < 2:
        raise ValueError("min_repetitions must be at least 2")
    if max_cycle_length is not None and max_cycle_length < min_cycle_length:
        raise ValueError("max_cycle_length must be >= min_cycle_length")

    N = len(history)
    if N < min_cycle_length * min_repetitions:
        return None

    max_L = N // min_repetitions
    if max_cycle_length is not None:
        max_L = min(max_L, max_cycle_length)

    tokens = _get_tokens(history, ignore_keys, key_fn)

    for L in range(min_cycle_length, max_L + 1):
        if tokens[N - 1] != tokens[N - 1 - L]:
            continue
        k = N - 1
        matches = 0
        while k - L >= 0 and tokens[k] == tokens[k - L]:
            matches += 1
            k -= 1

        span = matches + L
        full_reps = span // L
        if full_reps >= min_repetitions:
            start_idx = N - span
            pattern_tokens = tuple(tokens[start_idx : start_idx + L])
            if is_primitive(pattern_tokens):
                return CycleRecord(
                    cycle_length=L,
                    repetitions=full_reps,
                    fractional_repetitions=span / L,
                    pattern=tuple(history[start_idx : start_idx + L]),
                    start_index=start_idx,
                    end_index=N,
                    is_tail=True,
                )
    return None


def detect_all_cycles(
    history: Sequence[Any],
    min_cycle_length: int = 1,
    max_cycle_length: Optional[int] = None,
    min_repetitions: int = 2,
    ignore_keys: Optional[Iterable[str]] = None,
    key_fn: Optional[Callable[[Any], Any]] = None,
) -> List[CycleRecord]:
    """Find all repeating cycles across the entire history sequence."""
    if min_cycle_length < 1:
        raise ValueError("min_cycle_length must be at least 1")
    if min_repetitions < 2:
        raise ValueError("min_repetitions must be at least 2")
    if max_cycle_length is not None and max_cycle_length < min_cycle_length:
        raise ValueError("max_cycle_length must be >= min_cycle_length")

    N = len(history)
    if N < min_cycle_length * min_repetitions:
        return []

    max_L = N // min_repetitions
    if max_cycle_length is not None:
        max_L = min(max_L, max_cycle_length)

    tokens = _get_tokens(history, ignore_keys, key_fn)
    records: List[CycleRecord] = []

    for L in range(min_cycle_length, max_L + 1):
        i = 0
        limit = N - L
        while i < limit:
            if tokens[i] == tokens[i + L]:
                start_match = i
                while i < limit and tokens[i] == tokens[i + L]:
                    i += 1
                end_match = i - 1
                matches_count = end_match - start_match + 1
                span = matches_count + L
                full_reps = span // L
                if full_reps >= min_repetitions:
                    start_idx = start_match
                    end_idx = start_match + span
                    pattern_tokens = tuple(tokens[start_idx : start_idx + L])
                    if is_primitive(pattern_tokens):
                        records.append(
                            CycleRecord(
                                cycle_length=L,
                                repetitions=full_reps,
                                fractional_repetitions=span / L,
                                pattern=tuple(history[start_idx : start_idx + L]),
                                start_index=start_idx,
                                end_index=end_idx,
                                is_tail=(end_idx == N),
                            )
                        )
            else:
                i += 1

    records.sort(key=lambda r: (r.start_index, -r.repetitions, r.cycle_length))
    return records


def is_looping(
    history: Sequence[Any],
    min_cycle_length: int = 1,
    max_cycle_length: Optional[int] = None,
    min_repetitions: int = 2,
    ignore_keys: Optional[Iterable[str]] = None,
    key_fn: Optional[Callable[[Any], Any]] = None,
) -> bool:
    """Return True if history is currently caught in a cycle at the tail."""
    return (
        detect_tail_cycle(
            history,
            min_cycle_length=min_cycle_length,
            max_cycle_length=max_cycle_length,
            min_repetitions=min_repetitions,
            ignore_keys=ignore_keys,
            key_fn=key_fn,
        )
        is not None
    )


def detect_ping_pong(
    history: Sequence[Any],
    min_repetitions: int = 2,
    ignore_keys: Optional[Iterable[str]] = None,
    key_fn: Optional[Callable[[Any], Any]] = None,
) -> Optional[CycleRecord]:
    """Detect if history is trapped in a 2-step alternating ping-pong loop (A -> B -> A -> B)."""
    return detect_tail_cycle(
        history,
        min_cycle_length=2,
        max_cycle_length=2,
        min_repetitions=min_repetitions,
        ignore_keys=ignore_keys,
        key_fn=key_fn,
    )


def detect_stagnation(
    history: Sequence[Any],
    min_repetitions: int = 3,
    ignore_keys: Optional[Iterable[str]] = None,
    key_fn: Optional[Callable[[Any], Any]] = None,
) -> Optional[CycleRecord]:
    """Detect if the agent is repeatedly executing the exact same single action (A -> A -> A)."""
    return detect_tail_cycle(
        history,
        min_cycle_length=1,
        max_cycle_length=1,
        min_repetitions=min_repetitions,
        ignore_keys=ignore_keys,
        key_fn=key_fn,
    )


class LoopDetector:
    """Stateful, streaming cycle detector for incremental agent execution histories."""

    def __init__(
        self,
        min_cycle_length: int = 1,
        max_cycle_length: Optional[int] = None,
        min_repetitions: int = 2,
        ignore_keys: Optional[Iterable[str]] = None,
        key_fn: Optional[Callable[[Any], Any]] = None,
    ):
        if min_cycle_length < 1:
            raise ValueError("min_cycle_length must be at least 1")
        if min_repetitions < 2:
            raise ValueError("min_repetitions must be at least 2")
        if max_cycle_length is not None and max_cycle_length < min_cycle_length:
            raise ValueError("max_cycle_length must be >= min_cycle_length")

        self.min_cycle_length = min_cycle_length
        self.max_cycle_length = max_cycle_length
        self.min_repetitions = min_repetitions
        self.ignore_keys = set(DEFAULT_IGNORE_KEYS) if ignore_keys is None else set(ignore_keys)
        self.key_fn = key_fn
        self._history: List[Any] = []
        self._tokens: List[str] = []

    def add(self, action: Any) -> Optional[CycleRecord]:
        """Append an action to history and return CycleRecord if a tail loop is detected, else None."""
        self._history.append(action)
        extracted = self.key_fn(action) if self.key_fn is not None else action
        self._tokens.append(canonicalize_action(extracted, self.ignore_keys))
        return self._check_tail()

    def check(self) -> Optional[CycleRecord]:
        """Check current history for a tail loop without adding a new action."""
        return self._check_tail()

    def is_looping(self) -> bool:
        """Return True if current history ends in a repeating cycle."""
        return self._check_tail() is not None

    def get_history(self) -> List[Any]:
        """Return a copy of the recorded action history."""
        return list(self._history)

    def get_all_cycles(self) -> List[CycleRecord]:
        """Return all repeating cycles detected across the entire history."""
        return detect_all_cycles(
            self._history,
            min_cycle_length=self.min_cycle_length,
            max_cycle_length=self.max_cycle_length,
            min_repetitions=self.min_repetitions,
            ignore_keys=self.ignore_keys,
            key_fn=self.key_fn,
        )

    def clear(self) -> None:
        """Reset the detector state and clear history."""
        self._history.clear()
        self._tokens.clear()

    def __len__(self) -> int:
        return len(self._history)

    def _check_tail(self) -> Optional[CycleRecord]:
        N = len(self._tokens)
        if N < self.min_cycle_length * self.min_repetitions:
            return None

        max_L = N // self.min_repetitions
        if self.max_cycle_length is not None:
            max_L = min(max_L, self.max_cycle_length)

        tokens = self._tokens
        for L in range(self.min_cycle_length, max_L + 1):
            if tokens[N - 1] != tokens[N - 1 - L]:
                continue
            k = N - 1
            matches = 0
            while k - L >= 0 and tokens[k] == tokens[k - L]:
                matches += 1
                k -= 1

            span = matches + L
            full_reps = span // L
            if full_reps >= self.min_repetitions:
                start_idx = N - span
                pattern_tokens = tuple(tokens[start_idx : start_idx + L])
                if is_primitive(pattern_tokens):
                    return CycleRecord(
                        cycle_length=L,
                        repetitions=full_reps,
                        fractional_repetitions=span / L,
                        pattern=tuple(self._history[start_idx : start_idx + L]),
                        start_index=start_idx,
                        end_index=N,
                        is_tail=True,
                    )
        return None