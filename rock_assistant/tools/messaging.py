"""Ferramentas para envio de mensagens por webhooks e canais externos."""

from typing import Any, Dict, Optional

import requests

from rock_assistant import config


def send_message(channel: str, message: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Simula o envio de uma mensagem para um canal externo via webhook.

    Em uma implementação real, o código poderia postar para Slack, Telegram,
    Discord, WhatsApp ou outros serviços via webhook HTTP.
    """
    payload = {"channel": channel, "message": message}
    if metadata:
        payload["metadata"] = metadata
    return {"status": "queued", "payload": payload}


def send_whatsapp_message(recipient: str, message: str) -> Dict[str, Any]:
    """Envia uma mensagem de texto pela WhatsApp Cloud API."""
    if not config.META_ACCESS_TOKEN or not config.META_PHONE_NUMBER_ID:
        raise RuntimeError("META_ACCESS_TOKEN e META_PHONE_NUMBER_ID são obrigatórios")

    url = f"{config.META_GRAPH_API_URL}/{config.META_PHONE_NUMBER_ID}/messages"
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {config.META_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        json={
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "text",
            "text": {"body": message, "preview_url": False},
        },
        timeout=config.META_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


class MessagingTool:
    """Wrapper orientado a objeto para envio de mensagens."""

    def __init__(self) -> None:
        self.name = "messaging"

    def send(self, channel: str, message: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Envia uma mensagem usando a função base."""
        return send_message(channel=channel, message=message, metadata=metadata)
