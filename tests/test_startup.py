from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rock_assistant.core.reminder_interpreter import ReminderInterpreter
from rock_assistant.core.startup import StartupBriefing
from rock_assistant.tools.reminders import SQLiteReminderStorage


class StartupBriefingTests(unittest.TestCase):
    def test_urgent_alert_is_first_and_messages_can_be_delivered(self):
        with TemporaryDirectory() as directory:
            storage = SQLiteReminderStorage(Path(directory) / "reminders.db")
            draft = ReminderInterpreter().interpret(
                {"text": "ligar para o médico urgente", "kind": "self_message"},
                now=datetime.now().astimezone(),
            )
            storage.add_reminder(draft.short_text, draft.when, draft=draft)
            briefing = StartupBriefing(storage, greeting_picker=lambda greetings: greetings[0])

            opening = briefing.opening_lines()
            delivered = briefing.respond("quero ouvir")

            self.assertTrue(opening[0].startswith("Atenção:"))
            self.assertEqual(opening[2], "Você tem 1 mensagem pendente.")
            self.assertIn("Urgente:", delivered[1])
            self.assertEqual(storage.list_pending_messages(), [])

    def test_who_question_is_followed_by_confirmation_prompt(self):
        with TemporaryDirectory() as directory:
            storage = SQLiteReminderStorage(Path(directory) / "reminders.db")
            draft = ReminderInterpreter().interpret(
                {"text": "mensagem para mim", "kind": "self_message"},
            )
            storage.add_reminder(draft.short_text, draft.when, draft=draft)
            answers = iter(["de quem são?", "sim"])
            output = []
            briefing = StartupBriefing(storage, greeting_picker=lambda greetings: greetings[0])
            briefing.startup_text(input_func=lambda _: next(answers), output_func=output.append)

            self.assertTrue(any("não há remetente" in line for line in output))
            self.assertEqual(storage.list_pending_messages(), [])


if __name__ == "__main__":
    unittest.main()