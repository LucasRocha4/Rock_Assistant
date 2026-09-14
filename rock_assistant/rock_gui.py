"""GUI Qt (PySide6) do Rock Assistant: janela com resposta do LLM, log, input e recados/lembretes."""

from __future__ import annotations

import sys
import traceback
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.intent_parser import IntentParser
from core.memory import ConversationMemory
from main import build_router
from tools.conversation_goals import ConversationGoalStore
from tools.reminders import SQLiteReminderStorage
import config


def _normalize_response(result: Any) -> str:
    """Converte o retorno bruto do router (str | dict | outro) em texto exibível."""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return str(result.get("message", result))
    return str(result)


class PipelineWorker(QThread):
    """Executa parse + roteamento em background para não travar a janela."""

    intent_parsed = Signal(str, dict)
    result_ready = Signal(str, object)
    error_occurred = Signal(str, str)

    def __init__(
        self,
        parser: IntentParser,
        router: Any,
        memory: ConversationMemory,
        user_input: str,
    ) -> None:
        super().__init__()
        self.parser = parser
        self.router = router
        self.memory = memory
        self.user_input = user_input

    def run(self) -> None:
        try:
            self.memory.add_user_message(self.user_input)
            parsed = self.parser.parse_with_llm(self.user_input)
            intent = parsed.get("intent")
            payload = parsed.get("payload", {}) or {}
            if intent == "goal" and config.OWNER_PHONE:
                payload = {**payload, "owner_phone": config.OWNER_PHONE}
            self.intent_parsed.emit(str(intent), payload)

            result = self.router.route(intent, payload)
            response_text = _normalize_response(result)
            self.memory.add_assistant_message(response_text)
            self.result_ready.emit(response_text, result)
        except Exception as exc:
            self.error_occurred.emit(f"{exc.__class__.__name__}: {exc}", traceback.format_exc())


class ConversationWindow(QDialog):
    """Janela que acompanha ao vivo as mensagens enviadas e recebidas de uma conversa iniciada pelo Rock."""

    def __init__(self, goal_store: ConversationGoalStore, goal_id: int, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.goal_store = goal_store
        self.goal_id = goal_id
        self.setWindowTitle(title)
        self.resize(480, 520)

        layout = QVBoxLayout(self)
        self.transcript_view = QTextEdit(readOnly=True, objectName="transcript")
        layout.addWidget(self.transcript_view, 1)
        self.status_label = QLabel("Aguardando resposta...")
        layout.addWidget(self.status_label)
        self.setStyleSheet(
            """
            QDialog { background-color: #000000; }
            #transcript { background-color: #0a0a0a; color: #39ff14; border: 1px solid #00e5ff; }
            QLabel { color: #00e5ff; }
            """
        )

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(3000)
        self.refresh()

    def refresh(self) -> None:
        goal = self.goal_store.get_by_id(self.goal_id)
        if not goal:
            return

        transcript = goal.get("context", {}).get("transcript", [])
        lines = []
        for entry in transcript:
            label = "Rock (enviado)" if entry.get("sender") == "rock" else "Contato (recebido)"
            lines.append(f"**{label}** · {entry.get('at', '')}\n\n{entry.get('text', '')}\n")
        self.transcript_view.setMarkdown("\n---\n".join(lines) if lines else "_Nenhuma mensagem ainda._")

        status = goal.get("status", "desconhecido")
        self.status_label.setText(f"Status: {status}")
        if status == "completed":
            self._timer.stop()

    def closeEvent(self, event) -> None:
        self._timer.stop()
        super().closeEvent(event)


class RockWindow(QMainWindow):
    """Janela principal: resposta do assistente, telemetria, input e recados/lembretes."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ROCK ASSISTANT")
        self.resize(1150, 720)

        self.parser = IntentParser()
        self.memory = ConversationMemory()
        self.goal_store = ConversationGoalStore()
        self.router = build_router(memory=self.memory, goal_store=self.goal_store)
        self.reminder_storage = SQLiteReminderStorage()
        self._worker: Optional[PipelineWorker] = None
        self._last_payload: Dict[str, Any] = {}
        self._conversation_windows: Dict[int, ConversationWindow] = {}

        self._build_ui()
        self._apply_style()
        self._log("System Initialized.")
        self._log("Loading intent_parser.py...")
        self._log("Routing engine ready.")
        self.refresh_reminders()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)

        splitter = QSplitter(Qt.Horizontal)
        root_layout.addWidget(splitter, 1)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.addWidget(QLabel("RESPOSTA DO ASSISTENTE"))
        self.output_view = QTextEdit(readOnly=True, objectName="output")
        self.output_view.setMarkdown("# Rock Online\nAguardando comandos...")
        left_layout.addWidget(self.output_view, 1)

        self.input_line = QLineEdit(objectName="cmd_input")
        self.input_line.setPlaceholderText("> root@rock:~#")
        self.input_line.returnPressed.connect(self._on_submit)
        left_layout.addWidget(self.input_line)
        splitter.addWidget(left_widget)

        right_splitter = QSplitter(Qt.Vertical)

        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.addWidget(QLabel("TELEMETRIA & LOGS"))
        self.log_view = QTextEdit(readOnly=True, objectName="logs")
        log_layout.addWidget(self.log_view, 1)
        right_splitter.addWidget(log_widget)

        reminders_widget = QWidget()
        reminders_layout = QVBoxLayout(reminders_widget)
        header_row = QWidget()
        header_layout = QHBoxLayout(header_row)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addWidget(QLabel("LEMBRETES DE HOJE"), 1)
        refresh_btn = QPushButton("Atualizar")
        refresh_btn.clicked.connect(self.refresh_reminders)
        header_layout.addWidget(refresh_btn)
        reminders_layout.addWidget(header_row)
        self.reminders_list = QListWidget(objectName="reminders")
        reminders_layout.addWidget(self.reminders_list, 1)
        right_splitter.addWidget(reminders_widget)

        messages_widget = QWidget()
        messages_layout = QVBoxLayout(messages_widget)
        messages_layout.addWidget(QLabel("MENSAGENS NÃO LIDAS"))
        self.messages_list = QListWidget(objectName="messages")
        messages_layout.addWidget(self.messages_list, 1)
        right_splitter.addWidget(messages_widget)

        splitter.addWidget(right_splitter)
        splitter.setSizes([700, 450])

        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.close)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.log_view.clear)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background-color: #000000; color: #d0d0d0; }
            QLabel { color: #39ff14; font-weight: bold; }
            #output { background-color: #000000; color: #39ff14; border: 1px solid #00e5ff; }
            #logs { background-color: #0a0a0a; color: #00e5ff; border: 1px solid #39ff14; }
            #reminders { background-color: #0a0a0a; color: #d0d0d0; border: 1px solid #39ff14; }
            #messages { background-color: #0a0a0a; color: #d0d0d0; border: 1px solid #00e5ff; }
            #cmd_input { background-color: #000000; color: #ffffff; border: 2px solid #00e5ff; padding: 4px; }
            QPushButton { background-color: #000000; color: #39ff14; border: 1px solid #39ff14; padding: 3px 8px; }
            QPushButton:hover { background-color: #123312; }
            """
        )

    def _log(self, message: str) -> None:
        self.log_view.append(message)

    @staticmethod
    def _is_today(row: Dict[str, Any]) -> bool:
        raw = row.get("scheduled_at") or row.get("when_time")
        if not raw:
            return False
        try:
            return datetime.fromisoformat(str(raw)).date() == date.today()
        except ValueError:
            return False

    def _fill_list(self, list_widget: QListWidget, rows: List[Dict[str, Any]], empty_text: str) -> None:
        list_widget.clear()
        if not rows:
            placeholder = QListWidgetItem(empty_text)
            placeholder.setFlags(Qt.NoItemFlags)
            list_widget.addItem(placeholder)
            return

        for row in rows:
            when = row.get("scheduled_at") or row.get("when_time") or "sem data"
            text = row.get("short_text") or row.get("message") or ""
            importance = row.get("importance", "normal")
            list_widget.addItem(f"[{row.get('id')}] {text} · {when} · {importance}")

    def refresh_reminders(self) -> None:
        todays_reminders = [
            r for r in self.reminder_storage.list_reminders(limit=50)
            if r.get("kind") == "calendar_event" and self._is_today(r)
        ][:5]
        unread_messages = self.reminder_storage.list_pending_messages(limit=5)

        self._fill_list(self.reminders_list, todays_reminders, "Nenhum lembrete para hoje.")
        self._fill_list(self.messages_list, unread_messages, "Nenhuma mensagem não lida.")

    def _on_submit(self) -> None:
        user_input = self.input_line.text()
        if not user_input.strip():
            return

        self.input_line.clear()
        self.input_line.setEnabled(False)

        self._log(f"Input recebido: {user_input}")
        self._log("Classificando intent via parser...")
        self.output_view.setMarkdown(f"## Processando...\nExecutando ação para: `{user_input}`")

        self._worker = PipelineWorker(self.parser, self.router, self.memory, user_input)
        self._worker.intent_parsed.connect(self._on_intent_parsed)
        self._worker.result_ready.connect(self._on_result_ready)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.finished.connect(lambda: self.input_line.setEnabled(True))
        self._worker.start()

    def _on_intent_parsed(self, intent: str, payload: dict) -> None:
        self._last_payload = payload
        self._log(f"Intent: {intent} | payload={payload}")

    def _on_result_ready(self, response_text: str, result: Any) -> None:
        self._log("Ação concluída com sucesso.")
        self.output_view.setMarkdown(f"## Resposta\n{response_text}")
        self.refresh_reminders()
        if isinstance(result, dict) and result.get("status") == "goal_started":
            self.open_conversation_window(result["goal_id"], self._last_payload)

    def open_conversation_window(self, goal_id: int, payload: Dict[str, Any]) -> None:
        existing = self._conversation_windows.get(goal_id)
        if existing is not None:
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return

        target = payload.get("target") or "contato"
        title = f"Conversa com {target}"
        window = ConversationWindow(self.goal_store, goal_id, title, parent=self)
        window.finished.connect(lambda _: self._conversation_windows.pop(goal_id, None))
        self._conversation_windows[goal_id] = window
        window.show()

    def _on_error(self, error_text: str, tb: str) -> None:
        self._log(f"Erro: {error_text}")
        self._log(tb)
        self.output_view.setMarkdown(f"## Erro ao processar comando\n{error_text}")


def main() -> None:
    app = QApplication(sys.argv)
    window = RockWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
