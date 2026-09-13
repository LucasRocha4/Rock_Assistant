"""Servidor HTTP para integração local com a Evolution API (WhatsApp)."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request

from rock_assistant.core.intent_parser import IntentParser
from rock_assistant.core.memory import ConversationMemory
from rock_assistant.main import build_router
from rock_assistant.tools.messaging import send_whatsapp_message

logger = logging.getLogger(__name__)

app = FastAPI(title="Rock Assistant WhatsApp Webhook (Evolution API)")
parser = IntentParser()
memory = ConversationMemory()
router = build_router(memory=memory)


def _clean_phone_number(remote_jid: str) -> str:
    """Extrai apenas os números do remoteJid (ex: 5511999999999@s.whatsapp.net -> 5511999999999)."""
    if not remote_jid:
        return ""
    jid_user = remote_jid.split("@")[0] if "@" in remote_jid else remote_jid
    return re.sub(r"\D", "", jid_user)


def _extract_text(data: Dict[str, Any]) -> Optional[str]:
    """Extrai o texto da mensagem a partir da estrutura da Evolution API."""
    message = data.get("message")
    if not isinstance(message, dict):
        return None

    # Mensagem de texto simples
    conversation = message.get("conversation")
    if isinstance(conversation, str) and conversation.strip():
        return conversation.strip()

    # Mensagem de texto estendida (respostas, links preview, etc.)
    extended = message.get("extendedTextMessage")
    if isinstance(extended, dict):
        text = extended.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()

    # Fallback para legendas de mídia (imagem/documento/vídeo) caso enviadas com texto
    for media_type in ("imageMessage", "videoMessage", "documentMessage"):
        media_obj = message.get(media_type)
        if isinstance(media_obj, dict):
            caption = media_obj.get("caption")
            if isinstance(caption, str) and caption.strip():
                return caption.strip()

    return None


def _text_from_result(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        for key in ("message", "text", "response"):
            if result.get(key):
                return str(result[key])
    return str(result)


def _process_message(sender: str, text: str) -> None:
    parsed = parser.parse(text)
    intent = parsed.get("intent")
    if not intent:
        return
    if intent == "command":
        answer = "Por segurança, comandos do sistema não são executados pelo WhatsApp."
    else:
        answer = _text_from_result(router.route(intent, parsed.get("payload", {})))
    send_whatsapp_message(sender, answer)


@app.post("/webhook")
async def receive_webhook(request: Request) -> Dict[str, Any]:
    """Recebe e processa eventos enviados pela Evolution API via Webhook."""
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="JSON inválido") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload inválido")

    event = payload.get("event")
    if event != "messages.upsert":
        return {"status": "ok", "ignored": f"event_{event}"}

    data = payload.get("data")
    if not isinstance(data, dict):
        return {"status": "ok", "ignored": "missing_data"}

    key = data.get("key", {})
    if key.get("fromMe") is True:
        return {"status": "ok", "ignored": "fromMe"}

    remote_jid = key.get("remoteJid", "")
    sender = _clean_phone_number(remote_jid)
    if not sender:
        return {"status": "ok", "ignored": "invalid_sender"}

    text = _extract_text(data)
    if not text:
        return {"status": "ok", "ignored": "no_text"}

    _process_message(sender, text)
    return {"status": "ok", "processed": 1}