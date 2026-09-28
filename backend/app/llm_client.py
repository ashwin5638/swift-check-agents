"""
Minimal client for any OpenAI-compatible /chat/completions endpoint
(Groq or xAI, selected by which key is present in .env).

Kept separate from the agents so every agent enforces the same
"Caveman Standard" (JSON-only, no filler) at the transport layer, not
just via prompt string luck.
"""

import json
from typing import Any

import httpx

from app.config import settings

CAVEMAN_SYSTEM_SUFFIX = (
    " Output JSON only. No pleasantries, no markdown fences, "
    "no explanations, no preamble. Your entire response must be "
    "a single valid JSON object."
)


class LLMClient:
    def __init__(self) -> None:
        if not settings.llm_api_key:
            key_name = "GROQ_API_KEY" if settings.llm_provider == "groq" else "GROK_API_KEY"
            raise RuntimeError(
                f"{key_name} is not set. Add it to backend/.env"
            )
        self._client = httpx.Client(
            base_url=settings.llm_base_url,
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            timeout=60.0,
        )

    def json_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.4,
    ) -> dict[str, Any]:
        """Call the LLM and force-parse a JSON object back out of it."""
        payload = {
            "model": settings.llm_model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt + CAVEMAN_SYSTEM_SUFFIX},
                {"role": "user", "content": user_prompt},
            ],
        }
        resp = self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()

        # Strip stray markdown fences if the model ignores instructions.
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        return json.loads(raw)

    def close(self) -> None:
        self._client.close()


_client: LLMClient | None = None


def get_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
