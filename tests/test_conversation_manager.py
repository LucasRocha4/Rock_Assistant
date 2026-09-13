import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from rock_assistant.core.conversation_manager import ConversationManager, limit_conversation_text
from rock_assistant.tools.conversation_goals import ConversationGoalStore


class FakeSpecialist:
    def __init__(self):
        self.calls = []

    def chat(self, text, extra_system_prompt=None):
        self.calls.append((text, extra_system_prompt))
        return "Perguntei os detalhes que ainda faltavam."


class ConversationManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = ConversationGoalStore(Path(self.temp_dir.name) / "goals.db")
        self.parser = Mock()
        self.router = Mock()
        self.manager = ConversationManager(
            parser=self.parser,
            router=self.router,
            goal_store=self.store,
            silence_seconds=7,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_text_over_limit_discards_first_200_and_keeps_1000(self):
        text = "A" * 200 + "B" * 1000 + "C" * 100

        result = limit_conversation_text(text)

        self.assertEqual(len(result), 1000)
        self.assertTrue(result.startswith("B"))

    def test_messages_are_buffered_and_timer_is_reset(self):
        self.manager._process_after_silence = Mock()

        self.manager.receive("5511999999999", "primeira")
        first_timer = self.manager.states["5511999999999"].timer
        self.manager.receive("5511999999999", "segunda")
        second_timer = self.manager.states["5511999999999"].timer

        self.assertIsNot(first_timer, second_timer)
        self.manager._flush("5511999999999", self.manager.states["5511999999999"].generation)
        self.manager._process_after_silence.assert_called_once_with("5511999999999", "primeira\nsegunda")

    def test_typing_presence_pauses_and_resumes_timer(self):
        self.manager.receive("5511999999999", "aguardando")
        self.manager.set_typing("5511999999999", True)

        self.assertIsNone(self.manager.states["5511999999999"].timer)
        self.manager._process_after_silence = Mock()
        self.manager.set_typing("5511999999999", False)
        self.manager._flush("5511999999999", self.manager.states["5511999999999"].generation)

        self.manager._process_after_silence.assert_called_once_with("5511999999999", "aguardando")

    @patch("rock_assistant.core.conversation_manager.send_whatsapp_presence")
    @patch("rock_assistant.core.conversation_manager.send_whatsapp_message")
    def test_active_goal_uses_specialist_and_sends_generated_reply(self, send_message, send_presence):
        self.store.start_event_confirmation(
            owner_phone="5511999999999",
            target_phone="5511888888888",
            target_name="Contato",
            event_description="o churrasco no sábado",
            event_day="no sábado",
        )
        specialist = FakeSpecialist()
        manager = ConversationManager(
            parser=self.parser,
            router=self.router,
            goal_store=self.store,
            specialist_factory=lambda: specialist,
            silence_seconds=7,
        )

        manager._process_after_silence("5511888888888", "Vai ser às 14h e levarei bebidas")

        self.assertEqual(specialist.calls[0][0], "Vai ser às 14h e levarei bebidas")
        send_presence.assert_called_once_with("5511888888888", "composing", delay=7000)
        send_message.assert_called_once_with("5511888888888", "Perguntei os detalhes que ainda faltavam.")


if __name__ == "__main__":
    unittest.main()