"""RAG orchestration service for CyberGuide.

Purpose:
- Coordinate embedding, retrieval and grounded answer generation.

Inputs:
- A validated user query.

Outputs:
- A final response plus supporting source chunks.

Used by:
- `backend/app/main.py`
"""

import re

from typing import Optional

from ..config import Settings
from ..prompting import SYSTEM_PROMPT, build_user_prompt, is_narrow_fact_question
from ..schemas import ConversationTurn, QueryRequest, QueryResponse, ResponseTrace, RetrievedChunk, TraceStep
from .ingestion import PreparedChunk
from .ollama_client import OllamaClient
from .security_policy import (
    SafetyAssessment,
    assess_content_risk,
    build_cautious_answer,
    contains_unsafe_advice,
)
from .session_store import SessionStore
from .vector_store import VectorStore


class RagService:
    """High-level service that runs the local RAG workflow."""

    REJECTED_PATTERNS = (
        "2. referencias",
        "referencias [",
        "índice",
        "indice",
        "page 1 of",
    )
    MAX_RELEVANT_DISTANCE = 0.82
    LENIENT_FACT_DISTANCE = 0.9
    FACT_STOPWORDS = {
        "a",
        "al",
        "ante",
        "como",
        "con",
        "cual",
        "cuales",
        "cuál",
        "cuáles",
        "cuando",
        "cuándo",
        "de",
        "del",
        "donde",
        "dónde",
        "el",
        "en",
        "es",
        "esta",
        "este",
        "la",
        "las",
        "lo",
        "los",
        "para",
        "por",
        "que",
        "qué",
        "se",
        "son",
        "su",
        "sus",
        "un",
        "una",
        "y",
    }

    def __init__(
        self,
        settings: Settings,
        ollama_client: OllamaClient,
        vector_store: VectorStore,
        session_store: SessionStore,
    ) -> None:
        self.settings = settings
        self.ollama_client = ollama_client
        self.vector_store = vector_store
        self.session_store = session_store

    async def answer(self, request: QueryRequest) -> QueryResponse:
        """Answer a user query using local retrieval plus the chat model."""
        session_id, _ = self.session_store.get_or_create(request.session_id)
        history = self.session_store.get_recent_history(session_id)
        retrieval_query = self._build_retrieval_query(
            question=request.message,
            history=history,
        )
        query_embedding = (await self.ollama_client.embed([retrieval_query]))[0]
        factual_mode = is_narrow_fact_question(request.message)
        retrieved_chunks = self.vector_store.query(
            query_embedding=query_embedding,
            top_k=3 if factual_mode else request.top_k,
        )

        curated_chunks = self._curate_chunks(
            retrieved_chunks,
            max_chunks_override=2 if factual_mode else None,
        )
        if factual_mode:
            curated_chunks = self._rerank_fact_chunks(request.message, curated_chunks)
        if not curated_chunks and factual_mode:
            fallback_chunk = self._build_lenient_fact_fallback(retrieved_chunks)
            if fallback_chunk:
                curated_chunks = [fallback_chunk]
        if not curated_chunks:
            answer = (
                "Todavia no tengo contexto suficiente en el corpus local para responder "
                "con fiabilidad. Necesito que carguemos fuentes relevantes antes de "
                "dar una orientacion fundamentada."
            )
            return QueryResponse(
                answer=answer,
                sources=[],
                model=self.settings.ollama_chat_model,
                mode="corpus",
                session_id=session_id,
                trace=self._build_trace(
                    mode="corpus",
                    retrieved_candidates=len(retrieved_chunks),
                    curated_candidates=0,
                    history=history,
                    document_title=None,
                    note="No relevant evidence was found in the persistent local corpus.",
                ),
            )

        answer = await self._generate_answer(
            question=request.message,
            chunks=curated_chunks,
            history=history,
        )
        self._store_turn_pair(session_id=session_id, question=request.message, answer=answer)
        return QueryResponse(
            answer=answer,
            sources=curated_chunks,
            model=self.settings.ollama_chat_model,
            mode="corpus",
            session_id=session_id,
            trace=self._build_trace(
                mode="corpus",
                retrieved_candidates=len(retrieved_chunks),
                curated_candidates=len(curated_chunks),
                history=history,
                document_title=None,
                note="Persistent corpus retrieval was used to ground the final answer.",
            ),
        )

    async def answer_with_pdf(
        self,
        *,
        session_id: Optional[str],
        question: str,
        prepared_chunks: Optional[list[PreparedChunk]],
        title: Optional[str],
    ) -> QueryResponse:
        """Answer a user query using only the chunks extracted from an uploaded PDF."""
        return await self.answer_with_document(
            mode="pdf",
            session_id=session_id,
            question=question,
            prepared_chunks=prepared_chunks,
            title=title,
        )

    async def answer_with_image(
        self,
        *,
        session_id: Optional[str],
        question: str,
        prepared_chunks: Optional[list[PreparedChunk]],
        title: Optional[str],
        ocr_segments: int = 0,
    ) -> QueryResponse:
        """Answer a user query using OCR text extracted from an uploaded image."""
        return await self.answer_with_document(
            mode="image",
            session_id=session_id,
            question=question,
            prepared_chunks=prepared_chunks,
            title=title,
            ocr_segments=ocr_segments,
        )

    async def answer_with_document(
        self,
        *,
        mode: str,
        session_id: Optional[str],
        question: str,
        prepared_chunks: Optional[list[PreparedChunk]],
        title: Optional[str],
        ocr_segments: int = 0,
    ) -> QueryResponse:
        """Answer a query using the active uploaded document or OCR image session."""
        normalized_session_id, _ = self.session_store.get_or_create(session_id)
        history = self.session_store.get_recent_history(normalized_session_id)
        active_title, stored_chunks = self.session_store.get_document(normalized_session_id)

        effective_chunks = prepared_chunks if prepared_chunks is not None else stored_chunks
        fallback_title = "uploaded image" if mode == "image" else "uploaded pdf"
        effective_title = title or active_title or fallback_title
        extracted_text = "\n".join(chunk.text for chunk in effective_chunks) if effective_chunks else ""
        safety_assessment = assess_content_risk(
            question=question,
            content=extracted_text,
            mode=mode,
        )

        if prepared_chunks:
            self.session_store.set_document(
                normalized_session_id,
                title=effective_title,
                chunks=prepared_chunks,
            )

        if not effective_chunks:
            return QueryResponse(
                answer=(
                    "No tengo un documento activo en esta conversación. Sube un PDF o una imagen "
                    "para que pueda analizarlo y mantener el contexto en los siguientes turnos."
                ),
                sources=[],
                model=self.settings.ollama_chat_model,
                mode=mode,
                session_id=normalized_session_id,
                document_title=None,
                trace=self._build_trace(
                    mode=mode,
                    retrieved_candidates=0,
                    curated_candidates=0,
                    history=history,
                    document_title=None,
                    note="The request expected a session-scoped uploaded document, but no active document was available.",
                    ocr_segments=ocr_segments,
                    safety_assessment=safety_assessment,
                ),
            )

        retrieval_query = self._build_retrieval_query(
            question=question,
            history=history,
            document_title=effective_title,
        )
        query_embedding = (await self.ollama_client.embed([retrieval_query]))[0]
        chunk_embeddings = await self.ollama_client.embed([chunk.text for chunk in effective_chunks])

        scored_chunks: list[RetrievedChunk] = []
        for prepared_chunk, embedding in zip(effective_chunks, chunk_embeddings):
            distance = self._cosine_distance(query_embedding, embedding)
            scored_chunks.append(
                RetrievedChunk(
                    id=prepared_chunk.chunk_id,
                    text=prepared_chunk.text,
                    metadata=prepared_chunk.metadata,
                    distance=distance,
                )
            )

        scored_chunks.sort(key=lambda item: item.distance if item.distance is not None else 999.0)
        factual_mode = is_narrow_fact_question(question)
        curated_chunks = self._curate_chunks(
            scored_chunks,
            max_chunks_override=2 if factual_mode else None,
        )
        if factual_mode:
            curated_chunks = self._rerank_fact_chunks(question, curated_chunks)
        if not curated_chunks and factual_mode:
            fallback_chunk = self._build_lenient_fact_fallback(scored_chunks)
            if fallback_chunk:
                curated_chunks = [fallback_chunk]
        if not curated_chunks:
            return QueryResponse(
                answer=(
                    f"He leído el PDF \"{effective_title}\", pero no he encontrado fragmentos suficientemente "
                    "relevantes para responder con fiabilidad a esta pregunta."
                    if mode == "pdf"
                    else f"He procesado la imagen \"{effective_title}\", pero no he encontrado fragmentos suficientemente "
                    "relevantes para responder con fiabilidad a esta pregunta."
                ),
                sources=[],
                model=self.settings.ollama_chat_model,
                mode=mode,
                session_id=normalized_session_id,
                document_title=effective_title,
                trace=self._build_trace(
                    mode=mode,
                    retrieved_candidates=len(scored_chunks),
                    curated_candidates=0,
                    history=history,
                    document_title=effective_title,
                    note=(
                        "A PDF was active, but the retrieved chunks were too weak or too noisy for a grounded answer."
                        if mode == "pdf"
                        else "An OCR image was active, but the retrieved chunks were too weak or too noisy for a grounded answer."
                    ),
                    ocr_segments=ocr_segments,
                    safety_assessment=safety_assessment,
                ),
            )

        if safety_assessment.cautious_mode:
            answer = build_cautious_answer(
                question=question,
                document_title=effective_title,
                extracted_excerpt=curated_chunks[0].text[:220] if curated_chunks else "",
                signals=safety_assessment.signals,
            )
        else:
            answer = await self._generate_answer(
                question=question,
                chunks=curated_chunks,
                history=history,
                document_title=effective_title,
                safety_assessment=safety_assessment,
            )
            if contains_unsafe_advice(answer):
                answer = build_cautious_answer(
                    question=question,
                    document_title=effective_title,
                    extracted_excerpt=curated_chunks[0].text[:220] if curated_chunks else "",
                    signals=safety_assessment.signals,
                )
        self._store_turn_pair(
            session_id=normalized_session_id,
            question=question,
            answer=answer,
        )
        return QueryResponse(
            answer=answer,
            sources=curated_chunks,
            model=self.settings.ollama_chat_model,
            mode=mode,
            session_id=normalized_session_id,
            document_title=effective_title,
            trace=self._build_trace(
                mode=mode,
                retrieved_candidates=len(scored_chunks),
                curated_candidates=len(curated_chunks),
                history=history,
                document_title=effective_title,
                note=(
                    "The answer was grounded in the active uploaded PDF stored for this conversation."
                    if mode == "pdf"
                    else "The answer was grounded in OCR text extracted from the active uploaded image."
                ),
                ocr_segments=ocr_segments,
                safety_assessment=safety_assessment,
            ),
        )

    def _curate_chunks(
        self,
        chunks: list[RetrievedChunk],
        *,
        max_chunks_override: Optional[int] = None,
    ) -> list[RetrievedChunk]:
        """Filter noisy retrievals and trim the remaining chunks for prompting."""
        curated: list[RetrievedChunk] = []
        limit = max_chunks_override or self.settings.max_context_chunks
        for chunk in chunks:
            if self._is_low_value_chunk(chunk):
                continue
            if chunk.distance is not None and chunk.distance > self.MAX_RELEVANT_DISTANCE:
                continue
            chunk.text = chunk.text[: self.settings.max_context_chars_per_chunk]
            curated.append(chunk)
            if len(curated) >= limit:
                break
        return curated

    def _is_low_value_chunk(self, chunk: RetrievedChunk) -> bool:
        """Return True when a chunk looks like index/reference noise instead of evidence."""
        normalized = chunk.text.lower()
        return any(pattern in normalized for pattern in self.REJECTED_PATTERNS)

    def _rerank_fact_chunks(self, question: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """Prioritize chunks whose wording overlaps more directly with a narrow factual question."""
        keywords = self._extract_fact_keywords(question)
        if not keywords:
            return chunks

        scored: list[tuple[float, RetrievedChunk]] = []
        for chunk in chunks:
            overlap = sum(1 for keyword in keywords if keyword in chunk.text.lower())
            score = float(overlap)
            if ":" in chunk.text:
                score += 0.15
            if chunk.distance is not None:
                score += max(0.0, 1.0 - chunk.distance)
            scored.append((score, chunk))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [chunk for _, chunk in scored]

    def _build_lenient_fact_fallback(self, chunks: list[RetrievedChunk]) -> Optional[RetrievedChunk]:
        """Keep the best still-usable chunk when strict curation would otherwise over-reject."""
        for chunk in chunks:
            if self._is_low_value_chunk(chunk):
                continue
            if chunk.distance is not None and chunk.distance <= self.LENIENT_FACT_DISTANCE:
                fallback = chunk.model_copy(deep=True)
                fallback.text = fallback.text[: self.settings.max_context_chars_per_chunk]
                return fallback
        return None

    def _extract_fact_keywords(self, question: str) -> set[str]:
        """Extract content-bearing words from a factual query for lightweight reranking."""
        tokens = re.findall(r"[a-záéíóúñ0-9]{3,}", question.lower())
        return {token for token in tokens if token not in self.FACT_STOPWORDS}

    async def _generate_answer(
        self,
        *,
        question: str,
        chunks: list[RetrievedChunk],
        history: Optional[list[ConversationTurn]] = None,
        document_title: Optional[str] = None,
        safety_assessment: Optional[SafetyAssessment] = None,
    ) -> str:
        """Generate the final assistant answer from the curated evidence."""
        prompt = build_user_prompt(
            question,
            chunks,
            history=history,
            document_title=document_title,
            safety_assessment=safety_assessment,
        )
        return await self.ollama_client.chat(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=prompt,
        )

    def _build_retrieval_query(
        self,
        *,
        question: str,
        history: Optional[list[ConversationTurn]] = None,
        document_title: Optional[str] = None,
    ) -> str:
        """Expand short follow-up questions with recent local conversation context."""
        relevant_turns = history[-4:] if history else []
        history_lines = [f"{turn.role}: {turn.content}" for turn in relevant_turns]
        history_block = "\n".join(history_lines)
        document_line = f"document: {document_title}\n" if document_title else ""
        return f"{document_line}{history_block}\ncurrent question: {question}".strip()

    def _store_turn_pair(self, *, session_id: str, question: str, answer: str) -> None:
        """Persist the user question and assistant answer after one completed turn."""
        self.session_store.append_turn(session_id, "user", question)
        self.session_store.append_turn(session_id, "assistant", answer)

    def _build_trace(
        self,
        *,
        mode: str,
        retrieved_candidates: int,
        curated_candidates: int,
        history: list[ConversationTurn],
        document_title: Optional[str],
        note: str,
        ocr_segments: int = 0,
        safety_assessment: Optional[SafetyAssessment] = None,
    ) -> ResponseTrace:
        """Summarize the visible processing steps without exposing raw model reasoning."""
        steps = [
            TraceStep(
                title="Conversation context",
                detail=(
                    f"Recovered {len(history)} prior turn(s) from the current local session."
                    if history
                    else "No prior turns were available for this request."
                ),
            ),
            TraceStep(
                title="Grounding source",
                detail=(
                    f"Used the active uploaded PDF: {document_title}."
                    if mode == "pdf" and document_title
                    else f"Used OCR text extracted from the active uploaded image: {document_title}."
                    if mode == "image" and document_title
                    else "Used the persistent local INCIBE corpus stored in Chroma."
                ),
            ),
            TraceStep(
                title="Evidence retrieval",
                detail=(
                    f"Retrieved {retrieved_candidates} candidate chunk(s) and kept {curated_candidates} "
                    "after filtering noise and low-value matches."
                ),
            ),
            TraceStep(
                title="Answer synthesis",
                detail="Built the final answer only from the curated evidence and the active conversation context.",
            ),
        ]
        if mode == "image":
            steps.insert(
                2,
                TraceStep(
                    title="OCR extraction",
                    detail=(
                        f"Extracted {ocr_segments} text segment(s) from the uploaded image before retrieval."
                        if ocr_segments
                        else "Reused OCR text from the active uploaded image without running OCR again in this turn."
                    ),
                ),
            )
        if safety_assessment and safety_assessment.cautious_mode:
            steps.insert(
                1,
                TraceStep(
                    title="Safety policy",
                    detail=(
                        "Activated a cautious-response policy because the uploaded content contains "
                        f"sensitive interaction signals: {', '.join(safety_assessment.signals)}."
                    ),
                ),
            )
        return ResponseTrace(
            summary=note,
            steps=steps,
            retrieved_candidates=retrieved_candidates,
            curated_candidates=curated_candidates,
            active_document=document_title,
            history_turns=len(history),
            ocr_segments=ocr_segments,
            safety_mode=bool(safety_assessment and safety_assessment.cautious_mode),
            risk_signals=safety_assessment.signals if safety_assessment else [],
        )

    def _cosine_distance(self, a: list[float], b: list[float]) -> float:
        """Compute cosine distance between two embedding vectors."""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(y * y for y in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 1.0
        similarity = dot / (norm_a * norm_b)
        return 1.0 - similarity
