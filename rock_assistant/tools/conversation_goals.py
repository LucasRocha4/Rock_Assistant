"""Persistencia e primeira etapa de objetivos conversacionais do Rock."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from rock_assistant.config import DB_PATH


class ConversationGoalStore:
    """Mantem um objetivo ativo por proprietario, separado do historico curto."""

    def __init__(self, db_path: Path | str = DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        with sqlite3.connect(str(self.db_path)) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_goals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_phone TEXT NOT NULL,
                    goal_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    target_phone TEXT NOT NULL,
                    target_name TEXT,
                    current_step TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )
            connection.commit()

    def start_event_confirmation(
        self,
        owner_phone: str,
        target_phone: str,
        target_name: str,
        event_description: str,
        event_day: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        context = {
            "event_description": event_description,
            "event_day": event_day,
            "needed_facts": ["what_to_bring", "location", "time"],
            "collected_facts": {},
        }
        with sqlite3.connect(str(self.db_path)) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.execute(
                """
                INSERT INTO conversation_goals (
                    owner_phone, goal_type, status, target_phone, target_name,
                    current_step, context_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    owner_phone,
                    "event_confirmation",
                    "waiting_contact",
                    target_phone,
                    target_name,
                    "collect_event_details",
                    json.dumps(context, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            goal_id = cursor.lastrowid
            connection.commit()
            row = connection.execute(
                "SELECT * FROM conversation_goals WHERE id = ?", (goal_id,)
            ).fetchone()
        return self._row_to_dict(row)

    def get_active(self, owner_phone: str) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(str(self.db_path)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT * FROM conversation_goals
                WHERE owner_phone = ? AND status IN ('active', 'waiting_contact', 'waiting_owner')
                ORDER BY id DESC LIMIT 1
                """,
                (owner_phone,),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_active_for_target(self, target_phone: str) -> Optional[Dict[str, Any]]:
        """Retorna a missão ativa que aguarda resposta do contato alvo."""
        with sqlite3.connect(str(self.db_path)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT * FROM conversation_goals
                WHERE target_phone = ? AND status IN ('active', 'waiting_contact')
                ORDER BY id DESC LIMIT 1
                """,
                (target_phone,),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def append_exchange(self, goal_id: int, sender: str, text: str) -> Dict[str, Any]:
        """Guarda uma fala no contexto do objetivo sem inferir fatos localmente."""
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(str(self.db_path)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM conversation_goals WHERE id = ?", (goal_id,)
            ).fetchone()
            if not row:
                raise ValueError(f"Objetivo inexistente: {goal_id}")
            context = json.loads(row["context_json"])
            transcript = context.setdefault("transcript", [])
            transcript.append({"sender": sender, "text": text, "at": now})
            context["transcript"] = transcript[-12:]
            connection.execute(
                "UPDATE conversation_goals SET context_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(context, ensure_ascii=False), now, goal_id),
            )
            connection.commit()
            updated = connection.execute(
                "SELECT * FROM conversation_goals WHERE id = ?", (goal_id,)
            ).fetchone()
        return self._row_to_dict(updated)

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        result = dict(row)
        result["context"] = json.loads(result.pop("context_json"))
        return result