"""Módulo de integração de telefonia (Asterisk ARI) do Rock Assistant."""

from telephony.core.call_handler import CallHandler, get_call_handler
from telephony.core.pipeline import VoicePipeline, load_voice_system_prompt
from telephony.core.session import (
    CallDirection,
    CallSession,
    CallState,
    SessionManager,
    get_session_manager,
)

__all__ = [
    "CallHandler",
    "get_call_handler",
    "VoicePipeline",
    "load_voice_system_prompt",
    "CallSession",
    "CallDirection",
    "CallState",
    "SessionManager",
    "get_session_manager",
]
