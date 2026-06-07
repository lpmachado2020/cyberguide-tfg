"""Intent routing and assistant profile helpers for CyberGuide.

Purpose:
- Classify the user's turn before retrieval.
- Keep assistant/domain configuration reusable across corpora.

Inputs:
- The user question, recent history and active interaction mode.

Outputs:
- An intent decision with evidence policy and retrieval strategy.

Used by:
- `backend/app/services/rag.py`
- `backend/app/prompting.py`
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from .config import Settings
from .prompting import is_follow_up_question, is_narrow_fact_question
from .schemas import ConversationTurn


GREETING_PATTERNS = (
    r"^\s*hola\b",
    r"^\s*buenas\b",
    r"^\s*hey\b",
    r"^\s*holi\b",
    r"^\s*buenos dias\b",
    r"^\s*buenas tardes\b",
    r"^\s*buenas noches\b",
)

CAPABILITY_PATTERNS = (
    r"\bquien eres\b",
    r"\bquién eres\b",
    r"\bpara que sirves\b",
    r"\bpara qué sirves\b",
    r"\bque puedes hacer\b",
    r"\bqué puedes hacer\b",
    r"\bcomo funcionas\b",
    r"\bcómo funcionas\b",
    r"\bque sabes hacer\b",
    r"\bqué sabes hacer\b",
)

SCOPE_REDIRECT_PATTERNS = (
    r"\btiempo hace\b",
    r"\bcapital de\b",
    r"\bquien gano\b",
    r"\bquién ganó\b",
    r"\breceta\b",
)

EXPLICIT_GROUNDED_PATTERNS = (
    r"\bsegun el documento\b",
    r"\bsegún el documento\b",
    r"\bsegun la fuente\b",
    r"\bsegún la fuente\b",
    r"\bque dice el documento\b",
    r"\bqué dice el documento\b",
    r"\bmenciona el documento\b",
    r"\bmenciona la guía\b",
    r"\bsegun incibe\b",
    r"\bsegún incibe\b",
)

COMPARE_PATTERNS = (
    r"\bvs\b",
    r"\bversus\b",
    r"\bdiferencia\b",
    r"\bcompar",
    r"\bentre\b.+\by\b",
)

GUIDED_SUPPORT_HINTS = (
    "phishing",
    "hacke",
    "hackear",
    "hackeado",
    "correo sospechoso",
    "me han robado",
    "me han entrado",
    "mi cuenta",
    "me preocupa",
    "no se que hacer",
    "no sé qué hacer",
    "que hago",
    "qué hago",
    "problema",
    "incidente",
    "sospechoso",
    "clic",
    "hice click",
    "he hecho clic",
    "malware",
    "virus",
    "ransomware",
)


@dataclass(frozen=True)
class AssistantProfile:
    """Configurable assistant profile that can be swapped across domains."""

    name: str
    domain_name: str
    audience: str
    mission: str
    corpus_scope: str
    local_execution_rationale: str
    local_cost_rationale: str
    scope_boundary: str
    domain_keywords: tuple[str, ...]


@dataclass(frozen=True)
class IntentDecision:
    """Result of the pre-retrieval intent classification stage."""

    intent: str
    evidence_policy: str
    prompt_style: str
    should_retrieve: bool
    allow_general_guidance: bool
    rationale: str


def build_default_profile(settings: Settings) -> AssistantProfile:
    """Return the default reusable profile for the current assistant."""
    return AssistantProfile(
        name=settings.assistant_name,
        domain_name=settings.assistant_domain_name,
        audience=settings.assistant_audience,
        mission=settings.assistant_mission,
        corpus_scope=settings.assistant_corpus_scope,
        local_execution_rationale=settings.local_execution_rationale,
        local_cost_rationale=settings.local_cost_rationale,
        scope_boundary=settings.assistant_scope_boundary,
        domain_keywords=(
            "ciberseguridad",
            "phishing",
            "hacke",
            "contraseña",
            "contrasena",
            "incidente",
            "seguridad",
            "cuenta",
            "acceso",
            "teletrabajo",
            "copia de seguridad",
            "backup",
            "ransomware",
            "malware",
            "control de acceso",
            "crisis",
            "incibe",
            "pdf",
            "correo sospechoso",
        ),
    )


def classify_intent(
    *,
    question: str,
    history: list[ConversationTurn],
    mode: str,
    profile: AssistantProfile,
    active_document: bool = False,
    previous_intent: Optional[str] = None,
) -> IntentDecision:
    """Classify the user's turn into a reusable conversational intent."""
    normalized = question.strip().lower()

    if _matches_any(normalized, GREETING_PATTERNS):
        return IntentDecision(
            intent="greeting",
            evidence_policy="profile_only",
            prompt_style="meta",
            should_retrieve=False,
            allow_general_guidance=True,
            rationale="Greeting turn detected.",
        )

    if _matches_any(normalized, CAPABILITY_PATTERNS):
        return IntentDecision(
            intent="capabilities",
            evidence_policy="profile_only",
            prompt_style="meta",
            should_retrieve=False,
            allow_general_guidance=True,
            rationale="Capabilities or identity question detected.",
        )

    if _matches_any(normalized, SCOPE_REDIRECT_PATTERNS) or _looks_off_scope(normalized, profile):
        return IntentDecision(
            intent="scope_redirect",
            evidence_policy="profile_only",
            prompt_style="scope_redirect",
            should_retrieve=False,
            allow_general_guidance=False,
            rationale="Turn appears outside the configured assistant scope.",
        )

    if mode in {"pdf", "image"} or active_document:
        return IntentDecision(
            intent="document_analysis",
            evidence_policy="strict_grounded",
            prompt_style="document_analysis",
            should_retrieve=True,
            allow_general_guidance=False,
            rationale="Active document or image flow requires evidence-first analysis.",
        )

    if previous_intent in {"guided_support", "grounded_lookup"} and is_follow_up_question(question, history):
        inherited_intent = "guided_support" if previous_intent == "guided_support" else "grounded_lookup"
        return IntentDecision(
            intent=inherited_intent,
            evidence_policy="hybrid_guided" if inherited_intent == "guided_support" else "strict_grounded",
            prompt_style="guided_support" if inherited_intent == "guided_support" else "grounded_lookup",
            should_retrieve=True,
            allow_general_guidance=inherited_intent == "guided_support",
            rationale="Short follow-up inherited the previous conversational intent.",
        )

    if _matches_any(normalized, COMPARE_PATTERNS):
        return IntentDecision(
            intent="grounded_lookup",
            evidence_policy="strict_grounded",
            prompt_style="grounded_lookup",
            should_retrieve=True,
            allow_general_guidance=False,
            rationale="Comparison-style lookup detected.",
        )

    if _matches_any(normalized, EXPLICIT_GROUNDED_PATTERNS) or is_narrow_fact_question(question):
        return IntentDecision(
            intent="grounded_lookup",
            evidence_policy="strict_grounded",
            prompt_style="grounded_lookup",
            should_retrieve=True,
            allow_general_guidance=False,
            rationale="Explicit factual or document-style lookup detected.",
        )

    if any(hint in normalized for hint in GUIDED_SUPPORT_HINTS) or _looks_like_problem_statement(normalized):
        return IntentDecision(
            intent="guided_support",
            evidence_policy="hybrid_guided",
            prompt_style="guided_support",
            should_retrieve=True,
            allow_general_guidance=True,
            rationale="Problem-oriented guidance request detected.",
        )

    return IntentDecision(
        intent="guided_support",
        evidence_policy="hybrid_guided",
        prompt_style="guided_support",
        should_retrieve=True,
        allow_general_guidance=True,
        rationale="Defaulting to guided support for a natural conversational turn within scope.",
    )


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _looks_off_scope(text: str, profile: AssistantProfile) -> bool:
    """Return True when the turn seems unrelated to the configured assistant domain."""
    if any(keyword in text for keyword in profile.domain_keywords):
        return False
    if len(re.findall(r"\b\w+\b", text)) <= 3:
        return False
    return any(re.search(pattern, text) for pattern in SCOPE_REDIRECT_PATTERNS)


def _looks_like_problem_statement(text: str) -> bool:
    """Detect broad issue descriptions that deserve guided support."""
    return bool(
        re.search(
            r"\b(me pasa|me ocurre|tengo un problema|necesito ayuda|quiero mejorar|quiero revisar|quiero entender)\b",
            text,
        )
    )
