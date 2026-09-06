"""ToolCallRouter (16 section 5): a `cognition.think` tool_call becomes an
`action.proposed` payload. Guardian is the sole authority on whether it's
actually approved -- this only tags the request with the reversibility/
scope Guardian's policy reads (03 section 4.6).

v1's full 14-marker conversational set (PROPOSE/PATCH/BATCH/PLAN/EVOLVE/
USE/NEWS/GROWTH/FETCH/RUN/READ/LIST/RECALL/REMIND) is NOT implemented
this session -- only the plain tool_calls -> action.proposed path is.
See 16 section 12 Q4/Q5 and this package's README "Not done this session".
"""

from __future__ import annotations

# (reversibility, network) per known tool name -- conservative default
# for anything unlisted: irreversible, so an unrecognized tool never
# accidentally gets read_only's lighter Guardian scrutiny.
_TOOL_POLICY: dict[str, tuple[str, bool]] = {
    "read_file": ("read_only", False),
    "list_dir": ("read_only", False),
    "web_fetch": ("read_only", True),
    "run_python_sandboxed": ("reversible", False),
    "draft_candidate": ("reversible", False),
}


def to_action_payload(*, action_id: str, task_id: str, call: dict, rationale: str,
                      proposed_by: str = "orchestration") -> dict:
    tool = call.get("tool", "")
    args = call.get("args", {})
    reversibility, network = _TOOL_POLICY.get(tool, ("irreversible", False))
    paths = [args["path"]] if isinstance(args, dict) and "path" in args else []
    return {
        "action_id": action_id,
        "task_id": task_id,
        "tool": tool,
        "args": args if isinstance(args, dict) else {},
        "scope": {"paths": paths, "network": network},
        "reversibility": reversibility,
        "rationale": rationale,
        # 16-orchestration.md section 3.2: `proposed_by:"orchestration@wN"`
        # -- which Worker proposed it, not just which subsystem. The
        # caller passes its own bound `bus.source`; the default here only
        # covers a caller that never had one (e.g. an ad hoc unit test).
        "proposed_by": proposed_by,
    }
