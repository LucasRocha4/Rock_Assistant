"""Testes unitários para o aquecimento (warmup) do Llama, detecção de erro GPU e modo degradado."""

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from rock_assistant.core.local_llm import LocalLLMAgent, WarmupResult, is_gpu_error
from rock_assistant.rock_gui import RockWindow, WarmupSplash, parse_args


class TestWarmupAndDegradedMode(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])

    def test_is_gpu_error_detection(self):
        self.assertTrue(is_gpu_error("vk::Queue::submit: ErrorDeviceLost"))
        self.assertTrue(is_gpu_error("model runner has unexpectedly stopped"))
        self.assertTrue(is_gpu_error("llama-server process has terminated"))
        self.assertTrue(is_gpu_error("CUDA out of memory"))
        self.assertFalse(is_gpu_error("connection refused to 127.0.0.1:11434"))
        self.assertFalse(is_gpu_error("model not found"))

    @patch("requests.get")
    def test_warmup_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"models": [{"name": "llama3.2:latest"}]}
        mock_get.return_value = mock_resp

        agent = LocalLLMAgent(model="llama3.2")
        mock_client = MagicMock()
        mock_client.chat.return_value = {"message": {"content": "ok"}}
        agent._client = mock_client

        result = agent.warmup(force_cpu=False)
        self.assertTrue(result.ok)
        self.assertEqual(result.mode, "gpu")
        self.assertTrue(agent.is_ready())
        self.assertIsNotNone(result.latency_ms)

    @patch("requests.get")
    def test_warmup_model_missing(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"models": [{"name": "phi3:latest"}]}
        mock_get.return_value = mock_resp

        agent = LocalLLMAgent(model="llama3.2")
        result = agent.warmup(force_cpu=False)
        self.assertFalse(result.ok)
        self.assertFalse(agent.is_ready())
        self.assertIn("não foi encontrado", result.error)

    @patch("requests.get")
    def test_warmup_inference_gpu_failure(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"models": [{"name": "llama3.2"}]}
        mock_get.return_value = mock_resp

        agent = LocalLLMAgent(model="llama3.2")
        mock_client = MagicMock()
        mock_client.chat.side_effect = RuntimeError("vk::Queue::submit: ErrorDeviceLost")
        agent._client = mock_client

        result = agent.warmup(force_cpu=False)
        self.assertFalse(result.ok)
        self.assertFalse(agent.is_ready())
        self.assertTrue(is_gpu_error(result.error))

    def test_chat_short_circuit_when_not_ready(self):
        agent = LocalLLMAgent(model="llama3.2")
        agent.set_ready(False)
        reply = agent.chat("Olá, tudo bem?")
        self.assertIn("Modo Degradado", reply)

    def test_splash_ui_initialization(self):
        splash = WarmupSplash()
        splash.set_status("Testando status...")
        splash.append_log("Log teste 123")
        self.assertEqual(splash.status_label.text(), "Testando status...")

    def test_rock_window_degraded_banner(self):
        warmup_res = WarmupResult(
            ok=False,
            mode="unavailable",
            model="llama3.2",
            detail="Ollama offline",
            error="Connection refused",
            log_lines=["[00:00:00] Falha"],
        )
        window = RockWindow(llm_ready=False, warmup_result=warmup_res)
        self.assertIn("Modo Degradado", window.output_view.toPlainText())

    def test_parse_args_telemetry_flags(self):
        with patch("sys.argv", ["rock_gui.py", "-t"]):
            args = parse_args()
            self.assertTrue(args.telemetry)

        with patch("sys.argv", ["rock_gui.py", "--telemetry"]):
            args = parse_args()
            self.assertTrue(args.telemetry)

        with patch("sys.argv", ["rock_gui.py", "--test"]):
            args = parse_args()
            self.assertTrue(args.telemetry)


if __name__ == "__main__":
    unittest.main()
