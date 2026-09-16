"""Agente de IA local (Llama via Ollama) — cérebro padrão do Rock, com tool calling (base MCP)."""

import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# Garante acesso a configurações do projeto
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

try:
    from setup import config
    from core.memory import ConversationMemory
    from core.tool_schemas import get_tool_schemas
except ImportError:
    from rock_assistant.setup import config
    from rock_assistant.core.memory import ConversationMemory
    from rock_assistant.core.tool_schemas import get_tool_schemas

logger = logging.getLogger("rock.local_llm")

SYSTEM_PROMPT_DEFAULT = (
    "Você é Rock, o assistente pessoal do usuário, rodando localmente via Llama.\n"
    "Quando fizer sentido, use uma das ferramentas disponíveis (busca, lembrete, mensagem, "
    "e-mail, contato, comando ou objetivo); caso contrário, apenas responda diretamente.\n"
    "Responda em português do Brasil, com clareza, naturalidade e objetividade.\n"
    "Nunca invente fatos sobre o usuário, suas preferências ou ações já realizadas.\n"
)


class LocalLLMAgent:
    """Agente padrão do Rock: conversa com um modelo Llama local servido pelo Ollama."""

    def __init__(
        self,
        model: Optional[str] = None,
        host: Optional[str] = None,
        system_prompt: Optional[str] = None,
        memory: Optional[ConversationMemory] = None,
        timeout: Optional[int] = None,
    ) -> None:
        self.model = model or getattr(config, "OLLAMA_MODEL", "llama3.2")
        self.host = host or getattr(config, "OLLAMA_HOST", "http://localhost:11434")
        self.system_prompt = system_prompt or SYSTEM_PROMPT_DEFAULT
        self.memory = memory
        self.timeout = timeout or getattr(config, "OLLAMA_TIMEOUT", 60)
        self._client = None
        self._server_confirmed = False

    def _get_client(self):
        if self._client is None:
            from ollama import Client

            self._client = Client(host=self.host, timeout=self.timeout)
        return self._client

    def _ensure_server_running(self) -> bool:
        """Verifica se o Ollama está no ar; tenta iniciar `ollama serve` se necessário."""
        import requests

        try:
            requests.get(f"{self.host}/api/tags", timeout=2)
            return True
        except requests.RequestException:
            pass

        if not getattr(config, "OLLAMA_AUTOSTART", True):
            return False

        try:
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (FileNotFoundError, OSError) as exc:
            logger.warning("Não foi possível iniciar 'ollama serve' automaticamente: %s", exc)
            return False

        for _ in range(10):
            time.sleep(1)
            try:
                requests.get(f"{self.host}/api/tags", timeout=2)
                return True
            except requests.RequestException:
                continue
        return False

    def is_available(self) -> bool:
        """Confirma (e tenta iniciar) o servidor Ollama com o modelo local; resultado é memorizado."""
        if not self._server_confirmed:
            self._server_confirmed = self._ensure_server_running()
        return self._server_confirmed

    def _build_messages(
        self,
        user_input: str,
        memory: Optional[ConversationMemory],
        extra_system_prompt: Optional[str],
    ) -> List[Dict[str, Any]]:
        system = self.system_prompt
        if extra_system_prompt:
            system = f"{system}\n{extra_system_prompt}"
        messages: List[Dict[str, Any]] = [{"role": "system", "content": system}]

        active_memory = memory or self.memory
        if active_memory:
            for entry in active_memory.get_history():
                role = "assistant" if entry.get("role") == "assistant" else "user"
                messages.append({"role": role, "content": entry.get("content", "")})

        messages.append({"role": "user", "content": user_input})
        return messages

    def chat(
        self,
        user_input: str,
        memory: Optional[ConversationMemory] = None,
        extra_system_prompt: Optional[str] = None,
    ) -> str:
        """Conversa simples e direta, sem ferramentas."""
        cleaned = (user_input or "").strip()
        if not cleaned:
            return "Nenhuma entrada fornecida para o Rock."
        if not self.is_available():
            return (
                "🦙 [Rock Local] Não consegui falar com o Ollama/Llama local.\n"
                "💡 Verifique se o Ollama está instalado e se o modelo foi baixado (`ollama pull llama3.2`)."
            )
        try:
            client = self._get_client()
            messages = self._build_messages(cleaned, memory, extra_system_prompt)
            response = client.chat(
                model=self.model,
                messages=messages,
                options={"temperature": getattr(config, "OLLAMA_TEMPERATURE", 0.2)},
            )
            return (response["message"]["content"] or "").strip()
        except Exception as exc:
            logger.error("Erro ao conversar com Llama local: %s", exc)
            return f"❌ [Rock Local] Erro ao consultar o modelo local: {exc}"

    def converse_with_tools(
        self,
        user_input: str,
        tool_executor: Callable[[str, Dict[str, Any]], Any],
        memory: Optional[ConversationMemory] = None,
        extra_system_prompt: Optional[str] = None,
    ) -> str:
        """Fluxo estilo MCP: o próprio modelo decide se chama uma ferramenta antes de responder.

        `tool_executor(nome, argumentos)` deve executar a ferramenta real (em geral
        `router.route(nome, argumentos)`) e devolver o resultado bruto, que é
        realimentado ao modelo para compor a resposta final.
        """
        cleaned = (user_input or "").strip()
        if not cleaned:
            return "Nenhuma entrada fornecida para o Rock."
        if not self.is_available():
            return self.chat(cleaned, memory=memory, extra_system_prompt=extra_system_prompt)

        try:
            client = self._get_client()
            messages = self._build_messages(cleaned, memory, extra_system_prompt)
            response = client.chat(
                model=self.model,
                messages=messages,
                tools=get_tool_schemas(),
                options={"temperature": getattr(config, "OLLAMA_TEMPERATURE", 0.2)},
            )
            message = response["message"]
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                return (message.get("content") or "").strip()

            call = tool_calls[0]
            function = call.get("function", {})
            tool_name = function.get("name", "")
            raw_arguments = function.get("arguments", {})
            arguments = raw_arguments if isinstance(raw_arguments, dict) else json.loads(raw_arguments or "{}")

            tool_result = tool_executor(tool_name, arguments)

            messages.append({"role": "assistant", "content": message.get("content", ""), "tool_calls": tool_calls})
            messages.append({"role": "tool", "content": json.dumps(tool_result, ensure_ascii=False, default=str)})

            follow_up = client.chat(
                model=self.model,
                messages=messages,
                options={"temperature": getattr(config, "OLLAMA_TEMPERATURE", 0.2)},
            )
            return (follow_up["message"]["content"] or "").strip()
        except Exception as exc:
            logger.error("Erro no fluxo de tool calling com Llama local: %s", exc)
            return f"❌ [Rock Local] Erro ao processar a solicitação com ferramentas: {exc}"
