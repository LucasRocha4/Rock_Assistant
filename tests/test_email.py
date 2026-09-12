import base64
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from rock_assistant.core.intent_parser import IntentParser
from rock_assistant.tools.email import GmailTool, is_monitoring_enabled, set_monitoring_enabled


class GmailToolTests(unittest.TestCase):
    def setUp(self):
        self.service = MagicMock()
        self.messages = self.service.users.return_value.messages.return_value
        self.tool = GmailTool(service=self.service, user_id="me")

    def test_send_encodes_message_and_returns_id(self):
        self.messages.send.return_value.execute.return_value = {"id": "sent-1"}

        result = self.tool.send("ana@example.com", "Assunto", "Corpo")

        self.assertEqual(result, {"status": "sent", "message_id": "sent-1"})
        request = self.messages.send.call_args.kwargs
        decoded = base64.urlsafe_b64decode(request["body"]["raw"])
        self.assertIn(b"To: ana@example.com", decoded)
        self.assertIn(b"Corpo", decoded)

    def test_normalizes_body_and_attachment_metadata(self):
        encoded = base64.urlsafe_b64encode("Olá".encode()).decode().rstrip("=")
        self.messages.get.return_value.execute.return_value = {
            "id": "msg-1",
            "threadId": "thread-1",
            "labelIds": ["INBOX", "UNREAD"],
            "payload": {
                "headers": [
                    {"name": "From", "value": "ana@example.com"},
                    {"name": "Subject", "value": "Teste"},
                    {"name": "Message-ID", "value": "<msg@example.com>"},
                ],
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": encoded}},
                    {
                        "filename": "nota.pdf",
                        "mimeType": "application/pdf",
                        "body": {"size": 12, "attachmentId": "att-1"},
                    },
                ],
            },
        }

        result = self.tool.get_message("msg-1")

        self.assertEqual(result["body"], "Olá")
        self.assertFalse(result["is_read"])
        self.assertEqual(result["attachments"][0]["filename"], "nota.pdf")
        self.assertEqual(result["rfc822_message_id"], "<msg@example.com>")

    def test_list_marks_read_and_reply(self):
        self.messages.list.return_value.execute.return_value = {
            "messages": [{"id": "msg-1"}],
            "nextPageToken": "next-1",
        }
        self.messages.get.return_value.execute.return_value = {
            "id": "msg-1",
            "threadId": "thread-1",
            "labelIds": ["INBOX"],
            "payload": {"headers": [
                {"name": "From", "value": "ana@example.com"},
                {"name": "Subject", "value": "Olá"},
                {"name": "Message-ID", "value": "<msg@example.com>"},
            ]},
        }
        self.messages.modify.return_value.execute.return_value = {}
        self.messages.send.return_value.execute.return_value = {"id": "reply-1"}

        listed = self.tool.list_messages(query="is:unread")
        marked = self.tool.mark_as_read("msg-1")
        replied = self.tool.reply("msg-1", "Resposta")

        self.assertEqual(listed["next_page_token"], "next-1")
        self.assertTrue(marked["is_read"])
        self.assertEqual(replied["message_id"], "reply-1")
        self.assertEqual(self.messages.modify.call_args.kwargs["body"], {"removeLabelIds": ["UNREAD"]})


class EmailParserTests(unittest.TestCase):
    def test_email_operations_and_existing_messages(self):
        parser = IntentParser()
        self.assertEqual(
            parser.parse("enviar email para ana@example.com, assunto: Oi, corpo: Tudo bem?"),
            {"intent": "email", "payload": {"operation": "send", "to": "ana@example.com", "subject": "Oi", "body": "Tudo bem?"}},
        )
        self.assertEqual(
            parser.parse("listar emails não lidos"),
            {"intent": "email", "payload": {"operation": "list", "query": "is:unread"}},
        )
        self.assertEqual(
            parser.parse("enviar mensagem para maria: oi"),
            {"intent": "message", "payload": {"target": "maria", "text": "oi"}},
        )

    def test_monitoring_state_defaults_off_and_can_toggle(self):
        set_monitoring_enabled(False)
        self.assertFalse(is_monitoring_enabled())
        self.assertTrue(set_monitoring_enabled(True))
        self.assertTrue(is_monitoring_enabled())
        set_monitoring_enabled(False)


if __name__ == "__main__":
    unittest.main()
