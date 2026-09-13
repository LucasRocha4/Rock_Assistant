import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from rock_assistant.core.intent_parser import IntentParser
from rock_assistant.tools.conversation_goals import ConversationGoalStore
from rock_assistant.main import build_router


class MockSpecialist:
    def __init__(self, response):
        self.response = response

    def is_available(self):
        return True

    def chat(self, text, extra_system_prompt=None):
        return self.response


class WhatsAppMessageRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.goal_store = ConversationGoalStore(Path(self.temp_dir.name) / "goals.db")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parser_supports_natural_message_commands(self):
        parser = IntentParser()
        cases = [
            (
                "envia uma mensagem no whatsapp para +5511970799145 dando bom dia e se apresentando como Rock",
                {"target": "+5511970799145", "text": "dando bom dia e se apresentando como Rock"},
            ),
            ("fale com +5511970799145 dizendo bom dia", {"target": "+5511970799145", "text": "bom dia"}),
            ("avise fulano que a reunião mudou", {"target": "fulano", "text": "a reunião mudou"}),
            (
                "mande uma mensagem para o brother perguntando o que ele vai fazer hoje a noite",
                {"target": "brother", "text": "perguntando o que ele vai fazer hoje a noite"},
            ),
        ]

        for text, expected_payload in cases:
            with self.subTest(text=text):
                parsed = parser.parse(text)
                self.assertEqual(parsed["intent"], "message")
                self.assertEqual(parsed["payload"], expected_payload)

    @patch("rock_assistant.main.send_whatsapp_message")
    def test_message_route_sends_through_whatsapp(self, send_whatsapp):
        send_whatsapp.return_value = {"status": "SUCCESS"}
        router = build_router(goal_store=self.goal_store)

        result = router.route(
            "message",
            {"target": "+55 (11) 97079-9145", "text": "Bom dia"},
        )

        self.assertEqual(result, {"status": "SUCCESS"})
        send_whatsapp.assert_called_once_with("5511970799145", "Bom dia")

    @patch("rock_assistant.main.send_whatsapp_message")
    def test_message_body_is_composed_by_specialist(self, send_whatsapp):
        send_whatsapp.return_value = {"status": "SUCCESS"}
        specialist = MockSpecialist("Oi! O que você vai fazer hoje à noite?")
        router = build_router(goal_store=self.goal_store, specialist=specialist)

        router.route(
            "message",
            {
                "target": "brother",
                "text": "perguntando o que ele vai fazer hoje a noite",
            },
        )

        send_whatsapp.assert_called_once_with(
            "5511942689509", "Oi! O que você vai fazer hoje à noite?"
        )

    @patch("rock_assistant.main.send_whatsapp_message")
    def test_default_recipient_is_not_sent(self, send_whatsapp):
        result = build_router(goal_store=self.goal_store).route("message", {"target": "default", "text": "Bom dia"})

        self.assertEqual(result["status"], "needs_recipient")
        send_whatsapp.assert_not_called()

    @patch("rock_assistant.main.send_whatsapp_message")
    def test_event_goal_sends_initial_question_and_persists(self, send_whatsapp):
        send_whatsapp.return_value = {"status": "SUCCESS"}
        specialist = MockSpecialist("Onde será, que horas começa e o que precisamos levar?")
        router = build_router(goal_store=self.goal_store, specialist=specialist)

        result = router.route(
            "goal",
            {
                "target": "+5511942680509",
                "event_description": "o churrasco no sábado",
                "event_day": "no sábado",
                "owner_phone": "5511999999999",
            },
        )

        self.assertEqual(result["status"], "goal_started")
        self.assertEqual(result["state"], "waiting_contact")
        question = send_whatsapp.call_args.args[1].lower()
        self.assertIn("onde será", question)
        self.assertIn("que horas começa", question)
        self.assertIn("o que precisamos levar", question)

    @patch("rock_assistant.main.send_whatsapp_message")
    def test_event_goal_does_not_persist_when_delivery_fails(self, send_whatsapp):
        import requests

        send_whatsapp.side_effect = requests.HTTPError("Number not found")
        router = build_router(goal_store=self.goal_store)

        result = router.route(
            "goal",
            {
                "target": "+5511942680509",
                "event_description": "o churrasco no sábado",
                "event_day": "no sábado",
                "owner_phone": "5511999999999",
            },
        )

        self.assertEqual(result["status"], "goal_delivery_failed")


if __name__ == "__main__":
    unittest.main()