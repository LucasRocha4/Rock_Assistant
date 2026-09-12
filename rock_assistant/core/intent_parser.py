"""Lógica de parsing de intenção para comandos rápidos e roteamento para a LLM."""

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Garante acesso a configurações do projeto
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

try:
    from rock_assistant import config
except ImportError:
    import config


def ping_gemini(api_key: Optional[str] = None, model: Optional[str] = None) -> Dict[str, Any]:
    """Executa um smoke test mínimo de ping-pong com a API do Google Gemini."""
    key = api_key or os.getenv("GEMINI_API_KEY", getattr(config, "GEMINI_API_KEY", ""))
    if not key:
        print("[Gemini] Falha: GEMINI_API_KEY não configurada.")
        return {
            "success": False,
            "error": "chave ausente",
            "message": "Chave da API do Gemini ausente. Defina a variável de ambiente GEMINI_API_KEY.",
        }

    target_model = model or getattr(config, "GEMINI_MODEL_ROUTER", "gemini-2.0-flash-lite")

    try:
        from google import genai
        from google.genai import types
        from google.genai.errors import APIError, ClientError, ServerError

        timeout_val = getattr(config, "GEMINI_TIMEOUT", 30)
        gen_config = types.GenerateContentConfig(
            temperature=0.0,
        )

        client = genai.Client(
            api_key=key,
            http_options=types.HttpOptions(timeout=timeout_val * 1000 if timeout_val else 30000),
        )
        response = client.models.generate_content(
            model=target_model,
            contents="responda apenas com: ping",
            config=gen_config,
        )

        reply_text = (response.text or "").strip().lower()
        if "ping" in reply_text:
            print(f"[Gemini] Online. Comunicação validada com sucesso via modelo '{target_model}'.")
            return {"success": True, "model": target_model, "response": response.text.strip()}

        print(f"[Gemini] Resposta recebida mas inesperada: {response.text}")
        return {"success": True, "model": target_model, "response": response.text.strip()}

    except ImportError:
        err = "SDK 'google-genai' não está instalado."
        print(f"[Gemini] Falha: {err}")
        return {"success": False, "error": "sdk_ausente", "message": err}
    except (ClientError, APIError) as exc:
        err_str = str(exc).lower()
        if "quota" in err_str or "resource_exhausted" in err_str or "429" in err_str:
            reason = "quota excedida"
        elif "safety" in err_str or "blocked" in err_str:
            reason = "rejeição por segurança"
        elif "api_key" in err_str or "unauthenticated" in err_str or "invalid" in err_str or "403" in err_str or "401" in err_str:
            reason = "chave ausente ou inválida"
        else:
            reason = f"erro na api do gemini: {exc}"
        print(f"[Gemini] Erro de API ({reason}): {exc}")
        return {"success": False, "error": reason, "message": str(exc)}
    except TimeoutError:
        print("[Gemini] Timeout na comunicação com a API do Gemini.")
        return {"success": False, "error": "timeout", "message": "Tempo limite excedido."}
    except Exception as exc:
        err_str = str(exc).lower()
        if "timeout" in err_str or "timed out" in err_str or "deadline exceeded" in err_str:
            print(f"[Gemini] Timeout na comunicação com a API do Gemini: {exc}")
            return {"success": False, "error": "timeout", "message": str(exc)}
        print(f"[Gemini] Erro de rede ou comunicação: {exc}")
        return {"success": False, "error": "erro de rede", "message": str(exc)}


class IntentParser:
    """Identifica a intenção do usuário a partir de texto bruto e extrai payloads estruturados.

    Suporta parsing rápido determinístico via Expressões Regulares e
    roteamento contextual avançado via LLM (Google Gemini) com fallback automático.
    """

    # Expressões regulares para detecção de intenções
    SEARCH_PATTERN = re.compile(
        r"^(?:(?:você\s+pode|pode|poderia)\s+)?(?:busca(?:r|r por| por|que)?|busque(?: por)?|pesquisa(?:r|r por| por)?|pesquise(?: por)?|procur(?:ar|e|a|ar por)?|procure(?: por)?|google|ddg)\b(?:\s+(.+))?$",
        re.IGNORECASE,
    )
    NATURAL_SEARCH_PATTERN = re.compile(
        r"^(?:(?:eu\s+)?(?:quero|gostaria|preciso)\s+(?:que\s+)?|(?:eu\s+)?(?:pedi|peço|peco)\s+para\s+)(?:você\s+)?(?:busque|buscar|busca|pesquise|pesquisar|procure|procurar)\s+(.+)$",
        re.IGNORECASE,
    )

    REMINDER_KEYWORD = re.compile(
        r"\b(lembre-me|lembre|lembra|lembrar|lembrete|recordar|alarme|agendar|agende)\b",
        re.IGNORECASE,
    )

    MESSAGE_KEYWORD = re.compile(
        r"\b(mandar|enviar|mensagem|whatsapp|telegram|msg|notificar)\b",
        re.IGNORECASE,
    )
    EMAIL_KEYWORD = re.compile(
        r"\b(e-?mails?|correio eletrônico|correio eletronico)\b",
        re.IGNORECASE,
    )

    COMMAND_PREFIX = re.compile(
        r"^(?:exec|executa|executar|rode|rodar|run)\b(?:\s*(.*))?$",
        re.IGNORECASE,
    )
    COMMAND_KEYWORD = re.compile(
        r"\b(exec|executa|executar|rode|rodar|run|abrir|ligar|desligar)\b",
        re.IGNORECASE,
    )
    DIRECT_CLI = re.compile(
        r"^(?:nmap\b|ping\b|ip\s+a\b|ip\s+addr\b|ip\s+-4\b|ifconfig\b|ss\b|netstat\b|uname\b|uptime\b|ls\b|cat\b|pwd\b)",
        re.IGNORECASE,
    )

    # Expressões temporais para extração do campo 'when' em lembretes
    TIME_PATTERNS = [
        r"\b(?:depois de amanhã|depois de amanha|hoje|amanhã|amanha)\s+(?:às|as|ás|ao|a)?\s*(?:meio[- ]dia|meio dia|meia[- ]noite|meia noite|\d{1,2}(?:[:h]\d{2})?(?:\s*(?:am|pm))?)",
        r"\b(?:às|as|ás|para as|para às|para as|at)\s+\d{1,2}(?:[:h]\d{2})?(?:\s*(?:am|pm))?",
        r"\b(?:em|no dia|dia|data)\s+\d{1,2}(?:/\d{1,2}(?:/\d{2,4})?)?",
        r"\b(?:depois de amanhã|depois de amanha|hoje|amanhã|amanha)(?:\s+(?:às|as|ás|ao|a|de|pela)\s+[\w\d:]+)?",
        r"\b(?:pela manhã|pela manha|de manhã|de manha|pela tarde|de tarde|à tarde|a tarde|à noite|a noite|de noite|pela noite)\b",
        r"\b(?:segunda(?:-feira)?|terça(?:-feira)?|quarta(?:-feira)?|quinta(?:-feira)?|sexta(?:-feira)?|sábado|sabado|domingo)(?:\s+(?:às|as|ás)\s+[\w\d:]+)?",
        r"\b\d{1,2}[:h]\d{2}\b",
        r"\bpara\s+\d{1,2}(?:[:h]\d{2})?\b",
    ]

    def __init__(self) -> None:
        pass

    def _extract_search_payload(self, text: str) -> Dict[str, str]:
        """Extrai o termo de busca a partir do texto."""
        explicit_mode = re.match(
            r"^(?:busca|pesquisa)\s+(em\s+massa|(?:de\s+)?alvo\s+espec[ií]fico)\s*:\s*(.+)$",
            text,
            re.IGNORECASE,
        )
        if explicit_mode:
            mode = "bulk" if "massa" in explicit_mode.group(1).lower() else "target"
            return {"query": explicit_mode.group(2).strip(), "mode": mode}

        # Se for pergunta indireta como 'Você pode pesquisar ...?', preserva texto completo conforme especificado
        if re.match(r"^(?:você\s+pode|pode|poderia)\s+", text, re.IGNORECASE):
            return {"query": text}

        natural_match = self.NATURAL_SEARCH_PATTERN.match(text)
        if natural_match:
            query = natural_match.group(1).strip().rstrip("?")
            return self._add_search_mode(query)

        match = self.SEARCH_PATTERN.match(text)
        if match and match.group(1):
            query = match.group(1).strip()
        else:
            # Remove palavras-chave comuns de busca do início
            query = re.sub(
                r"^(?:busca(?:r|r por| por)?|pesquisa(?:r|r por| por)?|pesquise(?: por)?|procur(?:ar|e|a|ar por)?|google|ddg)\s*",
                "",
                text,
                flags=re.IGNORECASE,
            ).strip()

        # Limpa termos redundantes iniciais como "sobre " ou "por "
        query = re.sub(r"^(?:sobre|por)\s+", "", query, flags=re.IGNORECASE).strip()
        return self._add_search_mode(query if query else text)

    @staticmethod
    def _add_search_mode(query: str) -> Dict[str, str]:
        """Preserva buscas antigas e adiciona modo somente quando explícito."""
        cleaned = query.strip()
        mass_match = re.match(r"^(?:busca|pesquisa)\s+em\s+massa\s*:?[\s]+(.+)$", cleaned, re.IGNORECASE)
        if mass_match:
            return {"query": mass_match.group(1).strip(), "mode": "bulk"}
        target_match = re.match(r"^(?:busca|pesquisa)\s+(?:de\s+)?alvo\s+espec[ií]fico\s*:?[\s]+(.+)$", cleaned, re.IGNORECASE)
        if target_match:
            return {"query": target_match.group(1).strip(), "mode": "target"}
        return {"query": cleaned}

    def _extract_reminder_payload(self, text: str) -> Dict[str, Optional[str]]:
        """Extrai a descrição da tarefa e o horário/data em {'text': ..., 'when': ...}."""
        # 1. Remove gatilhos de comando do início com limites de palavra
        cleaned = re.sub(
            r"^(?:(?:eu\s+)?quero\s+que\s+(?:você\s+)?me\s+lembre(?:\s+de)?|não\s+esqueça\s+de\s+me\s+lembrar(?:\s+de)?|(?:pode\s+|por\s+favor\s+)?me\s+lembr(?:e|a)(?:\s+de)?|lembre-me(?:\s+de)?|lembrete(?:\s+de|:)?|lembre(?:\s+de)?|lembrar(?:\s+de)?|recordar(?:\s+de)?|agendar|agende|alarme(?:\s+para)?)\b\s*",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()

        when: Optional[str] = None
        task_text = cleaned

        # 2. Busca padrão temporal
        for pattern in self.TIME_PATTERNS:
            match = re.search(pattern, cleaned, re.IGNORECASE)
            if match:
                when = match.group(0).strip()
                # Remove a expressão de tempo do texto da tarefa
                before = cleaned[:match.start()].strip()
                after = cleaned[match.end():].strip()
                combined = f"{before} {after}".strip()
                if combined:
                    task_text = combined
                break

        # 3. Limpeza final de preposições no início/fim do texto da tarefa
        task_text = re.sub(r"^(?:de|para|que)\s+", "", task_text, flags=re.IGNORECASE).strip()
        task_text = re.sub(r"^[:;,\-]\s*", "", task_text).strip()
        task_text = re.sub(r"\s+(?:para|de|em|às|as|ás)$", "", task_text, flags=re.IGNORECASE).strip()

        if not task_text:
            task_text = cleaned if cleaned else text

        return {"text": task_text, "when": when}

    def _extract_message_payload(self, text: str) -> Dict[str, str]:
        """Extrai destino e conteúdo em {'target': ..., 'text': ...}."""
        # Padrão com destinatário explícito: mandar/enviar [mensagem] para <target>[:,-]? <text>
        match_target = re.match(
            r"^(?:mandar|enviar|notificar)?\s*(?:mensagem|msg|whatsapp|telegram)?\s*(?:para|pra|pro)\s+([^\s:,]+)\s*[:,-]?\s*(.*)$",
            text,
            re.IGNORECASE,
        )
        if match_target and match_target.group(1):
            target = match_target.group(1).strip().strip(":,;")
            msg_content = match_target.group(2).strip()
            if not msg_content:
                msg_content = text
            return {"target": target, "text": msg_content}

        # Padrão: enviar mensagem <text> (sem destinatário explícito)
        match_no_target = re.match(
            r"^(?:mandar|enviar|notificar)\s+(?:mensagem|msg|whatsapp|telegram)\s+(.*)$",
            text,
            re.IGNORECASE,
        )
        if match_no_target:
            return {"target": "default", "text": match_no_target.group(1).strip()}

        return {"target": "default", "text": text}

    def _extract_email_payload(self, text: str) -> Dict[str, Any]:
        """Extrai operação e parâmetros de e-mail em um payload estruturado."""
        normalized = re.sub(r"\be-?mail\b", "email", text, flags=re.IGNORECASE).strip()

        if re.search(r"\b(ativar|ligar|iniciar)\b", normalized, re.IGNORECASE) and re.search(
            r"\b(monitoramento|monitorar|notifica(?:ção|cao))\b", normalized, re.IGNORECASE
        ):
            return {"operation": "monitor", "enabled": True}
        if re.search(r"\b(desativar|desligar|parar)\b", normalized, re.IGNORECASE) and re.search(
            r"\b(monitoramento|monitorar|notifica(?:ção|cao))\b", normalized, re.IGNORECASE
        ):
            return {"operation": "monitor", "enabled": False}

        reply = re.search(
            r"\b(?:responder|responda)\s+(?:o\s+)?email\s+(?:de\s+)?([\w-]+)\s*[:,-]?\s*(.*)$",
            normalized,
            re.IGNORECASE,
        )
        if reply:
            return {"operation": "reply", "message_id": reply.group(1), "body": reply.group(2).strip()}

        mark_read = re.search(
            r"\bmar(?:car|que)\s+(?:o\s+)?email\s+([\w-]+)\s+(?:como\s+)?lido\b",
            normalized,
            re.IGNORECASE,
        )
        if mark_read:
            return {"operation": "mark_read", "message_id": mark_read.group(1)}

        read = re.search(
            r"\b(?:ler|leia|abrir|abra)\s+(?:o\s+)?email(?:\s+([\w-]+))?",
            normalized,
            re.IGNORECASE,
        )
        if read and read.group(1):
            return {"operation": "read", "message_id": read.group(1)}

        if re.search(r"\b(listar|liste|ver|mostrar|mostre|receber|receba)\b", normalized, re.IGNORECASE):
            query = "is:unread" if re.search(r"não\s+lidos|nao\s+lidos", normalized, re.IGNORECASE) else ""
            return {"operation": "list", "query": query}

        send = re.search(
            r"\b(?:enviar|envie|mandar|mande)\s+email\s+(?:para|pra)\s+([^,;:]+)"
            r"(?:\s*[,;:]?\s*(?:assunto|subject)\s*[:=-]\s*(.*?))?"
            r"(?:\s*[,;:]?\s*(?:corpo|mensagem|texto)\s*[:=-]\s*(.*))?$",
            normalized,
            re.IGNORECASE,
        )
        if send:
            return {
                "operation": "send",
                "to": send.group(1).strip(),
                "subject": (send.group(2) or "").strip(),
                "body": (send.group(3) or "").strip(),
            }

        return {"operation": "list", "query": ""}

    def _extract_command_payload(self, text: str) -> Dict[str, str]:
        """Extrai o comando do sistema em {'command': ...}."""
        match = self.COMMAND_PREFIX.match(text)
        if match and match.group(1):
            cmd = match.group(1).strip()
            return {"command": cmd if cmd else text}

        if re.search(r"\babrir\s+terminal\b", text, re.IGNORECASE):
            return {"command": "x-terminal-emulator"}

        return {"command": text}

    def parse(self, user_input: str) -> Dict[str, Any]:
        """Identifica a intenção e extrai parâmetros estruturados via RegEx.

        Aplica a ordem obrigatória de decisão:
        1. comando direto ou prefixado
        2. busca na web
        3. lembrete
        4. mensagem
        5. comando por palavra-chave
        6. conversa geral

        Retorna:
            Dict no formato: {'intent': <str>, 'payload': <dict>}
        """
        if user_input is None:
            return {"intent": None, "payload": {}}

        cleaned_input = user_input.strip()
        if not cleaned_input:
            return {"intent": None, "payload": {}}

        # 1. Comandos Diretos de CLI ou Prefixados
        if self.COMMAND_PREFIX.match(cleaned_input) or self.DIRECT_CLI.match(cleaned_input) or re.match(r"^abrir\s+terminal$", cleaned_input, re.IGNORECASE):
            return {
                "intent": "command",
                "payload": self._extract_command_payload(cleaned_input),
            }

        # 2. Busca na Web
        if self.SEARCH_PATTERN.match(cleaned_input) or self.NATURAL_SEARCH_PATTERN.match(cleaned_input):
            return {
                "intent": "search",
                "payload": self._extract_search_payload(cleaned_input),
            }

        # 3. Lembretes e Agendamento
        if self.REMINDER_KEYWORD.search(cleaned_input):
            return {
                "intent": "reminder",
                "payload": self._extract_reminder_payload(cleaned_input),
            }

        # 4. E-mails antes de mensagens, pois "enviar email" também contém "enviar"
        if self.EMAIL_KEYWORD.search(cleaned_input):
            return {
                "intent": "email",
                "payload": self._extract_email_payload(cleaned_input),
            }

        # 5. Mensagens
        if self.MESSAGE_KEYWORD.search(cleaned_input):
            return {
                "intent": "message",
                "payload": self._extract_message_payload(cleaned_input),
            }

        # 6. Outros Comandos de Sistema / Palavra-chave
        if self.COMMAND_KEYWORD.search(cleaned_input):
            return {
                "intent": "command",
                "payload": self._extract_command_payload(cleaned_input),
            }

        # 7. Intenção Geral / Conversação
        return {
            "intent": "general",
            "payload": {"text": cleaned_input},
        }

    def parse_with_llm(self, user_input: str) -> Dict[str, Any]:
        """Roteia a entrada do usuário utilizando a API do Google Gemini com fallback determinístico.

        Realiza chamada ao modelo GEMINI_MODEL_ROUTER da Google forçando saída em JSON estrito.
        """
        cleaned_input = (user_input or "").strip()
        if not cleaned_input:
            return {"intent": None, "payload": {}}

        # O parsing local determinístico evita chamadas à nuvem quando o roteador LLM está desligado
        if not getattr(config, "LLM_ROUTER_ENABLED", False):
            return self.parse(cleaned_input)

        api_key = getattr(config, "GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            print("[Gemini Router] GEMINI_API_KEY não configurada. Usando fallback de regras.")
            return self.parse(cleaned_input)

        system_instructions = (
            "Você é o modelo roteador do assistente Rock no Kali Linux.\n"
            "Sua única tarefa é analisar a entrada do usuário e extrair a intenção e os parâmetros estruturados.\n"
            "Você DEVE responder exclusivamente em formato JSON com duas chaves: 'intent' e 'payload'.\n\n"
            "Estruturas permitidas:\n"
            "- intent 'search' -> payload: {\"query\": \"termo de busca\"}\n"
            "- intent 'reminder' -> payload: {\"text\": \"descrição da tarefa\", \"when\": \"horário/data ou null\", \"kind\": \"calendar_event ou self_message\", \"importance\": \"low, normal, high ou urgent\"}\n"
            "- intent 'command' -> payload: {\"command\": \"comando do sistema operacional\"}\n"
            "- intent 'message' -> payload: {\"target\": \"destinatário ou default\", \"text\": \"conteúdo\"}\n"
            "- intent 'email' -> payload: {\"operation\": \"send|list|read|reply|mark_read|monitor\", \"message_id\": \"id opcional\", \"to\": \"destinatário opcional\", \"subject\": \"assunto opcional\", \"body\": \"corpo opcional\", \"query\": \"busca opcional\", \"enabled\": true ou false}\n"
            "- intent 'general' -> payload: {\"text\": \"texto completo do usuário\"}\n\n"
            "Exemplo 1: 'busca tutoriais de nmap' -> {\"intent\": \"search\", \"payload\": {\"query\": \"tutoriais de nmap\"}}\n"
            "Exemplo 2: 'lembrete reunião às 15:00' -> {\"intent\": \"reminder\", \"payload\": {\"text\": \"reunião\", \"when\": \"às 15:00\"}}\n"
            "Exemplo 3: 'exec nmap 127.0.0.1' -> {\"intent\": \"command\", \"payload\": {\"command\": \"nmap 127.0.0.1\"}}\n"
            "Exemplo 4: 'mandar whatsapp para joao tudo certo' -> {\"intent\": \"message\", \"payload\": {\"target\": \"joao\", \"text\": \"tudo certo\"}}\n"
            "Exemplo 5: 'listar emails não lidos' -> {\"intent\": \"email\", \"payload\": {\"operation\": \"list\", \"query\": \"is:unread\"}}\n"
        )

        try:
            from google import genai
            from google.genai import types

            timeout_val = getattr(config, "GEMINI_TIMEOUT", 30)
            client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=timeout_val * 1000 if timeout_val else 30000),
            )
            gen_config = types.GenerateContentConfig(
                system_instruction=system_instructions,
                temperature=0.0,
                response_mime_type="application/json",
            )

            model_name = getattr(config, "GEMINI_MODEL_ROUTER", "gemini-2.0-flash-lite")
            response = client.models.generate_content(
                model=model_name,
                contents=f"Entrada do usuário: {cleaned_input}",
                config=gen_config,
            )

            raw_content = (response.text or "").strip()
            if raw_content:
                parsed = json.loads(raw_content)
                intent = parsed.get("intent")
                payload = parsed.get("payload")

                valid_intents = {"search", "reminder", "command", "message", "email", "general"}
                if intent in valid_intents and isinstance(payload, dict):
                    return {"intent": intent, "payload": payload}

        except Exception as exc:
            print(f"[Gemini Router] Falha no roteamento via Gemini ({exc}). Usando fallback de regras.")

        return self.parse(cleaned_input)

