import hashlib
import hmac
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from rock_assistant import api


class WhatsAppWebhookTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(api.app)
        self.original_verify_token = api.config.META_VERIFY_TOKEN
        self.original_app_secret = api.config.META_APP_SECRET
        api.config.META_VERIFY_TOKEN = "verify-token"
        api.config.META_APP_SECRET = "app-secret"

    def tearDown(self):
        api.config.META_VERIFY_TOKEN = self.original_verify_token
        api.config.META_APP_SECRET = self.original_app_secret

    @staticmethod
    def _payload(text="Olá Rock"):
        return {
            "object": "whatsapp_business_account",
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "5511999999999",
                            "type": "text",
                            "text": {"body": text},
                        }]
                    }
                }]
            }],
        }

    def _signed_request(self, payload):
        body = json.dumps(payload).encode()
        digest = hmac.new(b"app-secret", body, hashlib.sha256).hexdigest()
        return body, {"X-Hub-Signature-256": f"sha256={digest}"}

    def test_verification_returns_plain_challenge(self):
        response = self.client.get(
            "/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "verify-token",
                "hub.challenge": "challenge-value",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "challenge-value")

    def test_text_message_is_processed_and_sent(self):
        body, headers = self._signed_request(self._payload())
        with patch.object(api, "_process_message") as process_message:
            response = self.client.post("/webhook", content=body, headers=headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "accepted", "processed": 1})
        process_message.assert_called_once_with("5511999999999", "Olá Rock")

    def test_invalid_signature_is_rejected(self):
        body = json.dumps(self._payload()).encode()
        response = self.client.post(
            "/webhook",
            content=body,
            headers={"X-Hub-Signature-256": "sha256=invalid"},
        )
        self.assertEqual(response.status_code, 403)

    def test_status_event_is_accepted_without_processing(self):
        body, headers = self._signed_request(
            {"object": "whatsapp_business_account", "entry": []}
        )
        response = self.client.post(
            "/webhook",
            content=body,
            headers=headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "accepted", "processed": 0})

    def test_command_does_not_reach_router(self):
        with patch.object(api.router, "route") as route, patch.object(api, "send_whatsapp_message") as send:
            api._process_message("5511999999999", "exec rm -rf /")

        route.assert_not_called()
        send.assert_called_once()
        self.assertIn("não são executados", send.call_args.args[1])


if __name__ == "__main__":
    unittest.main()