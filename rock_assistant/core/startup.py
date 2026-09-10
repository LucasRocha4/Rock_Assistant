"""Briefing mínimo apresentado quando o Rock é iniciado."""

from __future__ import annotations

import random
import re
from typing import Any, Dict, List, Optional

from rock_assistant.tools.reminders import SQLiteReminderStorage


GREETINGS = [
    "Bom dia. Rock online.",
    "Olá. Rock está pronto.",
    "Rock iniciado. Estou com você.",
    "Tudo certo. Rock à disposição.",
]


class StartupBriefing:
    """Anuncia mensagens pendentes e responde à primeira pergunta do usuário."""

    def __init__(
        self,
        storage: Optional[SQLiteReminderStorage] = None,
        greeting_picker: Any = random.choice,
    ) -> None:
        self.storage = storage or SQLiteReminderStorage()
        self.greeting_picker = greeting_picker
        self.pending: List[Dict[str, Any]] = []

    def opening_lines(self) -> List[str]:
        """Monta a abertura, sempre priorizando uma mensagem urgente."""
        self.pending = self.storage.list_pending_messages()
        urgent_count = sum(item.get("importance") in {"high", "urgent"} for item in self.pending)
        lines: List[str] = []
        if urgent_count:
            suffix = "mensagens urgentes" if urgent_count > 1 else "mensagem urgente"
            lines.append(f"Atenção: você tem {urgent_count} {suffix}.")
        lines.append(self.greeting_picker(GREETINGS))
        count = len(self.pending)
        suffix = "mensagens pendentes" if count != 1 else "mensagem pendente"
        lines.append(f"Você tem {count} {suffix}.")
        if count:
            lines.append("Quer saber de quem são ou ouvir uma mensagem?")
        return lines

    def respond(self, answer: str) -> List[str]:
        """Responde à escolha inicial sem enviar mensagens para canais externos."""
        if not self.pending:
            return []

        normalized = re.sub(r"[^a-záàâãéêíóôõúç0-9 ]", "", (answer or "").lower())
        if any(term in normalized for term in ("ouvir", "mensagem", "conteudo", "conteúdo", "ler", "sim", "pode", "quero")):
            lines = ["Aqui estão as mensagens pendentes:"]
            for item in self.pending:
                importance = item.get("importance", "normal")
                prefix = "Urgente: " if importance == "urgent" else "Prioridade alta: " if importance == "high" else ""
                lines.append(f"{prefix}{item.get('message', '')}")
            self.storage.mark_delivered([int(item["id"]) for item in self.pending])
            self.pending = []
            return lines

        if any(term in normalized for term in ("quem", "de quem", "remetente", "origem")):
            return [
                "Estas mensagens foram criadas por você e estão guardadas pelo Rock; "
                "não há remetente externo registrado."
            ]

        if any(term in normalized for term in ("nao", "não", "depois", "agora nao", "agora não")):
            return ["Certo. Vou manter as mensagens pendentes."]

        return ["Posso dizer de quem são ou ler as mensagens. O que você prefere?"]

    def startup_text(self, input_func=input, output_func=print) -> None:
        """Executa o briefing no modo texto."""
        for line in self.opening_lines():
            output_func(line)
        if self.pending:
            answer = input_func("Rock: ")
            response = self.respond(answer)
            for line in response:
                output_func(line)
            if self.pending and "quem" in (answer or "").lower():
                follow_up = input_func("Rock: ")
                for line in self.respond(follow_up):
                    output_func(line)

    def startup_voice(self, tts: Any, stt: Any) -> None:
        """Executa o briefing no modo voz."""
        for line in self.opening_lines():
            tts.speak(line)
        if self.pending and stt.is_microphone_available():
            answer = stt.listen(timeout=15, phrase_time_limit=10)
            response = self.respond(answer)
            for line in response:
                tts.speak(line)
            if self.pending and "quem" in (answer or "").lower():
                follow_up = stt.listen(timeout=15, phrase_time_limit=10)
                for line in self.respond(follow_up):
                    tts.speak(line)
