"""Shared helpers for the CyberGuide evaluation pipeline.

Purpose:
- Reuse common path, JSONL and local Ollama helpers across evaluation scripts.

Inputs:
- Local corpus files, generated JSONL datasets and local Ollama responses.

Outputs:
- Reusable parsed objects and persisted JSONL/JSON evaluation artifacts.

Used by:
- `scripts/generate_eval_dataset.py`
- `scripts/run_eval_benchmark.py`
- `scripts/judge_eval_results.py`
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import httpx


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS_ROOT = REPO_ROOT / "references" / "incibe-pdfs"
DEFAULT_EVAL_DIR = REPO_ROOT / "data" / "evals"


def ensure_repo_root_on_path() -> None:
    """Allow direct execution of scripts from the repository root or subfolders."""
    # Scripts are meant to be runnable directly, so we add the repo root before
    # importing backend modules that live outside the script directory.
    repo_root_str = str(REPO_ROOT)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load JSONL rows from disk."""
    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Persist JSONL rows to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Persist a JSON document to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_model_json(raw_text: str) -> dict[str, Any]:
    """Extract and parse a JSON object from a local-model response."""
    # Local models often wrap JSON in fences or extra prose, so strip the
    # response down to the first valid JSON block before parsing it.
    text = raw_text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", text, flags=re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    start = min((index for index in (text.find("{"), text.find("[")) if index != -1), default=-1)
    end_object = text.rfind("}")
    end_array = text.rfind("]")
    end = max(end_object, end_array)

    if start == -1 or end == -1 or end < start:
        raise ValueError(f"Could not find JSON payload in model output: {raw_text[:400]}")

    return json.loads(text[start : end + 1])


async def ollama_chat_json(
    *,
    base_url: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout: float = 180.0,
) -> dict[str, Any]:
    """Request a JSON response from the local Ollama chat endpoint."""
    # This helper keeps the generation and judge scripts fully local by using
    # the same Ollama endpoint everywhere.
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
        response = await client.post(
            "/api/chat",
            json={
                "model": model,
                "stream": False,
                "format": "json",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                # Deterministic decoding so dataset generation and judging are
                # reproducible across runs and version-to-version deltas are real.
                "options": {"temperature": 0, "seed": 42},
            },
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["message"]["content"].strip()
        return normalize_model_json(content)


def shorten_text(text: str, limit: int = 1200) -> str:
    """Trim a text block to a predictable maximum length."""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."

