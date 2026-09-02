"""Agente Especialista (Google Gemini) para raciocínio denso, código e conversação técnica."""

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Garante acesso a configurações do projeto
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

try:
    import config
    from config import GEMINI_GENERATION_CONFIG, GEMINI_MODEL_SPECIALIST
    from core.memory import ConversationMemory
except ImportError:
    from rock_assistant import config
    from rock_assistant.config import GEMINI_GENERATION_CONFIG, GEMINI_MODEL_SPECIALIST
    from rock_assistant.core.memory import ConversationMemory


SYSTEM_PROMPT_DEFAULT = (
    "Você é o Rock, um assistente especialista de inteligência artificial de alta performance executando no Kali Linux.\n"
    "Suas características principais são:\n"
    "- Respostas técnicas, precisas, objetivas e diretas ao ponto.\n"
    "- Especialista em Engenharia de Software, Python moderno, arquitetura de sistemas, segurança defensiva e ofensiva, redes e terminal Linux.\n"
    "- Sempre que solicitado código, forneça implementações limpas, funcionais, seguras e com breves explicações práticas.\n"
    "- Coloque um pouco de ironia e humor inteligente e ácido em suas respostas, mas sem perder a objetividade.\n"
)


class SpecialistAgent:
    """Agente Especialista baseado na API do Google Gemini para tarefas analíticas e conversação geral."""

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        system_prompt: Optional[str] = None,
        memory: Optional[ConversationMemory] = None,
        timeout: Optional[int] = None,
    ) -> None:
        self.model = model or getattr(config, "GEMINI_MODEL_SPECIALIST", "gemini-2.0-flash")
        self.api_key = api_key or getattr(config, "GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
        self.system_prompt = system_prompt or SYSTEM_PROMPT_DEFAULT
        self.memory = memory
        self.timeout = timeout or getattr(config, "GEMINI_TIMEOUT", 30)

    def is_available(self) -> bool:
        """Verifica se a chave de API está configurada."""
        key = self.api_key or os.getenv("GEMINI_API_KEY", "")
        return bool(key and key.strip())

    def chat(
        self,
        user_input: str,
        memory: Optional[ConversationMemory] = None,
        extra_system_prompt: Optional[str] = None,
    ) -> str:
        """Envia a entrada do usuário e o histórico de mensagens para a API do Google Gemini.

        Args:
            user_input: Texto da pergunta ou comando técnico do usuário.
            memory: Instância de ConversationMemory (opcional, usa a self.memory se não fornecida).
            extra_system_prompt: Instruções adicionais para o sistema.

        Returns:
            Resposta gerada pelo modelo ou mensagem de fallback amigável em caso de erro.
        """
        cleaned_input = (user_input or "").strip()
        if not cleaned_input:
            return "Nenhuma entrada fornecida para o agente especialista."

        key = self.api_key or os.getenv("GEMINI_API_KEY", "")
        if not key:
            return (
                "🔑 [Rock Auth] Chave de API do Gemini não configurada.\n"
                "💡 Defina a variável de ambiente GEMINI_API_KEY para habilitar a inteligência do assistente."
            )

        try:
            from google import genai
            from google.genai import types
            from google.genai.errors import APIError, ClientError, ServerError
        except ImportError:
            return "❌ [Rock Specialist] Biblioteca 'google-genai' não instalada. Execute `pip install google-genai`."

        active_memory = memory or self.memory

        # Monta a lista de conteúdos com histórico formatado para o SDK
        contents: List[types.Content] = []

        if active_memory:
            history = active_memory.get_history()
            # Utiliza as mensagens recentes para contexto
            for msg in history[-6:]:
                role = msg.get("role")
                content_text = (msg.get("content") or "").strip()
                if not content_text:
                    continue

                if role == "user":
                    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=content_text)]))
                elif role == "assistant" or role == "model":
                    contents.append(types.Content(role="model", parts=[types.Part.from_text(text=content_text)]))

            # Se o último item da memória não coincidir com a mensagem atual do usuário, adiciona
            if not history or history[-1].get("content") != cleaned_input or history[-1].get("role") != "user":
                contents.append(types.Content(role="user", parts=[types.Part.from_text(text=cleaned_input)]))
        else:
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=cleaned_input)]))

        # Configura system instruction e parâmetros
        sys_content = self.system_prompt
        if extra_system_prompt:
            sys_content += f"\n{extra_system_prompt}"

        gen_config_dict = getattr(config, "GEMINI_GENERATION_CONFIG", {})
        temp = gen_config_dict.get("temperature", 0.2)
        top_p = gen_config_dict.get("top_p", 0.95)

        gen_config = types.GenerateContentConfig(
            system_instruction=sys_content,
            temperature=temp,
            top_p=top_p,
            http_options=types.HttpOptions(timeout=self.timeout * 1000 if self.timeout else 30000),
        )

        try:
            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model=self.model,
                contents=contents,
                config=gen_config,
            )

            text_result = (response.text or "").strip()
            if text_result:
                return text_result
            return "Modelo respondeu sem conteúdo textual."

        except (ClientError, APIError) as exc:
            err_str = str(exc).lower()
            if "quota" in err_str or "resource_exhausted" in err_str or "429" in err_str:
                return f"⚠️ [Rock Quota] Limite de quota da API do Gemini excedido.\nDetalhes: {exc}"
            if "safety" in err_str or "blocked" in err_str:
                return f"🛡️ [Rock Segurança] A resposta foi bloqueada pelos filtros de segurança do Gemini.\nDetalhes: {exc}"
            if "api_key" in err_str or "unauthenticated" in err_str or "invalid" in err_str or "403" in err_str or "401" in err_str:
                return f"🔑 [Rock Auth] Chave de API do Gemini inválida ou não autorizada.\nDetalhes: {exc}"
            return f"⚠️ [Rock Specialist] A API do Gemini retornou erro.\nDetalhes: {exc}"

        except TimeoutError:
            return f"⏱️ [Rock Timeout] O modelo '{self.model}' excedeu o tempo limite de resposta ({self.timeout}s)."
        except Exception as exc:
            return f"❌ [Rock Specialist] Erro inesperado na comunicação com o Gemini: {exc}"

    def __call__(self, payload: Dict[str, Any]) -> str:
        """Permite que a instância seja invocada diretamente pelo Router."""
        text = payload.get("text", payload.get("query", ""))
        return self.chat(text)
