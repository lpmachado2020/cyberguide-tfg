"""Response-strategy classification layered on top of intent and dialogue goals.

Purpose:
- Decide how the assistant should answer the current turn.
- Keep response control reusable even when corpus or domain changes.

Inputs:
- User question, recent history, intent decision and dialogue-goal decision.

Outputs:
- A strategy decision that controls retrieval, clarification and answer mode.

Used by:
- `backend/app/services/rag.py`
- `backend/app/prompting.py`
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from .dialogue import DialogueDecision
from .intents import IntentDecision
from .schemas import ConversationTurn


GENERIC_HELP_PATTERNS = (
    r"^\s*me ayudas\??\s*$",
    r"^\s*puedes ayudarme\??\s*$",
    r"^\s*necesito ayuda\??\s*$",
    r"^\s*tengo un problema\??\s*$",
    r"^\s*no se que hacer\??\s*$",
    r"^\s*no sé qué hacer\??\s*$",
)

COMPARE_REQUEST_PATTERNS = (
    r"\bdiferencia\b",
    r"\bcompar",
    r"\bfrente a\b",
    r"\bvs\b",
)


@dataclass(frozen=True)
class StrategyDecision:
    """How the assistant should answer the current turn."""

    strategy: str
    answer_mode: str
    should_retrieve: bool
    needs_clarification: bool
    clarification_prompt: Optional[str]
    follow_up_policy: str
    rationale: str


def classify_response_strategy(
    *,
    question: str,
    history: list[ConversationTurn],
    intent_decision: IntentDecision,
    dialogue_decision: DialogueDecision,
    active_document: bool = False,
) -> StrategyDecision:
    """Choose the response strategy for the current conversational turn."""
    normalized = question.strip().lower()

    if intent_decision.intent in {"greeting", "capabilities", "scope_redirect"}:
        return StrategyDecision(
            strategy="deterministic_meta",
            answer_mode="deterministic_template",
            should_retrieve=False,
            needs_clarification=False,
            clarification_prompt=None,
            follow_up_policy="invite_supported_topic",
            rationale="Meta turns should stay fast, deterministic and retrieval-free.",
        )

    if active_document and _is_very_broad_document_turn(normalized):
        return StrategyDecision(
            strategy="clarify_document_goal",
            answer_mode="clarifying_question",
            should_retrieve=False,
            needs_clarification=True,
            clarification_prompt=(
                "Puedo seguir con el documento, pero aquí me ayudaría concretar un poco más: "
                "¿quieres un resumen, las ideas clave o responder una duda concreta?"
            ),
            follow_up_policy="wait_for_user_detail",
            rationale="Broad document turns benefit from one precise clarification before retrieval.",
        )

    if intent_decision.intent == "guided_support" and _is_generic_help_turn(normalized):
        return StrategyDecision(
            strategy="clarify_problem_space",
            answer_mode="clarifying_question",
            should_retrieve=False,
            needs_clarification=True,
            clarification_prompt=(
                "Puedo ayudarte, pero para orientarte bien dime si te preocupa sobre todo un correo sospechoso, "
                "una cuenta comprometida, contraseñas, acceso o revisión de un documento."
            ),
            follow_up_policy="wait_for_user_detail",
            rationale="Very broad help requests need one short clarification instead of a canned generic answer.",
        )

    if dialogue_decision.goal == "compare_options" and _missing_comparison_target(normalized):
        return StrategyDecision(
            strategy="clarify_comparison_target",
            answer_mode="clarifying_question",
            should_retrieve=False,
            needs_clarification=True,
            clarification_prompt="¿Qué dos opciones o conceptos quieres comparar exactamente?",
            follow_up_policy="wait_for_user_detail",
            rationale="Comparison turns need the compared items explicitly stated.",
        )

    if dialogue_decision.goal == "next_step":
        return StrategyDecision(
            strategy="direct_next_step",
            answer_mode="deterministic_or_grounded_short",
            should_retrieve=intent_decision.should_retrieve,
            needs_clarification=False,
            clarification_prompt=None,
            follow_up_policy="offer_one_branch",
            rationale="Immediate-action turns should prioritize the next concrete step.",
        )

    if dialogue_decision.goal == "compare_options":
        return StrategyDecision(
            strategy="direct_compare",
            answer_mode="grounded_comparison",
            should_retrieve=intent_decision.should_retrieve,
            needs_clarification=False,
            clarification_prompt=None,
            follow_up_policy="offer_practical_difference",
            rationale="Comparison turns should contrast the concepts directly instead of switching into incident handling.",
        )

    if dialogue_decision.goal == "triage":
        return StrategyDecision(
            strategy="triage_then_focus",
            answer_mode="deterministic_or_grounded_checklist",
            should_retrieve=intent_decision.should_retrieve,
            needs_clarification=False,
            clarification_prompt=None,
            follow_up_policy="invite_specific_signal",
            rationale="Triage turns should help classify the situation before broad remediation.",
        )

    if dialogue_decision.goal == "action_checklist":
        return StrategyDecision(
            strategy="direct_checklist",
            answer_mode="grounded_or_guided_checklist",
            should_retrieve=intent_decision.should_retrieve,
            needs_clarification=False,
            clarification_prompt=None,
            follow_up_policy="offer_next_step",
            rationale="Checklist turns should stay structured and easy to scan.",
        )

    if dialogue_decision.goal == "fact_lookup":
        return StrategyDecision(
            strategy="direct_fact",
            answer_mode="brief_grounded_fact",
            should_retrieve=intent_decision.should_retrieve,
            needs_clarification=False,
            clarification_prompt=None,
            follow_up_policy="stay_concise",
            rationale="Fact lookups should answer directly and avoid unnecessary expansion.",
        )

    if dialogue_decision.goal in {"explain_topic", "grounded_answer", "analyze_document", "explain_document_point"}:
        return StrategyDecision(
            strategy="grounded_explanation",
            answer_mode="grounded_explanation",
            should_retrieve=intent_decision.should_retrieve,
            needs_clarification=False,
            clarification_prompt=None,
            follow_up_policy="offer_deeper_follow_up",
            rationale="Explanatory turns should answer clearly first, then support understanding.",
        )

    if dialogue_decision.goal == "summarize_document":
        return StrategyDecision(
            strategy="grounded_summary",
            answer_mode="grounded_summary",
            should_retrieve=intent_decision.should_retrieve,
            needs_clarification=False,
            clarification_prompt=None,
            follow_up_policy="offer_key_point_follow_up",
            rationale="Summary turns should synthesize evidence before diving into detail.",
        )

    return StrategyDecision(
        strategy="default_guided_response",
        answer_mode="guided_response",
        should_retrieve=intent_decision.should_retrieve,
        needs_clarification=False,
        clarification_prompt=None,
        follow_up_policy="invite_relevant_follow_up",
        rationale="Default strategy is to answer helpfully without overcomplicating the turn.",
    )


def _is_generic_help_turn(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in GENERIC_HELP_PATTERNS)


def _is_very_broad_document_turn(text: str) -> bool:
    broad_prompts = {"que hago", "qué hago", "explicamelo", "explícamelo", "ayudame", "ayúdame"}
    compact = re.sub(r"[¿?!.]", "", text).strip()
    return compact in broad_prompts or len(re.findall(r"\b\w+\b", compact)) <= 3


def _missing_comparison_target(text: str) -> bool:
    if not any(re.search(pattern, text) for pattern in COMPARE_REQUEST_PATTERNS):
        return False
    if "entre " in text and " y " in text:
        return False
    connectors = re.findall(r"\b(vs|frente a|o)\b", text)
    return len(connectors) == 0
