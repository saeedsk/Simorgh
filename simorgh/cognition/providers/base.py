"""The guaranteed floor (principle 4.5): a stdlib, offline provider that
always answers every purpose with a fixed, clearly-labeled template.
Never raises -- it is what every other provider falls back to, so it
must have nowhere further to fall. `respond_for_purpose` is a floor-only
extension (not part of the `Provider` protocol): the Router calls it
directly when floor is the selected candidate, since the protocol's
`complete()` has no purpose parameter and the floor's whole point is a
purpose-specific honest template, not a generic non-answer.
"""

from __future__ import annotations

from simorgh.contracts.protocols import ProviderResponse

from ..api import Purpose

TEMPLATES: dict[Purpose, str] = {
    Purpose.CHAT: "[floor] I don't have a real reasoning provider available right now.",
    Purpose.DRAFT: "[floor] no real drafting intelligence available -- nothing drafted",
    Purpose.PLAN: "[floor] no real planning intelligence available -- nothing planned",
    Purpose.REVIEW: "[floor] no real reviewer available -- deferring to the mechanical gates alone",
    Purpose.RESEARCH: "[floor] no real reviewer available -- nothing to record",
    Purpose.DECOMPOSE: "[floor] no real drafting intelligence available -- nothing planned",
    Purpose.REGROUND: "[floor] no real reviewer available -- assuming the plan is still valid",
    Purpose.CONSOLIDATE: "[floor] no real reviewer available -- consolidation skipped this cycle",
    Purpose.ENSEMBLE: "[floor] no real reviewer available -- nothing to record",
}


class FloorProvider:
    name = "floor"

    def available(self) -> bool:
        return True

    async def complete(
        self, messages: list[dict], *, tools: list[dict] | None, max_tokens: int, timeout: float = 0.0,
    ) -> ProviderResponse:
        return self.respond_for_purpose(Purpose.CHAT)

    def respond_for_purpose(self, purpose: Purpose) -> ProviderResponse:
        text = TEMPLATES.get(purpose, TEMPLATES[Purpose.CHAT])
        return ProviderResponse(text=text, provider=self.name, input_tokens=0, output_tokens=0, cost_usd=0.0)


__all__ = ["FloorProvider", "TEMPLATES"]
