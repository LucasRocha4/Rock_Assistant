"""Integração com Gmail para envio, leitura e organização de mensagens."""

from __future__ import annotations

import base64
import html
import mimetypes
from email.message import EmailMessage
from typing import Any, Dict, Iterable, Optional

from rock_assistant import config


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
        return {"status": "sent", "message_id": response.get("id")}

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
        return {"status": "sent", "message_id": response.get("id")}

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


_default_tool: Optional[GmailTool] = None
_monitoring_enabled = config.GMAIL_MONITORING_ENABLED


def get_gmail_tool() -> GmailTool:
    global _default_tool
    if _default_tool is None:
        _default_tool = GmailTool()
    return _default_tool


def set_monitoring_enabled(enabled: bool) -> bool:
    """Atualiza o estado do monitoramento; o polling será conectado posteriormente."""
    global _monitoring_enabled
    _monitoring_enabled = bool(enabled)
    return _monitoring_enabled


def is_monitoring_enabled() -> bool:
    return _monitoring_enabled