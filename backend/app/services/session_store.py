"""In-memory session state for conversational CyberGuide prototypes.

Purpose:
- Keep lightweight chat history and temporary uploaded documents between turns.

Inputs:
- Session identifiers coming from the frontend.

Outputs:
- Session-scoped history and optional temporary document context.

Used by:
- `backend/app/main.py`
- `backend/app/services/rag.py`
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple
from uuid import uuid4

from ..schemas import ConversationTurn
from .ingestion import PreparedChunk


@dataclass
class SessionState:
    """Mutable state associated with one browser conversation."""

    history: list[ConversationTurn] = field(default_factory=list)
    document_title: Optional[str] = None
    document_chunks: list[PreparedChunk] = field(default_factory=list)


class SessionStore:
    """Small in-memory session registry for local prototype conversations."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def get_or_create(self, session_id: Optional[str]) -> Tuple[str, SessionState]:
        """Return an existing session or create a fresh one when missing."""
        normalized = session_id or str(uuid4())
        state = self._sessions.setdefault(normalized, SessionState())
        return normalized, state

    def append_turn(self, session_id: str, role: str, content: str) -> None:
        """Persist one user or assistant message in session history."""
        _, state = self.get_or_create(session_id)
        state.history.append(ConversationTurn(role=role, content=content))

    def get_recent_history(self, session_id: str, limit: int = 8) -> list[ConversationTurn]:
        """Return the latest conversation turns for contextual prompting."""
        _, state = self.get_or_create(session_id)
        if limit <= 0:
            return []
        return state.history[-limit:]

    def set_document(
        self,
        session_id: str,
        *,
        title: str,
        chunks: list[PreparedChunk],
    ) -> None:
        """Attach a temporary uploaded document to the current session."""
        _, state = self.get_or_create(session_id)
        state.document_title = title
        state.document_chunks = chunks

    def get_document(self, session_id: str) -> tuple[Optional[str], list[PreparedChunk]]:
        """Return the active uploaded document title and chunks for a session."""
        _, state = self.get_or_create(session_id)
        return state.document_title, state.document_chunks
