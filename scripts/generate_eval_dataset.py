"""Generate a synthetic benchmark dataset from the local CyberGuide corpus.

Purpose:
- Create question-answer evaluation cases derived from the ingested public corpus.

Inputs:
- Local source documents such as the INCIBE PDFs stored under `references/`.

Outputs:
- A JSONL dataset under `data/evals/` with questions, expected answers and source evidence.

Used by:
- Local validation and iterative benchmark creation for the TFG.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import re
from pathlib import Path
from typing import Any

from eval_shared import DEFAULT_CORPUS_ROOT, DEFAULT_EVAL_DIR, ensure_repo_root_on_path, ollama_chat_json, shorten_text, write_jsonl

ensure_repo_root_on_path()

from backend.app.config import get_settings
from backend.app.services.ingestion import load_source_manifest, load_source_register, prepare_chunks_from_file, supported_files
from scripts.ingest_corpus import resolve_source_url


GENERATOR_SYSTEM_PROMPT = """You generate evaluation cases for a cybersecurity RAG assistant.

Rules:
- Use only the provided excerpt.
- Write everything in Spanish.
- Generate answerable, concrete, grounded questions.
- Avoid trivia, document-title questions or meta questions.
- Avoid references to "the excerpt" or "the document".
- Keep expected answers concise but complete, using 1 to 3 short sentences.
- Evidence points must be concrete facts or recommendations from the excerpt, not section labels.
- Do not generate items from indexes, references pages, covers or dotted table-of-contents fragments.
- Return strict JSON with this shape:
  {
    "items": [
      {
        "question": "...",
        "expected_answer": "...",
        "evidence_points": ["...", "..."],
        "difficulty": "basic|intermediate"
      }
    ]
  }
"""

REJECTED_PATTERNS = (
    "índice",
    "indice",
    "2. referencias",
    "referencias",
    "checklist",
    "http://",
    "https://",
    "blog -",
    "blog-",
)


def build_case_id(chunk_id: str, question: str) -> str:
    """Build a stable case identifier from the source chunk and question."""
    digest = hashlib.sha1(f"{chunk_id}:{question}".encode("utf-8")).hexdigest()[:10]
    return f"eval-{digest}"


def is_eval_worthy_chunk(text: str) -> bool:
    """Return True when a chunk looks informative enough for evaluation generation."""
    normalized = text.lower()
    if any(pattern in normalized for pattern in REJECTED_PATTERNS):
        return False
    if re.search(r"\.{5,}", normalized):
        return False
    if len(re.findall(r"\[\d+\]", text)) >= 3:
        return False
    if len(re.findall(r"[.!?]", text)) < 2:
        return False
    if len(re.findall(r"[a-záéíóúñ]{4,}", normalized)) < 40:
        return False
    return True


async def generate_cases(
    *,
    root: Path,
    output: Path,
    max_chunks: int,
    questions_per_chunk: int,
    min_chars: int,
) -> dict[str, Any]:
    """Generate a synthetic evaluation dataset from selected corpus chunks."""
    settings = get_settings()
    source_register = load_source_register(settings)
    source_manifest = load_source_manifest(settings)

    prepared_chunks = []
    for path in supported_files(root):
        source_url = resolve_source_url(
            path=path,
            root=root,
            manifest=source_manifest,
            source_register=source_register,
        )
        prepared_chunks.extend(prepare_chunks_from_file(path, source_url=source_url))

    selected_chunks = [
        chunk
        for chunk in prepared_chunks
        if len(chunk.text) >= min_chars and is_eval_worthy_chunk(chunk.text)
    ][:max_chunks]

    rows: list[dict[str, Any]] = []
    for chunk in selected_chunks:
        prompt = f"""Create {questions_per_chunk} grounded evaluation items from this excerpt.

Document title: {chunk.metadata.get("title", "Unknown")}
Public source URL: {chunk.metadata.get("source_url", "")}
Excerpt:
\"\"\"
{shorten_text(chunk.text, limit=1600)}
\"\"\"
"""
        payload = await ollama_chat_json(
            base_url=settings.ollama_base_url,
            model=settings.ollama_chat_model,
            system_prompt=GENERATOR_SYSTEM_PROMPT,
            user_prompt=prompt,
        )
        items = payload.get("items", [])
        for item in items:
            question = (item.get("question") or "").strip()
            expected_answer = (item.get("expected_answer") or "").strip()
            evidence_points = item.get("evidence_points") or []
            difficulty = (item.get("difficulty") or "basic").strip().lower()

            if not question or not expected_answer:
                continue

            rows.append(
                {
                    "case_id": build_case_id(chunk.chunk_id, question),
                    "question": question,
                    "expected_answer": expected_answer,
                    "evidence_points": evidence_points,
                    "difficulty": difficulty,
                    "document_title": chunk.metadata.get("title", ""),
                    "source_url": chunk.metadata.get("source_url", ""),
                    "chunk_id": chunk.chunk_id,
                    "chunk_index": chunk.metadata.get("chunk_index"),
                    "chunk_text": chunk.text,
                    "generator_model": settings.ollama_chat_model,
                }
            )

    write_jsonl(output, rows)
    return {
        "output_path": str(output),
        "selected_chunks": len(selected_chunks),
        "generated_cases": len(rows),
        "generator_model": settings.ollama_chat_model,
    }


def main() -> None:
    """Parse CLI args and generate an evaluation dataset."""
    parser = argparse.ArgumentParser(description="Generate a synthetic evaluation dataset from the local corpus.")
    parser.add_argument("--root", type=Path, default=DEFAULT_CORPUS_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_EVAL_DIR / "generated_questions.jsonl")
    parser.add_argument("--max-chunks", type=int, default=18)
    parser.add_argument("--questions-per-chunk", type=int, default=2)
    parser.add_argument("--min-chars", type=int, default=500)
    args = parser.parse_args()

    report = asyncio.run(
        generate_cases(
            root=args.root,
            output=args.output,
            max_chunks=args.max_chunks,
            questions_per_chunk=args.questions_per_chunk,
            min_chars=args.min_chars,
        )
    )
    print(report)


if __name__ == "__main__":
    main()
