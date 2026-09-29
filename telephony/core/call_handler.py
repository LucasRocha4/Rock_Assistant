"""Manipulador de chamadas Asterisk ARI (Rota A) integrado ao Llama 3.2 e Piper."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin

import requests

from rock_assistant.setup import config
from telephony.core.pipeline import VoicePipeline
from telephony.core.session import CallDirection, CallSession, CallState, SessionManager, get_session_manager

logger = logging.getLogger("rock.telephony.call_handler")


class CallHandler:
    """Recebe eventos do Asterisk ARI e conduz chamadas como assistente Rock."""

    def __init__(
        self,
        ari_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        app_name: Optional[str] = None,
        session_manager: Optional[SessionManager] = None,
        pipeline: Optional[VoicePipeline] = None,
    ) -> None:
        self.ari_url = (ari_url or getattr(config, "ASTERISK_ARI_URL", "http://127.0.0.1:8088/ari")).rstrip("/")
        self.username = username or getattr(config, "ASTERISK_ARI_USER", "rock")
        self.password = password or getattr(config, "ASTERISK_ARI_PASS", "")
        self.app_name = app_name or getattr(config, "ASTERISK_STASIS_APP", "rock_agent")
        self.endpoint_prefix = getattr(config, "ASTERISK_PJSIP_ENDPOINT", "PJSIP")

        self.session_manager = session_manager or get_session_manager()
        self.pipeline = pipeline or VoicePipeline()

        self._ws_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._listener_thread: Optional[threading.Thread] = None
        self._running = False

    @property
    def auth(self) -> tuple[str, str]:
        return (self.username, self.password)

    def _api_url(self, path: str) -> str:
        clean_path = path.lstrip("/")
        return f"{self.ari_url}/{clean_path}"

    # -------------------------------------------------------------------------
    # Operações REST com Asterisk ARI
    # -------------------------------------------------------------------------

    def is_connected(self) -> bool:
        """Verifica se o servidor Asterisk ARI está acessível."""
        try:
            url = self._api_url(f"applications/{self.app_name}")
            resp = requests.get(url, auth=self.auth, timeout=3)
            return resp.status_code in (200, 404)
        except requests.RequestException:
            return False

    def answer_channel(self, channel_id: str) -> bool:
        """Atende o canal no Asterisk."""
        try:
            url = self._api_url(f"channels/{channel_id}/answer")
            resp = requests.post(url, auth=self.auth, timeout=5)
            if resp.status_code in (200, 204):
                logger.info("Canal %s atendido com sucesso.", channel_id)
                return True
            logger.warning("Falha ao atender canal %s: status %s - %s", channel_id, resp.status_code, resp.text)
            return False
        except requests.RequestException as exc:
            logger.error("Erro ao atender canal %s no ARI: %s", channel_id, exc)
            return False

    def hangup_channel(self, channel_id: str, reason: str = "normal") -> bool:
        """Encerra a chamada no canal."""
        try:
            url = self._api_url(f"channels/{channel_id}")
            resp = requests.delete(url, auth=self.auth, params={"reason": reason}, timeout=5)
            session = self.session_manager.get_session(channel_id)
            if session:
                session.set_state(CallState.ENDED)
            self.session_manager.remove_session(channel_id)
            return resp.status_code in (200, 204)
        except requests.RequestException as exc:
            logger.error("Erro ao desligar canal %s no ARI: %s", channel_id, exc)
            self.session_manager.remove_session(channel_id)
            return False

    def play_media_to_channel(self, channel_id: str, media_uri: str) -> Optional[str]:
        """Inicia reprodução de um media_uri (ex: sound:hello-world ou recording:nome) no canal."""
        try:
            url = self._api_url(f"channels/{channel_id}/play")
            resp = requests.post(url, auth=self.auth, json={"media": media_uri}, timeout=5)
            if resp.status_code in (200, 201):
                playback_data = resp.json()
                playback_id = playback_data.get("id")
                logger.info("Playback %s iniciado no canal %s (media: %s)", playback_id, channel_id, media_uri)
                return playback_id
            logger.warning("Falha ao tocar media no canal %s: %s", channel_id, resp.text)
            return None
        except requests.RequestException as exc:
            logger.error("Erro ao executar play no ARI para canal %s: %s", channel_id, exc)
            return None

    def speak_to_channel(self, channel_id: str, text: str) -> bool:
        """Sintetiza texto via VoicePipeline e reproduz no canal."""
        session = self.session_manager.get_session(channel_id)
        if session:
            session.add_assistant_message(text)

        try:
            # Sintetiza em arquivo WAV
            audio_path = self.pipeline.synthesize_audio_file(text)
            # No Asterisk ARI, se o arquivo estiver no diretório de recordings ou sounds:
            sound_name = audio_path.stem
            media_uri = f"sound:{sound_name}"
            self.play_media_to_channel(channel_id, media_uri)
            return True
        except Exception as exc:
            logger.error("Erro ao sintetizar e reproduzir fala para canal %s: %s", channel_id, exc)
            return False

    # -------------------------------------------------------------------------
    # Condução de Chamadas (Inbound & Outbound)
    # -------------------------------------------------------------------------

    def start_outbound_call(self, recipient: str, script: Optional[str] = None) -> Dict[str, Any]:
        """Origina uma ligação telefônica via Asterisk ARI e inicia a condução pelo Rock."""
        target = recipient.strip()
        endpoint = f"{self.endpoint_prefix}/{target}"

        logger.info("Iniciando chamada outbound para '%s' (endpoint: %s)", target, endpoint)

        payload = {
            "endpoint": endpoint,
            "app": self.app_name,
            "appArgs": f"outbound,{target}",
            "callerId": "Rock Assistant",
            "timeout": 60,
        }

        try:
            url = self._api_url("channels")
            resp = requests.post(url, auth=self.auth, json=payload, timeout=10)
            if resp.status_code in (200, 201):
                channel_info = resp.json()
                channel_id = channel_info.get("id", f"outbound-{int(time.time())}")
                session = self.session_manager.create_session(
                    channel_id=channel_id,
                    direction=CallDirection.OUTBOUND,
                    recipient=target,
                    script=script,
                    metadata={"channel_info": channel_info},
                )
                return {
                    "status": "originating",
                    "channel_id": channel_id,
                    "recipient": target,
                    "direction": "outbound",
                    "message": f"Ligação originada com sucesso para {target}. Aguardando atendimento.",
                }
            
            error_msg = f"Asterisk recusou originação (status {resp.status_code}): {resp.text}"
            logger.warning(error_msg)
            return {
                "status": "error",
                "recipient": target,
                "error": error_msg,
                "message": f"Não foi possível completar a chamada para {target}.",
            }
        except requests.RequestException as exc:
            logger.error("Falha ao comunicar com Asterisk ARI para outbound: %s", exc)
            return {
                "status": "error",
                "recipient": target,
                "error": str(exc),
                "message": f"Erro de conexão com o Asterisk ao tentar ligar para {target}.",
            }

    def handle_incoming_call(self, channel_id: str, caller_id: str = "") -> Dict[str, Any]:
        """Atende chamada recebida e inicia a interação como assistente."""
        logger.info("Atendendo chamada inbound no canal %s (origem: %s)", channel_id, caller_id)

        session = self.session_manager.get_session(channel_id)
        if not session:
            session = self.session_manager.create_session(
                channel_id=channel_id,
                direction=CallDirection.INBOUND,
                caller_id=caller_id,
            )

        answered = self.answer_channel(channel_id)
        session.set_state(CallState.IN_CALL if answered else CallState.FAILED)

        if answered:
            greeting = "Olá! Aqui é o Rock, assistente virtual. Como posso te ajudar hoje?"
            self.speak_to_channel(channel_id, greeting)
            return {
                "status": "answered",
                "channel_id": channel_id,
                "caller_id": caller_id,
                "message": "Chamada atendida com sucesso pelo Rock.",
            }

        return {
            "status": "error",
            "channel_id": channel_id,
            "error": "Falha ao atender canal no Asterisk.",
            "message": "Não foi possível atender a chamada no Asterisk.",
        }

    # -------------------------------------------------------------------------
    # Processamento de Eventos Stasis
    # -------------------------------------------------------------------------

    def on_stasis_start(self, event: Dict[str, Any]) -> None:
        """Manipula evento StasisStart emitido pelo Asterisk."""
        channel = event.get("channel", {})
        channel_id = channel.get("id", "")
        args = event.get("args", [])
        caller = channel.get("caller", {}).get("number", "")

        logger.info("Evento StasisStart recebido para canal %s com args %s", channel_id, args)

        session = self.session_manager.get_session(channel_id)
        if not session:
            direction = CallDirection.OUTBOUND if "outbound" in args else CallDirection.INBOUND
            session = self.session_manager.create_session(
                channel_id=channel_id,
                direction=direction,
                caller_id=caller,
            )

        session.set_state(CallState.IN_CALL)

        # Saudação inicial ou abertura do script
        if session.direction == CallDirection.OUTBOUND:
            if session.script:
                initial_prompt = f"Inicie a ligação cumprimentando e dizendo o objetivo: {session.script}"
                first_utterance = self.pipeline.process_turn(session, initial_prompt)
            else:
                first_utterance = "Olá! Aqui é o Rock, assistente virtual. Tudo bem?"
            self.speak_to_channel(channel_id, first_utterance)
        else:
            greeting = "Olá! Aqui é o Rock, assistente virtual. Como posso te ajudar?"
            self.speak_to_channel(channel_id, greeting)

    def on_stasis_end(self, event: Dict[str, Any]) -> None:
        """Manipula evento StasisEnd emitido pelo Asterisk."""
        channel = event.get("channel", {})
        channel_id = channel.get("id", "")
        logger.info("Evento StasisEnd recebido para canal %s", channel_id)
        self.session_manager.remove_session(channel_id)

    def handle_user_speech(self, channel_id: str, user_speech_text: str) -> str:
        """Processa a fala do usuário recebida pelo canal e responde via TTS."""
        session = self.session_manager.get_session(channel_id)
        if not session:
            logger.warning("Sessão não encontrada para o canal %s", channel_id)
            return ""

        reply = self.pipeline.process_turn(session, user_speech_text)
        self.speak_to_channel(channel_id, reply)
        return reply


_default_call_handler: Optional[CallHandler] = None


def get_call_handler() -> CallHandler:
    """Retorna a instância singleton do CallHandler."""
    global _default_call_handler
    if _default_call_handler is None:
        _default_call_handler = CallHandler()
    return _default_call_handler
