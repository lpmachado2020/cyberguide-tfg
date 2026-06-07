"""Safety-oriented policy checks for high-risk CyberGuide scenarios.

Purpose:
- Detect sensitive interaction patterns such as phishing-like screenshots and
  enforce safer response behavior.

Inputs:
- User question, uploaded text content and interaction mode.

Outputs:
- A structured assessment that downstream services can use for cautious replies.

Used by:
- `backend/app/services/rag.py`
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re


@dataclass
class SafetyAssessment:
    """Describe whether a request should trigger a cautious response policy."""

    cautious_mode: bool
    signals: list[str] = field(default_factory=list)


ACCOUNT_PATTERNS = (
    r"\bcuenta\b",
    r"\busuario\b",
    r"\baccount\b",
    r"\bprofile\b",
    r"\bbanca\b",
    r"\bbanco\b",
    r"\bsantander\b",
    r"\bbbva\b",
    r"\bpaypal\b",
)

IDENTITY_PATTERNS = (
    r"valida\w*\s+tu\s+identidad",
    r"verifica\w*\s+tu\s+identidad",
    r"identity\s+verification",
    r"\bkyc\b",
)

ACCESS_PATTERNS = (
    r"inicia\w*\s+sesi[oó]n",
    r"\blogin\b",
    r"\bsign in\b",
    r"\bcontrase(?:n|ñ)a\b",
    r"\bcredential",
    r"\botp\b",
    r"c[oó]digo",
)

ACTION_PATTERNS = (
    r"\bhaz\s+clic\b",
    r"\bclick\b",
    r"\benlace\b",
    r"\blink\b",
    r"\bformulario\b",
    r"\bconfirm\w*\b",
)

ALERT_PATTERNS = (
    r"\burgent",
    r"\burgente\b",
    r"inhabilitad",
    r"bloquead",
    r"suspendid",
    r"temporariamente",
    r"temporalmente",
    r"security",
    r"seguridad",
)

SIGNAL_LABELS = {
    "account-related language": "lenguaje relacionado con cuenta o banca",
    "identity-verification wording": "petición de validación o verificación de identidad",
    "login or credential language": "lenguaje de acceso, credenciales o códigos",
    "link or click request": "solicitud de pulsar un enlace, botón o formulario",
    "urgent or account-blocking message": "mensaje de urgencia o bloqueo de cuenta",
}


def assess_content_risk(*, question: str, content: str, mode: str) -> SafetyAssessment:
    """Return whether the request should activate safer response constraints."""
    normalized = f"{question}\n{content}".lower()
    matches: list[str] = []

    match_counts = {
        "account": _count_matches(normalized, ACCOUNT_PATTERNS),
        "identity": _count_matches(normalized, IDENTITY_PATTERNS),
        "access": _count_matches(normalized, ACCESS_PATTERNS),
        "action": _count_matches(normalized, ACTION_PATTERNS),
        "alert": _count_matches(normalized, ALERT_PATTERNS),
    }

    if match_counts["account"]:
        matches.append("account-related language")
    if match_counts["identity"]:
        matches.append("identity-verification wording")
    if match_counts["access"]:
        matches.append("login or credential language")
    if match_counts["action"]:
        matches.append("link or click request")
    if match_counts["alert"]:
        matches.append("urgent or account-blocking message")

    weighted_score = sum(1 for value in match_counts.values() if value > 0)
    high_risk_combo = (
        (match_counts["identity"] and match_counts["action"])
        or (match_counts["access"] and match_counts["action"])
        or (match_counts["account"] and match_counts["alert"] and match_counts["action"])
    )

    cautious_mode = mode == "image" and (high_risk_combo or weighted_score >= 3)
    return SafetyAssessment(
        cautious_mode=cautious_mode,
        signals=matches,
    )


def contains_unsafe_advice(answer: str) -> bool:
    """Return True when the generated answer suggests risky next steps."""
    normalized = answer.lower()
    forbidden_patterns = (
        r"haz clic",
        r"haga clic",
        r"click en el enlace",
        r"inicia sesi[oó]n",
        r"valida\w*\s+tu\s+identidad",
        r"verifica\w*\s+tu\s+identidad",
        r"rellena\w*\s+el\s+formulario",
        r"introduce\w*\s+tus?\s+datos",
    )
    return any(re.search(pattern, normalized) for pattern in forbidden_patterns)


def build_cautious_answer(
    *,
    question: str,
    document_title: str,
    extracted_excerpt: str,
    signals: list[str],
) -> str:
    """Build a deterministic safe answer for high-risk screenshot scenarios."""
    summary_line = (
        f'La captura "{document_title}" parece mostrar una solicitud sensible relacionada con acceso, '
        "verificación o recuperación de cuenta."
    )
    if extracted_excerpt:
        summary_line += f" El texto detectado incluye: \"{extracted_excerpt}\"."

    localized_signals = [SIGNAL_LABELS.get(signal, signal) for signal in signals]
    signals_line = (
        "Señales observadas: " + ", ".join(localized_signals) + "."
        if signals
        else "Se observan señales compatibles con una interacción sensible de acceso o verificación."
    )

    return (
        f"{summary_line}\n\n"
        f"{signals_line}\n\n"
        "Paso prudente recomendado:\n"
        "- No uses el enlace, botón, QR o formulario que aparezca en la propia captura.\n"
        "- No introduzcas credenciales, códigos OTP ni datos personales desde ese acceso.\n"
        "- Verifica el estado real de la cuenta entrando por la web o app oficial escrita manualmente por ti, "
        "o contacta con soporte por un canal independiente y conocido.\n"
        "- Si el contexto es laboral, notifícalo también al equipo de TI o seguridad antes de actuar.\n\n"
        f"No puedo confirmar con certeza que sea phishing solo a partir de esta evidencia, pero sí debo "
        "priorizar una recomendación segura."
    )


def _count_matches(text: str, patterns: tuple[str, ...]) -> int:
    """Count how many patterns match a normalized text block."""
    return sum(1 for pattern in patterns if re.search(pattern, text))
