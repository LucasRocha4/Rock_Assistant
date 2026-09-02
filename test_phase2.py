"""Script de testes e validação operacional da Fase 2 do Rock Assistant.

Validação da Memória de Curto Prazo e do Agente Especialista (Google Gemini).
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Configuração de paths para importação correta
PROJECT_ROOT = Path(__file__).resolve().parent
ROCK_ASSISTANT_DIR = PROJECT_ROOT / "rock_assistant"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(ROCK_ASSISTANT_DIR) not in sys.path:
    sys.path.insert(0, str(ROCK_ASSISTANT_DIR))

from rock_assistant import config
from rock_assistant.core.memory import ConversationMemory
from rock_assistant.core.router import Router
from rock_assistant.core.specialist import SpecialistAgent
from rock_assistant.main import build_router


class Phase2ValidationTests(unittest.TestCase):
    """Suíte de testes para validação da Memória e do Agente Especialista."""

    def test_01_conversation_memory_operations(self) -> None:
        """1. Teste de Operações Básicas, Limite de 10 Mensagens e Persistência JSON."""
        print("\n" + "=" * 65)
        print("▶️ [TESTE 1] Memória de Curto Prazo (Estrutura, Limite e JSON)")
        print("=" * 65)

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_memory_file = Path(tmpdir) / "test_memory.json"
            memory = ConversationMemory(file_path=temp_memory_file, max_messages=10, auto_save=True)

            self.assertEqual(len(memory), 0)
            self.assertEqual(memory.get_history(), [])

            # Adiciona mensagens simulando diálogo
            memory.add_user_message("Olá, Rock!")
            memory.add_assistant_message("Olá! Como posso ajudar nas tarefas no Kali Linux hoje?")

            history = memory.get_history()
            self.assertEqual(len(history), 2)
            self.assertEqual(history[0], {"role": "user", "content": "Olá, Rock!"})
            self.assertEqual(history[1]["role"], "assistant")

            # Verifica persistência no arquivo JSON
            self.assertTrue(temp_memory_file.exists(), "O arquivo memory.json deve ser criado automaticamente.")
            with open(temp_memory_file, "r", encoding="utf-8") as f:
                saved_data = json.load(f)
                self.assertEqual(len(saved_data), 2)
                self.assertEqual(saved_data[0]["content"], "Olá, Rock!")

            print(f"💾 Persistência JSON validada com sucesso em: {temp_memory_file}")

            # Testa limite máximo de 10 mensagens (5 turnos) com janela deslizante
            print("🔄 Testando janela deslizante de no máximo 10 mensagens...")
            for i in range(1, 8):
                memory.add_user_message(f"Pergunta {i}")
                memory.add_assistant_message(f"Resposta {i}")

            # Total inserido: 2 iniciais + 14 novas = 16 mensagens. Deve reter exatamente 10.
            self.assertEqual(len(memory), 10, "A memória deve limitar a exatamente 10 mensagens.")
            history = memory.get_history()
            self.assertEqual(history[0]["content"], "Pergunta 3", "Mensagens mais antigas devem ser descartadas.")
            self.assertEqual(history[-1]["content"], "Resposta 7", "A mensagem mais recente deve estar no fim.")

            print(f"✂️ Limite de 10 mensagens validado: {len(history)} mensagens retidas.")

            # Testa clear_memory()
            memory.clear_memory()
            self.assertEqual(len(memory), 0)
            with open(temp_memory_file, "r", encoding="utf-8") as f:
                cleared_data = json.load(f)
                self.assertEqual(cleared_data, [])

            print("🧹 Limpeza de memória com clear_memory() validada.")
            print("✅ Teste de Memória de Curto Prazo concluído com sucesso!")

    def test_02_context_retention_and_chat(self) -> None:
        """2. Teste de Retenção de Contexto (3 mensagens sequenciais de diálogo)."""
        print("\n" + "=" * 65)
        print("▶️ [TESTE 2] Retenção de Contexto em Conversação Sequencial")
        print("=" * 65)

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_memory_file = Path(tmpdir) / "context_memory.json"
            memory = ConversationMemory(file_path=temp_memory_file, max_messages=10)
            specialist = SpecialistAgent(memory=memory)

            turns = [
                ("Meu nome é Lucas", "Olá Lucas! Entendido."),
                ("Estou estudando Engenharia de Software", "Excelente área! Como posso ajudar em seus estudos?"),
                ("Qual é o meu nome e o que eu estudo?", "Seu nome é Lucas e você estuda Engenharia de Software."),
            ]

            if specialist.is_available():
                print("🟢 Gemini API Key detectada! Executando inferência com Gemini...")
                for user_text, _ in turns:
                    print(f"👤 Usuário: {user_text}")
                    memory.add_user_message(user_text)
                    response = specialist.chat(user_text)
                    print(f"🤖 Rock (Gemini): {response}\n")
                    memory.add_assistant_message(response)

                history = memory.get_history()
                self.assertEqual(len(history), 6)
                last_reply = history[-1]["content"].lower()
                self.assertIn("lucas", last_reply)
            else:
                print("🟡 Gemini API Key não configurada. Simulando diálogo sequencial e validando integridade do histórico...")
                for user_text, simulated_reply in turns:
                    memory.add_user_message(user_text)
                    # Simula a resposta do assistente
                    memory.add_assistant_message(simulated_reply)
                    print(f"👤 Usuário: {user_text}")
                    print(f"🤖 Assistente: {simulated_reply}")

                history = memory.get_history()
                self.assertEqual(len(history), 6)
                self.assertEqual(history[0]["content"], "Meu nome é Lucas")
                self.assertEqual(history[2]["content"], "Estou estudando Engenharia de Software")
                self.assertEqual(history[4]["content"], "Qual é o meu nome e o que eu estudo?")

            print("✅ Teste de Retenção de Contexto concluído com sucesso!")

    def test_03_technical_task_and_code_generation(self) -> None:
        """3. Teste de Tarefa Técnica e Raciocínio de Código."""
        print("\n" + "=" * 65)
        print("▶️ [TESTE 3] Tarefa Técnica e Geração de Código")
        print("=" * 65)

        task_prompt = "Escreva uma função em Python para validar se uma string é um endereço IP v4 válido."
        specialist = SpecialistAgent()

        print(f"💻 Solicitando tarefa técnica: '{task_prompt}'...")

        if specialist.is_available():
            response = specialist.chat(task_prompt)
            print("\n--- Resposta Gerada pelo Gemini ---")
            print(response)
            self.assertTrue(len(response) > 50)
            self.assertTrue(
                "def " in response or "ip" in response.lower(),
                "A resposta deve conter definição de função ou lógica de validação de IP.",
            )
        else:
            print("🟡 Gemini API Key não configurada. Validando estrutura com Mock do SDK...")
            simulated_code = (
                "```python\n"
                "import ipaddress\n\n"
                "def is_valid_ipv4(ip_str: str) -> bool:\n"
                "    \"\"\"Valida se a string informada é um IPv4 válido.\"\"\"\n"
                "    try:\n"
                "        ip = ipaddress.IPv4Address(ip_str.strip())\n"
                "        return True\n"
                "    except ipaddress.AddressValueError:\n"
                "        return False\n"
                "```\n\n"
                "Esta função utiliza o módulo nativo `ipaddress` do Python para garantir validação segura."
            )
            mock_client = MagicMock()
            mock_resp = MagicMock()
            mock_resp.text = simulated_code
            mock_client.models.generate_content.return_value = mock_resp

            with patch("google.genai.Client", return_value=mock_client):
                agent = SpecialistAgent(api_key="mock_key")
                response = agent.chat(task_prompt)
                print("\n--- Código Validado ---")
                print(response)
                self.assertIn("def is_valid_ipv4", response)
                self.assertIn("ipaddress", response)

        print("✅ Teste de Tarefa Técnica concluído com sucesso!")

    def test_04_resilience_and_missing_key_fallback(self) -> None:
        """4. Teste de Resiliência e Fallback Amigável em caso de ausência de chave."""
        print("\n" + "=" * 65)
        print("▶️ [TESTE 4] Resiliência e Tratamento de Erros (Chave Ausente / Inválida)")
        print("=" * 65)

        unconfigured_agent = SpecialistAgent(api_key="")

        print("🔑 Testando chamada sem chave de API do Gemini...")
        response = unconfigured_agent.chat("Como configurar firewall no Kali Linux?")

        print("\n--- Resposta de Fallback do Sistema ---")
        print(response)

        self.assertIsInstance(response, str)
        self.assertIn("[Rock Auth]", response)
        self.assertIn("GEMINI_API_KEY", response)

        print("✅ Teste de Resiliência concluído com sucesso!")

    def test_05_router_and_main_integration(self) -> None:
        """5. Teste de Integração do Router com a rota 'general' e Memória."""
        print("\n" + "=" * 65)
        print("▶️ [TESTE 5] Integração do Router com Agente Especialista e Memória")
        print("=" * 65)

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_memory_file = Path(tmpdir) / "router_memory.json"
            memory = ConversationMemory(file_path=temp_memory_file)
            specialist = SpecialistAgent(memory=memory)
            router = build_router(specialist=specialist, memory=memory)

            # 1. Rota 'general'
            with patch.object(specialist, "chat", return_value="Resposta do especialista técnico.") as mock_chat:
                result = router.route("general", {"text": "Explique o protocolo ARP"})
                self.assertEqual(result, "Resposta do especialista técnico.")
                mock_chat.assert_called_once_with("Explique o protocolo ARP", memory=memory)

            print("✅ Rota 'general' aciona SpecialistAgent corretamente.")


def run_all_tests() -> None:
    """Executa a suíte de testes da Fase 2 com formatação visual."""
    print("=" * 70)
    print(" 🚀 INICIANDO BATERIA DE TESTES - FASE 2 (ROCK ASSISTANT)")
    print("=" * 70)

    suite = unittest.TestLoader().loadTestsFromTestCase(Phase2ValidationTests)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 70)
    if result.wasSuccessful():
        print(" 🎉 TODOS OS TESTES DA FASE 2 FORAM EXECUTADOS COM SUCESSO!")
    else:
        print(f" ❌ FALHAS: {len(result.failures)} | ERROS: {len(result.errors)}")
    print("=" * 70)


if __name__ == "__main__":
    run_all_tests()
