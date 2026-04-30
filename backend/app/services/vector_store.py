"""Local vector store wrapper built on top of Chroma.

Purpose:
- Persist embeddings and retrieve relevant chunks for CyberGuide.

Inputs:
- Chunk ids, chunk text, embeddings and metadata.

Outputs:
- Stored records and ranked retrieval results.

Used by:
- `backend/app/main.py`
- `backend/app/services/rag.py`
- `scripts/ingest_corpus.py`
"""

from typing import Any

import chromadb
from chromadb.api.models.Collection import Collection

from ..config import Settings
from ..schemas import RetrievedChunk


class VectorStore:
    """Persistent Chroma-backed storage for the CyberGuide corpus."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(self.settings.chroma_dir))
        self.collection: Collection = self.client.get_or_create_collection(
            name=self.settings.chroma_collection,
            metadata={"description": "CyberGuide local knowledge base"},
        )

    def add_documents(
        self,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
    ) -> None:
        """Insert or update embedded chunks in the collection."""
        if not ids:
            return
        self.collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )

    def query(self, query_embedding: list[float], top_k: int) -> list[RetrievedChunk]:
        """Return the nearest chunks for a given query embedding."""
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        chunks: list[RetrievedChunk] = []
        for item_id, document, metadata, distance in zip(ids, documents, metadatas, distances):
            chunks.append(
                RetrievedChunk(
                    id=item_id,
                    text=document,
                    metadata=metadata or {},
                    distance=distance,
                )
            )
        return chunks

    def count(self) -> int:
        """Return the current number of stored chunks."""
        return self.collection.count()
