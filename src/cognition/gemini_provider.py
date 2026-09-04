"""Gemini provider for CognitionRouter.

Wraps Google's Gen AI Python SDK (`google-genai`), calling the *stable*
generateContent surface -- not the beta Interactions API, per Google's own
guidance to use generateContent for production.

The API key is read only from the GEMINI_API_KEY or GOOGLE_API_KEY
environment variable (or an explicitly injected value, for tests) -- it is
never hardcoded, logged, or written to any file this codebase creates. See
docs/SOUL.md and the security discussion around this provider's addition.

This provider must always be wrapped in src/cognition/budget.BudgetGuard
before being registered in a CognitionRouter -- see docs/EVOLUTION.md,
"Resilience Doctrine," point 5. src/main.py's build_cognition_router()
does this by default.
"""

from __future__ import annotations

import os
from typing import Any

from src.cognition.provider import LLMProvider, LLMResponse, ProviderUnavailable

DEFAULT_MODEL = "gemini-3.8-flash"


class GeminiProvider(LLMProvider):
    """Calls Gemini's stable generateContent API via the google-genai SDK.

    The real SDK client is constructed lazily, on first use -- not at
    construction -- so importing or instantiating this class never
    requires the `google-genai` package to be installed unless it's
    actually called. A `client` can be injected directly (tests use this
    to avoid any real network call or SDK dependency).
    """

    name = "gemini"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        client: Any | None = None,
    ) -> None:
        self._api_key = (
            api_key
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
        )
        self._model = model
        self._client = client

    def available(self) -> bool:
        return bool(self._api_key)

    def complete(self, prompt: str, **kwargs: Any) -> LLMResponse:
        if not self._api_key:
            raise ProviderUnavailable("no Gemini API key configured (GEMINI_API_KEY)")

        try:
            client = self._get_client()
            response = client.models.generate_content(model=self._model, contents=prompt)
        except Exception as exc:  # noqa: BLE001 -- any failure here (a
            # missing google-genai install, a network error, an API error,
            # etc.) must degrade to the next provider, never crash the
            # caller -- this used to only wrap the API call, not client
            # construction/import, which let ImportError escape uncaught
            raise ProviderUnavailable(f"Gemini request failed: {exc!r}") from exc

        usage = getattr(response, "usage_metadata", None)
        metadata = {
            "input_tokens": (getattr(usage, "prompt_token_count", 0) or 0) if usage else 0,
            "output_tokens": (
                (getattr(usage, "candidates_token_count", 0) or 0) if usage else 0
            ),
        }
        return LLMResponse(
            text=getattr(response, "text", None) or "",
            provider_name=self.name,
            metadata=metadata,
        )

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai  # optional dependency, imported lazily

            self._client = genai.Client(api_key=self._api_key)
        return self._client
