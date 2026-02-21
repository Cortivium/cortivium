"""MCP session management — in-memory sessions with expiration."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field


@dataclass
class Session:
    id: str = field(default_factory=lambda: secrets.token_hex(16))
    protocol_version: str = "2024-11-05"
    client_capabilities: dict = field(default_factory=dict)
    client_info: dict = field(default_factory=dict)
    initialized: bool = False
    created_at: float = field(default_factory=time.time)
    last_activity_at: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.last_activity_at = time.time()

    def idle_time(self) -> float:
        return time.time() - self.last_activity_at


class SessionManager:
    def __init__(self, timeout: float = 3600.0):
        self._sessions: dict[str, Session] = {}
        self._timeout = timeout

    def create(self) -> Session:
        session = Session()
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if session.idle_time() > self._timeout:
            self.remove(session_id)
            return None
        session.touch()
        return session

    def has(self, session_id: str) -> bool:
        return session_id in self._sessions

    def remove(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def count(self) -> int:
        return len(self._sessions)

    def cleanup(self) -> int:
        expired = [
            sid
            for sid, s in self._sessions.items()
            if s.idle_time() > self._timeout
        ]
        for sid in expired:
            del self._sessions[sid]
        return len(expired)
