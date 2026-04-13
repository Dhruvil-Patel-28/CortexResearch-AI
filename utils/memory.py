# Currently session-based memeory ,in future add persistence

"""
Session-based conversation memory manager.
Stores and retrieves chat history per session for multi-turn context.

Currently uses in-memory storage (suitable for single-server deployment).
For production, swap the dict with Redis or a database backend.
"""

import logging
from datetime import datetime
from utils.config import settings

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Manages conversation history across multiple sessions.

    Each session stores a list of query-response pairs with timestamps,
    enabling the agent to reference previous conversation context.
    """

    def __init__(self):
        self._sessions: dict[str, list[dict]] = {}
        self._max_turns = settings.max_memory_turns

    def get_history(self, session_id: str) -> list[dict]:
        """Get full conversation history for a session."""
        return self._sessions.get(session_id, [])

    def add_interaction(self, session_id: str, query: str, response: str):
        """
        Store a new query-response pair in the session.

        Args:
            session_id: The session identifier.
            query: The user's research query.
            response: The agent's response summary.
        """
        if session_id not in self._sessions:
            self._sessions[session_id] = []
            logger.info(f"New session created: {session_id}")

        self._sessions[session_id].append({
            "query": query,
            "response": response,
            "timestamp": datetime.now().isoformat(),
        })

        # Trim old turns if over the limit
        if len(self._sessions[session_id]) > self._max_turns:
            trimmed = len(self._sessions[session_id]) - self._max_turns
            self._sessions[session_id] = self._sessions[session_id][-self._max_turns:]
            logger.info(f"Session {session_id}: trimmed {trimmed} old turns")

        logger.info(f"Session {session_id}: {len(self._sessions[session_id])} turns stored")

    def get_context(self, session_id: str, max_turns: int = 5) -> str:
        """
        Build a formatted context string from recent conversation history.

        Args:
            session_id: The session identifier.
            max_turns: Maximum number of recent turns to include.

        Returns:
            Formatted string of recent conversation history,
            or empty string if no history exists.
        """
        history = self.get_history(session_id)
        if not history:
            return ""

        recent = history[-max_turns:]
        context_parts = ["Previous conversation context:"]

        for i, turn in enumerate(recent, 1):
            context_parts.append(
                f"\nTurn {i}:\n"
                f"  User: {turn['query']}\n"
                f"  Assistant: {turn['response'][:300]}"
            )

        return "\n".join(context_parts)

    def get_session_ids(self) -> list[str]:
        """Get all active session IDs."""
        return list(self._sessions.keys())

    def clear_session(self, session_id: str):
        """Clear history for a specific session."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info(f"Session cleared: {session_id}")


# Global singleton instance
session_manager = SessionManager()
