"""Ferramentas unificadas de contato: WhatsApp (Evolution API), E-mail (Gmail) e, em breve, ligações (Asterisk)."""

from __future__ import annotations

import base64
import html
import json
import logging
import mimetypes
import re
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any, Dict, Iterable, Optional

import requests

from rock_assistant.setup import config

logger = logging.getLogger(__name__)


# ==========================================
# WhatsApp (Evolution API)
# ==========================================

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


# ==========================================
# E-mail (Gmail)
# ==========================================

class GmailTool:
    """Executa operações Gmail com autenticação OAuth carregada sob demanda."""

    def __init__(self, service: Any = None, user_id: Optional[str] = None) -> None:
        self._service = service
        self.user_id = user_id or config.GMAIL_USER_ID

    def _get_service(self) -> Any:
        if self._service is not None:
            return self._service

        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError("Dependências OAuth do Gmail não estão instaladas.") from exc

        credentials = None
        if config.GMAIL_TOKEN_FILE.exists():
            credentials = Credentials.from_authorized_user_file(
                str(config.GMAIL_TOKEN_FILE), config.GMAIL_SCOPES
            )

        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        elif not credentials or not credentials.valid:
            if not config.GOOGLE_CREDENTIALS_FILE.exists():
                raise RuntimeError(f"Arquivo OAuth ausente: {config.GOOGLE_CREDENTIALS_FILE}")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(config.GOOGLE_CREDENTIALS_FILE), config.GMAIL_SCOPES
            )
            credentials = flow.run_local_server(port=0)

        config.GMAIL_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        config.GMAIL_TOKEN_FILE.write_text(credentials.to_json(), encoding="utf-8")
        self._service = build("gmail", "v1", credentials=credentials)
        return self._service

    def send(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[Iterable[str]] = None,
        bcc: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        """Envia texto simples e retorna apenas o identificador da mensagem."""
        if not to.strip():
            raise ValueError("Destinatário do e-mail não pode ser vazio.")
        message = EmailMessage()
        message["To"] = to
        message["Subject"] = subject
        if cc:
            message["Cc"] = ", ".join(cc)
        if bcc:
            message["Bcc"] = ", ".join(bcc)
        message.set_content(body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        response = self._get_service().users().messages().send(
            userId=self.user_id, body={"raw": raw}
        ).execute()
        result = {"status": "sent", "message_id": response.get("id")}
        if response.get("threadId"):
            result["thread_id"] = response["threadId"]
        return result

    def list_messages(
        self,
        query: str = "",
        max_results: Optional[int] = None,
        page_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        response = self._get_service().users().messages().list(
            userId=self.user_id,
            q=query,
            maxResults=max_results or config.GMAIL_MAX_MESSAGES,
            pageToken=page_token,
        ).execute()
        messages = [
            self.get_message(item["id"], include_body=False)
            for item in response.get("messages", [])
        ]
        return {
            "status": "ok",
            "messages": messages,
            "next_page_token": response.get("nextPageToken"),
            "result_size_estimate": response.get("resultSizeEstimate", 0),
        }

    def get_message(self, message_id: str, include_body: bool = True) -> Dict[str, Any]:
        if not message_id:
            raise ValueError("message_id é obrigatório.")
        response = self._get_service().users().messages().get(
            userId=self.user_id,
            id=message_id,
            format="full" if include_body else "metadata",
            metadataHeaders=[
                "From",
                "To",
                "Subject",
                "Date",
                "Message-ID",
                "Reply-To",
                "References",
            ],
        ).execute()
        return self._normalize_message(response, include_body=include_body)

    def mark_as_read(self, message_id: str) -> Dict[str, Any]:
        self._get_service().users().messages().modify(
            userId=self.user_id,
            id=message_id,
            body={"removeLabelIds": ["UNREAD"]},
        ).execute()
        return {"status": "updated", "message_id": message_id, "is_read": True}

    def reply(self, message_id: str, body: str) -> Dict[str, Any]:
        original = self.get_message(message_id, include_body=False)
        headers = original.get("headers", {})
        message = EmailMessage()
        message["To"] = headers.get("Reply-To") or headers.get("From", "")
        message["Subject"] = self._reply_subject(headers.get("Subject", ""))
        message["In-Reply-To"] = original.get("rfc822_message_id", "")
        message["References"] = original.get("references", "") or original.get(
            "rfc822_message_id", ""
        )
        message.set_content(body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        response = self._get_service().users().messages().send(
            userId=self.user_id,
            body={"raw": raw, "threadId": original.get("thread_id")},
        ).execute()
        result = {"status": "sent", "message_id": response.get("id")}
        if response.get("threadId"):
            result["thread_id"] = response["threadId"]
        return result

    @staticmethod
    def _reply_subject(subject: str) -> str:
        return subject if subject.lower().startswith("re:") else f"Re: {subject}"

    def _normalize_message(self, message: Dict[str, Any], include_body: bool) -> Dict[str, Any]:
        headers = {
            item.get("name", "").lower(): item.get("value", "")
            for item in message.get("payload", {}).get("headers", [])
        }
        result = {
            "id": message.get("id"),
            "thread_id": message.get("threadId"),
            "label_ids": message.get("labelIds", []),
            "is_read": "UNREAD" not in message.get("labelIds", []),
            "headers": headers,
            "subject": headers.get("subject", ""),
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "date": headers.get("date", ""),
            "message_id_header": headers.get("message-id", ""),
            "attachments": self._attachments(message.get("payload", {})),
        }
        if include_body or "message-id" in headers:
            result["body"] = self._body(message.get("payload", {}))
            result["rfc822_message_id"] = headers.get("message-id", "")
            result["references"] = headers.get("references", "")
            result["headers"]["reply-to"] = headers.get("reply-to", "")
        return result

    def _body(self, payload: Dict[str, Any]) -> str:
        plain_parts = []
        html_parts = []
        parts = payload.get("parts", []) or [payload]
        for part in self._walk_parts(parts):
            data = part.get("body", {}).get("data")
            if not data:
                continue
            decoded = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
                "utf-8", errors="replace"
            )
            mime_type = part.get("mimeType", "")
            if mime_type == "text/plain":
                plain_parts.append(decoded)
            elif mime_type == "text/html":
                html_parts.append(decoded)
        return "\n".join(plain_parts) or html.unescape("\n".join(html_parts))

    def _attachments(self, payload: Dict[str, Any]) -> list[Dict[str, Any]]:
        attachments = []
        for part in self._walk_parts(payload.get("parts", []) or [payload]):
            filename = part.get("filename")
            if filename:
                attachments.append(
                    {
                        "filename": filename,
                        "mime_type": part.get("mimeType") or mimetypes.guess_type(filename)[0],
                        "size": part.get("body", {}).get("size", 0),
                        "attachment_id": part.get("body", {}).get("attachmentId"),
                    }
                )
        return attachments

    @staticmethod
    def _walk_parts(parts: Iterable[Dict[str, Any]]) -> Iterable[Dict[str, Any]]:
        for part in parts:
            nested = part.get("parts")
            if nested:
                yield from GmailTool._walk_parts(nested)
            else:
                yield part


_default_gmail_tool: Optional[GmailTool] = None
_monitoring_enabled = config.GMAIL_MONITORING_ENABLED


def get_gmail_tool() -> GmailTool:
    global _default_gmail_tool
    if _default_gmail_tool is None:
        _default_gmail_tool = GmailTool()
    return _default_gmail_tool


def set_monitoring_enabled(enabled: bool) -> bool:
    """Atualiza o estado do monitoramento; o polling será conectado posteriormente."""
    global _monitoring_enabled
    _monitoring_enabled = bool(enabled)
    return _monitoring_enabled


def is_monitoring_enabled() -> bool:
    return _monitoring_enabled


class EmailDelegationManager:
    """Persiste assuntos delegados e identifica respostas sem responder sozinho."""

    def __init__(self, tool: Optional[GmailTool] = None, file_path: Optional[Any] = None) -> None:
        self.tool = tool or get_gmail_tool()
        self.file_path = file_path or config.GMAIL_DELEGATIONS_FILE
        self.delegations = self._load()

    def _load(self) -> list[Dict[str, Any]]:
        try:
            if self.file_path.exists():
                data = json.loads(self.file_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return [item for item in data if isinstance(item, dict)]
        except (OSError, ValueError):
            pass
        return []

    def _save(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_path.write_text(
            json.dumps(self.delegations, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def delegate(self, to: str, subject: str, body: str) -> Dict[str, Any]:
        result = self.tool.send(to, subject, body)
        delegation = {
            "id": uuid.uuid4().hex,
            "to": to,
            "subject": subject,
            "message_id": result.get("message_id"),
            "thread_id": result.get("thread_id"),
            "seen_message_ids": [result.get("message_id")],
            "status": "waiting_for_reply",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.delegations.append(delegation)
        self._save()
        return {
            "status": "delegated",
            "delegation_id": delegation["id"],
            "message_id": result.get("message_id"),
            "message": f"Enviei o e-mail para {to} e vou acompanhar o retorno sobre “{subject}”.",
        }

    def poll(self) -> list[Dict[str, Any]]:
        notices = []
        changed = False
        for delegation in self.delegations:
            if delegation.get("status") != "waiting_for_reply":
                continue
            query = f"thread:{delegation['thread_id']}" if delegation.get("thread_id") else (
                f"from:{delegation['to']} subject:\"{delegation['subject']}\""
            )
            result = self.tool.list_messages(query=query, max_results=config.GMAIL_MAX_MESSAGES)
            for message in result.get("messages", []):
                message_id = message.get("id")
                if not message_id or message_id in delegation.get("seen_message_ids", []):
                    continue
                delegation.setdefault("seen_message_ids", []).append(message_id)
                changed = True
                delegation["status"] = "reply_received"
                notices.append(
                    {
                        "delegation_id": delegation["id"],
                        "message_id": message_id,
                        "from": message.get("from", ""),
                        "subject": message.get("subject", delegation.get("subject", "")),
                        "message": (
                            f"Recebi uma resposta de {message.get('from', 'um contato')} "
                            f"sobre “{delegation.get('subject', '')}”. "
                            "Leia a mensagem e me diga se devo responder ou tomar outra decisão."
                        ),
                    }
                )
        if changed:
            self._save()
        return notices


_delegation_manager: Optional[EmailDelegationManager] = None


def get_email_delegation_manager() -> EmailDelegationManager:
    global _delegation_manager
    if _delegation_manager is None:
        _delegation_manager = EmailDelegationManager()
    return _delegation_manager


# ==========================================
# Classe unificada: WhatsApp + E-mail + Ligações (Asterisk, futuro)
# ==========================================

class ContactingTool:
    """Ponto único para todos os canais de contato do Rock (WhatsApp, e-mail e, em breve, chamadas)."""

    def __init__(self, gmail_tool: Optional[GmailTool] = None) -> None:
        self.gmail = gmail_tool or get_gmail_tool()

    # --- WhatsApp -------------------------------------------------------
    def send_whatsapp(self, recipient: str, message: str, delay: int = 1200, presence: str = "composing") -> Dict[str, Any]:
        return send_whatsapp_message(recipient, message, delay=delay, presence=presence)

    def send_whatsapp_presence(self, recipient: str, presence: str = "composing", delay: int = 7000) -> Dict[str, Any]:
        return send_whatsapp_presence(recipient, presence=presence, delay=delay)

    def send_whatsapp_media(
        self,
        recipient: str,
        media: str,
        mediatype: str = "image",
        caption: Optional[str] = None,
        delay: int = 1200,
        presence: str = "composing",
    ) -> Dict[str, Any]:
        return send_whatsapp_media(recipient, media, mediatype=mediatype, caption=caption, delay=delay, presence=presence)

    # --- E-mail -----------------------------------------------------------
    def send_email(self, to: str, subject: str, body: str, cc=None, bcc=None) -> Dict[str, Any]:
        return self.gmail.send(to, subject, body, cc=cc, bcc=bcc)

    def list_emails(self, query: str = "", max_results: Optional[int] = None) -> Dict[str, Any]:
        return self.gmail.list_messages(query=query, max_results=max_results)

    def get_email(self, message_id: str, include_body: bool = True) -> Dict[str, Any]:
        return self.gmail.get_message(message_id, include_body=include_body)

    def reply_email(self, message_id: str, body: str) -> Dict[str, Any]:
        return self.gmail.reply(message_id, body)

    def mark_email_read(self, message_id: str) -> Dict[str, Any]:
        return self.gmail.mark_as_read(message_id)

    # --- Ligações (Asterisk ARI) ------------------------------------------
    def make_call(self, recipient: str, script: Optional[str] = None) -> Dict[str, Any]:
        """Inicia uma ligação telefônica e conduz a conversa como assistente."""
        from rock_assistant.tools.contacts import is_phone_number, normalize_phone, resolve_contact
        from telephony.core.call_handler import get_call_handler

        target = recipient.strip()
        # Tenta resolver nome de contato para número se não for número direto
        resolved = resolve_contact(target, config.DB_PATH)
        phone = resolved if resolved else (normalize_phone(target) if is_phone_number(target) else target)

        handler = get_call_handler()
        return handler.start_outbound_call(recipient=phone, script=script)

    def answer_call(self, call_id: str) -> Dict[str, Any]:
        """Atende uma ligação recebida e conduz o diálogo como assistente."""
        from telephony.core.call_handler import get_call_handler

        handler = get_call_handler()
        return handler.handle_incoming_call(channel_id=call_id)


_default_contacting_tool: Optional[ContactingTool] = None


def get_contacting_tool() -> ContactingTool:
    global _default_contacting_tool
    if _default_contacting_tool is None:
        _default_contacting_tool = ContactingTool()
    return _default_contacting_tool
