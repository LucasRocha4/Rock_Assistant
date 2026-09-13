"""Coordena mensagens agrupadas e objetivos conversacionais ativos."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

from rock_assistant import config
from rock_assistant.core.memory import ConversationMemory
from rock_assistant.core.specialist import SpecialistAgent
from rock_assistant.tools.conversation_goals import ConversationGoalStore
from rock_assistant.tools.messaging import send_whatsapp_message, send_whatsapp_presence


def limit_conversation_text(text: str) -> str:
    """Mantem no maximo 1000 caracteres, descartando os 200 iniciais quando exceder."""
    if len(text) <= config.CONVERSATION_MAX_INPUT_CHARS:
        return text
    start = config.CONVERSATION_DISCARD_PREFIX_CHARS
    return text[start:start + config.CONVERSATION_MAX_INPUT_CHARS]


@dataclass
class _ConversationState:
    messages: list[str] = field(default_factory=list)
    timer: Optional[threading.Timer] = None
    generation: int = 0
    typing: bool = False
    lock: threading.RLock = field(default_factory=threading.RLock)


class ConversationManager:
    """Agrupa mensagens por remetente e delega objetivos ativos a um LLM especialista."""

    def __init__(
        self,
        parser,
        router,
        goal_store: Optional[ConversationGoalStore] = None,
        specialist_factory: Callable[[], SpecialistAgent] = SpecialistAgent,
        silence_seconds: Optional[float] = None,
    ) -> None:
        self.parser = parser
        self.router = router
        self.goal_store = goal_store or ConversationGoalStore()
        self.specialist_factory = specialist_factory
        self.silence_seconds = silence_seconds if silence_seconds is not None else config.CONVERSATION_SILENCE_SECONDS
        self.states: Dict[str, _ConversationState] = {}
        self.states_lock = threading.RLock()

    def receive(self, sender: str, text: str) -> None:
        cleaned = (text or "").strip()
        if not cleaned:
            return
        with self.states_lock:
            state = self.states.setdefault(sender, _ConversationState())
        with state.lock:
            state.messages.append(cleaned)
            state.generation += 1
            generation = state.generation
            if state.timer:
                state.timer.cancel()
            state.timer = None
            if not state.typing:
                state.timer = threading.Timer(self.silence_seconds, self._flush, args=(sender, generation))
                state.timer.daemon = True
                state.timer.start()

    def set_typing(self, sender: str, typing: bool) -> None:
        with self.states_lock:
            state = self.states.setdefault(sender, _ConversationState())
        with state.lock:
            state.typing = typing
            if typing and state.timer:
                state.timer.cancel()
                state.timer = None
            elif not typing and state.messages and state.timer is None:
                state.generation += 1
                state.timer = threading.Timer(self.silence_seconds, self._flush, args=(sender, state.generation))
                state.timer.daemon = True
                state.timer.start()

    def _flush(self, sender: str, generation: int) -> None:
        with self.states_lock:
            state = self.states.get(sender)
        if not state:
            return
        with state.lock:
            if generation != state.generation or state.typing:
                return
            text = limit_conversation_text("\n".join(state.messages))
            state.messages.clear()
            state.timer = None
        self._process_after_silence(sender, text)

    def _process_after_silence(self, sender: str, text: str) -> None:
        goal = self.goal_store.get_active_for_target(sender)
        if goal:
            self._process_goal_reply(sender, text, goal)
            return
        parsed = self.parser.parse(text)
        intent = parsed.get("intent")
        if not intent:
            return
        payload = dict(parsed.get("payload", {}))
        payload["owner_phone"] = sender
        result = self.router.route(intent, payload)
        answer = result if isinstance(result, str) else result.get("message", str(result)) if isinstance(result, dict) else str(result)
        if answer:
            send_whatsapp_message(sender, answer)

    def _process_goal_reply(self, sender: str, text: str, goal: dict) -> None:
        goal = self.goal_store.append_exchange(goal["id"], sender, text)
        specialist = self.specialist_factory()
        context = goal["context"]
        prompt = (
            "Você assumiu uma conversa ativa para concluir um objetivo. Responda somente ao contato, "
            "com personalidade natural e cordial. Objetivo: confirmar evento e obter local, horário e "
            "o que levar. Não invente informações. Use o histórico e a resposta recebida para identificar "
            "o que falta; faça perguntas curtas apenas do que estiver faltando.\n"
            f"Contexto: {context}\nResposta recebida agora: {text}"
        )
        try:
            send_whatsapp_presence(sender, "composing", delay=7000)
        except Exception:
            pass
        answer = specialist.chat(text, extra_system_prompt=prompt)
        if answer:
            send_whatsapp_message(sender, answer)