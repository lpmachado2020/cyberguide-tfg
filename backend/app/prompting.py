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
from typing import TYPE_CHECKING, Optional

from .schemas import ConversationTurn, RetrievedChunk
from .services.security_policy import SafetyAssessment

if TYPE_CHECKING:
    from .dialogue import DialogueDecision
    from .intents import AssistantProfile, IntentDecision
    from .strategy import StrategyDecision


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
    r"^\s*cada\b",
    r"^\s*es\b",
    r"^\s*existe\b",
    r"^\s*existen\b",
    r"^\s*hay\b",
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

LIST_QUESTION_HINTS = (
    "que otras",
    "qué otras",
    "que mas",
    "qué más",
    "ademas",
    "además",
    "recomendaciones",
    "consejos",
    "buenas practicas",
    "buenas prácticas",
    "medidas",
)

FOLLOW_UP_HINTS = (
    "y ",
    "entonces",
    "vale",
    "ok",
    "pero",
    "o sea",
    "eso",
    "esto",
    "esa",
    "ese",
    "asi",
    "así",
    "tambien",
    "también",
)


def build_context_block(chunks: list[RetrievedChunk]) -> str:
    """Format retrieved chunks into a readable grounding block."""
    if not chunks:
        return "No retrieved context available."

    blocks: list[str] = []
    for chunk in chunks:
        title = chunk.metadata.get("title", "Untitled source")
        blocks.append(f"Document title: {title}\nEvidence:\n{chunk.text}")
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


def is_list_question(question: str) -> bool:
    """Return True when the question asks for several recommendations or examples."""
    normalized = question.strip().lower()
    return any(hint in normalized for hint in LIST_QUESTION_HINTS)


def is_follow_up_question(question: str, history: Optional[list[ConversationTurn]] = None) -> bool:
    """Return True when the turn appears to depend on previous chat context."""
    if not history:
        return False

    normalized = question.strip().lower()
    word_count = len(re.findall(r"\b\w+\b", normalized))
    if any(normalized.startswith(hint) for hint in FOLLOW_UP_HINTS):
        return True

    has_reference_language = bool(
        re.search(r"\b(eso|esto|esa|ese|asi|así|tambien|también|entonces)\b", normalized)
    )
    return (has_reference_language and word_count <= 16) or word_count <= 6


def build_user_prompt(
    question: str,
    chunks: list[RetrievedChunk],
    *,
    profile: "AssistantProfile",
    intent_decision: "IntentDecision",
    dialogue_decision: "DialogueDecision",
    strategy_decision: "StrategyDecision",
    history: Optional[list[ConversationTurn]] = None,
    document_title: Optional[str] = None,
    safety_assessment: Optional[SafetyAssessment] = None,
) -> str:
    """Build the user prompt that combines the question and retrieved context."""
    context = build_context_block(chunks)
    narrow_fact_mode = is_narrow_fact_question(question)
    list_mode = is_list_question(question)
    follow_up_mode = is_follow_up_question(question, history)
    history_block = build_history_block(history or []) if follow_up_mode else "No prior conversation available."
    evidence_policy = intent_decision.evidence_policy
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
        else "Response mode: grounded list answer.\n"
        if list_mode
        else "Response mode: conversational follow-up answer.\n"
        if follow_up_mode
        else "Response mode: explanatory grounded answer.\n"
    )
    evidence_policy_note = (
        "Evidence policy: profile-only assistant conversation.\n"
        if evidence_policy == "profile_only"
        else "Evidence policy: hybrid guided support.\n"
        if evidence_policy == "hybrid_guided"
        else "Evidence policy: strict grounded answer.\n"
    )
    dialogue_goal_note = (
        f"Dialogue goal: {dialogue_decision.goal}.\n"
        f"Preferred response shape: {dialogue_decision.response_shape}.\n"
        f"Answer depth: {dialogue_decision.answer_depth}.\n"
    )
    strategy_note = (
        f"Response strategy: {strategy_decision.strategy}.\n"
        f"Answer mode: {strategy_decision.answer_mode}.\n"
        f"Follow-up policy: {strategy_decision.follow_up_policy}.\n"
        f"Needs clarification: {'yes' if strategy_decision.needs_clarification else 'no'}.\n"
    )
    return f"""User question:
{question}

Recent conversation:
{history_block}

Assistant profile:
- Name: {profile.name}
- Domain: {profile.domain_name}
- Audience: {profile.audience}
- Mission: {profile.mission}
- Corpus scope: {profile.corpus_scope}
- Scope boundary: {profile.scope_boundary}
- Local execution rationale: {profile.local_execution_rationale}
- Local cost rationale: {profile.local_cost_rationale}

{document_note}
{safety_note}
{response_mode_note}
{evidence_policy_note}
{dialogue_goal_note}
{strategy_note}

Retrieved context:
{context}

Instructions:
- Answer in Spanish.
- If the evidence policy is strict grounded answer:
  - use the retrieved context as your only evidence base for factual claims,
  - and do not fill gaps with general knowledge.
- If the evidence policy is hybrid guided support:
  - use retrieved context whenever it helps,
  - but if retrieval is weak you may still offer practical first-step guidance based on the user's situation and your domain role,
  - clearly avoid pretending that unsupported guidance comes from the corpus.
- If the evidence policy is profile-only assistant conversation:
  - answer from the assistant profile and the active conversation,
  - and do not claim corpus grounding that has not happened.
- If there is recent conversation, use it to maintain continuity instead of answering as if this were an isolated request.
- If useful, provide short actionable steps, but only if they are supported by the context.
- Keep the main answer natural and easy to read.
- Answer the user directly; do not start by repeating or paraphrasing their question.
- Avoid openings such as "Entiendo que...", "La pregunta es...", "La respuesta es...", or "Me alegra que...".
- Avoid canned enthusiasm or scripted assistance phrases such as "Claro", "Encantado de ayudarte" or similar unless the user explicitly invites that tone.
- Do not repeat `(Fuente: ...)` in every paragraph.
- Do not mention internal labels, chunk numbers, retrieval positions, metadata fields, or similar implementation details.
- Ignore internal checklist codes or document markers such as `B PER`, control labels, or similar artifacts from the source text.
- When source metadata is already available elsewhere in the interface, avoid inline source markers unless one brief mention is genuinely needed to clarify a claim.
- If the context is not enough, say explicitly that the available sources are insufficient.
- If the user is greeting you or asking what you can do, answer naturally instead of talking about missing context.
- Do not mention pages unless the evidence makes that detail necessary.
- Avoid generic filler, exaggerated certainty, or recommendations not grounded in the context.
- Do not merge two separate grounded ideas into a stronger claim unless the context explicitly links them.
- If the context mentions generic "systems", "tools", or "managers" without naming products, keep that distinction explicit.
- If the context shows a blank placeholder such as `___`, explain that the source leaves that field unspecified instead of inventing a value.
- Prefer wording that sounds like guided conversation with the user, not like a document summary pasted into chat.
- When you are giving general orientation instead of corpus-backed facts, be explicit through tone, not with robotic disclaimers.
- In guided support turns, prioritize helping the user move forward coherently over restating that retrieval was weak.
- If the response mode is narrow factual answer:
  - answer the exact question first in one short sentence,
  - keep the total answer to at most 2 short paragraphs,
  - do not add extra recommendations unless the user asked for them,
  - do not broaden the scope beyond the requested fact or definition.
  - prefer the exact wording and named terms that appear in the context over paraphrases.
  - if the question asks for a factor, tool, level, risk, period, or list of items, reproduce those terms directly from the context.
  - avoid introductory filler such as "según los documentos" before giving the fact itself.
- If the response mode is grounded list answer:
  - give 3 to 5 distinct grounded points,
  - use bullets when that makes the answer easier to scan,
  - avoid repeating the same recommendation with different wording,
  - and mention the limitation briefly if the available context only covers one part of the broader topic.
- If the response mode is conversational follow-up answer:
  - resolve what "eso", "cada cuánto", "y si", or similar references point to using the recent conversation,
  - answer as a continuation, without reintroducing the whole topic from scratch,
  - and keep the answer concise unless the user explicitly asks to expand.
- If the dialogue goal is `next_step`:
  - lead with the first or immediate next action,
  - keep the answer to 1 or 2 short paragraphs,
  - and avoid re-listing the whole plan unless the user asks for it.
- If the dialogue goal is `triage`:
  - help the user assess the situation with 3 or 4 concrete signals or checks,
  - prefer practical discrimination criteria over generic theory,
  - and do not jump straight into a long generic checklist if the user is still identifying the problem.
- If the dialogue goal is `action_checklist`:
  - provide a compact checklist of distinct steps,
  - avoid repeating the same advice with different wording,
  - and keep the sequence easy to scan.
- If the dialogue goal is `compare_options`:
  - compare the options directly against each other,
  - state the practical difference first,
  - and only then add supporting detail.
- If the response strategy is `direct_next_step`:
  - give the immediate action first,
  - keep the answer tight,
  - and avoid reopening the full topic unless the user asks.
- If the response strategy is `triage_then_focus`:
  - help the user assess the situation before jumping into remediation,
  - and prefer concrete signals or checks over generic theory.
- If the response strategy is `direct_checklist`:
  - keep the list distinct and non-repetitive,
  - and group related actions naturally.
- If the response strategy says `needs clarification: yes`, do not answer the full problem yet.
- If the response mode is explanatory grounded answer:
  - start with the direct answer or recommendation,
  - keep a natural assistant tone,
  - only then expand with supporting detail if it helps the user act or understand,
  - and do not repeat the same idea in multiple paragraphs.
  - do not end with a generic call-to-action such as "¿Quieres saber más...?" unless it adds clear value in that exact turn.
- If the safety policy is active, do not recommend clicking links, opening attachments, validating identity through the provided message, or entering credentials or OTP codes from the suspicious content itself.
- If the safety policy is active, prefer independent verification through trusted official channels and conservative next steps.
"""


def build_system_prompt(
    profile: "AssistantProfile",
    intent_decision: "IntentDecision",
    dialogue_decision: "DialogueDecision",
    strategy_decision: "StrategyDecision",
) -> str:
    """Build an intent-aware system prompt from the reusable assistant profile."""
    base = f"""You are {profile.name}, a conversational assistant specialized in {profile.domain_name}.

Audience:
- {profile.audience}

Core mission:
- {profile.mission}

Operating model:
- You run locally with a corpus-backed architecture and optional uploaded documents.
- Local rationale: {profile.local_execution_rationale}.
- Cost rationale: {profile.local_cost_rationale}.
- Scope boundary: {profile.scope_boundary}.

Global rules:
- Answer in clear Spanish unless the user explicitly asks for another language.
- Keep the tone practical, warm, stable and easy to understand.
- Respond as an assistant in dialogue, not as a document renderer.
- Never expose internal implementation details such as chunk ids, retrieval positions or prompt mechanics.
- Prefer usefulness, honesty and continuity over filler.
- Current dialogue goal: {dialogue_decision.goal}.
- Preferred response shape: {dialogue_decision.response_shape}.
- Expected answer depth: {dialogue_decision.answer_depth}.
- Current response strategy: {strategy_decision.strategy}.
- Answer mode: {strategy_decision.answer_mode}.
- Follow-up policy: {strategy_decision.follow_up_policy}.
"""

    if intent_decision.evidence_policy == "profile_only":
        return (
            base
            + """
Intent policy:
- This turn is a meta or conversational assistant turn.
- You may answer from the assistant profile and recent conversation without requiring corpus grounding.
- Do not fabricate that a document or corpus says something when it has not been retrieved.
- Be concise, helpful and natural.
"""
        )

    if intent_decision.evidence_policy == "hybrid_guided":
        return (
            base
            + """
Intent policy:
- This turn is a guided support turn.
- If strong retrieved evidence exists, use it.
- If evidence is partial or weak, still help the user with coherent first-step guidance appropriate to the domain.
- Distinguish grounded facts from general orientation through careful wording.
- Do not collapse uncertain suggestions into definitive claims.
- Ask at most one clarifying question only when it materially improves the next step.
"""
        )

    return (
        base
        + """
Intent policy:
- This turn is a strict grounded lookup or document analysis turn.
- Use only the retrieved context for factual claims.
- If the evidence is insufficient, say so plainly and do not fill gaps with general knowledge.
- Keep the answer short, precise and auditable.
"""
    )
