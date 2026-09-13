"""Ponto de entrada da aplicação Rock com Memória, Especialista e Interface de Voz (STT/TTS)."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Optional

import requests

# Garante que módulos e pacotes internos sejam importados corretamente
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.intent_parser import IntentParser
from core.memory import ConversationMemory
from core.reminder_interpreter import ReminderInterpreter
from core.router import Router
from core.speech_formatter import format_for_speech
from core.specialist import SpecialistAgent
from core.startup import StartupBriefing
from rock_assistant import config
from tools.contacts import add_contact, initialize_contacts_db, is_phone_number, list_contacts, normalize_phone, resolve_contact
from tools.conversation_goals import ConversationGoalStore
from tools.messaging import send_whatsapp_message
from tools.email import get_email_delegation_manager, get_gmail_tool, set_monitoring_enabled
from tools.reminders import create_reminder, SQLiteReminderStorage
from tools.stt import SpeechToText, get_stt
from tools.system_cmd import run_system_command
from tools.tts import TextToSpeech, get_tts
from tools.web_search import search_web


def build_router(
    specialist: Optional[SpecialistAgent] = None,
    memory: Optional[ConversationMemory] = None,
    goal_store: Optional[ConversationGoalStore] = None,
) -> Router:
    """Configura as rotas principais da aplicação mapeando intenções e payloads."""
    router = Router()
    specialist_agent = specialist or SpecialistAgent(memory=memory)
    reminder_interpreter = ReminderInterpreter()
    goal_store = goal_store or ConversationGoalStore()
    initialize_contacts_db()

    def handle_reminder(payload):
        draft = reminder_interpreter.interpret(
            {**payload, "raw_text": payload.get("raw_text", payload.get("text", ""))}
        )
        if draft.needs_confirmation:
            return {
                "status": "needs_confirmation",
                "message": f"Preciso confirmar o lembrete: {draft.confirmation_reason}.",
                "resumo": draft.short_text,
                "importancia": draft.importance,
            }
        result = create_reminder(
            draft.short_text,
            draft.when,
            draft=draft,
        )
        if isinstance(result, dict) and str(result.get("status", "")).startswith("created_"):
            target = "agenda" if draft.kind == "calendar_event" else "mensagem pendente"
            return f"Salvo na {target}: {draft.short_text} ({draft.importance})."
        return result

    router.register(
        "search",
        lambda payload: search_web(
            payload.get("query", payload.get("text", "")),
            max_results=int(payload.get("max_results", 5)),
            mode=payload.get("mode"),
        ),
    )
    router.register(
        "reminder",
        handle_reminder,
    )
    router.register(
        "command",
        lambda payload: run_system_command(
            payload.get("command", payload.get("text", "")),
        ),
    )
    def handle_message(payload):
        target = str(payload.get("target", "")).strip()
        message = str(payload.get("text", "")).strip()
        if not target or target.lower() == "default":
            return {"status": "needs_recipient", "message": "Informe o numero ou nome do contato para enviar pelo WhatsApp."}
        if not message:
            return {"status": "invalid_message", "message": "Informe o texto da mensagem."}

        recipient = normalize_phone(target) if is_phone_number(target) else resolve_contact(target, config.DB_PATH)
        if not recipient:
            return {
                "status": "contact_not_found",
                "message": f"Nao encontrei um numero para '{target}'. Informe o numero ou cadastre o contato.",
            }
        composed_message = message
        if specialist_agent.is_available() and re.search(
            r"\b(perguntando|pergunta|dizendo|diga|avisando|avise|explique|convide)\b",
            message,
            re.IGNORECASE,
        ):
            composed_message = specialist_agent.chat(
                message,
                extra_system_prompt=(
                    "Redija somente a mensagem final que será enviada pelo WhatsApp ao destinatário. "
                    "Interprete instruções como 'perguntando', 'dizendo' ou 'avisando' como intenção de redação. "
                    "Use português brasileiro, tom natural e cordial, boa pontuação e personalidade do Rock. "
                    "Não explique o que fez, não use aspas e não acrescente informações que não foram dadas."
                ),
            ) or message
        return send_whatsapp_message(recipient, composed_message)

    router.register("message", handle_message)

    def handle_contact(payload):
        try:
            contact = add_contact(
                contact_name=str(payload.get("contact_name") or ""),
                contact_number=str(payload.get("contact_number") or ""),
                contact_description=payload.get("contact_description"),
                contact_email=payload.get("contact_email"),
                contact_call=payload.get("contact_call"),
            )
        except ValueError as exc:
            return {"status": "invalid_contact", "message": str(exc)}
        return {
            "status": "contact_created",
            "contact_id": contact["id"],
            "message": f"Contato {contact['contact_name']} salvo com sucesso.",
        }

    router.register("contact", handle_contact)

    def handle_list_contacts(payload):
        contacts = list_contacts()
        if not contacts:
            return {"status": "empty", "message": "Nenhum contato cadastrado no rock.db ainda."}
        lines = [
            f"- {c['contact_name']} | {c['contact_number']}" + (f" | chamada: {c['contact_call']}" if c.get("contact_call") else "")
            for c in contacts
        ]
        return {
            "status": "ok",
            "contacts": contacts,
            "message": "Contatos cadastrados no rock.db:\n" + "\n".join(lines),
        }

    router.register("list_contacts", handle_list_contacts)

    def handle_goal(payload):
        target = str(payload.get("target") or "").strip()
        event_description = str(payload.get("event_description") or "").strip()
        owner_phone = normalize_phone(str(payload.get("owner_phone") or ""))
        if not target:
            return {"status": "needs_recipient", "message": "Informe com quem devo falar para confirmar o evento."}
        if not event_description:
            return {"status": "needs_goal", "message": "Informe qual evento devo confirmar."}
        if not owner_phone:
            return {"status": "needs_owner", "message": "Não consegui identificar quem iniciou este objetivo."}

        target_phone = normalize_phone(target) if is_phone_number(target) else resolve_contact(target, config.DB_PATH)
        if not target_phone:
            return {
                "status": "contact_not_found",
                "message": f"Não encontrei um número para '{target}'. Cadastre o contato antes de iniciar a confirmação.",
            }

        event_day = payload.get("event_day")
        fallback_question = (
            f"Oi! Estou confirmando {event_description}. "
            "Você pode me dizer onde será, que horas começa e o que precisamos levar?"
        )
        question = fallback_question
        if specialist_agent.is_available():
            question = specialist_agent.chat(
                event_description,
                extra_system_prompt=(
                    "Você está iniciando uma conversa em nome do Rock para confirmar um evento. "
                    "Escreva somente a primeira mensagem para o contato, em português brasileiro, "
                    "cordial e natural. Pergunte de forma clara o local, o horário e o que é necessário levar. "
                    "Não invente detalhes, não explique seu raciocínio e não use marcadores."
                ),
            ) or fallback_question
        try:
            delivery = send_whatsapp_message(target_phone, question)
        except requests.RequestException as exc:
            return {
                "status": "goal_delivery_failed",
                "message": f"Não consegui iniciar a conversa com {target}: o número não está disponível no WhatsApp ou a Evolution API falhou ({exc}).",
            }
        goal = goal_store.start_event_confirmation(
            owner_phone=owner_phone,
            target_phone=target_phone,
            target_name=target,
            event_description=event_description,
            event_day=event_day,
        )
        return {
            "status": "goal_started",
            "goal_id": goal["id"],
            "state": goal["status"],
            "delivery": delivery,
            "message": "Pergunta enviada. Vou aguardar a resposta sobre o local, horário e o que levar.",
        }

    router.register("goal", handle_goal)

    def handle_email(payload):
        tool = get_gmail_tool()
        operation = payload.get("operation", "list")
        if operation == "send":
            return tool.send(payload.get("to", ""), payload.get("subject", ""), payload.get("body", ""))
        if operation == "delegate":
            return get_email_delegation_manager().delegate(
                payload.get("to", ""),
                payload.get("subject", ""),
                payload.get("body", ""),
            )
        if operation == "list":
            return tool.list_messages(query=payload.get("query", ""))
        if operation == "read":
            return tool.get_message(payload.get("message_id", ""), include_body=True)
        if operation == "reply":
            return tool.reply(payload.get("message_id", ""), payload.get("body", ""))
        if operation == "mark_read":
            return tool.mark_as_read(payload.get("message_id", ""))
        if operation == "monitor":
            enabled = set_monitoring_enabled(payload.get("enabled", False))
            return {
                "status": "updated",
                "monitoring_enabled": enabled,
                "message": "Monitoramento contínuo configurado; a consulta automática será adicionada na próxima etapa.",
            }
        raise ValueError(f"Operação de e-mail desconhecida: {operation}")

    router.register("email", handle_email)
    router.register(
        "general",
        lambda payload: specialist_agent.chat(
            payload.get("text", ""),
            memory=memory,
        ),
    )

    return router


def poll_email_delegations() -> list[dict]:
    """Consulta respostas dos assuntos delegados sem bloquear quando não há tarefas."""
    try:
        manager = get_email_delegation_manager()
        if not manager.delegations:
            return []
        return manager.poll()
    except Exception as exc:
        print(f"⚠️ Não foi possível verificar respostas de e-mail: {exc}")
        return []


def run_voice_loop(
    router: Router,
    parser: IntentParser,
    memory: ConversationMemory,
    tts: TextToSpeech,
    stt: SpeechToText,
    specialist: Optional[SpecialistAgent] = None,
    owner_phone: str = "",
) -> None:
    """Executa o loop interativo em Modo Voz (Ouvidos com STT e Voz com TTS)."""
    mic_available = stt.is_microphone_available()
    if not mic_available:
        print("⚠️ [Aviso] Microfone ou PyAudio não detectado no sistema.")
        print("💡 Para digitar no terminal com resposta em áudio falado (TTS), prossiga abaixo.")

    while True:
        for notice in poll_email_delegations():
            print(f"\n📨 {notice['message']}")
            tts.speak(notice["message"])
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
            if intent == "reminder":
                payload = {**payload, "raw_text": user_input}
            if intent == "goal" and owner_phone:
                payload = {**payload, "owner_phone": owner_phone}
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
            tts.speak(format_for_speech(response_text, intent=intent))

        except Exception as exc:
            err_msg = f"Erro ao processar comando: {exc}"
            print(f"❌ {err_msg}")
            tts.speak(format_for_speech(err_msg))
            memory.add_assistant_message(err_msg)


def run_text_loop(
    router: Router,
    parser: IntentParser,
    memory: ConversationMemory,
    owner_phone: str = "",
) -> None:
    """Executa o loop interativo padrão em Modo Texto."""
    while True:
        for notice in poll_email_delegations():
            print(f"\n📨 {notice['message']}")
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
            if intent == "reminder":
                payload = {**payload, "raw_text": user_input}
            if intent == "goal" and owner_phone:
                payload = {**payload, "owner_phone": owner_phone}
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
    cli_parser.add_argument(
        "--owner-phone",
        default=config.OWNER_PHONE,
        help="Número do proprietário para objetivos iniciados neste terminal, com DDI e DDD.",
    )
    args = cli_parser.parse_args()
    owner_phone = normalize_phone(args.owner_phone)

    memory = ConversationMemory()
    specialist = SpecialistAgent(memory=memory)
    intent_parser = IntentParser()
    router = build_router(specialist=specialist, memory=memory)
    briefing = StartupBriefing(storage=SQLiteReminderStorage())

    if args.voz:
        tts = get_tts()
        stt = get_stt()
        briefing.startup_voice(tts, stt)
        run_voice_loop(
            router=router,
            parser=intent_parser,
            memory=memory,
            tts=tts,
            stt=stt,
            specialist=specialist,
            owner_phone=owner_phone,
        )
    else:
        briefing.startup_text()
        run_text_loop(
            router=router,
            parser=intent_parser,
            memory=memory,
            owner_phone=owner_phone,
        )


if __name__ == "__main__":
    main()
