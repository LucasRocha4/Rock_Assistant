"""Resolucao local de destinatarios para mensagens WhatsApp."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

from rock_assistant.config import DB_PATH


def normalize_phone(value: str) -> str:
    """Retorna somente os digitos de um telefone ou JID."""
    if "@" in value:
        value = value.split("@", 1)[0]
    return re.sub(r"\D", "", value)


def is_phone_number(value: str) -> bool:
    """Aceita numeros internacionais com quantidade plausivel de digitos."""
    return len(normalize_phone(value)) >= 10


def initialize_contacts_db(db_path: Path | str = DB_PATH) -> None:
    """Cria a tabela de contatos sem alterar registros existentes."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(path)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contact_name TEXT NOT NULL,
                contact_number TEXT NOT NULL,
                contact_description TEXT NULL,
                contact_email TEXT NULL,
                contact_call TEXT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.commit()


def add_contact(
    contact_name: str,
    contact_number: str,
    contact_description: Optional[str] = None,
    contact_email: Optional[str] = None,
    contact_call: Optional[str] = None,
    db_path: Path | str = DB_PATH,
) -> Dict[str, Any]:
    """Adiciona um contato; campos informativos vazios são gravados como NULL."""
    name = (contact_name or "").strip()
    number = normalize_phone(contact_number or "")
    if not name:
        raise ValueError("Nome do contato é obrigatório")
    if not is_phone_number(number):
        raise ValueError("Número do contato é inválido")

    initialize_contacts_db(db_path)
    optional_values = [
        value.strip() if isinstance(value, str) and value.strip() else None
        for value in (contact_description, contact_email, contact_call)
    ]
    with sqlite3.connect(str(db_path)) as connection:
        connection.row_factory = sqlite3.Row
        cursor = connection.execute(
            """
            INSERT INTO contacts (
                contact_name, contact_number, contact_description,
                contact_email, contact_call
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (name, number, *optional_values),
        )
        contact_id = cursor.lastrowid
        connection.commit()
        row = connection.execute(
            "SELECT * FROM contacts WHERE id = ?", (contact_id,)
        ).fetchone()
    return dict(row)


def resolve_contact(name: str, db_path: Path) -> Optional[str]:
    """Procura um contato por nome ou forma alternativa de chamada."""
    if not name.strip() or not db_path.exists():
        return None

    try:
        with sqlite3.connect(str(db_path)) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            table_name = next((table for table in ("contacts", "contact") if table in tables), None)
            if not table_name:
                return None

            columns = {
                row[1]
                for row in connection.execute(f'PRAGMA table_info("{table_name}")')
            }
            name_column = next(
                (column for column in ("name", "nome", "contact_name") if column in columns),
                None,
            )
            phone_column = next(
                (
                    column
                    for column in (
                        "phone",
                        "telefone",
                        "number",
                        "phone_number",
                        "contact_number",
                    )
                    if column in columns
                ),
                None,
            )
            if not name_column or not phone_column:
                return None

            call_column = "contact_call" if "contact_call" in columns else None
            selected_columns = [f'"{phone_column}"', f'"{name_column}"']
            if call_column:
                selected_columns.append(f'"{call_column}"')
            rows = connection.execute(
                f'SELECT {", ".join(selected_columns)} FROM "{table_name}"'
            ).fetchall()
            query = name.strip().casefold()
            matches = []
            for row in rows:
                aliases = [str(row[1]).casefold()]
                if call_column and row[2]:
                    aliases.extend(
                        alias.strip().casefold()
                        for alias in re.split(r"[,;|]", str(row[2]))
                        if alias.strip()
                    )
                if query in aliases:
                    matches.append(row[0])
            if len(matches) != 1 or not matches[0]:
                return None
            phone = normalize_phone(str(matches[0]))
            return phone if is_phone_number(phone) else None
    except sqlite3.Error:
        return None