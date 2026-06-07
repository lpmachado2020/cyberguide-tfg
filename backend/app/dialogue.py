"""Dialogue-goal classification layered on top of intent routing.

Purpose:
- Decide what the user expects to receive inside the resolved intent.
- Keep answer structure reusable across domains and corpora.

Inputs:
- User question, recent conversation and the already-resolved intent.

Outputs:
- A dialogue decision with conversational goal and preferred response shape.

Used by:
- `backend/app/services/rag.py`
- `backend/app/prompting.py`
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from .intents import IntentDecision
from .prompting import is_follow_up_question, is_list_question, is_narrow_fact_question
from .schemas import ConversationTurn


NEXT_STEP_HINTS = (
    "primer paso",
    "primeros pasos",
    "por donde empiezo",
    "por dónde empiezo",
    "por donde empezarias",
    "por donde empezarías",
    "por dónde empezarías",
    "que hago ahora",
    "qué hago ahora",
    "y ahora que",
    "y ahora qué",
)

CHECKLIST_HINTS = (
    "recomendaciones",
    "medidas",
    "buenas practicas",
    "buenas prácticas",
    "que debo hacer",
    "qué debo hacer",
    "como reforzar",
    "cómo reforzar",
    "mejorar",
)

COMPARISON_HINTS = (
    "diferencia",
    "compar",
    "mejor que",
    "peor que",
    "frente a",
    "vs",
)

TRIAGE_HINTS = (
    "no se si",
    "no sé si",
    "parece",
    "correo raro",
    "correo sospechoso",
    "es phishing o",
    "es normal o",
    "no sabemos si",
)

CONTAINMENT_HINTS = (
    "he hecho clic",
    "hice click",
    "ya he hecho clic",
    "ya hice clic",
    "meti la contraseña",
    "metí la contraseña",
    "introduje la contraseña",
    "me han hackeado",
    "me han entrado",
    "comprometida",
)

EXPLANATION_HINTS = (
    r"^\s*que es\b",
    r"^\s*qué es\b",
    r"^\s*como funciona\b",
    r"^\s*cómo funciona\b",
    r"^\s*por que\b",
    r"^\s*por qué\b",
)

SUMMARY_HINTS = (
    "resume",
    "resumen",
    "principales medidas",
    "ideas clave",
)


@dataclass(frozen=True)
class DialogueDecision:
    """Conversational goal chosen after intent routing."""

    goal: str
    response_shape: str
    answer_depth: str
    rationale: str


def classify_dialogue_goal(
    *,
    question: str,
    history: list[ConversationTurn],
    intent_decision: IntentDecision,
    previous_goal: Optional[str] = None,
) -> DialogueDecision:
    """Decide what the user is trying to get from the assistant right now."""
    normalized = question.strip().lower()

    if intent_decision.intent == "greeting":
        return DialogueDecision(
            goal="open_conversation",
            response_shape="brief_welcome",
            answer_depth="brief",
            rationale="Greeting turns should open the conversation naturally.",
        )

    if intent_decision.intent == "capabilities":
        return DialogueDecision(
            goal="describe_capabilities",
            response_shape="capability_summary",
            answer_depth="medium",
            rationale="The user is asking what the assistant is for.",
        )

    if intent_decision.intent == "scope_redirect":
        return DialogueDecision(
            goal="redirect_scope",
            response_shape="scope_redirect",
            answer_depth="brief",
            rationale="The turn should redirect the conversation into supported scope.",
        )

    if intent_decision.intent == "document_analysis":
        if _has_any(normalized, SUMMARY_HINTS):
            return DialogueDecision(
                goal="summarize_document",
                response_shape="grounded_summary",
                answer_depth="medium",
                rationale="The user is asking for a grounded summary of the active document.",
            )
        if _matches_any(normalized, EXPLANATION_HINTS):
            return DialogueDecision(
                goal="explain_document_point",
                response_shape="grounded_explanation",
                answer_depth="medium",
                rationale="The user is asking for explanation inside the active document.",
            )
        if is_narrow_fact_question(question):
            return DialogueDecision(
                goal="fact_lookup",
                response_shape="brief_fact",
                answer_depth="brief",
                rationale="The document turn expects a concrete factual lookup.",
            )
        return DialogueDecision(
            goal="analyze_document",
            response_shape="grounded_explanation",
            answer_depth="medium",
            rationale="Default document flow should explain the active evidence clearly.",
        )

    if _looks_like_next_step(normalized):
        return DialogueDecision(
            goal="next_step",
            response_shape="single_next_step",
            answer_depth="brief",
            rationale="The user is asking what to do first or next.",
        )

    if _has_any(normalized, CONTAINMENT_HINTS):
        return DialogueDecision(
            goal="next_step",
            response_shape="single_next_step",
            answer_depth="brief",
            rationale="The user is reporting a risky action or compromise and needs immediate containment.",
        )

    if is_narrow_fact_question(question):
        return DialogueDecision(
            goal="fact_lookup",
            response_shape="brief_fact",
            answer_depth="brief",
            rationale="The turn expects a short direct fact or definition.",
        )

    if is_list_question(question) or _has_any(normalized, CHECKLIST_HINTS):
        return DialogueDecision(
            goal="action_checklist",
            response_shape="bullet_checklist",
            answer_depth="medium",
            rationale="The user expects several concrete recommendations or actions.",
        )

    if _has_any(normalized, COMPARISON_HINTS):
        return DialogueDecision(
            goal="compare_options",
            response_shape="compare",
            answer_depth="medium",
            rationale="The user is comparing options or concepts.",
        )

    if _matches_any(normalized, EXPLANATION_HINTS):
        return DialogueDecision(
            goal="explain_topic",
            response_shape="grounded_explanation",
            answer_depth="medium",
            rationale="The user is asking for understanding rather than just a fact.",
        )

    if previous_goal and is_follow_up_question(question, history):
        if previous_goal in {"triage", "next_step", "action_checklist", "fact_lookup"}:
            return DialogueDecision(
                goal=previous_goal,
                response_shape=_shape_for_goal(previous_goal),
                answer_depth="brief" if previous_goal in {"next_step", "fact_lookup"} else "medium",
                rationale="Short follow-up inherited the previous dialogue goal.",
            )

    if intent_decision.intent == "guided_support" and _has_any(normalized, TRIAGE_HINTS):
        return DialogueDecision(
            goal="triage",
            response_shape="triage_checklist",
            answer_depth="medium",
            rationale="The user is describing a situation and needs help assessing it.",
        )

    if intent_decision.intent == "grounded_lookup":
        return DialogueDecision(
            goal="grounded_answer",
            response_shape="grounded_explanation",
            answer_depth="medium",
            rationale="The turn needs a grounded answer without broader guidance.",
        )

    return DialogueDecision(
        goal="guided_answer",
        response_shape="grounded_explanation",
        answer_depth="medium",
        rationale="Default conversational goal is to provide a useful guided answer.",
    )


def _has_any(text: str, hints: tuple[str, ...]) -> bool:
    return any(hint in text for hint in hints)


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _looks_like_next_step(text: str) -> bool:
    return _has_any(text, NEXT_STEP_HINTS)


def _shape_for_goal(goal: str) -> str:
    mapping = {
        "triage": "triage_checklist",
        "next_step": "single_next_step",
        "action_checklist": "bullet_checklist",
        "fact_lookup": "brief_fact",
    }
    return mapping.get(goal, "grounded_explanation")
