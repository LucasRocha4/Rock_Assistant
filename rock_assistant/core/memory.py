"""Módulo de gerenciamento de memória de curto prazo do Rock Assistant."""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Garante acesso a configurações do projeto
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

try:
    import config
    from config import MAX_MEMORY_MESSAGES, MEMORY_FILE
except ImportError:
    from rock_assistant import config
    from rock_assistant.config import MAX_MEMORY_MESSAGES, MEMORY_FILE


class ConversationMemory:
    """Gerencia a memória de curto prazo (histórico de conversas) do assistente.

    Mantém uma janela deslizante de no máximo `max_messages` (por padrão 10 mensagens,
    equivalente a 5 turnos de diálogo) e permite persistência em arquivo JSON.
    """

    def __init__(
        self,
        file_path: Optional[Path | str] = None,
        max_messages: Optional[int] = None,
        auto_save: bool = True,
    ) -> None:
        self.file_path = Path(file_path) if file_path else Path(MEMORY_FILE)
        self.max_messages = max_messages if max_messages is not None else MAX_MEMORY_MESSAGES
        self.auto_save = auto_save
        self.messages: List[Dict[str, str]] = []

        # Tenta carregar histórico existente do arquivo
        self.load_from_file()

    def _trim_memory(self) -> None:
        """Garante que a lista de mensagens não ultrapasse o limite configurado."""
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]

    def add_user_message(self, text: str) -> None:
        """Adiciona uma mensagem enviada pelo usuário à memória."""
        cleaned = (text or "").strip()
        if cleaned:
            self.messages.append({"role": "user", "content": cleaned})
            self._trim_memory()
            if self.auto_save:
                self.save_to_file()

    def add_assistant_message(self, text: str) -> None:
        """Adiciona uma resposta gerada pelo assistente à memória."""
        cleaned = (text or "").strip()
        if cleaned:
            self.messages.append({"role": "assistant", "content": cleaned})
            self._trim_memory()
            if self.auto_save:
                self.save_to_file()

    def get_history(self) -> List[Dict[str, str]]:
        """Retorna uma cópia da lista com o histórico de mensagens formatado."""
        return [dict(msg) for msg in self.messages]

    def clear_memory(self) -> None:
        """Limpa todo o histórico de mensagens em memória e remove/zera o arquivo persistido."""
        self.messages = []
        if self.auto_save:
            self.save_to_file()

    def save_to_file(self, path: Optional[Path | str] = None) -> bool:
        """Persiste o histórico atual em formato JSON no caminho especificado."""
        target_path = Path(path) if path else self.file_path
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with open(target_path, "w", encoding="utf-8") as f:
                json.dump(self.messages, f, ensure_ascii=False, indent=2)
            return True
        except Exception as exc:
            # Não quebra a execução em caso de falha de I/O
            return False

    def load_from_file(self, path: Optional[Path | str] = None) -> bool:
        """Carrega o histórico a partir de um arquivo JSON se ele existir."""
        target_path = Path(path) if path else self.file_path
        if not target_path.exists():
            return False

        try:
            with open(target_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    # Valida formato das mensagens
                    valid_msgs = [
                        {"role": str(item.get("role", "user")), "content": str(item.get("content", ""))}
                        for item in data
                        if isinstance(item, dict) and "content" in item
                    ]
                    self.messages = valid_msgs
                    self._trim_memory()
                    return True
        except Exception:
            self.messages = []

        return False

    def __len__(self) -> int:
        return len(self.messages)

    def __repr__(self) -> str:
        return f"<ConversationMemory messages={len(self.messages)} max={self.max_messages}>"
