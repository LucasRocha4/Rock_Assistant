"""Testes unitários para o sistema de logs centralizado e modo de teste da GUI."""

import logging
import os
import unittest
from unittest.mock import MagicMock

# Define plataforma offscreen para testes Qt em ambiente headless
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from rock_assistant.rock_gui import ProjectLogWindow, QtLogBridge, parse_args
from rock_assistant.setup.logger_config import BroadcastLogHandler, LogEmitter, setup_logging


class TestLoggingSystem(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])

    def test_log_emitter_and_broadcast_handler(self):
        received = []

        def callback(record, formatted):
            received.append((record.levelname, formatted, record.getMessage()))

        emitter = LogEmitter(callback=callback)
        handler = BroadcastLogHandler(emitter=emitter)
        logger = logging.getLogger("test_logger")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)

        logger.info("Mensagem de teste para o emitter")
        self.assertTrue(len(received) > 0)
        self.assertEqual(received[0][0], "INFO")
        self.assertIn("Mensagem de teste", received[0][2])

    def test_project_log_window_filtering(self):
        bridge = QtLogBridge()
        window = ProjectLogWindow(bridge=bridge)

        # Emite registros simulados
        record_info = logging.LogRecord("rock.test", logging.INFO, "", 0, "Info test message", (), None)
        record_error = logging.LogRecord("rock.test", logging.ERROR, "", 0, "Error test message", (), None)

        bridge.emit_log(record_info, "formatted info")
        bridge.emit_log(record_error, "formatted error")

        self.assertEqual(len(window._all_records), 2)

        # Testa filtro por nível
        window.level_filter.setCurrentText("ERROR")
        window._apply_filters()
        self.assertIn("Error test message", window.log_text_view.toPlainText())
        self.assertNotIn("Info test message", window.log_text_view.toPlainText())

        # Testa filtro por busca de texto
        window.level_filter.setCurrentText("TODOS")
        window.search_input.setText("Info")
        window._apply_filters()
        self.assertIn("Info test message", window.log_text_view.toPlainText())
        self.assertNotIn("Error test message", window.log_text_view.toPlainText())

    def test_parse_args_test_flag(self):
        with unittest.mock.patch("sys.argv", ["rock_gui.py", "--test"]):
            args = parse_args()
            self.assertTrue(args.test)

        with unittest.mock.patch("sys.argv", ["rock_gui.py"]):
            args = parse_args()
            self.assertFalse(args.test)


if __name__ == "__main__":
    unittest.main()
