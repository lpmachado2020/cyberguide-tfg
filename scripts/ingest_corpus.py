"""Command-line corpus ingestion entrypoint for CyberGuide.

Purpose:
- Read raw local files, generate embeddings and populate the Chroma collection.

Inputs:
- Files stored under `data/raw/` or a custom directory passed with `--root`.

Outputs:
- A JSON ingestion report printed to stdout.

Used by:
- Local development and corpus refresh workflows.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from backend.app.config import get_settings
from backend.app.schemas import IngestReport
from backend.app.services.ingestion import (
    load_source_manifest,
    load_source_register,
    prepare_chunks_from_file,
    supported_files,
)
from backend.app.services.ollama_client import OllamaClient
from backend.app.services.vector_store import VectorStore


async def ingest(root: Path) -> IngestReport:
    """Embed and store every supported file found under the target directory."""
    settings = get_settings()
    ollama_client = OllamaClient(settings)
    vector_store = VectorStore(settings)
    manifest = load_source_manifest(settings)
    source_register = load_source_register(settings)

    files = supported_files(root)
    processed_files = 0
    processed_chunks = 0

    for path in files:
        source_url = resolve_source_url(
            path=path,
            root=root,
            manifest=manifest,
            source_register=source_register,
        )
        prepared_chunks = prepare_chunks_from_file(
            path,
            source_url=source_url,
        )
        if not prepared_chunks:
            continue

        embeddings = await ollama_client.embed([chunk.text for chunk in prepared_chunks])
        vector_store.add_documents(
            ids=[chunk.chunk_id for chunk in prepared_chunks],
            documents=[chunk.text for chunk in prepared_chunks],
            embeddings=embeddings,
            metadatas=[chunk.metadata for chunk in prepared_chunks],
        )
        processed_files += 1
        processed_chunks += len(prepared_chunks)

    return IngestReport(
        processed_files=processed_files,
        processed_chunks=processed_chunks,
        collection=settings.chroma_collection,
    )


def resolve_source_url(
    *,
    path: Path,
    root: Path,
    manifest: dict[str, str],
    source_register: dict[str, str],
) -> str | None:
    """Resolve the public source URL for a local file when known."""
    keys = [
        str(path),
        path.name,
    ]

    try:
        keys.append(str(path.relative_to(root)))
    except ValueError:
        pass

    for key in keys:
        if key in source_register:
            return source_register[key]
        if key in manifest:
            return manifest[key]
    return None


def main() -> None:
    """Parse CLI arguments and run corpus ingestion."""
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Ingest local corpus into Chroma.")
    parser.add_argument(
        "--root",
        type=Path,
        default=settings.raw_data_dir,
        help="Directory containing raw corpus files.",
    )
    args = parser.parse_args()

    report = asyncio.run(ingest(args.root))
    print(json.dumps(report.model_dump(), ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
