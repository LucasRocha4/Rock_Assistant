import sqlite3
import tempfile
import unittest
from pathlib import Path

from rock_assistant.tools.contacts import add_contact, initialize_contacts_db, resolve_contact
from rock_assistant.core.intent_parser import IntentParser


class ContactTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "contacts.db"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_add_contact_persists_optional_fields_as_null(self):
        contact = add_contact("João", "+55 (11) 97079-9145", db_path=self.db_path)

        self.assertEqual(contact["contact_name"], "João")
        self.assertEqual(contact["contact_number"], "5511970799145")
        self.assertIsNone(contact["contact_description"])
        self.assertIsNone(contact["contact_email"])
        self.assertIsNone(contact["contact_call"])

    def test_empty_optional_fields_are_null_and_duplicates_are_allowed(self):
        first = add_contact(
            "João",
            "5511970799145",
            contact_description="amigo",
            contact_email="",
            contact_call="",
            db_path=self.db_path,
        )
        second = add_contact(
            "João",
            "5511970799145",
            db_path=self.db_path,
        )

        self.assertNotEqual(first["id"], second["id"])
        with sqlite3.connect(self.db_path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM contacts").fetchone()[0], 2)

    def test_initialize_is_idempotent(self):
        initialize_contacts_db(self.db_path)
        initialize_contacts_db(self.db_path)

        with sqlite3.connect(self.db_path) as connection:
            columns = [row[1] for row in connection.execute("PRAGMA table_info(contacts)")]
        self.assertIn("contact_call", columns)

    def test_invalid_contact_data_is_rejected(self):
        with self.assertRaises(ValueError):
            add_contact("João", "123", db_path=self.db_path)

    def test_resolve_contact_uses_contact_name_and_number(self):
        add_contact("João", "5511970799145", db_path=self.db_path)

        self.assertEqual(resolve_contact("joão", self.db_path), "5511970799145")

    def test_parser_extracts_contact_registration(self):
        parsed = IntentParser().parse(
            "cadastrar contato Valdier Rocha, número +5511942689509, chamada brother"
        )

        self.assertEqual(parsed["intent"], "contact")
        self.assertEqual(parsed["payload"]["contact_name"], "Valdier Rocha")
        self.assertEqual(parsed["payload"]["contact_number"], "+5511942689509")
        self.assertEqual(parsed["payload"]["contact_call"], "brother")


if __name__ == "__main__":
    unittest.main()