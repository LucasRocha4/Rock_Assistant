"""Esquemas de ferramentas (estilo MCP/function calling) expostos ao LLM local.

Cada entrada descreve uma ferramenta disponível no Router para que o modelo
(Llama via Ollama) possa decidir qual delas chamar, com quais argumentos,
antes da execução real feita por core/router.py.
"""

from typing import Any, Dict, List

# Formato compatível com o parâmetro `tools` da API de chat do Ollama
# (mesmo formato usado por function calling estilo OpenAI).
TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Pesquisa na web (DuckDuckGo/Wikipedia) por um termo ou pergunta.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Termo ou pergunta a pesquisar."},
                    "max_results": {"type": "integer", "description": "Quantidade máxima de resultados."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reminder",
            "description": "Cria um lembrete ou evento de calendário a partir de texto em linguagem natural.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "O que deve ser lembrado."},
                    "when": {"type": "string", "description": "Quando o lembrete deve ocorrer."},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "command",
            "description": "Executa um comando de diagnóstico/sistema local (uso restrito, apenas terminal local).",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Comando a executar."},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "message",
            "description": "Envia uma mensagem de WhatsApp para um contato ou número.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "Nome do contato ou número de telefone."},
                    "text": {"type": "string", "description": "Texto da mensagem."},
                },
                "required": ["target", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "email",
            "description": "Envia, lista, lê ou responde e-mails via Gmail.",
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["send", "list", "read", "reply", "mark_read", "delegate", "monitor"],
                    },
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "query": {"type": "string"},
                    "message_id": {"type": "string"},
                },
                "required": ["operation"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "contact",
            "description": "Cadastra um novo contato (nome, número, e opcionalmente e-mail/descrição).",
            "parameters": {
                "type": "object",
                "properties": {
                    "contact_name": {"type": "string"},
                    "contact_number": {"type": "string"},
                    "contact_email": {"type": "string"},
                    "contact_description": {"type": "string"},
                },
                "required": ["contact_name", "contact_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "goal",
            "description": "Inicia uma confirmação de evento com um contato via WhatsApp (local, horário, o que levar).",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "Nome ou número do contato."},
                    "event_description": {"type": "string", "description": "O que precisa ser confirmado."},
                },
                "required": ["target", "event_description"],
            },
        },
    },
]


def get_tool_schemas() -> List[Dict[str, Any]]:
    """Retorna a lista de schemas de ferramentas registradas para function calling."""
    return TOOL_SCHEMAS
