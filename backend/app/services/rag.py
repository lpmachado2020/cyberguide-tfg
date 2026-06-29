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

import json
import re
from time import perf_counter
from datetime import datetime, timezone

from typing import Optional

from ..dialogue import classify_dialogue_goal
from ..intents import build_default_profile, classify_intent
from ..config import Settings
from ..prompting import (
    build_system_prompt,
    build_user_prompt,
    is_follow_up_question,
    is_list_question,
    is_narrow_fact_question,
)
from ..schemas import ConversationTurn, QueryRequest, QueryResponse, ResponseTrace, RetrievedChunk, TraceStep
from ..strategy import classify_response_strategy
from .ingestion import PreparedChunk
from .ollama_client import ChatResult, EmbedResult, OllamaClient
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
        "más información al respecto",
        "mas información al respecto",
        "mas informacion al respecto",
        "https://",
        "http://",
    )
    MAX_RELEVANT_DISTANCE = 0.82
    LENIENT_FACT_DISTANCE = 0.9
    FOLLOW_UP_PREFIXES = (
        "y ",
        "y si",
        "y eso",
        "entonces",
        "vale",
        "ok",
        "oka",
        "pero",
        "o sea",
        "puedes ampliar",
        "puedes desarrollarlo",
        "desarrolla",
        "explica",
        "y en ese caso",
        "me refiero",
    )
    BROADENING_HINTS = (
        "que otras",
        "qué otras",
        "que mas",
        "qué más",
        "ademas",
        "además",
        "en general",
        "aparte",
        "otras recomendaciones",
        "más recomendaciones",
        "mas recomendaciones",
    )
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
        self.profile = build_default_profile(settings)

    async def answer(self, request: QueryRequest) -> QueryResponse:
        """Answer a user query using local retrieval plus the chat model."""
        started_at = perf_counter()
        session_id, _ = self.session_store.get_or_create(request.session_id)
        history = self.session_store.get_recent_history(session_id)
        previous_intent = self.session_store.get_last_intent(session_id)
        previous_dialogue_goal = self.session_store.get_last_dialogue_goal(session_id)
        # The request is classified before retrieval so the rest of the pipeline
        # can decide whether to answer, clarify, or stay strict about grounding.
        intent_decision = classify_intent(
            question=request.message,
            history=history,
            mode="corpus",
            profile=self.profile,
            active_document=False,
            previous_intent=previous_intent,
        )
        dialogue_decision = classify_dialogue_goal(
            question=request.message,
            history=history,
            intent_decision=intent_decision,
            previous_goal=previous_dialogue_goal,
        )
        strategy_decision = classify_response_strategy(
            question=request.message,
            history=history,
            intent_decision=intent_decision,
            dialogue_decision=dialogue_decision,
            active_document=False,
        )
        list_mode = is_list_question(request.message)
        factual_mode = is_narrow_fact_question(request.message)
        embedding_ms = 0.0
        retrieval_ms = 0.0
        generation_ms = 0.0
        model_result = ChatResult(content="")
        retrieved_chunks: list[RetrievedChunk] = []
        curated_chunks: list[RetrievedChunk] = []
        reused_previous_evidence = False

        if strategy_decision.needs_clarification and strategy_decision.clarification_prompt:
            # Short-circuit early when the system needs clarification; this avoids
            # wasting retrieval or generation work on an underspecified turn.
            answer = strategy_decision.clarification_prompt
            total_ms = (perf_counter() - started_at) * 1000.0
            self.session_store.set_last_intent(session_id, intent_decision.intent)
            self.session_store.set_last_dialogue_goal(session_id, dialogue_decision.goal)
            self._store_turn_pair(session_id=session_id, question=request.message, answer=answer)
            trace_note = self._resolve_trace_note(
                mode="corpus",
                intent_decision=intent_decision,
                dialogue_decision=dialogue_decision,
                strategy_decision=strategy_decision,
                reused_previous_evidence=False,
                curated_chunks=[],
            )
            self._append_runtime_audit(
                session_id=session_id,
                mode="corpus",
                question=request.message,
                answer=answer,
                intent_decision=intent_decision,
                dialogue_decision=dialogue_decision,
                strategy_decision=strategy_decision,
                trace_note=trace_note,
                retrieved_chunks=[],
                curated_chunks=[],
                embedding_ms=0.0,
                retrieval_ms=0.0,
                generation_ms=0.0,
                total_ms=total_ms,
                model_result=model_result,
            )
            return QueryResponse(
                answer=answer,
                sources=[],
                model=self.settings.ollama_chat_model,
                mode="corpus",
                session_id=session_id,
                trace=self._build_trace(
                    mode="corpus",
                    retrieved_candidates=0,
                    curated_candidates=0,
                    history=history,
                    document_title=None,
                    intent_decision=intent_decision,
                    dialogue_decision=dialogue_decision,
                    strategy_decision=strategy_decision,
                    note=trace_note,
                    selected_chunks=[],
                    embedding_ms=0.0,
                    retrieval_ms=0.0,
                    generation_ms=0.0,
                    total_ms=total_ms,
                    model_result=model_result,
                ),
            )

        if strategy_decision.should_retrieve:
            # Only query the vector store when the strategy says grounding is
            # required. That keeps casual follow-ups and clarifications cheap.
            retrieval_query = self._build_retrieval_query(
                question=request.message,
                history=history,
            )
            embed_started = perf_counter()
            embed_result = await self.ollama_client.embed_with_metrics([retrieval_query])
            embedding_ms = embed_result.total_duration_ms or (perf_counter() - embed_started) * 1000.0
            query_embedding = embed_result.embeddings[0]

            retrieval_started = perf_counter()
            retrieved_chunks = self.vector_store.query(
                query_embedding=query_embedding,
                top_k=5 if factual_mode else min(request.top_k + 2, 6) if list_mode else request.top_k,
            )
            retrieval_ms = (perf_counter() - retrieval_started) * 1000.0

            curated_chunks = self._curate_chunks(
                retrieved_chunks,
                max_chunks_override=2 if factual_mode else None,
                max_distance_override=0.96 if intent_decision.evidence_policy == "hybrid_guided" else None,
            )
            if factual_mode:
                curated_chunks = self._rerank_fact_chunks(request.message, curated_chunks)
            if not curated_chunks and factual_mode:
                fallback_chunk = self._build_lenient_fact_fallback(retrieved_chunks)
                if fallback_chunk:
                    curated_chunks = [fallback_chunk]
            if not curated_chunks and intent_decision.evidence_policy == "hybrid_guided":
                curated_chunks = self._build_lenient_guidance_fallback(retrieved_chunks)

        if not curated_chunks and strategy_decision.should_retrieve:
            # If retrieval was weak, try to reuse the last grounded evidence from
            # the current session so short follow-ups can still stay coherent.
            previous_sources = self.session_store.get_last_sources(session_id)
            if self._should_reuse_previous_evidence(
                question=request.message,
                history=history,
                previous_sources=previous_sources,
                ):
                curated_chunks = previous_sources[: self.settings.max_context_chunks]
                reused_previous_evidence = True

        if not curated_chunks and intent_decision.evidence_policy == "strict_grounded":
            # When the profile demands strict grounding and no evidence exists,
            # return a safe miss message instead of inventing a plausible answer.
            answer = self._build_grounded_miss_response(request.message)
            total_ms = (perf_counter() - started_at) * 1000.0
            self.session_store.set_last_intent(session_id, intent_decision.intent)
            self.session_store.set_last_dialogue_goal(session_id, dialogue_decision.goal)
            self._append_runtime_audit(
                session_id=session_id,
                mode="corpus",
                question=request.message,
                answer=answer,
                intent_decision=intent_decision,
                dialogue_decision=dialogue_decision,
                strategy_decision=strategy_decision,
                trace_note="No relevant evidence was found in the persistent local corpus.",
                retrieved_chunks=retrieved_chunks,
                curated_chunks=[],
                embedding_ms=embedding_ms,
                retrieval_ms=retrieval_ms,
                generation_ms=0.0,
                total_ms=total_ms,
                model_result=model_result,
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
                    intent_decision=intent_decision,
                    dialogue_decision=dialogue_decision,
                    strategy_decision=strategy_decision,
                    note="No relevant evidence was found in the persistent local corpus.",
                    selected_chunks=[],
                    embedding_ms=embedding_ms,
                    retrieval_ms=retrieval_ms,
                    generation_ms=0.0,
                    total_ms=total_ms,
                    model_result=model_result,
                ),
            )

        answer = self._maybe_answer_with_intent_template(
            question=request.message,
            history=history,
            chunks=curated_chunks,
            intent_decision=intent_decision,
            dialogue_decision=dialogue_decision,
        )
        if answer is None:
            # Try deterministic templates before calling the model. This keeps
            # common answers stable and avoids unnecessary generation latency.
            answer = self._maybe_answer_with_grounded_template(
                question=request.message,
                chunks=curated_chunks,
            )
        if answer is None:
            generation_started = perf_counter()
            model_result = await self._generate_answer(
                question=request.message,
                chunks=curated_chunks,
                intent_decision=intent_decision,
                dialogue_decision=dialogue_decision,
                strategy_decision=strategy_decision,
                history=history,
            )
            generation_ms = model_result.total_duration_ms or (perf_counter() - generation_started) * 1000.0
            answer = model_result.content
        answer = self._polish_answer(answer)
        total_ms = (perf_counter() - started_at) * 1000.0
        self.session_store.set_last_sources(session_id, curated_chunks)
        self.session_store.set_last_intent(session_id, intent_decision.intent)
        self.session_store.set_last_dialogue_goal(session_id, dialogue_decision.goal)
        self._store_turn_pair(session_id=session_id, question=request.message, answer=answer)
        trace_note = self._resolve_trace_note(
            mode="corpus",
            intent_decision=intent_decision,
            dialogue_decision=dialogue_decision,
            strategy_decision=strategy_decision,
            reused_previous_evidence=reused_previous_evidence,
            curated_chunks=curated_chunks,
        )
        self._append_runtime_audit(
            session_id=session_id,
            mode="corpus",
            question=request.message,
            answer=answer,
            intent_decision=intent_decision,
            dialogue_decision=dialogue_decision,
            strategy_decision=strategy_decision,
            trace_note=trace_note,
            retrieved_chunks=retrieved_chunks,
            curated_chunks=curated_chunks,
            embedding_ms=embedding_ms,
            retrieval_ms=retrieval_ms,
            generation_ms=generation_ms,
            total_ms=total_ms,
            model_result=model_result,
        )
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
                intent_decision=intent_decision,
                dialogue_decision=dialogue_decision,
                strategy_decision=strategy_decision,
                note=trace_note,
                selected_chunks=curated_chunks,
                embedding_ms=embedding_ms,
                retrieval_ms=retrieval_ms,
                generation_ms=generation_ms,
                total_ms=total_ms,
                model_result=model_result,
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
        started_at = perf_counter()
        normalized_session_id, _ = self.session_store.get_or_create(session_id)
        history = self.session_store.get_recent_history(normalized_session_id)
        previous_intent = self.session_store.get_last_intent(normalized_session_id)
        previous_dialogue_goal = self.session_store.get_last_dialogue_goal(normalized_session_id)
        active_title, stored_chunks = self.session_store.get_document(normalized_session_id)

        effective_chunks = prepared_chunks if prepared_chunks is not None else stored_chunks
        fallback_title = "uploaded image" if mode == "image" else "uploaded pdf"
        effective_title = title or active_title or fallback_title
        extracted_text = "\n".join(chunk.text for chunk in effective_chunks) if effective_chunks else ""
        # Document turns first reuse session state, then classify the turn, and
        # only after that decide whether OCR or PDF content is safe to process.
        safety_assessment = assess_content_risk(
            question=question,
            content=extracted_text,
            mode=mode,
        )
        intent_decision = classify_intent(
            question=question,
            history=history,
            mode=mode,
            profile=self.profile,
            active_document=bool(effective_chunks),
            previous_intent=previous_intent,
        )
        dialogue_decision = classify_dialogue_goal(
            question=question,
            history=history,
            intent_decision=intent_decision,
            previous_goal=previous_dialogue_goal,
        )
        strategy_decision = classify_response_strategy(
            question=question,
            history=history,
            intent_decision=intent_decision,
            dialogue_decision=dialogue_decision,
            active_document=bool(effective_chunks),
        )

        if prepared_chunks:
            # Persist the new temporary document only when one was uploaded in
            # this request; follow-ups can then reuse it without re-uploading.
            self.session_store.set_document(
                normalized_session_id,
                title=effective_title,
                chunks=prepared_chunks,
            )

        if not effective_chunks:
            # Without document chunks there is nothing to ground the answer on,
            # so explain the missing context rather than pretending otherwise.
            total_ms = (perf_counter() - started_at) * 1000.0
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
                    intent_decision=intent_decision,
                    dialogue_decision=dialogue_decision,
                    strategy_decision=strategy_decision,
                    note="The request expected a session-scoped uploaded document, but no active document was available.",
                    selected_chunks=[],
                    embedding_ms=0.0,
                    retrieval_ms=0.0,
                    generation_ms=0.0,
                    total_ms=total_ms,
                    model_result=ChatResult(content=""),
                    ocr_segments=ocr_segments,
                    safety_assessment=safety_assessment,
                ),
            )

        if strategy_decision.needs_clarification and strategy_decision.clarification_prompt:
            answer = strategy_decision.clarification_prompt
            total_ms = (perf_counter() - started_at) * 1000.0
            self.session_store.set_last_intent(normalized_session_id, intent_decision.intent)
            self.session_store.set_last_dialogue_goal(normalized_session_id, dialogue_decision.goal)
            self._store_turn_pair(session_id=normalized_session_id, question=question, answer=answer)
            trace_note = self._resolve_trace_note(
                mode=mode,
                intent_decision=intent_decision,
                dialogue_decision=dialogue_decision,
                strategy_decision=strategy_decision,
                reused_previous_evidence=False,
                curated_chunks=[],
            )
            self._append_runtime_audit(
                session_id=normalized_session_id,
                mode=mode,
                question=question,
                answer=answer,
                intent_decision=intent_decision,
                dialogue_decision=dialogue_decision,
                strategy_decision=strategy_decision,
                trace_note=trace_note,
                retrieved_chunks=[],
                curated_chunks=[],
                embedding_ms=0.0,
                retrieval_ms=0.0,
                generation_ms=0.0,
                total_ms=total_ms,
                model_result=ChatResult(content=""),
                ocr_segments=ocr_segments,
                safety_assessment=safety_assessment,
            )
            return QueryResponse(
                answer=answer,
                sources=[],
                model=self.settings.ollama_chat_model,
                mode=mode,
                session_id=normalized_session_id,
                document_title=effective_title,
                trace=self._build_trace(
                    mode=mode,
                    retrieved_candidates=0,
                    curated_candidates=0,
                    history=history,
                    document_title=effective_title,
                    intent_decision=intent_decision,
                    dialogue_decision=dialogue_decision,
                    strategy_decision=strategy_decision,
                    note=trace_note,
                    selected_chunks=[],
                    embedding_ms=0.0,
                    retrieval_ms=0.0,
                    generation_ms=0.0,
                    total_ms=total_ms,
                    model_result=ChatResult(content=""),
                    ocr_segments=ocr_segments,
                    safety_assessment=safety_assessment,
                ),
            )

        retrieval_query = self._build_retrieval_query(
            question=question,
            history=history,
            document_title=effective_title,
        )
        # For temporary documents we embed the question and each chunk directly
        # because there is no persistent vector store for uploaded files.
        embed_started = perf_counter()
        query_embed_result = await self.ollama_client.embed_with_metrics([retrieval_query])
        chunk_embed_result = await self.ollama_client.embed_with_metrics([chunk.text for chunk in effective_chunks])
        embedding_ms = (
            query_embed_result.total_duration_ms
            + chunk_embed_result.total_duration_ms
            or (perf_counter() - embed_started) * 1000.0
        )
        query_embedding = query_embed_result.embeddings[0]
        chunk_embeddings = chunk_embed_result.embeddings

        scored_chunks: list[RetrievedChunk] = []
        retrieval_started = perf_counter()
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
        retrieval_ms = (perf_counter() - retrieval_started) * 1000.0

        scored_chunks.sort(key=lambda item: item.distance if item.distance is not None else 999.0)
        factual_mode = is_narrow_fact_question(question)
        list_mode = is_list_question(question)
        curated_chunks = self._curate_chunks(
            scored_chunks,
            max_chunks_override=2 if factual_mode else self.settings.max_context_chunks if list_mode else None,
            max_distance_override=0.96 if intent_decision.evidence_policy == "hybrid_guided" else None,
        )
        if factual_mode:
            curated_chunks = self._rerank_fact_chunks(question, curated_chunks)
        if not curated_chunks and factual_mode:
            fallback_chunk = self._build_lenient_fact_fallback(scored_chunks)
            if fallback_chunk:
                curated_chunks = [fallback_chunk]
        if not curated_chunks and intent_decision.evidence_policy == "hybrid_guided":
            curated_chunks = self._build_lenient_guidance_fallback(scored_chunks)
        reused_previous_evidence = False
        if not curated_chunks:
            previous_sources = self.session_store.get_last_sources(normalized_session_id)
            if self._should_reuse_previous_evidence(
                question=question,
                history=history,
                previous_sources=previous_sources,
                ):
                curated_chunks = previous_sources[: self.settings.max_context_chunks]
                reused_previous_evidence = True
        if not curated_chunks:
            # If nothing survives curation, be explicit that the document was
            # processed but not useful enough to ground a reliable answer.
            answer = (
                f"He leído el PDF \"{effective_title}\", pero no he encontrado fragmentos suficientemente "
                "relevantes para responder con fiabilidad a esta pregunta."
                if mode == "pdf"
                else f"He procesado la imagen \"{effective_title}\", pero no he encontrado fragmentos suficientemente "
                "relevantes para responder con fiabilidad a esta pregunta."
            )
            total_ms = (perf_counter() - started_at) * 1000.0
            return QueryResponse(
                answer=answer,
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
                    intent_decision=intent_decision,
                    dialogue_decision=dialogue_decision,
                    strategy_decision=strategy_decision,
                    note=(
                        "A PDF was active, but the retrieved chunks were too weak or too noisy for a grounded answer."
                        if mode == "pdf"
                        else "An OCR image was active, but the retrieved chunks were too weak or too noisy for a grounded answer."
                    ),
                    selected_chunks=[],
                    embedding_ms=embedding_ms,
                    retrieval_ms=retrieval_ms,
                    generation_ms=0.0,
                    total_ms=total_ms,
                    model_result=ChatResult(content=""),
                    ocr_segments=ocr_segments,
                    safety_assessment=safety_assessment,
                ),
            )

        generation_ms = 0.0
        model_result = ChatResult(content="")
        if safety_assessment.cautious_mode:
            # High-risk image turns short-circuit to a deterministic safe reply.
            answer = build_cautious_answer(
                question=question,
                document_title=effective_title,
                extracted_excerpt=curated_chunks[0].text[:220] if curated_chunks else "",
                signals=safety_assessment.signals,
            )
        else:
            answer = self._maybe_answer_with_intent_template(
                question=question,
                history=history,
                chunks=curated_chunks,
                intent_decision=intent_decision,
                dialogue_decision=dialogue_decision,
            )
            if answer is None:
                answer = self._maybe_answer_with_grounded_template(
                    question=question,
                    chunks=curated_chunks,
                )
            if answer is None:
                generation_started = perf_counter()
                model_result = await self._generate_answer(
                    question=question,
                    chunks=curated_chunks,
                    intent_decision=intent_decision,
                    dialogue_decision=dialogue_decision,
                    strategy_decision=strategy_decision,
                    history=history,
                    document_title=effective_title,
                    safety_assessment=safety_assessment,
                )
                generation_ms = model_result.total_duration_ms or (perf_counter() - generation_started) * 1000.0
                answer = model_result.content
                if contains_unsafe_advice(answer):
                    # If the model drifts into unsafe advice, replace it with the
                    # deterministic safe answer used for high-risk scenarios.
                    answer = build_cautious_answer(
                        question=question,
                        document_title=effective_title,
                        extracted_excerpt=curated_chunks[0].text[:220] if curated_chunks else "",
                        signals=safety_assessment.signals,
                    )
        answer = self._polish_answer(answer)
        total_ms = (perf_counter() - started_at) * 1000.0
        self.session_store.set_last_sources(normalized_session_id, curated_chunks)
        self.session_store.set_last_intent(normalized_session_id, intent_decision.intent)
        self.session_store.set_last_dialogue_goal(normalized_session_id, dialogue_decision.goal)
        self._store_turn_pair(
            session_id=normalized_session_id,
            question=question,
            answer=answer,
        )
        trace_note = self._resolve_trace_note(
            mode=mode,
            intent_decision=intent_decision,
            dialogue_decision=dialogue_decision,
            strategy_decision=strategy_decision,
            reused_previous_evidence=reused_previous_evidence,
            curated_chunks=curated_chunks,
        )
        self._append_runtime_audit(
            session_id=normalized_session_id,
            mode=mode,
            question=question,
            answer=answer,
            intent_decision=intent_decision,
            dialogue_decision=dialogue_decision,
            strategy_decision=strategy_decision,
            trace_note=trace_note,
            retrieved_chunks=scored_chunks,
            curated_chunks=curated_chunks,
            embedding_ms=embedding_ms,
            retrieval_ms=retrieval_ms,
            generation_ms=generation_ms,
            total_ms=total_ms,
            model_result=model_result,
            ocr_segments=ocr_segments,
            safety_assessment=safety_assessment,
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
                intent_decision=intent_decision,
                dialogue_decision=dialogue_decision,
                strategy_decision=strategy_decision,
                note=trace_note,
                selected_chunks=curated_chunks,
                embedding_ms=embedding_ms,
                retrieval_ms=retrieval_ms,
                generation_ms=generation_ms,
                total_ms=total_ms,
                model_result=model_result,
                ocr_segments=ocr_segments,
                safety_assessment=safety_assessment,
            ),
        )

    def _curate_chunks(
        self,
        chunks: list[RetrievedChunk],
        *,
        max_chunks_override: Optional[int] = None,
        max_distance_override: Optional[float] = None,
    ) -> list[RetrievedChunk]:
        """Filter noisy retrievals and trim the remaining chunks for prompting."""
        curated: list[RetrievedChunk] = []
        limit = max_chunks_override or self.settings.max_context_chunks
        distance_limit = max_distance_override or self.MAX_RELEVANT_DISTANCE
        for chunk in chunks:
            if self._is_low_value_chunk(chunk):
                continue
            if chunk.distance is not None and chunk.distance > distance_limit:
                continue
            chunk.text = chunk.text[: self.settings.max_context_chars_per_chunk]
            curated.append(chunk)
            if len(curated) >= limit:
                break
        return curated

    def _is_low_value_chunk(self, chunk: RetrievedChunk) -> bool:
        """Return True when a chunk looks like index/reference noise instead of evidence."""
        normalized = chunk.text.lower()
        if any(pattern in normalized for pattern in self.REJECTED_PATTERNS):
            return True

        reference_markers = len(re.findall(r"\[\d+\]", chunk.text))
        url_markers = normalized.count("http")
        return reference_markers >= 3 or url_markers >= 2

    def _rerank_fact_chunks(self, question: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """Prioritize chunks whose wording overlaps more directly with a narrow factual question."""
        keywords = self._extract_fact_keywords(question)
        definition_subject = self._extract_definition_subject(question)
        if not keywords:
            return chunks

        scored: list[tuple[float, RetrievedChunk]] = []
        for chunk in chunks:
            normalized_text = chunk.text.lower()
            overlap = sum(1 for keyword in keywords if keyword in chunk.text.lower())
            score = float(overlap)
            if ":" in chunk.text:
                score += 0.15
            if chunk.distance is not None:
                score += max(0.0, 1.0 - chunk.distance)
            if definition_subject:
                if definition_subject in normalized_text:
                    score += 1.0
                if self._looks_like_definition_chunk(definition_subject, normalized_text):
                    score += 2.0
                if "|" in chunk.text and definition_subject in normalized_text:
                    score -= 0.2
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

    def _build_lenient_guidance_fallback(self, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """Keep a small set of weaker-but-usable chunks for guided support turns."""
        fallback: list[RetrievedChunk] = []
        for chunk in chunks:
            if self._is_low_value_chunk(chunk):
                continue
            if chunk.distance is not None and chunk.distance <= 0.98:
                kept = chunk.model_copy(deep=True)
                kept.text = kept.text[: self.settings.max_context_chars_per_chunk]
                fallback.append(kept)
            if len(fallback) >= 2:
                break
        return fallback

    def _extract_fact_keywords(self, question: str) -> set[str]:
        """Extract content-bearing words from a factual query for lightweight reranking."""
        tokens = re.findall(r"[a-záéíóúñ0-9]{3,}", question.lower())
        return {token for token in tokens if token not in self.FACT_STOPWORDS}

    def _extract_definition_subject(self, question: str) -> Optional[str]:
        """Extract the concept being defined in turns like `que es spam`."""
        normalized = re.sub(r"[¿?!.]", " ", question.lower())
        match = re.match(r"^\s*(que|qué)\s+es\s+(.+?)\s*$", normalized)
        if not match:
            return None

        subject = re.sub(r"\b(el|la|los|las|un|una)\b", " ", match.group(2))
        subject = re.sub(r"\s+", " ", subject).strip()
        return subject or None

    def _looks_like_definition_chunk(self, subject: str, text: str) -> bool:
        """Detect whether a chunk appears to define the requested concept instead of only mentioning it."""
        subject_markers = {
            "spam": (
                "mensajes no deseados",
                "correo no deseado",
                "finalidad comercial",
                "mensajes no solicitados",
            ),
            "phishing": (
                "suplantando a una entidad legítima",
                "suplantando a una entidad legitima",
                "información confidencial",
                "informacion confidencial",
                "credenciales",
                "web fraudulenta",
            ),
        }
        generic_patterns = (
            rf"{re.escape(subject)}\s+(es|son|se refiere|consiste)",
            rf"¿cómo funciona\?.*{re.escape(subject)}",
            rf"{re.escape(subject)}.*¿cómo funciona\?",
        )

        if any(re.search(pattern, text) for pattern in generic_patterns):
            return True

        markers = subject_markers.get(subject, ())
        return any(marker in text for marker in markers)

    def _should_reuse_previous_evidence(
        self,
        *,
        question: str,
        history: list[ConversationTurn],
        previous_sources: list[RetrievedChunk],
    ) -> bool:
        """Reuse prior grounded evidence when the new turn is clearly a follow-up."""
        if not history or not previous_sources:
            return False

        normalized = question.strip().lower()
        if self._is_broadening_question(normalized):
            if is_list_question(question) and self._looks_like_password_scope(previous_sources):
                return True
            if any(normalized.startswith(prefix) for prefix in self.FOLLOW_UP_PREFIXES):
                word_count = len(re.findall(r"\b\w+\b", normalized))
                if word_count <= 10:
                    return True
            return False

        word_count = len(re.findall(r"\b\w+\b", normalized))
        if "___" in question:
            return True
        if word_count <= 6:
            return True

        if any(normalized.startswith(prefix) for prefix in self.FOLLOW_UP_PREFIXES):
            return True

        has_reference_pronoun = bool(
            re.search(r"\b(eso|esto|esa|ese|asi|así|entonces|tambien|también)\b", normalized)
        )
        return has_reference_pronoun and word_count <= 16

    async def _generate_answer(
        self,
        *,
        question: str,
        chunks: list[RetrievedChunk],
        intent_decision,
        dialogue_decision,
        strategy_decision,
        history: Optional[list[ConversationTurn]] = None,
        document_title: Optional[str] = None,
        safety_assessment: Optional[SafetyAssessment] = None,
    ) -> ChatResult:
        """Generate the final assistant answer from the curated evidence."""
        prompt = build_user_prompt(
            question,
            chunks,
            profile=self.profile,
            intent_decision=intent_decision,
            dialogue_decision=dialogue_decision,
            strategy_decision=strategy_decision,
            history=history,
            document_title=document_title,
            safety_assessment=safety_assessment,
        )
        return await self.ollama_client.chat_with_metrics(
            system_prompt=build_system_prompt(self.profile, intent_decision, dialogue_decision, strategy_decision),
            user_prompt=prompt,
        )

    def _build_retrieval_query(
        self,
        *,
        question: str,
        history: Optional[list[ConversationTurn]] = None,
        document_title: Optional[str] = None,
    ) -> str:
        """Expand ambiguous follow-ups without over-anchoring broader new questions."""
        relevant_user_turns = [turn.content for turn in (history or []) if turn.role == "user"]
        recent_user_turns = relevant_user_turns[-2:]
        document_line = f"document: {document_title}\n" if document_title else ""
        if self._should_include_history_in_retrieval(question, history):
            history_block = "\n".join(f"previous user topic: {turn}" for turn in recent_user_turns)
            return f"{document_line}{history_block}\ncurrent question: {question}".strip()
        return f"{document_line}current question: {question}".strip()

    def _store_turn_pair(self, *, session_id: str, question: str, answer: str) -> None:
        """Persist the user question and assistant answer after one completed turn."""
        self.session_store.append_turn(session_id, "user", question)
        self.session_store.append_turn(session_id, "assistant", answer)

    def _maybe_answer_with_grounded_template(
        self,
        *,
        question: str,
        chunks: list[RetrievedChunk],
    ) -> Optional[str]:
        """Return a deterministic grounded answer for common conversational patterns."""
        if not chunks:
            return None

        normalized = question.strip().lower()
        combined_text = " ".join(chunk.text for chunk in chunks)
        combined_lower = combined_text.lower()

        if any(phrase in normalized for phrase in ("cada cuanto", "cada cuánto", "cuanto tiempo", "cuánto tiempo")):
            if "periodicidad dependerá de la criticidad" in combined_lower or "periodicidad dependera de la criticidad" in combined_lower:
                if "cada __" in combined_lower or "___" in question:
                    return (
                        "No fija un plazo concreto. En el checklist aparece el hueco en blanco (`___`) "
                        "y, en el texto explicativo, dice que la periodicidad depende de la criticidad "
                        "de la información a la que dan acceso esas contraseñas."
                    )
                return (
                    "No fija un plazo concreto. Lo que dice el documento es que la periodicidad del cambio "
                    "depende de la criticidad de la información a la que dan acceso las contraseñas."
                )

        if "___" in question and ("cuanto" in normalized or "tiempo" in normalized):
            if "periodicidad dependerá de la criticidad" in combined_lower or "periodicidad dependera de la criticidad" in combined_lower:
                return (
                    "Ese hueco no viene relleno en la fuente. El checklist deja `___`, y el texto que lo acompaña "
                    "solo aclara que la periodicidad del cambio depende de la criticidad de la información."
                )

        if "gestor" in normalized and ("cambiar" in normalized or "3 meses" in normalized):
            mentions_forced_rotation = "fuercen al cambio de contraseña en el plazo elegido" in combined_lower
            mentions_password_managers = "gestores de contraseñas" in combined_lower
            if mentions_forced_rotation and mentions_password_managers:
                return (
                    "Con lo que tengo cargado aquí, el documento no da nombres concretos ni dice que un gestor "
                    "de contraseñas cambie automáticamente las claves cada 3 meses. Lo que sí dice es dos cosas "
                    "por separado: que pueden usarse sistemas que fuercen el cambio en el plazo elegido y que "
                    "conviene usar gestores de contraseñas cuando tienes que recordar muchas."
                )

        if "mejorar mis contrase" in normalized:
            recommendations = self._extract_password_recommendations(chunks)
            if recommendations:
                bullets = "\n".join(f"- {item}" for item in recommendations[:4])
                return (
                    "Si quieres empezar por lo más útil, yo reforzaría esto:\n\n"
                    f"{bullets}"
                )

        if is_list_question(question):
            recommendations = self._extract_password_recommendations(chunks)
            if recommendations:
                bullets = "\n".join(f"- {item}" for item in recommendations[:4])
                if any(phrase in normalized for phrase in ("seguridad online", "seguridad en internet", "seguridad digital")):
                    return (
                        "Con lo que tengo cargado ahora, lo más claro que puedo respaldar sigue yendo sobre contraseñas y acceso. "
                        "Si te sirve, empezaría por esto:\n\n"
                        f"{bullets}"
                    )
                return (
                    "Con lo que puedo respaldar ahora mismo en el corpus, estas son las recomendaciones más claras:\n\n"
                    f"{bullets}"
                )

        return None

    def _maybe_answer_with_intent_template(
        self,
        *,
        question: str,
        history: list[ConversationTurn],
        chunks: list[RetrievedChunk],
        intent_decision,
        dialogue_decision,
    ) -> Optional[str]:
        """Handle high-value support intents with more stable local guidance."""
        normalized = question.strip().lower()
        recent_user_turns = [turn.content.lower() for turn in history[-4:] if turn.role == "user"]
        recent_user_text = " ".join(recent_user_turns)
        combined = f"{recent_user_text} {normalized}".strip()

        phishing_terms = (
            "phishing",
            "correo sospechoso",
            "valide mi cuenta",
            "haga clic",
            "he hecho clic",
            "hice click",
            "enlace",
        )
        phishing_signal_terms = (
            "señal",
            "señales",
            "indicador",
            "indicadores",
            "en que me tengo que fijar",
            "en qué me tengo que fijar",
            "que mirar",
            "qué mirar",
            "que revisar",
            "qué revisar",
        )
        compromised_terms = (
            "hackeado",
            "me han entrado",
            "me han robado la cuenta",
            "accedido a mi cuenta",
            "comprometida",
        )
        current_mentions_phishing = any(term in normalized for term in phishing_terms)
        phishing_context_detected = current_mentions_phishing or any(term in recent_user_text for term in phishing_terms)
        current_mentions_compromised_account = any(term in normalized for term in compromised_terms)
        compromised_context_detected = current_mentions_compromised_account or any(
            term in recent_user_text for term in compromised_terms
        )

        if intent_decision.intent == "greeting":
            if history:
                return (
                    f"Aquí sigo. Soy {self.profile.name} y puedo seguir contigo en la misma conversación, "
                    "apoyándome en el corpus local o en un PDF o imagen que subas.\n\n"
                    "Cuéntame qué te preocupa y lo aterrizamos paso a paso."
                )
            return (
                f"Hola, soy {self.profile.name}. Puedo orientarte sobre ciberseguridad con un enfoque práctico, "
                "apoyándome en el corpus local y en documentos que subas en la conversación.\n\n"
                "Si quieres, cuéntame tu caso o pregúntame por un tema concreto."
            )

        if intent_decision.intent == "capabilities":
            return (
                f"Soy {self.profile.name}, un asistente centrado en {self.profile.domain_name}.\n\n"
                "Puedo ayudarte a entender recomendaciones del corpus local, responder dudas sobre problemas "
                "frecuentes como phishing o cuentas comprometidas, y analizar PDFs o imágenes que subas para "
                "seguir la conversación con ese contexto.\n\n"
                "Además, todo corre en local, así que no depende de APIs externas de pago y la traza de tiempos, "
                "chunks y tokens queda registrada para validación."
            )

        if intent_decision.intent == "scope_redirect":
            return (
                f"Ahora mismo estoy enfocado en {self.profile.domain_name}. Si quieres, puedo ayudarte si lo "
                "llevamos a ese terreno: por ejemplo, protección de cuentas, phishing, contraseñas, incidentes, "
                "teletrabajo seguro o revisión de un documento.\n\n"
                "Si me das el problema desde ese ángulo, te respondo mejor."
            )

        if dialogue_decision.goal == "compare_options":
            return None

        if intent_decision.intent != "guided_support":
            return None

        if "pdf" in normalized and any(
            term in normalized for term in ("revisar", "analizar", "mirar", "que pone", "qué pone", "sospechoso")
        ):
            return (
                "Si quieres que revise un PDF concreto, necesito que lo subas en esta misma conversación.\n\n"
                "En cuanto lo adjuntes, puedo leer su contenido, responder a dudas sobre lo que pone y ayudarte a "
                "valorar si hay señales sospechosas."
            )

        if phishing_context_detected:
            if any(term in normalized for term in phishing_signal_terms):
                return (
                    "Para revisar si ese mensaje encaja con phishing, yo me fijaría sobre todo en estas señales:\n\n"
                    "- Si mete prisa o intenta que actúes sin pensar.\n"
                    "- Si el remitente, el dominio o el enlace no coinciden exactamente con el servicio legítimo.\n"
                    "- Si pide credenciales, códigos, datos bancarios o validaciones que no deberían llegar por esa vía.\n"
                    "- Si el tono es genérico, contiene errores raros o no encaja con el contexto habitual.\n"
                    "- Si te empuja a entrar desde un botón o enlace en lugar de ir tú por la web o la app oficial.\n\n"
                    "Si quieres, puedes copiarme el texto del correo o contarme qué elementos te generan duda y lo revisamos punto por punto."
                )
            if dialogue_decision.goal == "triage":
                return (
                    "Para distinguir si es phishing o no, yo miraría primero estas señales:\n\n"
                    "- Si te mete prisa, te amenaza o te pide actuar ya.\n"
                    "- Si el enlace o el remitente no coincide exactamente con el servicio real.\n"
                    "- Si te pide contraseña, códigos o datos que normalmente no te pedirían por correo.\n"
                    "- Si el mensaje suena genérico, raro o no encaja con el contexto habitual.\n\n"
                    "Si quieres, puedes contarme qué pone o qué te llama la atención y lo revisamos juntos."
                )
            if dialogue_decision.goal == "next_step":
                if any(term in combined for term in ("meti la contraseña", "metí la contraseña", "introduje la contraseña", "he puesto la contraseña", "escribi la contraseña", "escribí la contraseña")):
                    return (
                        "Si además llegaste a introducir la contraseña, yo actuaría como si la cuenta ya estuviera comprometida:\n\n"
                        "- Cambia la contraseña desde un dispositivo de confianza.\n"
                        "- Cierra sesiones abiertas y revisa si hay reglas de reenvío o cambios en la cuenta.\n"
                        "- Activa doble factor si todavía no estaba activo.\n"
                        "- Si es una cuenta de trabajo, avisa al equipo de TI o seguridad cuanto antes.\n\n"
                        "Si me dices qué cuenta era, te ayudo a priorizar el orden y a revisar qué más comprobar."
                    )
                if any(term in combined for term in ("he hecho clic", "hice click", "ya he hecho clic", "ya hice clic")):
                    return (
                        "El primer paso sería cortar la interacción con ese enlace: cierra la página y no introduzcas "
                        "más datos.\n\n"
                        "Después revisaría si llegaste a escribir credenciales o descargar algo, porque ahí cambia el "
                        "siguiente paso y te lo puedo ordenar."
                    )
                if current_mentions_phishing:
                    return (
                        "El primer paso sería no interactuar con el correo: no hagas clic, no respondas y no metas datos.\n\n"
                        "Después puedes comprobar la situación desde la web o app oficial, entrando por tu cuenta."
                    )
                return None
            if any(term in combined for term in ("meti la contraseña", "metí la contraseña", "introduje la contraseña", "he puesto la contraseña", "escribi la contraseña", "escribí la contraseña")):
                return (
                    "Si llegaste a escribir la contraseña, yo actuaría como si la cuenta ya estuviera en riesgo:\n\n"
                    "- Cambia la contraseña desde un dispositivo de confianza.\n"
                    "- Cierra sesiones abiertas y revisa si hay reglas de reenvío o cambios en la cuenta.\n"
                    "- Activa doble factor si todavía no estaba activo.\n"
                    "- Si es una cuenta de trabajo, avisa al equipo de TI o seguridad cuanto antes.\n\n"
                    "Si me dices qué cuenta era, te ayudo a priorizar el orden."
                )
            if any(term in combined for term in ("he hecho clic", "hice click", "ya he hecho clic", "ya hice clic")):
                return (
                    "Si ya has hecho clic, lo más prudente ahora es contener el riesgo cuanto antes:\n\n"
                    "- Cierra la página y no introduzcas credenciales ni códigos.\n"
                    "- Si has descargado algo, no lo abras y avisa al equipo de TI si es un entorno de trabajo.\n"
                    "- Cambia la contraseña de la cuenta afectada desde un dispositivo de confianza si llegaste a introducirla.\n"
                    "- Revisa si hay sesiones abiertas, reglas de reenvío o cambios raros en la cuenta.\n"
                    "- Si es una cuenta laboral, notifícalo cuanto antes al equipo de soporte o seguridad.\n\n"
                    "Si me dices si solo hiciste clic o además escribiste la contraseña, te oriento mejor con el siguiente paso."
                )
            if current_mentions_phishing or dialogue_decision.goal == "triage":
                return (
                    "Por lo que describes, yo lo trataría como un posible phishing.\n\n"
                    "- No hagas clic en el enlace ni respondas al mensaje.\n"
                    "- No introduzcas contraseñas, códigos ni datos personales.\n"
                    "- Verifica la situación desde la web o la app oficial entrando por tu cuenta, no desde el correo.\n"
                    "- Si es una cuenta de trabajo, reenvíalo al equipo de TI o seguridad para que lo revisen.\n"
                    "- Conserva el correo por si necesitas reportarlo, pero sin interactuar con él.\n\n"
                    "Si quieres, puedo ayudarte a revisar qué señales concretas suelen delatar este tipo de correos."
                )
            return None

        if compromised_context_detected:
            lost_access_terms = (
                "no puedo acceder",
                "no puedo entrar",
                "no me deja entrar",
                "me han cambiado la contraseña",
                "han cambiado la contraseña",
                "me cambiaron la contraseña",
                "me han cambiado el correo",
                "han cambiado el correo",
                "me cambiaron el correo",
                "me han cambiado el telefono",
                "me han cambiado el teléfono",
                "han cambiado el telefono",
                "han cambiado el teléfono",
                "no tengo acceso",
            )
            if any(term in normalized for term in lost_access_terms):
                return (
                    "Si ya no puedes acceder a la cuenta, no intentaría seguir por el mismo enlace o mensaje.\n\n"
                    "Lo prioritario ahora sería iniciar la recuperación desde la web o la app oficial del servicio, "
                    "usando un dispositivo de confianza y comprobando si también han cambiado el correo o el teléfono "
                    "de recuperación.\n\n"
                    "Si el sistema ya no te deja recuperarla por esa vía, intentaría contactar cuanto antes con el "
                    "soporte oficial o, si es una cuenta de trabajo, con el equipo de TI o seguridad. Mientras tanto, "
                    "revisaría otras cuentas por si reutilizaban la misma contraseña y guardaría cualquier evidencia "
                    "útil del acceso no autorizado."
                )
            if dialogue_decision.goal == "next_step":
                return (
                    "El primer paso sería cambiar la contraseña desde un dispositivo de confianza.\n\n"
                    "En cuanto lo hagas, revisaría sesiones abiertas, métodos de recuperación y cualquier cambio raro "
                    "en la cuenta para ver hasta dónde ha llegado el acceso."
                )
            if current_mentions_compromised_account:
                return (
                    "Si crees que te han comprometido la cuenta, priorizaría esto en este orden:\n\n"
                    "- Cambia la contraseña desde un dispositivo de confianza.\n"
                    "- Cierra sesiones abiertas y revisa si han cambiado correo de recuperación, teléfono o reglas automáticas.\n"
                    "- Activa o refuerza el doble factor si todavía no lo tenías.\n"
                    "- Si es una cuenta de trabajo, avisa al equipo de TI o seguridad cuanto antes.\n"
                    "- Guarda cualquier evidencia útil: correos raros, avisos de acceso, capturas o cambios detectados.\n\n"
                    "Si me dices qué cuenta es y qué síntomas has visto, te ayudo a ordenar mejor el siguiente paso."
                )
            return None

        return None

    def _extract_password_recommendations(self, chunks: list[RetrievedChunk]) -> list[str]:
        """Extract distinct password recommendations directly from retrieved evidence."""
        combined = " ".join(chunk.text for chunk in chunks).lower()
        recommendations: list[str] = []

        if "cambiadas periódicamente" in combined or "cambiar las contraseñas periódicamente" in combined:
            recommendations.append(
                "Cambia las contraseñas periódicamente; el documento indica que la frecuencia debe ajustarse a la criticidad de la información."
            )
        if "no deben utilizarse contraseñas que hayan sido usadas con anterioridad" in combined:
            recommendations.append("No reutilices contraseñas que ya hayas usado antes.")
        if "recordatorio de contraseñas" in combined:
            recommendations.append(
                "Evita las funciones de recordatorio de contraseñas en navegadores y aplicaciones."
            )
        if "gestores de contraseñas" in combined:
            recommendations.append(
                "Usa un gestor de contraseñas cuando tengas que recordar muchas claves distintas."
            )
        if "periodos de validez para las contraseñas" in combined:
            recommendations.append(
                "Define una política clara de validez y renovación de contraseñas en tus sistemas."
            )
        if "no utilizar la misma contraseña para servicios diferentes" in combined:
            recommendations.append("No uses la misma contraseña en servicios diferentes.")
        if "las contraseñas deben de ser robustas" in combined or "deben contener al menos doce caracteres" in combined:
            recommendations.append(
                "Haz que las contraseñas sean robustas: largas y con mezcla de tipos de caracteres."
            )
        if "doble factor de autenticación" in combined or "autenticación multifactor" in combined:
            recommendations.append(
                "Activa doble factor de autenticación cuando el servicio lo permita."
            )

        # Preserve order while removing duplicates.
        unique_recommendations: list[str] = []
        seen: set[str] = set()
        for item in recommendations:
            if item in seen:
                continue
            seen.add(item)
            unique_recommendations.append(item)
        return unique_recommendations

    def _looks_like_password_scope(self, chunks: list[RetrievedChunk]) -> bool:
        """Return True when the previous grounded evidence is mainly about passwords."""
        for chunk in chunks:
            title = str(chunk.metadata.get("title", "")).lower()
            text = chunk.text.lower()
            if "contrasen" in title or "contraseñ" in title:
                return True
            if "gestores de contraseñas" in text or "cambiar las contraseñas" in text:
                return True
        return False

    def _build_grounded_miss_response(self, question: str) -> str:
        """Return a softer, non-technical miss when strict grounding finds nothing usable."""
        normalized = question.strip().lower()
        if any(term in normalized for term in (" vs ", "versus", "diferencia", "compar")):
            return (
                "Ahora mismo no veo una base suficientemente clara en el corpus local para comparar bien esos dos conceptos. "
                "Y, revisando las fuentes cargadas, no tenemos todavía un documento específico sobre `spam` o una comparación "
                "directa entre `spam` y `phishing`. Si quieres, ese es un buen hueco para ampliar el corpus con una fuente de INCIBE "
                "u otra referencia fiable antes de responderlo como parte estable del sistema."
            )
        if "documento" in normalized or "segun" in normalized or "según" in normalized:
            return (
                "Ahora mismo no encuentro una referencia suficientemente clara en el corpus local para "
                "responder con seguridad a eso. Si quieres, puedo ayudarte a reformular la pregunta con el "
                "nombre del documento, el tema exacto o el fragmento que quieres localizar."
            )
        return (
            "Ahora mismo no estoy viendo una base lo bastante clara en el corpus local para responder bien a eso. "
            "Si quieres, cuéntame un poco más del caso, dime el tema concreto o sube un documento y seguimos desde ahí."
        )

    def _append_runtime_audit(
        self,
        *,
        session_id: str,
        mode: str,
        question: str,
        answer: str,
        intent_decision,
        dialogue_decision,
        strategy_decision,
        trace_note: str,
        retrieved_chunks: list[RetrievedChunk],
        curated_chunks: list[RetrievedChunk],
        embedding_ms: float,
        retrieval_ms: float,
        generation_ms: float,
        total_ms: float,
        model_result: ChatResult,
        ocr_segments: int = 0,
        safety_assessment: Optional[SafetyAssessment] = None,
    ) -> None:
        """Append a local runtime record for later cost/performance analysis."""
        try:
            self.settings.processed_data_dir.mkdir(parents=True, exist_ok=True)
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "session_id": session_id,
                "mode": mode,
                "question": question,
                "answer_excerpt": answer[:280],
                "intent": intent_decision.intent,
                "evidence_policy": intent_decision.evidence_policy,
                "dialogue_goal": dialogue_decision.goal,
                "response_shape": dialogue_decision.response_shape,
                "response_strategy": strategy_decision.strategy,
                "answer_mode": strategy_decision.answer_mode,
                "follow_up_policy": strategy_decision.follow_up_policy,
                "needs_clarification": strategy_decision.needs_clarification,
                "trace_note": trace_note,
                "retrieved_candidates": len(retrieved_chunks),
                "curated_candidates": len(curated_chunks),
                "retrieved_chunk_refs": [self._chunk_ref(chunk) for chunk in retrieved_chunks],
                "selected_chunk_refs": [self._chunk_ref(chunk) for chunk in curated_chunks],
                "embedding_ms": round(embedding_ms, 2),
                "retrieval_ms": round(retrieval_ms, 2),
                "generation_ms": round(generation_ms, 2),
                "total_ms": round(total_ms, 2),
                "prompt_tokens": model_result.prompt_tokens,
                "completion_tokens": model_result.completion_tokens,
                "total_tokens": model_result.total_tokens,
                "estimated_external_cost_eur": 0.0,
                "model_total_duration_ms": round(model_result.total_duration_ms, 2),
                "ocr_segments": ocr_segments,
                "safety_mode": bool(safety_assessment and safety_assessment.cautious_mode),
                "risk_signals": safety_assessment.signals if safety_assessment else [],
                "local_execution": True,
                "local_execution_rationale": self.profile.local_execution_rationale,
                "local_cost_rationale": self.profile.local_cost_rationale,
                "cost_measurement_note": "El coste facturable externo es 0 porque el pipeline se ejecuta completamente en local. Los tokens se guardan para comparar consumo relativo entre flujos.",
                "chat_model": self.settings.ollama_chat_model,
                "embed_model": self.settings.ollama_embed_model,
            }
            with self.settings.runtime_audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            return

    def _chunk_ref(self, chunk: RetrievedChunk) -> str:
        """Return a compact chunk reference for traces and runtime audits."""
        title = str(chunk.metadata.get("title", "untitled"))
        chunk_index = chunk.metadata.get("chunk_index", "?")
        return f"{title}#{chunk_index}"

    def _resolve_trace_note(
        self,
        *,
        mode: str,
        intent_decision,
        dialogue_decision,
        strategy_decision,
        reused_previous_evidence: bool,
        curated_chunks: list[RetrievedChunk],
    ) -> str:
        """Explain at a high level how the final answer was produced."""
        if reused_previous_evidence:
            return (
                "Reused grounded evidence from the previous turn because the new request behaved like a follow-up "
                f"and kept the dialogue goal `{dialogue_decision.goal}` with strategy `{strategy_decision.strategy}`."
            )
        if intent_decision.evidence_policy == "profile_only":
            return (
                "Answered from the assistant profile and the active conversation without needing corpus retrieval, "
                f"with dialogue goal `{dialogue_decision.goal}` and strategy `{strategy_decision.strategy}`."
            )
        if strategy_decision.needs_clarification:
            return (
                "Paused the full answer to ask one clarifying question because the response strategy "
                f"`{strategy_decision.strategy}` judged the turn too ambiguous."
            )
        if not curated_chunks and intent_decision.evidence_policy == "hybrid_guided":
            return (
                "Answered in guided-support mode using the assistant profile and conversation context because retrieval "
                f"was weak, prioritizing the dialogue goal `{dialogue_decision.goal}` and strategy `{strategy_decision.strategy}`."
            )
        if intent_decision.evidence_policy == "hybrid_guided":
            return (
                "Combined conversational guidance with the most relevant local evidence recovered for this turn, "
                f"targeting the dialogue goal `{dialogue_decision.goal}` through strategy `{strategy_decision.strategy}`."
            )
        if mode == "pdf":
            return "The answer was grounded in the active uploaded PDF stored for this conversation."
        if mode == "image":
            return "The answer was grounded in OCR text extracted from the active uploaded image."
        return "Persistent corpus retrieval was used to ground the final answer."

    def _polish_answer(self, answer: str) -> str:
        """Reduce report-like artifacts so the final text feels more conversational."""
        cleaned = answer.strip()
        cleaned = re.sub(r"^\s*[¡!]?\s*hola de nuevo[!.]?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^\s*[¡!]?\s*claro[.!]?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^\s*respuesta\s*:\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(
            r"^\s*(entiendo que (?:quieres|deseas|buscas|preguntas)[^.\n]*[.\n]+\s*)",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"^\s*la pregunta es\s*:[^\n]*\n+",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"^\s*respuesta breve y directa\s*:\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"^\s*la respuesta a tu pregunta es\s*:\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"^\s*me alegra que[^.\n]*[.\n]+\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"^\s*me alegra ayudarte[^.\n]*[.\n]+\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\s+en\s+\[source\s+\d+\]", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\[source\s+\d+\]", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bchunk\s*\d+\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bfragmento\s*\d+\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\(\s*[A-Z]\s+[A-Z]{2,}\s*\)", "", cleaned)
        cleaned = re.sub(r"\b[A-Z]\s+[A-Z]{2,}\b", "", cleaned)
        cleaned = re.sub(r"\(\s*fuente\s*:\s*[^)]+\)", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(
            r"\n*\s*¿?quieres saber más[^?\n]*\??\s*$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"[ \t]+([,.;:])", r"\1", cleaned)
        cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        return cleaned.strip()

    def _should_include_history_in_retrieval(
        self,
        question: str,
        history: Optional[list[ConversationTurn]] = None,
    ) -> bool:
        """Use recent user turns only when the new question is clearly underspecified."""
        if not history:
            return False

        normalized = question.strip().lower()
        if self._is_broadening_question(normalized):
            return False

        return is_follow_up_question(question, history)

    def _is_broadening_question(self, question: str) -> bool:
        """Detect when the user is opening scope instead of asking about the same fact."""
        normalized = question.strip().lower()
        if is_list_question(normalized):
            return True
        return any(hint in normalized for hint in self.BROADENING_HINTS)

    def _build_trace(
        self,
        *,
        mode: str,
        retrieved_candidates: int,
        curated_candidates: int,
        history: list[ConversationTurn],
        document_title: Optional[str],
        intent_decision,
        dialogue_decision,
        strategy_decision,
        note: str,
        selected_chunks: list[RetrievedChunk],
        embedding_ms: float,
        retrieval_ms: float,
        generation_ms: float,
        total_ms: float,
        model_result: ChatResult,
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
                title="Intent routing",
                detail=(
                    f"Resolved the turn as `{intent_decision.intent}` with evidence policy "
                    f"`{intent_decision.evidence_policy}`. {intent_decision.rationale}"
                ),
            ),
            TraceStep(
                title="Dialogue goal",
                detail=(
                    f"Planned the answer as `{dialogue_decision.goal}` with response shape "
                    f"`{dialogue_decision.response_shape}`. {dialogue_decision.rationale}"
                ),
            ),
            TraceStep(
                title="Response strategy",
                detail=(
                    f"Chose strategy `{strategy_decision.strategy}` with answer mode "
                    f"`{strategy_decision.answer_mode}` and follow-up policy "
                    f"`{strategy_decision.follow_up_policy}`. {strategy_decision.rationale}"
                ),
            ),
            TraceStep(
                title="Grounding source",
                detail=(
                    "Used the assistant profile and the active conversation without needing corpus retrieval."
                    if intent_decision.evidence_policy == "profile_only"
                    else f"Used the active uploaded PDF: {document_title}."
                    if mode == "pdf" and document_title
                    else f"Used OCR text extracted from the active uploaded image: {document_title}."
                    if mode == "image" and document_title
                    else "Used the persistent local INCIBE corpus stored in Chroma."
                ),
            ),
            TraceStep(
                title="Evidence retrieval",
                detail=(
                    "No corpus retrieval was needed for this turn."
                    if intent_decision.evidence_policy == "profile_only"
                    else f"Retrieved {retrieved_candidates} candidate chunk(s) and kept {curated_candidates} "
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
            intent=intent_decision.intent,
            evidence_policy=intent_decision.evidence_policy,
            dialogue_goal=dialogue_decision.goal,
            response_shape=dialogue_decision.response_shape,
            response_strategy=strategy_decision.strategy,
            answer_mode=strategy_decision.answer_mode,
            follow_up_policy=strategy_decision.follow_up_policy,
            needs_clarification=strategy_decision.needs_clarification,
            active_document=document_title,
            history_turns=len(history),
            ocr_segments=ocr_segments,
            safety_mode=bool(safety_assessment and safety_assessment.cautious_mode),
            risk_signals=safety_assessment.signals if safety_assessment else [],
            selected_chunk_refs=[self._chunk_ref(chunk) for chunk in selected_chunks],
            retrieval_ms=round(retrieval_ms, 2),
            embedding_ms=round(embedding_ms, 2),
            generation_ms=round(generation_ms, 2),
            total_ms=round(total_ms, 2),
            prompt_tokens=model_result.prompt_tokens,
            completion_tokens=model_result.completion_tokens,
            total_tokens=model_result.total_tokens,
            estimated_external_cost_eur=0.0,
            local_execution=True,
            local_execution_note=(
                f"{self.profile.local_execution_rationale}. {self.profile.local_cost_rationale}."
            ),
            cost_measurement_note=(
                "El coste facturable externo es 0 porque chat, embeddings y retrieval se ejecutan en local. "
                "Aun así se registran tokens y tiempos para medir consumo relativo y poder compararlo con precios de terceros si hiciera falta."
            ),
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
