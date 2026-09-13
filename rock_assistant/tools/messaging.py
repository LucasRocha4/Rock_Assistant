"""Ferramentas para envio de mensagens por webhooks e canais externos."""

import logging
import re
from typing import Any, Dict, Optional

import requests

from rock_assistant import config

logger = logging.getLogger(__name__)


def _sanitize_phone_number(phone: str) -> str:
    """Extrai apenas os dígitos numéricos do telefone ou remoteJid."""
    if "@" in phone:
        phone = phone.split("@")[0]
    return re.sub(r"\D", "", phone)


def _check_evolution_config() -> None:
    """Valida as variáveis de ambiente necessárias para a Evolution API."""
    if not config.EVOLUTION_API_KEY or not config.EVOLUTION_INSTANCE:
        raise RuntimeError("EVOLUTION_API_KEY e EVOLUTION_INSTANCE são obrigatórios")


def send_message(channel: str, message: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Simula o envio de uma mensagem para um canal externo via webhook.

    Em uma implementação real, o código poderia postar para Slack, Telegram,
    Discord, WhatsApp ou outros serviços via webhook HTTP.
    """
    payload = {"channel": channel, "message": message}
    if metadata:
        payload["metadata"] = metadata
    return {"status": "queued", "payload": payload}


def send_whatsapp_message(
    recipient: str,
    message: str,
    delay: int = 1200,
    presence: str = "composing",
) -> Dict[str, Any]:
    """Envia uma mensagem de texto pela Evolution API."""
    _check_evolution_config()

    phone_number = _sanitize_phone_number(recipient)
    if not phone_number:
        raise ValueError("Número de telefone destinatário inválido")

    url = f"{config.EVOLUTION_API_URL}/message/sendText/{config.EVOLUTION_INSTANCE}"
    headers = {
        "apikey": config.EVOLUTION_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "number": phone_number,
        "options": {
            "delay": delay,
            "presence": presence,
        },
        "text": message,
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=config.EVOLUTION_REQUEST_TIMEOUT,
        )
        if not response.ok:
            error_detail = response.text
            logger.error(
                "Falha ao enviar mensagem de texto Evolution API (status %s): %s",
                response.status_code,
                error_detail,
            )
            if response.status_code in (400, 401):
                logger.error("Erro de autenticação ou parâmetros inválidos na Evolution API.")
            elif response.status_code == 422:
                logger.error("Número de destino '%s' não possui WhatsApp registrado.", phone_number)
            response.raise_for_status()

        return response.json()
    except requests.RequestException as exc:
        logger.error("Erro na requisição para Evolution API: %s", exc)
        raise


def send_whatsapp_presence(
    recipient: str,
    presence: str = "composing",
    delay: int = 7000,
) -> Dict[str, Any]:
    """Atualiza a presenca de digitacao quando a Evolution API oferecer a rota."""
    _check_evolution_config()
    phone_number = _sanitize_phone_number(recipient)
    if not phone_number:
        raise ValueError("Número de telefone destinatário inválido")
    url = f"{config.EVOLUTION_API_URL}/chat/sendPresence/{config.EVOLUTION_INSTANCE}"
    response = requests.post(
        url,
        headers={"apikey": config.EVOLUTION_API_KEY, "Content-Type": "application/json"},
        json={"number": phone_number, "presence": presence, "delay": delay},
        timeout=config.EVOLUTION_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def send_whatsapp_media(
    recipient: str,
    media: str,
    mediatype: str = "image",
    caption: Optional[str] = None,
    delay: int = 1200,
    presence: str = "composing",
) -> Dict[str, Any]:
    """Envia mídia (imagem, vídeo, áudio, documento) pela Evolution API."""
    _check_evolution_config()

    phone_number = _sanitize_phone_number(recipient)
    if not phone_number:
        raise ValueError("Número de telefone destinatário inválido")

    url = f"{config.EVOLUTION_API_URL}/message/sendMedia/{config.EVOLUTION_INSTANCE}"
    headers = {
        "apikey": config.EVOLUTION_API_KEY,
        "Content-Type": "application/json",
    }
    media_data: Dict[str, Any] = {
        "mediatype": mediatype,
        "media": media,
    }
    if caption:
        media_data["caption"] = caption

    payload = {
        "number": phone_number,
        "options": {
            "delay": delay,
            "presence": presence,
        },
        "mediaMessage": media_data,
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=config.EVOLUTION_REQUEST_TIMEOUT,
        )
        if not response.ok:
            error_detail = response.text
            logger.error(
                "Falha ao enviar mídia Evolution API (status %s): %s",
                response.status_code,
                error_detail,
            )
            if response.status_code in (400, 401):
                logger.error("Erro de autenticação ou parâmetros inválidos na Evolution API.")
            elif response.status_code == 422:
                logger.error("Número de destino '%s' não possui WhatsApp registrado.", phone_number)
            response.raise_for_status()

        return response.json()
    except requests.RequestException as exc:
        logger.error("Erro na requisição de mídia para Evolution API: %s", exc)
        raise


class MessagingTool:
    """Wrapper orientado a objeto para envio de mensagens."""

    def __init__(self) -> None:
        self.name = "messaging"

    def send(self, channel: str, message: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Envia uma mensagem usando a função base."""
        return send_message(channel=channel, message=message, metadata=metadata)

    def send_whatsapp(
        self,
        recipient: str,
        message: str,
        delay: int = 1200,
        presence: str = "composing",
    ) -> Dict[str, Any]:
        """Envia mensagem de WhatsApp via Evolution API."""
        return send_whatsapp_message(recipient, message, delay=delay, presence=presence)

    def send_whatsapp_media(
        self,
        recipient: str,
        media: str,
        mediatype: str = "image",
        caption: Optional[str] = None,
        delay: int = 1200,
        presence: str = "composing",
    ) -> Dict[str, Any]:
        """Envia mídia de WhatsApp via Evolution API."""
        return send_whatsapp_media(
            recipient=recipient,
            media=media,
            mediatype=mediatype,
            caption=caption,
            delay=delay,
            presence=presence,
        )
