"""GUI Qt (PySide6) do Rock Assistant com Splash de Warmup do Llama, Fallback CPU e Telemetria."""

from __future__ import annotations

import argparse
import html
import logging
import os
import sys
import traceback
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.intent_parser import IntentParser
from core.local_llm import LocalLLMAgent, WarmupResult, is_gpu_error
from core.memory import ConversationMemory
from main import build_router
from setup import config
from setup.logger_config import LogEmitter, setup_logging
from tools.conversation_goals import ConversationGoalStore
from tools.reminders import SQLiteReminderStorage

logger = logging.getLogger("rock.gui")


def _normalize_response(result: Any) -> str:
    """Converte o retorno bruto do router (str | dict | outro) em texto exibível."""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return str(result.get("message", result))
    return str(result)


class QtLogBridge(QObject):
    """Ponte thread-safe entre o logging do Python e os widgets do PySide6."""

    log_received = Signal(str, str, str, str)  # timestamp, level, logger_name, message

    def emit_log(self, record: logging.LogRecord, formatted: str) -> None:
        dt_str = datetime.fromtimestamp(record.created).strftime("%H:%M:%S.%f")[:-3]
        self.log_received.emit(dt_str, record.levelname, record.name, record.getMessage())


class ProjectLogWindow(QMainWindow):
    """Janela dedicada para monitoramento de telemetria e logs em tempo real de todo o projeto."""

    LEVEL_COLORS = {
        "DEBUG": "#7f8c8d",
        "INFO": "#00e5ff",
        "WARNING": "#ffb86c",
        "ERROR": "#ff5555",
        "CRITICAL": "#ff007f",
    }

    def __init__(self, bridge: QtLogBridge, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.bridge = bridge
        self._all_records: List[tuple[str, str, str, str]] = []
        self._auto_scroll = True

        self.setWindowTitle("ROCK ASSISTANT - TELEMETRIA & LOGS DO PROJETO")
        self.resize(950, 650)
        self._build_ui()
        self._apply_style()

        self.bridge.log_received.connect(self._on_new_log)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Barra de Controles e Filtros
        toolbar = QHBoxLayout()

        toolbar.addWidget(QLabel("Nível:"))
        self.level_filter = QComboBox()
        self.level_filter.addItems(["TODOS", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self.level_filter.setCurrentIndex(0)
        self.level_filter.currentTextChanged.connect(self._apply_filters)
        toolbar.addWidget(self.level_filter)

        toolbar.addWidget(QLabel("Filtro:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filtrar por texto, módulo...")
        self.search_input.textChanged.connect(self._apply_filters)
        toolbar.addWidget(self.search_input, 1)

        self.autoscroll_chk = QCheckBox("Auto-scroll")
        self.autoscroll_chk.setChecked(True)
        self.autoscroll_chk.toggled.connect(self._toggle_autoscroll)
        toolbar.addWidget(self.autoscroll_chk)

        clear_btn = QPushButton("Limpar")
        clear_btn.clicked.connect(self._clear_logs)
        toolbar.addWidget(clear_btn)

        save_btn = QPushButton("Salvar Log")
        save_btn.clicked.connect(self._save_logs_to_file)
        toolbar.addWidget(save_btn)

        layout.addLayout(toolbar)

        # Área de Visualização de Logs
        self.log_text_view = QTextEdit(readOnly=True, objectName="project_log_view")
        self.log_text_view.setFont(QFont("Monospace", 9))
        layout.addWidget(self.log_text_view, 1)

        # Rodapé com estatísticas
        status_bar = QHBoxLayout()
        self.status_label = QLabel("Total: 0 logs | Exibindo: 0")
        status_bar.addWidget(self.status_label)
        layout.addLayout(status_bar)

        QShortcut(QKeySequence("Ctrl+L"), self, activated=self._clear_logs)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self._save_logs_to_file)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background-color: #0b0c10; color: #c5c6c7; font-family: monospace; }
            QLabel { color: #66fcf1; font-weight: bold; }
            QLineEdit, QComboBox { background-color: #1f2833; color: #ffffff; border: 1px solid #45a29e; padding: 4px; border-radius: 2px; }
            #project_log_view { background-color: #050608; color: #00e5ff; border: 1px solid #45a29e; }
            QPushButton { background-color: #1f2833; color: #66fcf1; border: 1px solid #66fcf1; padding: 4px 10px; font-weight: bold; border-radius: 2px; }
            QPushButton:hover { background-color: #45a29e; color: #0b0c10; }
            QCheckBox { color: #66fcf1; }
            QCheckBox::indicator { width: 14px; height: 14px; }
            """
        )

    def _toggle_autoscroll(self, checked: bool) -> None:
        self._auto_scroll = checked

    def _clear_logs(self) -> None:
        self._all_records.clear()
        self.log_text_view.clear()
        self._update_status(0, 0)

    def _save_logs_to_file(self) -> None:
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar logs do projeto",
            str(Path.home() / "rock_project_logs.txt"),
            "Arquivos de Texto (*.txt *.log)",
        )
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    for ts, lvl, name, msg in self._all_records:
                        f.write(f"[{ts}] [{lvl:5s}] [{name}] {msg}\n")
                logger.info("Logs salvos com sucesso em: %s", file_path)
            except Exception as exc:
                logger.error("Erro ao salvar logs em arquivo: %s", exc)

    def _matches_filter(self, ts: str, level: str, name: str, msg: str) -> bool:
        selected_level = self.level_filter.currentText()
        if selected_level != "TODOS" and level.upper() != selected_level:
            return False

        search_query = self.search_input.text().strip().lower()
        if search_query:
            combined = f"{ts} {level} {name} {msg}".lower()
            if search_query not in combined:
                return False

        return True

    def _format_record_html(self, ts: str, level: str, name: str, msg: str) -> str:
        color = self.LEVEL_COLORS.get(level.upper(), "#ffffff")
        esc_ts = html.escape(ts)
        esc_lvl = html.escape(f"{level:5s}")
        esc_name = html.escape(name)
        esc_msg = html.escape(msg)
        return (
            f'<div style="margin-bottom: 2px; line-height: 1.25;">'
            f'<span style="color: #6272a4;">[{esc_ts}]</span> '
            f'<span style="color: {color}; font-weight: bold;">[{esc_lvl}]</span> '
            f'<span style="color: #bd93f9;">[{esc_name}]</span> '
            f'<span style="color: #f8f8f2;">{esc_msg}</span>'
            f'</div>'
        )

    def _on_new_log(self, ts: str, level: str, name: str, msg: str) -> None:
        record = (ts, level, name, msg)
        self._all_records.append(record)

        if self._matches_filter(ts, level, name, msg):
            html_line = self._format_record_html(ts, level, name, msg)
            cursor = self.log_text_view.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.insertHtml(html_line)
            if self._auto_scroll:
                self.log_text_view.ensureCursorVisible()

        self._update_status(len(self._all_records), None)

    def _apply_filters(self) -> None:
        self.log_text_view.clear()
        visible_count = 0
        html_buffer = []

        for ts, lvl, name, msg in self._all_records:
            if self._matches_filter(ts, lvl, name, msg):
                visible_count += 1
                html_buffer.append(self._format_record_html(ts, lvl, name, msg))

        if html_buffer:
            self.log_text_view.setHtml("".join(html_buffer))
            if self._auto_scroll:
                self.log_text_view.ensureCursorVisible()

        self._update_status(len(self._all_records), visible_count)

    def _update_status(self, total: int, visible: Optional[int]) -> None:
        vis = visible if visible is not None else total
        self.status_label.setText(f"Total: {total} logs | Exibindo: {vis}")


class WarmupWorker(QThread):
    """Executa o processo de pré-aquecimento e validação do Llama em background."""

    progress = Signal(str)
    log_line = Signal(str)
    finished = Signal(object)  # WarmupResult

    def __init__(self, llm_agent: LocalLLMAgent, force_cpu: bool = False) -> None:
        super().__init__()
        self.llm_agent = llm_agent
        self.force_cpu = force_cpu

    def run(self) -> None:
        def on_step(msg: str) -> None:
            self.progress.emit(msg)
            self.log_line.emit(msg)

        if self.force_cpu:
            self.progress.emit("Reiniciando servidor Ollama com OLLAMA_NUM_GPU=0...")
            self.llm_agent.restart_ollama(force_cpu=True)

        result = self.llm_agent.warmup(
            force_cpu=self.force_cpu,
            progress_callback=on_step,
        )
        self.finished.emit(result)


class WarmupSplash(QDialog):
    """Tela de splash/carregamento exibida durante o pré-aquecimento do Llama."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ROCK ASSISTANT - INICIALIZANDO")
        self.setFixedSize(560, 380)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Dialog)

        self._build_ui()
        self._apply_style()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        # Cabeçalho Cyberpunk
        title_label = QLabel("ROCK ASSISTANT")
        title_label.setObjectName("splash_title")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        sub_label = QLabel("Inicializando subsistemas de Inteligência Artificial...")
        sub_label.setObjectName("splash_subtitle")
        sub_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(sub_label)

        layout.addSpacing(8)

        # Status Label
        self.status_label = QLabel("Verificando servidor Ollama...")
        self.status_label.setObjectName("splash_status")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        # Barra de Progresso
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("splash_progress")
        self.progress_bar.setRange(0, 0)  # Indeterminada
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        # Mini Console de Log do Warmup
        self.log_view = QTextEdit(readOnly=True, objectName="splash_log")
        self.log_view.setFont(QFont("Monospace", 8))
        layout.addWidget(self.log_view, 1)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QDialog { background-color: #0b0c10; border: 2px solid #00e5ff; }
            #splash_title { color: #39ff14; font-size: 22px; font-weight: bold; letter-spacing: 2px; }
            #splash_subtitle { color: #00e5ff; font-size: 11px; }
            #splash_status { color: #ffffff; font-size: 12px; font-weight: bold; }
            #splash_progress { background-color: #1f2833; border: 1px solid #45a29e; height: 8px; }
            #splash_progress::chunk { background-color: #39ff14; }
            #splash_log { background-color: #050608; color: #66fcf1; border: 1px solid #1f2833; padding: 4px; }
            """
        )

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def append_log(self, text: str) -> None:
        self.log_view.append(f"> {text}")


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
            logger.info("PipelineWorker recebeu comando: '%s'", self.user_input)
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
            logger.info("PipelineWorker finalizou execução com sucesso para intent '%s'", intent)
        except Exception as exc:
            tb = traceback.format_exc()
            logger.error("Erro no PipelineWorker ao executar '%s': %s\n%s", self.user_input, exc, tb)
            self.error_occurred.emit(f"{exc.__class__.__name__}: {exc}", tb)


class ConversationWindow(QDialog):
    """Janela que acompanha ao vivo mensagens de objetivos conversacionais."""

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
    """Janela principal do assistente Rock com suporte a modo degradado e telemetria."""

    def __init__(
        self,
        llm_agent: Optional[LocalLLMAgent] = None,
        llm_ready: bool = True,
        warmup_result: Optional[WarmupResult] = None,
        show_telemetry: bool = False,
    ) -> None:
        super().__init__()
        self.llm_ready = llm_ready
        self.warmup_result = warmup_result
        self.show_telemetry = show_telemetry

        title_suffix = " [TELEMETRIA]" if show_telemetry else (" [MODO DEGRADADO]" if not llm_ready else "")
        self.setWindowTitle(f"ROCK ASSISTANT{title_suffix}")
        self.resize(1150, 720)

        self.memory = ConversationMemory()
        self.goal_store = ConversationGoalStore()
        self.llm_agent = llm_agent or LocalLLMAgent(memory=self.memory)
        self.llm_agent.set_ready(llm_ready, mode=warmup_result.mode if warmup_result else "gpu")

        self.parser = IntentParser()
        self.router = build_router(llm=self.llm_agent, memory=self.memory, goal_store=self.goal_store)
        self.reminder_storage = SQLiteReminderStorage()

        self._worker: Optional[PipelineWorker] = None
        self._last_payload: Dict[str, Any] = {}
        self._conversation_windows: Dict[int, ConversationWindow] = {}

        self._build_ui()
        self._apply_style()

        # Injeta log do warmup na telemetria
        if self.warmup_result:
            self._log("=== INFORMAÇÕES DE WARMUP DO LLM ===")
            for line in self.warmup_result.log_lines:
                self._log(line)
            if not self.llm_ready:
                self._log(f"AVISO: Sistema inicializado em MODO DEGRADADO. Erro: {self.warmup_result.error}")
            else:
                self._log(f"SUCESSO: Llama pronto ({self.warmup_result.mode.upper()}). Latência: {self.warmup_result.latency_ms:.0f}ms")

        self.refresh_reminders()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)

        self.splitter = QSplitter(Qt.Horizontal)
        root_layout.addWidget(self.splitter, 1)

        # Painel Esquerdo: Resposta + Input
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.addWidget(QLabel("RESPOSTA DO ASSISTENTE"))
        self.output_view = QTextEdit(readOnly=True, objectName="output")

        # Define mensagem de abertura
        if not self.llm_ready:
            self.output_view.setMarkdown(
                "# Rock Online (Modo Degradado)\n\n"
                "> ⚠️ **Llama local indisponível.** Chat conversacional direto desativado.\n\n"
                "✅ **Módulos disponíveis:** Lembretes, Contatos, Comandos de Sistema, Busca Web, E-mail e WhatsApp.\n\n"
                "_Consulte a telemetria ao lado para detalhes do erro de inicialização._"
            )
        else:
            mode_desc = f" ({self.warmup_result.mode.upper()})" if self.warmup_result else ""
            lat_desc = f" | Latência: {self.warmup_result.latency_ms:.0f}ms" if (self.warmup_result and self.warmup_result.latency_ms) else ""
            self.output_view.setMarkdown(
                f"# Rock Online\n\n"
                f"🦙 **Llama {self.llm_agent.model} pronto{mode_desc}.**{lat_desc}\n\n"
                f"Aguardando comandos..."
            )

        left_layout.addWidget(self.output_view, 1)

        self.input_line = QLineEdit(objectName="cmd_input")
        self.input_line.setPlaceholderText("> root@rock:~#")
        self.input_line.returnPressed.connect(self._on_submit)
        left_layout.addWidget(self.input_line)
        self.splitter.addWidget(left_widget)

        # Painel Direito: Telemetria & Listas
        right_splitter = QSplitter(Qt.Vertical)

        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.addWidget(QLabel("TELEMETRIA LOCAL"))
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

        self.splitter.addWidget(right_splitter)

        # Ajusta tamanhos do splitter (com telemetria em evidência se solicitado)
        if self.show_telemetry:
            self.splitter.setSizes([550, 600])
            right_splitter.setSizes([350, 150, 150])
        else:
            self.splitter.setSizes([700, 450])
            right_splitter.setSizes([200, 200, 200])

        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.close)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.log_view.clear)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background-color: #000000; color: #d0d0d0; }
            QLabel { color: #39ff14; font-weight: bold; }
            #output { background-color: #000000; color: #39ff14; border: 1px solid #00e5ff; font-size: 13px; }
            #logs { background-color: #0a0a0a; color: #00e5ff; border: 1px solid #39ff14; font-family: monospace; font-size: 11px; }
            #reminders { background-color: #0a0a0a; color: #d0d0d0; border: 1px solid #39ff14; }
            #messages { background-color: #0a0a0a; color: #d0d0d0; border: 1px solid #00e5ff; }
            #cmd_input { background-color: #000000; color: #ffffff; border: 2px solid #00e5ff; padding: 6px; font-size: 13px; }
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
        logger.info("Comando submetido pelo usuário na GUI: %s", user_input)
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
        logger.debug("Intent processada na GUI: %s, payload=%s", intent, payload)

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


def ask_retry_cpu(parent: Optional[QWidget], error_detail: str) -> bool:
    """Apresenta diálogo modal perguntando se deseja tentar inicializar sem GPU."""
    msg_box = QMessageBox(parent)
    msg_box.setWindowTitle("Falha ao carregar Llama na GPU")
    msg_box.setText("Não foi possível inicializar o modelo Llama na GPU.")
    msg_box.setInformativeText(
        f"Detalhe: {error_detail}\n\n"
        "Deseja tentar reiniciar e executar o Ollama no modo CPU (OLLAMA_NUM_GPU=0)?\n"
        "(O modo CPU pode ser mais lento, mas evita erros de GPU/Vulkan)."
    )
    msg_box.setIcon(QMessageBox.Warning)
    yes_btn = msg_box.addButton("Sim (Tentar sem GPU)", QMessageBox.YesRole)
    no_btn = msg_box.addButton("Não (Modo Degradado)", QMessageBox.NoRole)
    msg_box.setStyleSheet(
        """
        QMessageBox { background-color: #0b0c10; color: #ffffff; }
        QLabel { color: #ffffff; }
        QPushButton { background-color: #1f2833; color: #66fcf1; border: 1px solid #45a29e; padding: 4px 10px; }
        """
    )
    msg_box.exec()
    return msg_box.clickedButton() == yes_btn


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rock Assistant Qt GUI")
    parser.add_argument(
        "-t",
        "--telemetry",
        "--test",
        dest="telemetry",
        action="store_true",
        help="Abre a interface com destaque na telemetria e logs em tempo real do projeto.",
    )
    args = parser.parse_args()
    args.test = args.telemetry
    return args



class AppController(QObject):
    """Controlador que coordena o fluxo de Splash -> Warmup -> Retry CPU -> RockWindow."""

    def __init__(self, app: QApplication, log_bridge: QtLogBridge, telemetry: bool = False) -> None:
        super().__init__()
        self.app = app
        self.log_bridge = log_bridge
        self.telemetry = telemetry

        self.llm_agent = LocalLLMAgent()
        self.splash = WarmupSplash()
        self.main_window: Optional[RockWindow] = None
        self.log_window: Optional[ProjectLogWindow] = None
        self._worker: Optional[WarmupWorker] = None

    def start(self) -> None:
        self.splash.show()
        self._run_warmup(force_cpu=False)

    def _run_warmup(self, force_cpu: bool = False) -> None:
        self.splash.set_status(
            "Validando Llama (modo CPU)..." if force_cpu else "Validando Llama (Ollama)..."
        )
        self._worker = WarmupWorker(self.llm_agent, force_cpu=force_cpu)
        self._worker.progress.connect(self.splash.set_status)
        self._worker.log_line.connect(self.splash.append_log)
        self._worker.finished.connect(lambda res: self._on_warmup_finished(res, force_cpu))
        self._worker.start()

    def _on_warmup_finished(self, result: WarmupResult, was_forced_cpu: bool) -> None:
        if result.ok:
            self.splash.append_log("Inicialização do Llama concluída com sucesso.")
            QTimer.singleShot(400, lambda: self._open_main_app(llm_ready=True, result=result))
            return

        # Se falhou e ainda não tentamos CPU, verifica se deve perguntar retry sem GPU
        err_str = result.error or result.detail or ""
        if not was_forced_cpu and (is_gpu_error(err_str) or "inferência" in err_str.lower() or "timeout" in err_str.lower()):
            self.splash.hide()
            retry = ask_retry_cpu(None, result.detail)
            if retry:
                self.splash.show()
                self.splash.append_log("Tentando reinicialização sem GPU (OLLAMA_NUM_GPU=0)...")
                self._run_warmup(force_cpu=True)
                return

        # Falha final -> abre em modo degradado
        self.splash.append_log("Iniciando em modo degradado...")
        QTimer.singleShot(400, lambda: self._open_main_app(llm_ready=False, result=result))

    def _open_main_app(self, llm_ready: bool, result: WarmupResult) -> None:
        self.splash.close()

        self.main_window = RockWindow(
            llm_agent=self.llm_agent,
            llm_ready=llm_ready,
            warmup_result=result,
            show_telemetry=self.telemetry,
        )

        if self.telemetry:
            self.log_window = ProjectLogWindow(bridge=self.log_bridge)

            screen = self.app.primaryScreen().availableGeometry()
            screen_width = screen.width()
            screen_height = screen.height()

            half_width = max(600, screen_width // 2)
            window_height = min(850, screen_height - 60)

            self.main_window.setGeometry(0, 30, half_width, window_height)
            self.log_window.setGeometry(half_width, 30, half_width, window_height)

            self.main_window.show()
            self.log_window.show()
        else:
            self.main_window.show()


def main() -> None:
    args = parse_args()

    # Cria a ponte de logs para a interface gráfica
    log_bridge = QtLogBridge()
    emitter = LogEmitter(callback=log_bridge.emit_log)

    # Configura o sistema de logging do projeto
    log_level = logging.DEBUG if args.telemetry else logging.INFO
    setup_logging(level=log_level, emitter=emitter)

    app = QApplication(sys.argv)

    controller = AppController(app=app, log_bridge=log_bridge, telemetry=args.telemetry)
    controller.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
