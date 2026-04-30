"""Corpus ingestion helpers for local text-based sources.

Purpose:
- Read supported files, normalize content and prepare chunks for embedding.

Inputs:
- Files stored under `data/raw/`.
- Optional source metadata stored in `references/source-register.csv`.

Outputs:
- Prepared chunks with metadata ready for vectorization.

Used by:
- `scripts/ingest_corpus.py`
"""

from __future__ import annotations

import hashlib
import json
import re
from csv import DictReader
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Optional, Union

from pypdf import PdfReader

from ..config import Settings


SUPPORTED_EXTENSIONS = {".txt", ".md", ".html", ".htm", ".pdf"}


@dataclass
class PreparedChunk:
    chunk_id: str
    text: str
    metadata: dict[str, Union[str, int]]


def _strip_html(text: str) -> str:
    """Remove simple HTML tags before chunking."""
    return re.sub(r"<[^>]+>", " ", text)


def _normalize_whitespace(text: str) -> str:
    """Collapse repeated whitespace into a compact plain-text form."""
    return re.sub(r"\s+", " ", text).strip()


def read_supported_file(path: Path) -> str:
    """Load and normalize a supported local corpus file."""
    if path.suffix.lower() == ".pdf":
        return read_pdf_file(path)

    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".html", ".htm"}:
        text = _strip_html(text)
    return _normalize_whitespace(text)


def read_pdf_file(path: Path) -> str:
    """Extract and normalize plain text from a PDF file."""
    reader = PdfReader(str(path))
    return _extract_text_from_pdf_reader(reader)


def read_pdf_bytes(data: bytes) -> str:
    """Extract and normalize plain text from PDF bytes."""
    reader = PdfReader(BytesIO(data))
    return _extract_text_from_pdf_reader(reader)


def _extract_text_from_pdf_reader(reader: PdfReader) -> str:
    """Collect text from a PDF reader instance and normalize it."""
    text_parts: list[str] = []
    for page in reader.pages:
        page_text = page.extract_text() or ""
        if page_text.strip():
            text_parts.append(page_text)
    return _normalize_whitespace("\n".join(text_parts))


def chunk_text(
    text: str,
    *,
    chunk_size: int = 900,
    chunk_overlap: int = 150,
) -> list[str]:
    """Split a document into overlapping chunks suitable for retrieval."""
    if not text.strip():
        return []

    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        start = max(end - chunk_overlap, start + 1)
    return chunks


def prepare_chunks_from_file(path: Path, source_url: Optional[str] = None) -> list[PreparedChunk]:
    """Convert a local file into chunk records with stable metadata."""
    text = read_supported_file(path)
    title = path.stem.replace("_", " ").replace("-", " ").strip()
    return prepare_chunks_from_text(
        text=text,
        document_key=str(path),
        title=title,
        source_url=source_url,
    )


def prepare_chunks_from_text(
    *,
    text: str,
    document_key: str,
    title: str,
    source_url: Optional[str] = None,
) -> list[PreparedChunk]:
    """Convert plain text into prepared chunk records with stable metadata."""
    chunks = chunk_text(text)

    prepared: list[PreparedChunk] = []
    for idx, chunk in enumerate(chunks, start=1):
        digest = hashlib.sha1(f"{document_key}:{idx}:{chunk}".encode("utf-8")).hexdigest()[:12]
        prepared.append(
            PreparedChunk(
                chunk_id=f"{title.replace(' ', '-').lower()}-{idx}-{digest}",
                text=chunk,
                metadata={
                    "title": title,
                    "path": document_key,
                    "source_url": source_url or "",
                    "chunk_index": idx,
                },
            )
        )
    return prepared


def load_source_manifest(settings: Settings) -> dict[str, str]:
    """Load the optional mapping between local files and original public URLs."""
    manifest_path = settings.processed_data_dir / "source_manifest.json"
    if not manifest_path.exists():
        return {}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def load_source_register(settings: Settings) -> dict[str, str]:
    """Load URL mappings from the local bibliography/source register."""
    register_path = settings.references_dir / "source-register.csv"
    if not register_path.exists():
        return {}

    mappings: dict[str, str] = {}
    with register_path.open("r", encoding="utf-8", newline="") as handle:
        reader = DictReader(handle)
        for row in reader:
            local_file = (row.get("local_file") or "").strip()
            source_url = (row.get("url") or "").strip()
            if local_file and source_url:
                mappings[local_file] = source_url
                mappings[Path(local_file).name] = source_url
    return mappings


def supported_files(root: Path) -> list[Path]:
    """Return every currently supported corpus file under the given root."""
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )
