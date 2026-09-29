"""Gerenciamento de sessões e estado de chamadas telefônicas."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("rock.telephony.session")


class CallDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class CallState(str, Enum):
    RINGING = "ringing"
    ANSWERED = "answered"
    IN_CALL = "in_call"
    HANGING_UP = "hanging_up"
    ENDED = "ended"
    FAILED = "failed"


@dataclass
class CallSession:
    """Representa a sessão isolada de uma chamada telefônica em andamento."""

    channel_id: str
    direction: CallDirection
    caller_id: str = ""
    recipient: str = ""
    script: Optional[str] = None
    state: CallState = CallState.RINGING
    history: List[Dict[str, str]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    ended_at: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add_user_message(self, text: str) -> None:
        """Adiciona fala do interlocutor ao histórico da sessão."""
        with self._lock:
            self.history.append({"role": "user", "content": text.strip()})

    def add_assistant_message(self, text: str) -> None:
        """Adiciona fala do Rock ao histórico da sessão."""
        with self._lock:
            self.history.append({"role": "assistant", "content": text.strip()})

    def get_dialogue_history(self) -> List[Dict[str, str]]:
        """Retorna uma cópia do histórico de diálogo."""
        with self._lock:
            return list(self.history)

    def set_state(self, state: CallState) -> None:
        with self._lock:
            self.state = state
            if state in (CallState.ENDED, CallState.FAILED) and self.ended_at is None:
                self.ended_at = time.time()

    def is_active(self) -> bool:
        with self._lock:
            return self.state in (CallState.RINGING, CallState.ANSWERED, CallState.IN_CALL)

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "channel_id": self.channel_id,
                "direction": self.direction.value if isinstance(self.direction, CallDirection) else self.direction,
                "caller_id": self.caller_id,
                "recipient": self.recipient,
                "script": self.script,
                "state": self.state.value if isinstance(self.state, CallState) else self.state,
                "turns_count": len(self.history),
                "created_at": self.created_at,
                "ended_at": self.ended_at,
                "metadata": dict(self.metadata),
            }


class SessionManager:
    """Armazena e coordena as sessões de chamadas ativas."""

    def __init__(self) -> None:
        self._sessions: Dict[str, CallSession] = {}
        self._lock = threading.Lock()

    def create_session(
        self,
        channel_id: str,
        direction: CallDirection = CallDirection.INBOUND,
        caller_id: str = "",
        recipient: str = "",
        script: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CallSession:
        """Cria e registra uma nova sessão de chamada."""
        with self._lock:
            session = CallSession(
                channel_id=channel_id,
                direction=direction,
                caller_id=caller_id,
                recipient=recipient,
                script=script,
                metadata=metadata or {},
            )
            self._sessions[channel_id] = session
            logger.info("Sessão telefônica criada para canal %s (%s)", channel_id, direction.value)
            return session

    def get_session(self, channel_id: str) -> Optional[CallSession]:
        """Obtém uma sessão ativa pelo channel_id."""
        with self._lock:
            return self._sessions.get(channel_id)

    def remove_session(self, channel_id: str) -> Optional[CallSession]:
        """Remove e retorna a sessão finalizada."""
        with self._lock:
            session = self._sessions.pop(channel_id, None)
            if session:
                session.set_state(CallState.ENDED)
                logger.info("Sessão telefônica encerrada e removida para canal %s", channel_id)
            return session

    def list_active_sessions(self) -> List[CallSession]:
        """Lista todas as sessões ativas no momento."""
        with self._lock:
            return [s for s in self._sessions.values() if s.is_active()]


_default_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """Obtém a instância global do SessionManager."""
    global _default_session_manager
    if _default_session_manager is None:
        _default_session_manager = SessionManager()
    return _default_session_manager
