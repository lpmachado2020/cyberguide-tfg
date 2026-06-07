"""Minimal Ollama client for local generation and embeddings.

Purpose:
- Encapsulate HTTP calls to the local Ollama server.

Inputs:
- Plain text for embeddings or chat messages for generation.

Outputs:
- Embedding vectors or generated assistant text.

Used by:
- `backend/app/services/rag.py`
- `scripts/ingest_corpus.py`
"""

from dataclasses import dataclass
from typing import Any

import httpx

from ..config import Settings


@dataclass
class EmbedResult:
    """Embeddings plus lightweight runtime metadata returned by Ollama."""

    embeddings: list[list[float]]
    total_duration_ms: float = 0.0


@dataclass
class ChatResult:
    """Generated assistant text plus Ollama token/runtime metadata."""

    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    total_duration_ms: float = 0.0
    load_duration_ms: float = 0.0
    prompt_eval_duration_ms: float = 0.0
    eval_duration_ms: float = 0.0


class OllamaClient:
    """Thin async wrapper around the local Ollama HTTP API."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embedding vectors for a batch of texts."""
        result = await self.embed_with_metrics(texts)
        return result.embeddings

    async def embed_with_metrics(self, texts: list[str]) -> EmbedResult:
        """Generate embeddings and capture any runtime metadata returned by Ollama."""
        async with httpx.AsyncClient(base_url=self.settings.ollama_base_url, timeout=120.0) as client:
            response = await client.post(
                "/api/embed",
                json={
                    "model": self.settings.ollama_embed_model,
                    "input": texts,
                },
            )
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
            return EmbedResult(
                embeddings=payload["embeddings"],
                total_duration_ms=_ns_to_ms(payload.get("total_duration")),
            )

    async def chat(self, system_prompt: str, user_prompt: str) -> str:
        """Generate a grounded answer using the configured local chat model."""
        result = await self.chat_with_metrics(system_prompt=system_prompt, user_prompt=user_prompt)
        return result.content

    async def chat_with_metrics(self, *, system_prompt: str, user_prompt: str) -> ChatResult:
        """Generate an answer and capture Ollama token/runtime metadata."""
        async with httpx.AsyncClient(base_url=self.settings.ollama_base_url, timeout=180.0) as client:
            response = await client.post(
                "/api/chat",
                json={
                    "model": self.settings.ollama_chat_model,
                    "stream": False,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
            )
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
            prompt_tokens = int(payload.get("prompt_eval_count") or 0)
            completion_tokens = int(payload.get("eval_count") or 0)
            return ChatResult(
                content=payload["message"]["content"].strip(),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                total_duration_ms=_ns_to_ms(payload.get("total_duration")),
                load_duration_ms=_ns_to_ms(payload.get("load_duration")),
                prompt_eval_duration_ms=_ns_to_ms(payload.get("prompt_eval_duration")),
                eval_duration_ms=_ns_to_ms(payload.get("eval_duration")),
            )


def _ns_to_ms(value: Any) -> float:
    """Convert Ollama nanosecond durations to milliseconds when available."""
    if value is None:
        return 0.0
    try:
        return float(value) / 1_000_000.0
    except (TypeError, ValueError):
        return 0.0
