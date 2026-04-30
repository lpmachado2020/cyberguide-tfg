"""Prompt-building helpers for grounded response generation.

Purpose:
- Build the system and user prompts used by the local chat model.

Inputs:
- Retrieved chunks and the user's question.

Outputs:
- Prompt strings ready to be sent to Ollama.

Used by:
- `backend/app/services/rag.py`
"""

import re
from typing import Optional

from .schemas import ConversationTurn, RetrievedChunk
from .services.security_policy import SafetyAssessment


SYSTEM_PROMPT = """You are CyberGuide, a specialized assistant for cybersecurity literacy in SMEs and self-employment contexts.

Rules:
- Answer in clear Spanish unless the user explicitly asks for another language.
- Use only the retrieved context as evidence for factual claims.
- If the context is insufficient, say so clearly and do not fill gaps with general knowledge.
- Keep the tone practical, cautious, and easy to understand.
- Do not present your answer as legal or forensic certainty.
- Do not cite information that does not appear in the provided context.
- Prefer a short, structured answer over a long speculative one.
"""

FACTUAL_QUESTION_PATTERNS = (
    r"^\s*que\b",
    r"^\s*qué\b",
    r"^\s*cual\b",
    r"^\s*cuál\b",
    r"^\s*cuales\b",
    r"^\s*cuáles\b",
    r"^\s*quien\b",
    r"^\s*quién\b",
    r"^\s*cuando\b",
    r"^\s*cuándo\b",
    r"^\s*como\b",
    r"^\s*cómo\b",
    r"^\s*es\b",
    r"^\s*son\b",
)

GUIDANCE_QUESTION_HINTS = (
    "que debo",
    "qué debo",
    "que deberia",
    "qué debería",
    "como puedo",
    "cómo puedo",
    "paso a paso",
    "recomienda",
    "recomiendas",
    "medidas",
    "primeros pasos",
)


def build_context_block(chunks: list[RetrievedChunk]) -> str:
    """Format retrieved chunks into a readable grounding block."""
    blocks: list[str] = []
    for idx, chunk in enumerate(chunks, start=1):
        title = chunk.metadata.get("title", "Untitled source")
        source_url = chunk.metadata.get("source_url", "local")
        chunk_index = chunk.metadata.get("chunk_index", "?")
        blocks.append(
            f"[Source {idx}] title={title}; chunk={chunk_index}; url={source_url}\n{chunk.text}"
        )
    return "\n\n".join(blocks)


def build_history_block(history: list[ConversationTurn]) -> str:
    """Format recent chat turns so the model can resolve follow-up questions."""
    if not history:
        return "No prior conversation available."

    lines = [f"{turn.role.title()}: {turn.content}" for turn in history]
    return "\n".join(lines)


def is_narrow_fact_question(question: str) -> bool:
    """Return True when the question likely expects a short exact answer."""
    normalized = question.strip().lower()
    if any(hint in normalized for hint in GUIDANCE_QUESTION_HINTS):
        return False

    word_count = len(re.findall(r"\b\w+\b", normalized))
    matches_factual_shape = any(re.search(pattern, normalized) for pattern in FACTUAL_QUESTION_PATTERNS)
    return matches_factual_shape and word_count <= 18


def build_user_prompt(
    question: str,
    chunks: list[RetrievedChunk],
    *,
    history: Optional[list[ConversationTurn]] = None,
    document_title: Optional[str] = None,
    safety_assessment: Optional[SafetyAssessment] = None,
) -> str:
    """Build the user prompt that combines the question and retrieved context."""
    context = build_context_block(chunks)
    history_block = build_history_block(history or [])
    narrow_fact_mode = is_narrow_fact_question(question)
    document_note = (
        f'Active uploaded document: "{document_title}"\n'
        if document_title
        else "Active uploaded document: none\n"
    )
    safety_note = (
        "Active safety policy: high-risk screenshot or document interaction detected.\n"
        f"Detected signals: {', '.join(safety_assessment.signals) or 'not specified'}\n"
        if safety_assessment and safety_assessment.cautious_mode
        else "Active safety policy: normal grounding mode.\n"
    )
    response_mode_note = (
        "Response mode: narrow factual answer.\n"
        if narrow_fact_mode
        else "Response mode: explanatory grounded answer.\n"
    )
    return f"""User question:
{question}

Recent conversation:
{history_block}

{document_note}
{safety_note}
{response_mode_note}

Retrieved context:
{context}

Instructions:
- Answer in Spanish.
- Use the retrieved context as your only evidence base.
- If useful, provide short actionable steps, but only if they are supported by the context.
- Cite support naturally using the document title, for example: "(Fuente: Políticas de seguridad para la pyme: copias de seguridad)".
- If the context is not enough, say explicitly that the available sources are insufficient.
- Do not mention pages unless the evidence makes that detail necessary.
- Avoid generic filler, exaggerated certainty, or recommendations not grounded in the context.
- If the response mode is narrow factual answer:
  - answer the exact question first in one short sentence,
  - keep the total answer to at most 2 short paragraphs,
  - do not add extra recommendations unless the user asked for them,
  - do not broaden the scope beyond the requested fact or definition.
  - prefer the exact wording and named terms that appear in the context over paraphrases.
  - if the question asks for a factor, tool, level, risk, period, or list of items, reproduce those terms directly from the context.
  - avoid introductory filler such as "según los documentos" before giving the fact itself.
- If the safety policy is active, do not recommend clicking links, opening attachments, validating identity through the provided message, or entering credentials or OTP codes from the suspicious content itself.
- If the safety policy is active, prefer independent verification through trusted official channels and conservative next steps.
"""
