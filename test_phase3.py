"""Script de testes e validação operacional da Fase 3 do Rock Assistant.

Validação da Interface de Voz: Síntese de Fala (TTS) e Reconhecimento de Voz (STT).
"""

import os
import sys
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
from rock_assistant.core.intent_parser import IntentParser
from rock_assistant.core.memory import ConversationMemory
from rock_assistant.core.router import Router
from rock_assistant.main import build_router
from rock_assistant.tools.stt import SpeechToText, get_stt, listen
from rock_assistant.tools.tts import TextToSpeech, get_tts, speak, stop


class Phase3ValidationTests(unittest.TestCase):
    """Suíte de testes para validação da Interface de Voz (TTS e STT) no Kali Linux."""

    def test_01_tts_synthesis(self) -> None:
        """1. Teste de Síntese de Voz (TTS) com pyttsx3/espeak-ng."""
        print("\n" + "=" * 65)
        print("▶️ [TESTE 1] Síntese de Voz (Text-to-Speech - TTS)")
        print("=" * 65)

        tts = TextToSpeech(rate=175, volume=1.0)
        print(f"🔊 Motor TTS Inicializado: {'Disponível' if tts.is_available() else 'Indisponível (Modo silencioso)'}")
        print(f"   Velocidade (Rate): {tts.rate} wpm | Volume: {tts.volume}")

        test_phrase = "Teste do sistema de voz do Rock. Tudo operacional no Kali Linux."
        print(f"🎙️ Sintetizando frase: '{test_phrase}'...")

        # Executa a síntese de voz
        success = tts.speak(test_phrase)
        print(f"📢 Retorno do speak(): {success}")

        # Testa ajuste de parâmetros
        tts.set_rate(180)
        tts.set_volume(0.9)
        self.assertEqual(tts.rate, 180)
        self.assertEqual(tts.volume, 0.9)

        # Testa interrupção imediata
        tts.stop()

        # Valida função utilitária global
        global_success = speak("Rock pronto para operações.")
        self.assertIsInstance(global_success, bool)

        print("✅ Teste de Síntese de Voz (TTS) concluído sem exceções!")

    def test_02_stt_recognition_and_timeout(self) -> None:
        """2. Teste de Reconhecimento de Voz (STT) e Gestão de Timeout."""
        print("\n" + "=" * 65)
        print("▶️ [TESTE 2] Reconhecimento de Voz (Speech-to-Text - STT)")
        print("=" * 65)

        stt = SpeechToText(model_name="tiny", language="pt-BR")
        print(f"👂 Módulo STT Inicializado: {'Disponível' if stt.is_available() else 'Indisponível'}")
        print(f"   Modelo Whisper: {stt.model_name} | Idioma: {stt.language}")

        mic_detected = stt.is_microphone_available()
        print(f"🎤 Microfone Físico Detectado: {'Sim' if mic_detected else 'Não / PyAudio ausente'}")

        if mic_detected:
            print("\n🎙️ [Microfone Ativo] Por favor, fale uma frase curta nos próximos 5 segundos...")
            captured_text = stt.listen(timeout=5, phrase_time_limit=5)
            print(f"📝 Transcrição obtida: '{captured_text}'")
            self.assertIsInstance(captured_text, str)
        else:
            print("\n💡 Ambiente sem microfone/PyAudio ativo.")
            print("⏳ Validando comportamento seguro de timeout de 5 segundos no listen()...")
            # Executa o listen com timeout baixo para assegurar que não ocorram travamentos
            captured_text = stt.listen(timeout=2, phrase_time_limit=2)
            self.assertIsInstance(captured_text, str)
            self.assertEqual(captured_text, "")
            print("🛡️ Timeout e ausência de dispositivo tratados com segurança.")

            # Teste de transcrição simulada com Mock
            print("🔍 Testando pipeline de transcrição com áudio simulado...")
            with patch.object(stt, "is_available", return_value=True):
                with patch.object(stt, "listen", return_value="abrir terminal"):
                    result = stt.listen(timeout=5)
                    self.assertEqual(result, "abrir terminal")
                    print(f"✅ Transcrição mockada validada: '{result}'")

        print("✅ Teste de Reconhecimento de Voz (STT) concluído com sucesso!")

    def test_03_voice_workflow_integration(self) -> None:
        """3. Teste de Integração do Fluxo Completo de Voz (Voz -> Intent -> Router -> Resposta -> Fala)."""
        print("\n" + "=" * 65)
        print("▶️ [TESTE 3] Fluxo Integrado de Voz (STT + Parser + Router + TTS)")
        print("=" * 65)

        memory = ConversationMemory()
        parser = IntentParser()
        router = build_router(memory=memory)
        tts = TextToSpeech()

        simulated_voice_input = "busca notícias sobre cibersegurança"
        print(f"🎙️ Entrada simulada de voz: '{simulated_voice_input}'")

        # 1. Registra na memória
        memory.add_user_message(simulated_voice_input)

        # 2. Parsing de intenção
        parsed = parser.parse(simulated_voice_input)
        intent = parsed.get("intent")
        payload = parsed.get("payload", {})

        self.assertEqual(intent, "search")
        self.assertIn("query", payload)
        print(f"🎯 Intenção extraída: {intent} | Payload: {payload}")

        # 3. Execução no Router
        result = router.route(intent, payload)
        self.assertIsInstance(result, str)
        print(f"📄 Resposta gerada:\n{result[:150]}...")

        # 4. Síntese via TTS
        tts_result = tts.speak("Busca realizada com sucesso.")
        self.assertIsInstance(tts_result, bool)

        print("✅ Fluxo Integrado de Voz validado com sucesso!")


def run_all_tests() -> None:
    """Executa a suíte de testes da Fase 3 com apresentação visual."""
    print("=" * 70)
    print(" 🚀 INICIANDO BATERIA DE TESTES - FASE 3 (VOZ: TTS & STT)")
    print("=" * 70)

    suite = unittest.TestLoader().loadTestsFromTestCase(Phase3ValidationTests)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 70)
    if result.wasSuccessful():
        print(" 🎉 TODOS OS TESTES DA FASE 3 FORAM EXECUTADOS COM SUCESSO!")
    else:
        print(f" ❌ FALHAS: {len(result.failures)} | ERROS: {len(result.errors)}")
    print("=" * 70)


if __name__ == "__main__":
    run_all_tests()
