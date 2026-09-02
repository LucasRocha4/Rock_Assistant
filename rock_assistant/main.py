"""Ponto de entrada da aplicação Rock com Memória, Especialista e Interface de Voz (STT/TTS)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

# Garante que módulos e pacotes internos sejam importados corretamente
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.intent_parser import IntentParser
from core.memory import ConversationMemory
from core.router import Router
from core.specialist import SpecialistAgent
from tools.messaging import send_message
from tools.reminders import create_reminder
from tools.stt import SpeechToText, get_stt
from tools.system_cmd import run_system_command
from tools.tts import TextToSpeech, get_tts
from tools.web_search import search_web


def build_router(
    specialist: Optional[SpecialistAgent] = None,
    memory: Optional[ConversationMemory] = None,
) -> Router:
    """Configura as rotas principais da aplicação mapeando intenções e payloads."""
    router = Router()
    specialist_agent = specialist or SpecialistAgent(memory=memory)

    router.register(
        "search",
        lambda payload: search_web(payload.get("query", payload.get("text", ""))),
    )
    router.register(
        "reminder",
        lambda payload: create_reminder(
            payload.get("text", ""),
            payload.get("when"),
        ),
    )
    router.register(
        "command",
        lambda payload: run_system_command(
            payload.get("command", payload.get("text", "")),
        ),
    )
    router.register(
        "message",
        lambda payload: send_message(
            payload.get("target", payload.get("channel", "default")),
            payload.get("text", ""),
        ),
    )
    router.register(
        "general",
        lambda payload: specialist_agent.chat(
            payload.get("text", ""),
            memory=memory,
        ),
    )

    return router


def run_voice_loop(
    router: Router,
    parser: IntentParser,
    memory: ConversationMemory,
    tts: TextToSpeech,
    stt: SpeechToText,
    specialist: Optional[SpecialistAgent] = None,
) -> None:
    """Executa o loop interativo em Modo Voz (Ouvidos com STT e Voz com TTS)."""
    print("\n" + "=" * 60)
    print(" 🎙️ [MODO VOZ ATIVO] Rock Assistant (Kali Linux)")
    print(" Fale no microfone ou diga 'sair' para encerrar.")
    print(" Diga 'limpar memoria' para reiniciar o contexto.")
    print("=" * 60)

    welcome_msg = "Modo de voz ativado. Rock escutando."
    tts.speak(welcome_msg)

    print("⏳ Aquecendo o modelo Gemini...")
    if specialist is not None and specialist.is_available():
        request_timeout = specialist.timeout
        specialist.timeout = max(request_timeout, 60)
        specialist.chat("OK", memory=None)
        specialist.timeout = request_timeout
    print("✅ Modelo pronto.")

    mic_available = stt.is_microphone_available()
    if not mic_available:
        print("⚠️ [Aviso] Microfone ou PyAudio não detectado no sistema.")
        print("💡 Para digitar no terminal com resposta em áudio falado (TTS), prossiga abaixo.")

    while True:
        try:
            if mic_available:
                print("\n🎧 Rock escutando... (fale agora)")
                user_input = stt.listen(timeout=10, phrase_time_limit=15)
                if not user_input:
                    # Nenhum áudio capturado no timeout, continua escutando
                    continue
                print(f"👤 Você (Voz): {user_input}")
            else:
                user_input = input("\nVocê (Texto): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nRock encerrado.")
            tts.speak("Rock encerrado. Até logo!")
            break

        if user_input.lower() in {"sair", "exit", "quit"}:
            print("Rock encerrado.")
            tts.speak("Encerrando assistente Rock.")
            break

        if not user_input.strip():
            continue

        # Comando especial para limpar histórico de memória
        if user_input.lower() in {"limpar memoria", "limpar memória", "/clear", "clear memory"}:
            memory.clear_memory()
            msg = "Histórico de conversa limpo com sucesso."
            print(f"🧹 [Memória] {msg}")
            tts.speak(msg)
            continue

        # 1. Registra entrada na memória
        memory.add_user_message(user_input)

        # 2. Parse da intenção
        parsed = parser.parse_with_llm(user_input)
        intent = parsed.get("intent")
        payload = parsed.get("payload", {})

        if intent is None:
            intent = "general"
            payload = {"text": user_input}

        print(f"🎯 Intenção detectada: {intent}")
        if intent != "general":
            print(f"📦 Payload extraído: {payload}")

        try:
            result = router.route(intent, payload)
            if isinstance(result, str):
                response_text = result
            elif isinstance(result, dict):
                response_text = "\n".join(f"  {k}: {v}" for k, v in result.items())
            else:
                response_text = str(result)

            print("\n--- [Resultado] ---")
            print(response_text)

            # 3. Registra resposta na memória e sintetiza áudio falado via TTS
            memory.add_assistant_message(response_text)
            tts.speak(response_text)

        except Exception as exc:
            err_msg = f"Erro ao processar comando: {exc}"
            print(f"❌ {err_msg}")
            tts.speak(err_msg)
            memory.add_assistant_message(err_msg)


def run_text_loop(
    router: Router,
    parser: IntentParser,
    memory: ConversationMemory,
) -> None:
    """Executa o loop interativo padrão em Modo Texto."""
    print("=" * 60)
    print(" 🎸 Rock Assistant (Fase 3 - Kali Linux)")
    print(" Digite 'sair', 'exit' ou 'quit' para encerrar.")
    print(" Digite 'limpar memoria' para reiniciar o histórico.")
    print(" Use '--voz' ou '-v' para ativar o Modo Voz com STT e TTS.")
    print("=" * 60)

    while True:
        try:
            user_input = input("\nVocê: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nRock encerrado.")
            break

        if user_input.lower() in {"sair", "exit", "quit"}:
            print("Rock encerrado.")
            break

        if not user_input:
            continue

        # Comando especial para limpar histórico de memória
        if user_input.lower() in {"limpar memoria", "limpar memória", "/clear", "clear memory"}:
            memory.clear_memory()
            print("🧹 [Memória] Histórico de conversa limpo com sucesso.")
            continue

        # 1. Registra a entrada do usuário na memória de curto prazo
        memory.add_user_message(user_input)

        # 2. Parse da intenção com roteador LLM / RegEx
        parsed = parser.parse_with_llm(user_input)
        intent = parsed.get("intent")
        payload = parsed.get("payload", {})

        if intent is None:
            intent = "general"
            payload = {"text": user_input}

        print(f"🎯 Intenção detectada: {intent}")
        if intent != "general":
            print(f"📦 Payload extraído: {payload}")

        try:
            result = router.route(intent, payload)
            print("\n--- [Resultado] ---")
            if isinstance(result, str):
                response_text = result
            elif isinstance(result, dict):
                response_text = "\n".join(f"  {k}: {v}" for k, v in result.items())
            else:
                response_text = str(result)

            print(response_text)

            # 3. Registra a resposta do assistente na memória
            memory.add_assistant_message(response_text)

        except ValueError as exc:
            err_msg = f"❌ Erro de roteamento: {exc}"
            print(err_msg)
            memory.add_assistant_message(err_msg)
        except Exception as exc:
            err_msg = f"❌ Erro na execução da ferramenta: {exc}"
            print(err_msg)
            memory.add_assistant_message(err_msg)


def main() -> None:
    """Ponto de entrada do Rock Assistant com suporte a argumentos CLI."""
    cli_parser = argparse.ArgumentParser(
        description="Rock Assistant - Assistente de IA no Kali Linux com Voz, Memória e Ferramentas.",
    )
    cli_parser.add_argument(
        "-v",
        "--voz",
        action="store_true",
        help="Inicia o assistente no Modo Voz com escuta por microfone (STT) e fala (TTS).",
    )
    args = cli_parser.parse_args()

    memory = ConversationMemory()
    specialist = SpecialistAgent(memory=memory)
    intent_parser = IntentParser()
    router = build_router(specialist=specialist, memory=memory)

    if args.voz:
        tts = get_tts()
        stt = get_stt()
        run_voice_loop(
            router=router,
            parser=intent_parser,
            memory=memory,
            tts=tts,
            stt=stt,
            specialist=specialist,
        )
    else:
        run_text_loop(
            router=router,
            parser=intent_parser,
            memory=memory,
        )


if __name__ == "__main__":
    main()
