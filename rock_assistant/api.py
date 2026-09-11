"""Servidor HTTP para integração local com a WhatsApp Cloud API."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Dict, Iterable, Optional

from fastapi import FastAPI, HTTPException, Request, Response

from rock_assistant import config
from rock_assistant.core.intent_parser import IntentParser
from rock_assistant.core.memory import ConversationMemory
from rock_assistant.main import build_router
from rock_assistant.tools.messaging import send_whatsapp_message

app = FastAPI(title="Rock Assistant WhatsApp Webhook")
parser = IntentParser()
memory = ConversationMemory()
router = build_router(memory=memory)


def _signature_is_valid(body: bytes, signature: Optional[str]) -> bool:
    """Valida a assinatura da Meta quando o app secret está configurado."""
    if not config.META_APP_SECRET:
        return True
    if not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(config.META_APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature.removeprefix("sha256="), expected)


def _text_from_result(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        for key in ("message", "text", "response"):
            if result.get(key):
                return str(result[key])
    return str(result)


def _text_messages(payload: Dict[str, Any]) -> Iterable[tuple[str, str]]:
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                text = message.get("text", {}).get("body")
                sender = message.get("from")
                if isinstance(sender, str) and isinstance(text, str) and text.strip():
                    yield sender, text.strip()


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


@app.get("/webhook")
async def verify_webhook(request: Request) -> Response:
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and hmac.compare_digest(
        params.get("hub.verify_token", ""), config.META_VERIFY_TOKEN
    ):
        return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
    raise HTTPException(status_code=403, detail="token de verificação inválido")


@app.post("/webhook")
async def receive_webhook(request: Request) -> Dict[str, Any]:
    body = await request.body()
    if not _signature_is_valid(body, request.headers.get("x-hub-signature-256")):
        raise HTTPException(status_code=403, detail="assinatura inválida")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="JSON inválido") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload inválido")

    processed = 0
    for sender, text in _text_messages(payload):
        _process_message(sender, text)
        processed += 1
    return {"status": "accepted", "processed": processed}