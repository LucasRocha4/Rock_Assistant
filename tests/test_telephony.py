"""Testes unitários e de integração para o módulo de telefonia Asterisk ARI."""

import unittest
from unittest.mock import MagicMock, patch

from rock_assistant.tools.contacting import ContactingTool
from telephony.core.call_handler import CallHandler
from telephony.core.pipeline import VoicePipeline, load_voice_system_prompt
from telephony.core.session import CallDirection, CallSession, CallState, SessionManager


class TestCallSession(unittest.TestCase):
    def test_session_lifecycle_and_history(self):
        session = CallSession(
            channel_id="channel-123",
            direction=CallDirection.INBOUND,
            caller_id="11999998888",
        )
        self.assertEqual(session.state, CallState.RINGING)
        self.assertTrue(session.is_active())

        session.add_user_message("Olá, tudo bem?")
        session.add_assistant_message("Olá! Aqui é o Rock. Como posso te ajudar?")

        history = session.get_dialogue_history()
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[1]["role"], "assistant")

        session.set_state(CallState.ENDED)
        self.assertFalse(session.is_active())
        self.assertIsNotNone(session.ended_at)

    def test_session_manager(self):
        manager = SessionManager()
        session = manager.create_session(
            channel_id="chan-001",
            direction=CallDirection.OUTBOUND,
            recipient="5511988887777",
            script="Avisar sobre a reunião",
        )
        self.assertIsNotNone(manager.get_session("chan-001"))
        self.assertEqual(len(manager.list_active_sessions()), 1)

        removed = manager.remove_session("chan-001")
        self.assertEqual(removed.channel_id, "chan-001")
        self.assertIsNone(manager.get_session("chan-001"))


class TestVoicePipeline(unittest.TestCase):
    def test_clean_text_for_speech(self):
        text = "Aqui está um link: https://google.com/ e **negrito** e `código` ```bloco```"
        cleaned = VoicePipeline.clean_text_for_speech(text)
        self.assertNotIn("https://", cleaned)
        self.assertNotIn("**", cleaned)
        self.assertNotIn("```", cleaned)

    def test_process_turn_with_mock_llm(self):
        mock_llm = MagicMock()
        mock_client = MagicMock()
        mock_client.chat.return_value = {
            "message": {"content": "Olá! Posso ajudar com a sua consulta médica."}
        }
        mock_llm._get_client.return_value = mock_client
        mock_llm.model = "llama3.2"

        pipeline = VoicePipeline(llm_agent=mock_llm)
        session = CallSession(channel_id="chan-test", direction=CallDirection.INBOUND)

        reply = pipeline.process_turn(session, "Preciso de ajuda com a consulta.")
        self.assertIn("consulta", reply)
        self.assertEqual(len(session.history), 2)


class TestCallHandler(unittest.TestCase):
    def setUp(self):
        self.session_manager = SessionManager()
        self.mock_pipeline = MagicMock()
        self.mock_pipeline.synthesize_audio_file.return_value = MagicMock(stem="audio123")
        self.handler = CallHandler(
            ari_url="http://localhost:8088/ari",
            username="rock",
            password="test_password",
            app_name="rock_agent",
            session_manager=self.session_manager,
            pipeline=self.mock_pipeline,
        )

    @patch("requests.post")
    def test_start_outbound_call_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "chan-out-99"}
        mock_post.return_value = mock_resp

        result = self.handler.start_outbound_call("5511999990000", script="Confirmar presença")
        self.assertEqual(result["status"], "originating")
        self.assertEqual(result["channel_id"], "chan-out-99")
        self.assertEqual(result["recipient"], "5511999990000")

        session = self.session_manager.get_session("chan-out-99")
        self.assertIsNotNone(session)
        self.assertEqual(session.script, "Confirmar presença")

    @patch("requests.post")
    def test_handle_incoming_call_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        result = self.handler.handle_incoming_call("chan-in-11", caller_id="5511888887777")
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["channel_id"], "chan-in-11")

    def test_stasis_events(self):
        start_event = {
            "channel": {"id": "chan-stasis-1", "caller": {"number": "1234"}},
            "args": ["inbound"],
        }
        self.handler.on_stasis_start(start_event)
        session = self.session_manager.get_session("chan-stasis-1")
        self.assertIsNotNone(session)
        self.assertEqual(session.state, CallState.IN_CALL)

        end_event = {"channel": {"id": "chan-stasis-1"}}
        self.handler.on_stasis_end(end_event)
        self.assertIsNone(self.session_manager.get_session("chan-stasis-1"))


class TestContactingToolTelephony(unittest.TestCase):
    @patch("telephony.core.call_handler.get_call_handler")
    @patch("rock_assistant.tools.contacts.resolve_contact")
    def test_make_call_contact_resolution(self, mock_resolve, mock_get_handler):
        mock_resolve.return_value = "5511999991234"
        mock_handler = MagicMock()
        mock_handler.start_outbound_call.return_value = {
            "status": "originating",
            "channel_id": "chan-123",
        }
        mock_get_handler.return_value = mock_handler

        tool = ContactingTool(gmail_tool=MagicMock())
        result = tool.make_call("Lucas", script="Assunto importante")

        mock_resolve.assert_called_once()
        mock_handler.start_outbound_call.assert_called_once_with(
            recipient="5511999991234", script="Assunto importante"
        )
        self.assertEqual(result["status"], "originating")

    @patch("telephony.core.call_handler.get_call_handler")
    def test_answer_call(self, mock_get_handler):
        mock_handler = MagicMock()
        mock_handler.handle_incoming_call.return_value = {
            "status": "answered",
            "channel_id": "chan-456",
        }
        mock_get_handler.return_value = mock_handler

        tool = ContactingTool(gmail_tool=MagicMock())
        result = tool.answer_call("chan-456")

        mock_handler.handle_incoming_call.assert_called_once_with(channel_id="chan-456")
        self.assertEqual(result["status"], "answered")


if __name__ == "__main__":
    unittest.main()
