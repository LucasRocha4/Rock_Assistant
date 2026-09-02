"""Script de testes e validação operacional da Fase 1 do Rock Assistant no Kali Linux."""

import os
import sqlite3
import sys
import unittest
from pathlib import Path

# Configuração de paths para importação correta
PROJECT_ROOT = Path(__file__).resolve().parent
ROCK_ASSISTANT_DIR = PROJECT_ROOT / "rock_assistant"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(ROCK_ASSISTANT_DIR) not in sys.path:
    sys.path.insert(0, str(ROCK_ASSISTANT_DIR))

from rock_assistant import config
from rock_assistant.core.intent_parser import IntentParser
from rock_assistant.core.router import Router
from rock_assistant.main import build_router
from rock_assistant.tools.messaging import send_message
from rock_assistant.tools.reminders import (
    GoogleCalendarAdapter,
    SQLiteReminderStorage,
    create_reminder,
    list_reminders,
)
from rock_assistant.tools.system_cmd import (
    get_local_ip,
    run_nmap_scan,
    run_system_command,
)
from rock_assistant.tools.web_search import search_web, search_web_raw


class Phase1ValidationTests(unittest.TestCase):
    """Suíte de testes para validação dos componentes da Fase 1."""

    def test_01_web_search(self) -> None:
        """1. Teste de Busca Web com DuckDuckGo (DDGS)."""
        print("\n" + "=" * 60)
        print("▶️ [TESTE 1] Busca Web (DuckDuckGo / DDGS)")
        print("=" * 60)

        query = "Ozzy Osbourne e 3 fatos marcantes de sua carreira"
        print(f"🔎 Executando busca para: '{query}'...")

        raw_results = search_web_raw(query, max_results=3)
        self.assertIsInstance(raw_results, list)
        self.assertGreater(len(raw_results), 0, "A busca deve retornar ao menos um resultado.")

        formatted_result = search_web(query, max_results=3)
        self.assertIsInstance(formatted_result, str)
        self.assertIn("Ozzy", formatted_result, "O resultado formatado deve conter o termo pesquisado.")
        self.assertIn("Link:", formatted_result)

        print("\n--- Síntese Textual Retornada ---")
        print(formatted_result)
        print("✅ Teste de Busca Web concluído com sucesso!")

    def test_02_system_commands_kali(self) -> None:
        """2. Teste de Comandos de Sistema no Kali Linux (IP, nmap e diagnóstico)."""
        print("\n" + "=" * 60)
        print("▶️ [TESTE 2] Comandos de Sistema no Kali Linux")
        print("=" * 60)

        # a) Identificar o endereço IP local da máquina
        local_ip = get_local_ip()
        print(f"🌐 [Passo A] Endereço IP Local identificado: {local_ip}")
        self.assertTrue(local_ip and len(local_ip.split(".")) == 4, "Deve retornar um IPv4 válido.")

        # Teste de comando auxiliar ip a / uname
        uname_output = run_system_command("uname -a")
        print(f"🐧 Kernel / Sistema: {uname_output}")
        self.assertNotIn("❌", uname_output)

        # b) e c) Executar escaneamento nmap básico contra loopback ou IP local
        print(f"\n🛡️ [Passo B & C] Executando escaneamento contra '127.0.0.1'...")
        nmap_result = run_nmap_scan(target="127.0.0.1", options="-F")

        print("\n--- Resultado do Diagnóstico / Nmap ---")
        print(nmap_result)
        self.assertTrue(len(nmap_result) > 0, "O resultado do escaneamento não pode ser vazio.")
        print("✅ Teste de Comandos de Sistema no Kali Linux concluído com sucesso!")

    def test_03_reminders_sqlite_and_google_calendar(self) -> None:
        """3. Teste de Lembretes no SQLite local e verificação de Google Calendar API."""
        print("\n" + "=" * 60)
        print("▶️ [TESTE 3] Lembretes (SQLite Local + Google Calendar Adapter)")
        print("=" * 60)

        test_message = "Reunião do projeto Rock às 15:00"
        test_when = "às 15:00"

        print(f"📝 Agendando lembrete: '{test_message}' (horário: {test_when})...")
        reminder_res = create_reminder(test_message, when=test_when)

        # Verificação do status do lembrete
        self.assertIn(reminder_res.get("status"), ["created_local", "created_synced"])
        self.assertEqual(reminder_res.get("message"), test_message)
        self.assertEqual(reminder_res.get("when"), test_when)
        self.assertIn("db_path", reminder_res)

        db_path = Path(reminder_res["db_path"])
        self.assertTrue(db_path.exists(), f"O arquivo de banco de dados {db_path} deve existir.")

        # Verificar persistência direta no SQLite
        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, message, when_time FROM reminders WHERE id = ?", (reminder_res["id"],))
            row = cursor.fetchone()
            self.assertIsNotNone(row, "O registro deve existir no banco SQLite.")
            self.assertEqual(row[1], test_message)
            self.assertEqual(row[2], test_when)

        print(f"💾 Lembrete persistido no SQLite (ID: {reminder_res['id']}, BD: {db_path})")

        # Teste de listagem
        all_reminders = list_reminders(limit=5)
        self.assertGreater(len(all_reminders), 0)
        print(f"📋 Total de lembretes listados: {len(all_reminders)}")

        # Verificação da autenticação com Google Calendar API
        adapter = GoogleCalendarAdapter()
        google_info = reminder_res.get("google_sync", {})
        print(f"\n🔐 Verificação Google Calendar OAuth2:")
        print(f"   Configurado: {'Sim' if adapter.is_configured() else 'Não (Credenciais não encontradas)'}")
        print(f"   Arquivo credentials.json: {adapter.credentials_file} (Existe: {adapter.credentials_file.exists()})")
        print(f"   Arquivo token.json: {adapter.token_file} (Existe: {adapter.token_file.exists()})")
        print(f"   Detalhes da Sincronização: {google_info.get('info')}")

        if not adapter.is_configured():
            print("\n💡 AVISO: Para ativar a sincronização com o Google Calendar em nuvem,")
            print("   coloque o arquivo 'credentials.json' ou 'token.json' na pasta do projeto.")

        print("✅ Teste de Lembretes e SQLite concluído com sucesso!")

    def test_04_intent_parser_and_router(self) -> None:
        """4. Teste do Intent Parser (RegEx e Fallback) e Roteamento de Payloads."""
        print("\n" + "=" * 60)
        print("▶️ [TESTE 4] Intent Parser & Router (Payloads e Roteamento)")
        print("=" * 60)

        parser = IntentParser()
        router = build_router()

        test_cases = [
            (
                "busca Ozzy Osbourne carreira",
                "search",
                "query",
            ),
            (
                "lembre de comprar café às 10:00",
                "reminder",
                "text",
            ),
            (
                "exec ifconfig",
                "command",
                "command",
            ),
            (
                "mandar mensagem para suporte servidor caiu",
                "message",
                "target",
            ),
            (
                "olá assistente rock!",
                "general",
                "text",
            ),
        ]

        for user_input, expected_intent, expected_payload_key in test_cases:
            parsed = parser.parse(user_input)
            intent = parsed.get("intent")
            payload = parsed.get("payload", {})

            print(f"Input: '{user_input}' -> Intent: {intent}, Payload: {payload}")
            self.assertEqual(intent, expected_intent)
            self.assertIn(expected_payload_key, payload)

            # Teste de execução do router
            route_res = router.route(intent, payload)
            self.assertIsNotNone(route_res)

        # Teste do parse_with_llm (com fallback determinístico se Gemini não configurado)
        llm_parsed = parser.parse_with_llm("busca documentação python")
        self.assertEqual(llm_parsed.get("intent"), "search")
        self.assertIn("query", llm_parsed.get("payload", {}))
        print("✅ Teste de Intent Parser & Router concluído com sucesso!")


def run_all_tests() -> None:
    """Executa a suíte de testes completa com apresentação visual formatada."""
    print("=" * 70)
    print(" 🚀 INICIANDO BATERIA DE TESTES - FASE 1 (ROCK ASSISTANT)")
    print("=" * 70)

    suite = unittest.TestLoader().loadTestsFromTestCase(Phase1ValidationTests)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 70)
    if result.wasSuccessful():
        print(" 🎉 TODOS OS TESTES DA FASE 1 FORAM EXECUTADOS COM SUCESSO!")
    else:
        print(f" ❌ FALHAS: {len(result.failures)} | ERROS: {len(result.errors)}")
    print("=" * 70)


if __name__ == "__main__":
    run_all_tests()
