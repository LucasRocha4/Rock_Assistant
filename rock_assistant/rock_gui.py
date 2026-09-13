"""GUI Qt (PySide6) do Rock Assistant: janela com resposta do LLM, log, input e recados/lembretes."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
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
from tools.reminders import SQLiteReminderStorage


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
    result_ready = Signal(str)
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
            self.intent_parsed.emit(str(intent), payload)

            result = self.router.route(intent, payload)
            response_text = _normalize_response(result)
            self.memory.add_assistant_message(response_text)
            self.result_ready.emit(response_text)
        except Exception as exc:
            self.error_occurred.emit(f"{exc.__class__.__name__}: {exc}", traceback.format_exc())


class RockWindow(QMainWindow):
    """Janela principal: resposta do assistente, telemetria, input e recados/lembretes."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ROCK ASSISTANT")
        self.resize(1150, 720)

        self.parser = IntentParser()
        self.memory = ConversationMemory()
        self.router = build_router(memory=self.memory)
        self.reminder_storage = SQLiteReminderStorage()
        self._worker: Optional[PipelineWorker] = None

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
        header_layout.addWidget(QLabel("RECADOS, MENSAGENS E LEMBRETES"), 1)
        refresh_btn = QPushButton("Atualizar")
        refresh_btn.clicked.connect(self.refresh_reminders)
        header_layout.addWidget(refresh_btn)
        reminders_layout.addWidget(header_row)
        self.reminders_list = QListWidget(objectName="reminders")
        reminders_layout.addWidget(self.reminders_list, 1)
        right_splitter.addWidget(reminders_widget)

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
            #cmd_input { background-color: #000000; color: #ffffff; border: 2px solid #00e5ff; padding: 4px; }
            QPushButton { background-color: #000000; color: #39ff14; border: 1px solid #39ff14; padding: 3px 8px; }
            QPushButton:hover { background-color: #123312; }
            """
        )

    def _log(self, message: str) -> None:
        self.log_view.append(message)

    def _add_reminder_section(self, title: str, rows: List[Dict[str, Any]], empty_text: str) -> None:
        header = QListWidgetItem(f"— {title} —")
        header.setFlags(Qt.NoItemFlags)
        self.reminders_list.addItem(header)

        if not rows:
            placeholder = QListWidgetItem(empty_text)
            placeholder.setFlags(Qt.NoItemFlags)
            self.reminders_list.addItem(placeholder)
            return

        for row in rows:
            when = row.get("scheduled_at") or row.get("when_time") or "sem data"
            text = row.get("short_text") or row.get("message") or ""
            importance = row.get("importance", "normal")
            self.reminders_list.addItem(f"[{row.get('id')}] {text} · {when} · {importance}")

    def refresh_reminders(self) -> None:
        self.reminders_list.clear()
        reminders = [r for r in self.reminder_storage.list_reminders(limit=30) if r.get("kind") == "calendar_event"]
        recados = [r for r in self.reminder_storage.list_reminders(limit=30) if r.get("kind") == "self_message"]
        pendentes = self.reminder_storage.list_pending_messages(limit=30)

        self._add_reminder_section("Lembretes", reminders, "Nenhum lembrete cadastrado.")
        self._add_reminder_section("Recados", recados, "Nenhum recado cadastrado.")
        self._add_reminder_section("Mensagens pendentes de entrega", pendentes, "Nenhuma mensagem pendente.")

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
        self._log(f"Intent: {intent} | payload={payload}")

    def _on_result_ready(self, response_text: str) -> None:
        self._log("Ação concluída com sucesso.")
        self.output_view.setMarkdown(f"## Resposta\n{response_text}")
        self.refresh_reminders()

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
