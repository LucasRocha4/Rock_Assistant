"""Coordena mensagens agrupadas e objetivos conversacionais ativos."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

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
        needed_facts = context.get("needed_facts", [])
        collected_facts = context.get("collected_facts", {})
        prompt = (
            "Você assumiu uma conversa ativa para concluir um objetivo em nome do Rock. "
            f"Objetivo: confirmar '{context.get('event_description', '')}' obtendo os seguintes fatos: "
            f"{needed_facts}. Fatos já coletados: {collected_facts}.\n"
            "Responda SOMENTE em JSON válido, sem markdown e sem texto fora do JSON, com este formato exato:\n"
            '{"reply": "mensagem curta e natural para o contato", '
            '"collected_facts": {"location": null ou texto, "time": null ou texto, "what_to_bring": null ou texto}, '
            '"completed": true ou false}\n'
            "Regras: preencha collected_facts somente com o que já foi dito no histórico ou na resposta agora "
            "(não invente); use null para o que ainda falta. completed deve ser true apenas quando location, "
            "time e what_to_bring estiverem preenchidos. Se completed for true, 'reply' deve ser uma mensagem "
            "de agradecimento/confirmação final, sem novas perguntas. Se completed for false, 'reply' deve "
            "perguntar de forma natural apenas o que ainda falta.\n"
            f"Histórico da conversa: {context.get('transcript', [])}\n"
            f"Resposta recebida agora: {text}"
        )
        try:
            send_whatsapp_presence(sender, "composing", delay=7000)
        except Exception:
            pass
        raw_answer = specialist.chat(text, extra_system_prompt=prompt)
        reply_text, new_facts, completed = self._parse_goal_response(raw_answer)

        if new_facts:
            goal = self.goal_store.update_collected_facts(goal["id"], new_facts)
            collected_facts = goal["context"].get("collected_facts", {})

        all_collected = bool(needed_facts) and all(collected_facts.get(fact) for fact in needed_facts)
        is_done = completed or all_collected

        # Nunca deixa a conversa parada: se o LLM não devolveu uma pergunta útil, pergunta pelo que falta
        if not reply_text:
            reply_text = self._fallback_goal_message(needed_facts, collected_facts, is_done)

        if is_done:
            self.goal_store.mark_completed(goal["id"])
            self._notify_owner_goal_completed(goal, collected_facts)

        if reply_text:
            self.goal_store.append_exchange(goal["id"], "rock", reply_text)
            try:
                send_whatsapp_message(sender, reply_text)
            except Exception:
                pass

    @staticmethod
    def _parse_goal_response(raw_answer: str) -> tuple[str, Dict[str, Any], bool]:
        """Extrai (reply, collected_facts, completed) da resposta JSON do especialista.

        Faz fallback para tratar a resposta inteira como texto quando o JSON é inválido.
        """
        text = (raw_answer or "").strip()
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                parsed = json.loads(text[start:end + 1])
                reply = str(parsed.get("reply") or "").strip()
                facts = parsed.get("collected_facts") or {}
                completed = bool(parsed.get("completed"))
                # Reply vazio aqui não deve virar o JSON cru; deixa o chamador decidir um fallback
                return (reply, facts if isinstance(facts, dict) else {}, completed)
            except (json.JSONDecodeError, TypeError):
                pass
        return (text, {}, False)

    @staticmethod
    def _fallback_goal_message(needed_facts: list[str], collected_facts: Dict[str, Any], completed: bool) -> str:
        """Pergunta determinística pelo que falta, usada quando o LLM não devolve uma pergunta útil."""
        if completed:
            return "Perfeito, já tenho tudo que preciso. Obrigado!"
        labels = {"location": "o local", "time": "o horário", "what_to_bring": "o que levar"}
        missing = [labels.get(fact, fact) for fact in needed_facts if not collected_facts.get(fact)]
        if not missing:
            return "Perfeito, já tenho tudo que preciso. Obrigado!"
        if len(missing) == 1:
            return f"Show! Só falta saber {missing[0]}."
        return "Show! Ainda falta saber " + ", ".join(missing[:-1]) + f" e {missing[-1]}."

    def _notify_owner_goal_completed(self, goal: dict, collected_facts: Dict[str, Any]) -> None:
        """Avisa quem pediu a confirmação que o objetivo foi concluído, com o resumo coletado."""
        owner_phone = goal.get("owner_phone")
        if not owner_phone:
            return
        target_name = goal.get("target_name") or goal.get("target_phone")
        context = goal.get("context", {})
        event_description = context.get("event_description", "")
        summary_lines = [f"- {key}: {value}" for key, value in collected_facts.items() if value]
        summary = "\n".join(summary_lines) if summary_lines else "sem detalhes adicionais."
        message = (
            f"✅ Objetivo concluído com {target_name} sobre '{event_description}':\n{summary}"
        )
        try:
            send_whatsapp_message(owner_phone, message)
        except Exception:
            pass