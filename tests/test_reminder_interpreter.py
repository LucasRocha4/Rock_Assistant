from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock

from rock_assistant.core.reminder_interpreter import ReminderInterpreter
from rock_assistant.tools.reminders import SQLiteReminderStorage, create_reminder


REFERENCE = datetime.fromisoformat("2026-09-10T09:00:00-03:00")


class ReminderInterpreterTests(unittest.TestCase):
    def test_calendar_event_is_normalized_with_short_text_and_importance(self):
        draft = ReminderInterpreter().interpret(
            {"text": "pagar a conta importante", "when": "amanhã às 20h30"},
            now=REFERENCE,
        )

        self.assertEqual(draft.kind, "calendar_event")
        self.assertEqual(draft.importance, "high")
        self.assertEqual(draft.short_text, "pagar a conta importante")
        self.assertEqual(draft.scheduled_at, "2026-09-11T20:30:00-03:00")
        self.assertFalse(draft.needs_confirmation)


    def test_message_for_user_does_not_become_calendar_event(self):
        draft = ReminderInterpreter().interpret(
            {"text": "me entregue esta mensagem urgente", "when": "amanhã"},
            now=REFERENCE,
        )

        self.assertEqual(draft.kind, "self_message")
        self.assertEqual(draft.importance, "urgent")
        self.assertTrue(draft.all_day)


    def test_calendar_event_without_date_requires_confirmation(self):
        draft = ReminderInterpreter().interpret(
            {"text": "revisar o relatório", "when": None},
            now=REFERENCE,
        )

        self.assertTrue(draft.needs_confirmation)
        self.assertIn("data", draft.confirmation_reason)


    def test_self_message_is_persisted_without_google_sync(self):
        with TemporaryDirectory() as directory:
            storage = SQLiteReminderStorage(Path(directory) / "reminders.db")
            adapter = MagicMock()
            draft = ReminderInterpreter().interpret(
                {"text": "me entregar a mensagem", "when": None},
                now=REFERENCE,
            )
            result = create_reminder(
                draft.short_text,
                draft.when,
                storage=storage,
                google_adapter=adapter,
                draft=draft,
            )

            self.assertEqual(result["status"], "created_local")
            self.assertEqual(result["kind"], "self_message")
            adapter.is_configured.assert_not_called()
            self.assertEqual(storage.list_reminders()[0]["delivery_status"], "pending")


if __name__ == "__main__":
    unittest.main()
