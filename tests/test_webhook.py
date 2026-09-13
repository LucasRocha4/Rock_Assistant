import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
import requests

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from rock_assistant import api, config
from rock_assistant.tools import messaging


class EvolutionApiWebhookTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(api.app)
        self.original_api_url = config.EVOLUTION_API_URL
        self.original_api_key = config.EVOLUTION_API_KEY
        self.original_instance = config.EVOLUTION_INSTANCE

        config.EVOLUTION_API_URL = "http://localhost:8080"
        config.EVOLUTION_API_KEY = "test-api-key"
        config.EVOLUTION_INSTANCE = "SuporteBot"

    def tearDown(self):
        config.EVOLUTION_API_URL = self.original_api_url
        config.EVOLUTION_API_KEY = self.original_api_key
        config.EVOLUTION_INSTANCE = self.original_instance

    @staticmethod
    def _evolution_payload(text="Olá Rock", from_me=False, remote_jid="5511999999999@s.whatsapp.net", is_extended=False):
        message_dict = (
            {"extendedTextMessage": {"text": text}}
            if is_extended
            else {"conversation": text}
        )
        return {
            "event": "messages.upsert",
            "instance": "SuporteBot",
            "data": {
                "key": {
                    "remoteJid": remote_jid,
                    "fromMe": from_me,
                    "id": "BAE5XXXXX",
                },
                "pushName": "Usuário Teste",
                "messageType": "extendedTextMessage" if is_extended else "conversation",
                "message": message_dict,
            },
        }

    def test_text_message_is_processed_and_sent(self):
        payload = self._evolution_payload("Olá Rock")
        with patch.object(api, "_process_message") as process_message:
            response = self.client.post("/webhook", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "processed": 1})
        process_message.assert_called_once_with("5511999999999", "Olá Rock")

    def test_extended_text_message_is_processed(self):
        payload = self._evolution_payload("Resposta a mensagem", is_extended=True)
        with patch.object(api, "_process_message") as process_message:
            response = self.client.post("/webhook", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "processed": 1})
        process_message.assert_called_once_with("5511999999999", "Resposta a mensagem")

    def test_own_messages_from_me_are_ignored(self):
        payload = self._evolution_payload("Mensagem própria", from_me=True)
        with patch.object(api, "_process_message") as process_message:
            response = self.client.post("/webhook", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "ignored": "fromMe"})
        process_message.assert_not_called()

    def test_non_upsert_event_is_ignored(self):
        payload = {
            "event": "connection.update",
            "instance": "SuporteBot",
            "data": {"state": "open"},
        }
        with patch.object(api, "_process_message") as process_message:
            response = self.client.post("/webhook", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "ignored": "event_connection.update"})
        process_message.assert_not_called()

    def test_clean_phone_number_removes_jid_and_symbols(self):
        self.assertEqual(api._clean_phone_number("5511999999999@s.whatsapp.net"), "5511999999999")
        self.assertEqual(api._clean_phone_number("+55 (11) 99999-9999@s.whatsapp.net"), "5511999999999")
        self.assertEqual(api._clean_phone_number("5511999999999"), "5511999999999")
        self.assertEqual(api._clean_phone_number(""), "")

    def test_command_safety_block(self):
        with patch.object(api.conversation_manager, "receive") as receive:
            api._process_message("5511999999999", "exec rm -rf /")

        receive.assert_called_once_with("5511999999999", "exec rm -rf /")

    def test_invalid_json_returns_400(self):
        response = self.client.post(
            "/webhook",
            content="invalid-json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 400)


class EvolutionApiMessagingTests(unittest.TestCase):
    def setUp(self):
        self.original_api_url = config.EVOLUTION_API_URL
        self.original_api_key = config.EVOLUTION_API_KEY
        self.original_instance = config.EVOLUTION_INSTANCE

        config.EVOLUTION_API_URL = "http://localhost:8080"
        config.EVOLUTION_API_KEY = "test-api-key"
        config.EVOLUTION_INSTANCE = "SuporteBot"

    def tearDown(self):
        config.EVOLUTION_API_URL = self.original_api_url
        config.EVOLUTION_API_KEY = self.original_api_key
        config.EVOLUTION_INSTANCE = self.original_instance

    @patch("requests.post")
    def test_send_whatsapp_message_payload_and_headers(self, mock_post):
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {"status": "SUCCESS"}
        mock_post.return_value = mock_response

        res = messaging.send_whatsapp_message("5511999999999@s.whatsapp.net", "Olá Mundo")

        self.assertEqual(res, {"status": "SUCCESS"})
        mock_post.assert_called_once()
        url, kwargs = mock_post.call_args
        self.assertEqual(url[0], "http://localhost:8080/message/sendText/SuporteBot")
        self.assertEqual(kwargs["headers"]["apikey"], "test-api-key")
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")
        self.assertEqual(
            kwargs["json"],
            {
                "number": "5511999999999",
                "options": {
                    "delay": 1200,
                    "presence": "composing",
                },
                "text": "Olá Mundo",
            },
        )

    @patch("requests.post")
    def test_send_whatsapp_media_payload_and_headers(self, mock_post):
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {"status": "SUCCESS"}
        mock_post.return_value = mock_response

        res = messaging.send_whatsapp_media(
            recipient="5511999999999",
            media="https://example.com/image.png",
            mediatype="image",
            caption="Legenda do arquivo",
        )

        self.assertEqual(res, {"status": "SUCCESS"})
        mock_post.assert_called_once()
        url, kwargs = mock_post.call_args
        self.assertEqual(url[0], "http://localhost:8080/message/sendMedia/SuporteBot")
        self.assertEqual(kwargs["headers"]["apikey"], "test-api-key")
        self.assertEqual(
            kwargs["json"],
            {
                "number": "5511999999999",
                "options": {
                    "delay": 1200,
                    "presence": "composing",
                },
                "mediaMessage": {
                    "mediatype": "image",
                    "media": "https://example.com/image.png",
                    "caption": "Legenda do arquivo",
                },
            },
        )

    def test_send_whatsapp_missing_config_raises_error(self):
        config.EVOLUTION_API_KEY = ""
        with self.assertRaises(RuntimeError):
            messaging.send_whatsapp_message("5511999999999", "Teste")

    @patch("requests.post")
    def test_send_whatsapp_error_status(self, mock_post):
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 422
        mock_response.text = '{"message": "Number not found"}'
        mock_response.raise_for_status.side_effect = requests.HTTPError(response=mock_response)
        mock_post.return_value = mock_response

        with self.assertRaises(requests.HTTPError):
            messaging.send_whatsapp_message("5511999999999", "Teste")


if __name__ == "__main__":
    unittest.main()