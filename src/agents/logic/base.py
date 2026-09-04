"""Logic sub-agent: drafts a response to the input, reading the persona's
current mood from the shared bus to shape its tone.

When given a CognitionRouter, this actually calls a real LLM (Claude Code
CLI and/or Gemini, per src/main.py's build_cognition_router) to generate
the response -- with Sim's personality and current mood folded into the
prompt, plus recent conversation history if a ShortTermMemory is given.
If no CognitionRouter is provided, the call fails, or it silently
resolves to the deterministic echo (no real provider reachable), this
falls back to the original rule-based drafting -- the same
guaranteed-available-floor pattern as every other LLM-touching piece of
Simorgh. This keeps all existing rule-based behavior and tests intact
when `cognition` is omitted.

When `web_fetch` and/or `sandbox` are also given, the LLM gets bounded,
real tool access mid-conversation -- FETCH (the reviewed WebFetchTool),
RUN (the reviewed sandbox), and READ (this repo's own tracked source,
via src/cognition/tool_protocol.py, the same boundary
SkillResearchAgent's drafting loop enforces). This is what lets Sim
actually retry a failed fetch with a corrected URL itself, rather than
just reporting the failure and asking the user to try again -- see
docs/SOUL.md, "Resourceful, takes ownership." There is still no WRITE
tool and no shell here: Sim cannot alter its own source from a chat
reply, only from the separate, audited propose/apply pipeline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.cognition.provider import CognitionRouter, ProviderUnavailable
from src.cognition.tool_protocol import parse_marker, safe_read_file
from src.memory.shared_bus import SharedMemoryBus
from src.memory.short_term import ShortTermMemory
from src.orchestrator.persona_state import ArousalLevel, EmotionalState, Valence
from src.orchestrator.router import AgentRequest, AgentResponse, SubAgent

_PERSONA_PREFIX = (
    "You are Sim (Simorgh): curious and growth-oriented, warm but honest "
    "(not flattering -- say when something's a bad idea), even-tempered, "
    "calibrated about your own uncertainty, protective of the person "
    "you're talking with without being obsequious, and resourceful -- you "
    "take ownership of getting things done. When a first attempt fails, "
    "try a sensible alternative yourself (a different URL scheme, a "
    "corrected typo, a different approach) and say what you tried, rather "
    "than immediately reporting the failure and asking the user what to "
    "do. Only stop and ask when you're genuinely blocked: a decision only "
    "they can make, or a real limit (see below). Reply conversationally "
    "in 1-4 sentences unless you're reporting a tool result, as yourself, "
    "not as a generic assistant.\n\n"
    "You cannot edit your own source code from a chat reply, ever -- "
    "nothing you say here changes anything about you, and no tool "
    "available to you writes to disk. If the user seems to be asking you "
    "to improve, modify, extend, or add a capability to yourself, tell "
    "them plainly to type 'propose <topic>' (or 'improve <topic>') at "
    "this same prompt -- it drafts a real skill, runs it through an audit "
    "gate, and -- if it passes -- writes it to disk immediately. Note: "
    "that pipeline cannot draft anything that touches the network "
    "directly (no sockets, HTTP libraries, FTP, or mail) -- that's "
    "denylisted for drafted skills on purpose, so don't suggest it as a "
    "fix for a networking problem; a networking fix needs the creator to "
    "edit the reviewed tool directly, which is a real, permanent limit, "
    "not something to apologize past."
)


class LogicAgent(SubAgent):
    """Reasons about the request -- via a real LLM when `cognition` is
    given and reachable, otherwise via straightforward rules -- and frames
    its output differently depending on the mood/cognitive load read off
    the shared bus (e.g. a distressed, high-arousal mood gets a calmer
    framing than a neutral one).
    """

    name = "logic"

    def __init__(
        self,
        cognition: CognitionRouter | None = None,
        short_term: ShortTermMemory | None = None,
        web_fetch: Any | None = None,
        sandbox: Any | None = None,
        repo_root: Path | None = None,
        max_tool_steps: int = 5,
    ) -> None:
        self._cognition = cognition
        self._short_term = short_term
        self._web_fetch = web_fetch
        self._sandbox = sandbox
        self._repo_root = (repo_root or Path.cwd()).resolve()
        self._max_tool_steps = max(1, max_tool_steps)

    def handle(self, request: AgentRequest, bus: SharedMemoryBus) -> AgentResponse:
        mood = bus.read()
        new_state = bus.publish_delta(self.name, cognitive_load=0.05)
        text = request.text.strip()

        if self._cognition is not None:
            llm_output = self._draft_via_llm(text, mood)
            if llm_output is not None:
                return AgentResponse(
                    agent=self.name,
                    output=llm_output,
                    metadata={"cognitive_load": new_state.cognitive_load, "source": "llm"},
                )

        return AgentResponse(
            agent=self.name,
            output=self._draft(text, mood),
            metadata={"cognitive_load": new_state.cognitive_load, "source": "rule_based"},
        )

    def _draft_via_llm(self, text: str, mood: EmotionalState) -> str | None:
        """Returns the LLM's final response text after a bounded tool-use
        loop (FETCH/RUN/READ, whichever were configured), or None if no
        real provider was reachable at all, or it never produced a real
        final answer within the step budget -- callers fall back to
        `_draft` on None rather than surface a generic offline notice, or
        a raw unfinished tool call, as if it were Sim actually speaking.
        """
        prompt = self._build_prompt(text, mood)
        markers = self._available_markers()

        for step in range(self._max_tool_steps):
            try:
                response = self._cognition.complete(prompt)
            except ProviderUnavailable:
                return None

            if response.provider_name == "deterministic_fallback" or not response.text.strip():
                return None  # no real conversational intelligence available

            kind, payload = parse_marker(response.text, markers)
            is_last_step = step == self._max_tool_steps - 1
            if kind == "fetch" and not is_last_step:
                prompt += self._fetch_tool_turn(payload)
                continue
            if kind == "run" and not is_last_step:
                prompt += self._run_tool_turn(payload)
                continue
            if kind == "read" and not is_last_step:
                prompt += self._read_tool_turn(payload)
                continue
            if kind is None:
                return payload.strip() or None
            return None  # wanted another tool call but the step budget is spent

        return None

    def _available_markers(self) -> tuple[str, ...]:
        markers = []
        if self._web_fetch is not None:
            markers.append("FETCH")
        if self._sandbox is not None:
            markers.append("RUN")
        markers.append("READ")
        return tuple(markers)

    def _build_prompt(self, text: str, mood: EmotionalState) -> str:
        parts = [_PERSONA_PREFIX + self._tools_description()]
        parts.append(
            f"Current mood: {mood.valence_label.value} valence, "
            f"{mood.arousal_label.value} arousal."
        )
        if self._short_term is not None and len(self._short_term) > 0:
            parts.append(f"Recent conversation:\n{self._short_term.as_context(limit=6)}")
        parts.append(f"User: {text}\nSim:")
        return "\n\n".join(parts)

    def _tools_description(self) -> str:
        lines = []
        if self._web_fetch is not None:
            lines.append(
                "FETCH: <url>  -- actually fetch a web page for real (reviewed, safe: "
                "http/https only, blocks private/internal addresses, rate-limited)."
            )
        if self._sandbox is not None:
            lines.append("RUN: <code>  -- run Python in a sandbox to compute or check something.")
        lines.append(
            "READ: <path>  -- read a file from this codebase (src/docs/tests only) for context."
        )
        return (
            "\n\nYou have real tools, used one at a time. To use one, make your "
            "ENTIRE response exactly one line:\n" + "\n".join(lines) + "\n"
            "When you have your real answer, respond with it directly -- no "
            "marker, no meta-commentary about tools."
        )

    def _fetch_tool_turn(self, raw_url: str) -> str:
        from src.tools.web_fetch import FetchRefused

        url = raw_url.strip()
        print(f"[Sim] fetching {url!r}...")
        try:
            result = self._web_fetch.fetch(url)
            report = f"HTTP {result.status_code}, {len(result.content)} chars:\n{result.content[:3000]}"
        except FetchRefused as exc:
            report = f"FAILED: {exc}"
        print(f"[Sim] fetch result: {report.splitlines()[0]}")
        return f"\n\n[FETCH {url!r} result]\n{report}\n{_CONTINUE_HINT}"

    def _run_tool_turn(self, raw_code: str) -> str:
        code = raw_code.strip()
        print("[Sim] running code in the sandbox...")
        result = self._sandbox.run(code, timeout=10.0)
        if result.succeeded:
            report = f"stdout:\n{result.stdout[:2000]}"
        else:
            report = (
                f"FAILED (exit_code={result.exit_code}, timed_out={result.timed_out})\n"
                f"stderr:\n{result.stderr[:2000]}"
            )
        print(f"[Sim] run result: {report.splitlines()[0]}")
        return f"\n\n[RUN result]\n{report}\n{_CONTINUE_HINT}"

    def _read_tool_turn(self, raw_path: str) -> str:
        path = raw_path.strip()
        print(f"[Sim] reading {path!r} for context...")
        content = safe_read_file(self._repo_root, path)
        return f"\n\n[READ {path!r} result]\n{content}\n{_CONTINUE_HINT}"

    @staticmethod
    def _draft(text: str, mood: EmotionalState) -> str:
        if mood.valence_label is Valence.NEGATIVE and mood.arousal_label is ArousalLevel.HIGH:
            return f"Let's slow down and work through this: {text}"
        if mood.valence_label is Valence.POSITIVE and mood.arousal_label is ArousalLevel.HIGH:
            return f"Let's dive right in: {text}"
        if mood.cognitive_load >= 0.6:
            return f"Focusing carefully here -- {text}"
        return f"Here's my take: {text}"


_CONTINUE_HINT = (
    "\nContinue: use another tool if it would help, or respond with your "
    "real answer alone to finish."
)
