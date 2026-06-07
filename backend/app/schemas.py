"""Pydantic schemas used by the CyberGuide backend API.

Purpose:
- Define request and response models for the first local backend version.

Inputs:
- API payloads and internal service outputs.

Outputs:
- Validated data structures shared across routes and services.

Used by:
- `backend/app/main.py`
- `backend/app/services/rag.py`
- `scripts/ingest_corpus.py`
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    message: str = Field(..., min_length=3, description="User query")
    top_k: int = Field(default=4, ge=1, le=10)
    session_id: Optional[str] = None


class ConversationTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1)


class TraceStep(BaseModel):
    title: str
    detail: str


class ResponseTrace(BaseModel):
    summary: str
    steps: list[TraceStep]
    retrieved_candidates: int = 0
    curated_candidates: int = 0
    intent: Optional[str] = None
    evidence_policy: Optional[str] = None
    dialogue_goal: Optional[str] = None
    response_shape: Optional[str] = None
    response_strategy: Optional[str] = None
    answer_mode: Optional[str] = None
    follow_up_policy: Optional[str] = None
    needs_clarification: bool = False
    active_document: Optional[str] = None
    history_turns: int = 0
    ocr_segments: int = 0
    safety_mode: bool = False
    risk_signals: list[str] = Field(default_factory=list)
    selected_chunk_refs: list[str] = Field(default_factory=list)
    retrieval_ms: float = 0.0
    embedding_ms: float = 0.0
    generation_ms: float = 0.0
    total_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_external_cost_eur: float = 0.0
    local_execution: bool = True
    local_execution_note: Optional[str] = None
    cost_measurement_note: Optional[str] = None


class RetrievedChunk(BaseModel):
    id: str
    text: str
    metadata: dict[str, Any]
    distance: Optional[float] = None


class QueryResponse(BaseModel):
    answer: str
    sources: list[RetrievedChunk]
    model: str
    mode: str = "corpus"
    session_id: str
    document_title: Optional[str] = None
    trace: Optional[ResponseTrace] = None


class HealthResponse(BaseModel):
    status: str
    app_name: str
    version: str
    chat_model: str
    embed_model: str


class IngestReport(BaseModel):
    processed_files: int
    processed_chunks: int
    collection: str
