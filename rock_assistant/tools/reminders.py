"""Ferramentas para agendamento de lembretes e tarefas recorrentes com SQLite e Google Calendar API."""

import sqlite3
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# Garante acesso a configurações do projeto
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

try:
    import config
    from config import DB_PATH, get_credentials_path, get_token_path
except ImportError:
    from rock_assistant import config
    from rock_assistant.config import DB_PATH, get_credentials_path, get_token_path


class GoogleCalendarAuthError(Exception):
    """Exceção levantada quando as credenciais do Google Calendar não estão disponíveis ou válidas."""
    pass


class SQLiteReminderStorage:
    """Gerencia a persistência local de lembretes no banco de dados SQLite."""

    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        if db_path is None:
            self.db_path = Path(DB_PATH)
        else:
            self.db_path = Path(db_path)

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Cria as tabelas necessárias se não existirem."""
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message TEXT NOT NULL,
                    when_time TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    synced_google INTEGER DEFAULT 0,
                    google_event_id TEXT
                )
                """
            )
            conn.commit()

    def add_reminder(
        self,
        message: str,
        when_time: Optional[str] = None,
        google_event_id: Optional[str] = None,
        synced_google: bool = False,
    ) -> Dict[str, Any]:
        """Insere um novo lembrete no banco de dados local."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO reminders (message, when_time, synced_google, google_event_id)
                VALUES (?, ?, ?, ?)
                """,
                (message, when_time, 1 if synced_google else 0, google_event_id),
            )
            conn.commit()
            reminder_id = cursor.lastrowid
            cursor.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,))
            row = cursor.fetchone()
            return dict(row) if row else {"id": reminder_id, "message": message, "when_time": when_time}

    def list_reminders(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retorna os lembretes mais recentes do banco SQLite."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM reminders ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def mark_synced(self, reminder_id: int, google_event_id: str) -> bool:
        """Atualiza o registro de um lembrete indicando sincronização com o Google Calendar."""
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE reminders
                SET synced_google = 1, google_event_id = ?
                WHERE id = ?
                """,
                (google_event_id, reminder_id),
            )
            conn.commit()
            return cursor.rowcount > 0


class GoogleCalendarAdapter:
    """Adaptador modular para sincronização com a API do Google Calendar / Tasks."""

    SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

    def __init__(
        self,
        credentials_file: Optional[Path | str] = None,
        token_file: Optional[Path | str] = None,
    ) -> None:
        self.credentials_file = Path(credentials_file) if credentials_file else get_credentials_path()
        self.token_file = Path(token_file) if token_file else get_token_path()

    def is_configured(self) -> bool:
        """Verifica se os arquivos de credenciais OAuth2 estão presentes localmente."""
        return self.credentials_file.exists() or self.token_file.exists()

    def get_credentials(self) -> Any:
        """Obtém credenciais válidas do Google OAuth2.

        Lança GoogleCalendarAuthError caso as credenciais não estejam configuradas.
        """
        creds = None

        if self.token_file.exists():
            try:
                from google.oauth2.credentials import Credentials
                creds = Credentials.from_authorized_user_file(str(self.token_file), self.SCOPES)
            except Exception:
                creds = None

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    from google.auth.transport.requests import Request
                    creds.refresh(Request())
                    with open(self.token_file, "w", encoding="utf-8") as token_out:
                        token_out.write(creds.to_json())
                except Exception:
                    creds = None

            if not creds:
                if not self.credentials_file.exists():
                    raise GoogleCalendarAuthError(
                        f"Arquivos de credenciais do Google Calendar não encontrados "
                        f"('{self.credentials_file.name}' ou '{self.token_file.name}'). "
                        f"Para sincronizar com o Google Calendar, configure os arquivos "
                        f"OAuth2 'credentials.json' ou 'token.json' no diretório do projeto."
                    )
                try:
                    from google_auth_oauthlib.flow import InstalledAppFlow
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(self.credentials_file), self.SCOPES
                    )
                    creds = flow.run_local_server(port=0)
                    with open(self.token_file, "w", encoding="utf-8") as token_out:
                        token_out.write(creds.to_json())
                except Exception as exc:
                    raise GoogleCalendarAuthError(
                        f"Falha na autenticação OAuth2 do Google Calendar: {exc}"
                    )

        return creds

    @staticmethod
    def _parse_when(when: Optional[str]) -> tuple[Optional[datetime], bool]:
        """Converte expressões simples do parser em data/hora do Calendar."""
        value = (when or "").strip().lower()
        now = datetime.now().astimezone()

        midday_match = re.search(r"(?:ao\s+)?meio[- ]dia", value)
        midnight_match = re.search(r"(?:à|a|pela)?\s*meia[- ]noite", value)
        time_match = re.search(r"(?:às|as|ás|at)\s+(\d{1,2})(?::|h)?(\d{2})?", value)
        if midday_match:
            hour, minute = 12, 0
        elif midnight_match:
            hour, minute = 0, 0
        else:
            hour = int(time_match.group(1)) if time_match else None
            minute = int(time_match.group(2) or 0) if time_match else 0

        if "depois de amanhã" in value or "depois de amanha" in value:
            event_date = now.date() + timedelta(days=2)
        elif "amanhã" in value or "amanha" in value:
            event_date = now.date() + timedelta(days=1)
        elif "hoje" in value:
            event_date = now.date()
        else:
            date_match = re.search(r"(?:dia|data|no dia)\s+(\d{1,2})(?:/(\d{1,2})(?:/(\d{2,4}))?)?", value)
            if not date_match:
                return None, False
            day = int(date_match.group(1))
            month = int(date_match.group(2) or now.month)
            year_text = date_match.group(3)
            year = int(year_text) if year_text else now.year
            if year < 100:
                year += 2000
            try:
                event_date = datetime(year, month, day).date()
            except ValueError:
                return None, False

        if hour is None:
            return datetime.combine(event_date, datetime.min.time(), tzinfo=now.tzinfo), True
        if hour > 23 or minute > 59:
            return None, False
        return datetime.combine(event_date, datetime.min.time(), tzinfo=now.tzinfo).replace(
            hour=hour,
            minute=minute,
        ), False

    def sync_event(self, message: str, when: Optional[str] = None) -> Dict[str, Any]:
        """Cria um evento no Google Calendar."""
        creds = self.get_credentials()
        from googleapiclient.discovery import build
        service = build("calendar", "v3", credentials=creds)

        scheduled_at, all_day = self._parse_when(when)
        if scheduled_at is None:
            scheduled_at = datetime.now().astimezone()

        event_body = {
            "summary": f"[Rock] {message}",
            "description": f"Lembrete agendado pelo Rock Assistant: {message}\nHorário informado: {when or 'Não especificado'}",
        }
        if all_day:
            event_body["start"] = {"date": scheduled_at.date().isoformat()}
            event_body["end"] = {"date": (scheduled_at.date() + timedelta(days=1)).isoformat()}
        else:
            event_body["start"] = {"dateTime": scheduled_at.isoformat()}
            event_body["end"] = {"dateTime": (scheduled_at + timedelta(minutes=30)).isoformat()}

        created_event = service.events().insert(calendarId="primary", body=event_body).execute()
        return {
            "event_id": created_event.get("id"),
            "html_link": created_event.get("htmlLink"),
            "status": "synced",
        }


def create_reminder(
    message: str,
    when: Optional[str] = None,
    db_path: Optional[Path | str] = None,
    storage: Optional[SQLiteReminderStorage] = None,
    google_adapter: Optional[GoogleCalendarAdapter] = None,
) -> Dict[str, Any]:
    """Cria um lembrete no SQLite local e tenta sincronizar com o Google Calendar.

    Se as credenciais do Google Calendar não estiverem presentes localmente,
    o lembrete é registrado com sucesso no banco SQLite local e a resposta
    indica que as credenciais do Google precisam ser configuradas.
    """
    cleaned_message = (message or "").strip()
    if not cleaned_message:
        return {
            "status": "error",
            "message": "Descrição do lembrete não pode estar vazia.",
        }

    storage = storage or SQLiteReminderStorage(db_path)
    google_adapter = google_adapter or GoogleCalendarAdapter()

    # 1. Salva no SQLite local
    record = storage.add_reminder(message=cleaned_message, when_time=when)
    reminder_id = record["id"]

    # 2. Tenta sincronização com Google Calendar
    google_sync_result: Dict[str, Any] = {
        "synced": False,
        "event_id": None,
        "info": None,
    }

    try:
        if not google_adapter.is_configured():
            google_sync_result["info"] = (
                "Lembrete persistido no SQLite local (data/rock.db). "
                "Para sincronização em nuvem, forneça 'credentials.json' ou 'token.json' do Google Calendar."
            )
        else:
            sync_res = google_adapter.sync_event(message=cleaned_message, when=when)
            event_id = sync_res.get("event_id")
            storage.mark_synced(reminder_id, event_id)
            google_sync_result["synced"] = True
            google_sync_result["event_id"] = event_id
            google_sync_result["html_link"] = sync_res.get("html_link")
            google_sync_result["info"] = "Sincronizado com sucesso com o Google Calendar."

    except GoogleCalendarAuthError as auth_err:
        google_sync_result["info"] = str(auth_err)
    except Exception as exc:
        google_sync_result["info"] = f"Aviso: Não foi possível sincronizar com Google Calendar: {exc}"

    return {
        "status": "created_synced" if google_sync_result["synced"] else "created_local",
        "id": reminder_id,
        "message": record["message"],
        "when": record.get("when_time"),
        "created_at": record.get("created_at"),
        "storage": "sqlite",
        "db_path": str(storage.db_path),
        "google_sync": google_sync_result,
    }


def list_reminders(limit: int = 50, db_path: Optional[Path | str] = None) -> List[Dict[str, Any]]:
    """Lista os lembretes cadastrados no banco de dados SQLite."""
    storage = SQLiteReminderStorage(db_path)
    return storage.list_reminders(limit=limit)


class ReminderTool:
    """Wrapper orientado a objetos para gestão e agendamento de lembretes."""

    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        self.name = "reminder"
        self.storage = SQLiteReminderStorage(db_path)
        self.google_adapter = GoogleCalendarAdapter()

    def create(self, message: str, when: Optional[str] = None) -> Dict[str, Any]:
        """Cria um novo lembrete persistindo no SQLite e tentando sincronização."""
        return create_reminder(
            message=message,
            when=when,
            storage=self.storage,
            google_adapter=self.google_adapter,
        )

    def list(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Lista os lembretes armazenados."""
        return self.storage.list_reminders(limit=limit)

