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

from typing import Any

import httpx

from ..config import Settings


class OllamaClient:
    """Thin async wrapper around the local Ollama HTTP API."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embedding vectors for a batch of texts."""
        async with httpx.AsyncClient(base_url=self.settings.ollama_base_url, timeout=120.0) as client:
            response = await client.post(
                "/api/embed",
                json={
                    "model": self.settings.ollama_embed_model,
                    "input": texts,
                },
            )
            response.raise_for_status()
            payload = response.json()
            return payload["embeddings"]

    async def chat(self, system_prompt: str, user_prompt: str) -> str:
        """Generate a grounded answer using the configured local chat model."""
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
            return payload["message"]["content"].strip()
