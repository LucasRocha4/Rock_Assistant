"""Módulo de Síntese de Fala (Text-to-Speech - TTS) do Rock Assistant."""

import logging
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Optional

# Garante acesso a configurações do projeto
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

try:
    import config
    from config import TTS_RATE, TTS_VOLUME
except ImportError:
    from rock_assistant import config
    from rock_assistant.config import TTS_RATE, TTS_VOLUME

logger = logging.getLogger("rock.tts")


class TextToSpeech:
    """Transforma as respostas de texto do Rock em áudio falado utilizando pyttsx3 / espeak-ng."""

    def __init__(
        self,
        rate: Optional[int] = None,
        volume: Optional[float] = None,
    ) -> None:
        self.rate = rate if rate is not None else getattr(config, "TTS_RATE", 175)
        self.volume = volume if volume is not None else getattr(config, "TTS_VOLUME", 1.0)
        self.engine = None
        self.voice_id: Optional[str] = None
        self._lock = threading.Lock()
        self._init_engine()

    def _init_engine(self) -> None:
        """Inicializa o motor de síntese de voz pyttsx3."""
        try:
            import pyttsx3
            self.engine = pyttsx3.init()
            self.rate = 160
            self.volume = 1.0
            self.engine.setProperty("rate", self.rate)
            self.engine.setProperty("volume", self.volume)

            voices = self.engine.getProperty("voices") or []
            selected_voice = self._select_portuguese_voice(voices)
            if selected_voice is not None:
                self.voice_id = selected_voice.id
                self.engine.setProperty("voice", self.voice_id)
                logger.info(f"Voz TTS selecionada: {self.voice_id}")
            else:
                logger.warning("Nenhuma voz PT-BR/PT foi encontrada no espeak-ng.")
        except Exception as exc:
            logger.warning(f"Não foi possível inicializar o motor TTS pyttsx3: {exc}")
            self.engine = None

    @staticmethod
    def _select_portuguese_voice(voices):
        """Seleciona PT-BR por idioma exato, sem confundir inglês com português."""
        candidates = []
        for voice in voices:
            raw_languages = getattr(voice, "languages", []) or []
            language_text = " ".join(
                item.decode(errors="ignore") if isinstance(item, bytes) else str(item)
                for item in raw_languages
            ).lower()
            metadata = f"{voice.id} {getattr(voice, 'name', '')} {language_text}".lower()
            language_codes = set(re.findall(r"(?<![a-z])pt(?:[-_]br)?(?![a-z])", metadata))
            if "pt-br" in language_codes or "pt_br" in language_codes or "brazil" in metadata:
                return voice
            if "pt" in language_codes or "portuguese" in metadata:
                candidates.append(voice)
        return candidates[0] if candidates else None

    def _speak_with_gtts(self, text: str) -> bool:
        """Usa gTTS opcionalmente quando o espeak-ng não está disponível."""
        try:
            from gtts import gTTS

            player = next((command for command in ("mpg123", "mpv", "ffplay") if shutil.which(command)), None)
            if not player:
                return False

            with tempfile.NamedTemporaryFile(suffix=".mp3") as audio_file:
                gTTS(text=text, lang="pt", tld="com.br").save(audio_file.name)
                subprocess.run(
                    [player, "-q", audio_file.name] if player == "mpg123" else [player, audio_file.name],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            return True
        except Exception as exc:
            logger.warning(f"Fallback gTTS indisponível: {exc}")
            return False

    def is_available(self) -> bool:
        """Verifica se o motor de voz está instanciado e operacional."""
        return self.engine is not None

    def set_rate(self, rate: int) -> None:
        """Ajusta a velocidade de fala (palavras por minuto)."""
        self.rate = rate
        if self.engine is not None:
            try:
                self.engine.setProperty("rate", self.rate)
            except Exception:
                pass

    def set_volume(self, volume: float) -> None:
        """Ajusta o volume do áudio (escala de 0.0 a 1.0)."""
        self.volume = max(0.0, min(1.0, volume))
        if self.engine is not None:
            try:
                self.engine.setProperty("volume", self.volume)
            except Exception:
                pass

    def speak(self, text: str) -> bool:
        """Sintetiza e reproduz o texto fornecido.

        Args:
            text: Texto a ser falado pelo assistente.

        Returns:
            bool: True se o áudio foi reproduzido com sucesso, False em caso de falha.
        """
        cleaned_text = (text or "").strip()
        if not cleaned_text:
            return False

        with self._lock:
            try:
                if self.engine is None:
                    self._init_engine()

                if self.engine is not None:
                    self.engine.say(cleaned_text)
                    self.engine.runAndWait()
                    return True
                else:
                    logger.warning(f"[TTS Offline] Mensagem que seria sintetizada: {cleaned_text}")
                    return self._speak_with_gtts(cleaned_text)
            except Exception as exc:
                logger.warning(f"Falha na reprodução de áudio TTS: {exc}")
                # Tenta reinicializar o motor para as próximas chamadas
                self._init_engine()
                return self._speak_with_gtts(cleaned_text)

    def stop(self) -> None:
        """Interrompe imediatamente a reprodução de fala em andamento."""
        with self._lock:
            if self.engine is not None:
                try:
                    self.engine.stop()
                except Exception as exc:
                    logger.warning(f"Erro ao tentar parar TTS: {exc}")


_global_tts_instance: Optional[TextToSpeech] = None


def get_tts() -> TextToSpeech:
    """Obtém a instância global singleton de TextToSpeech."""
    global _global_tts_instance
    if _global_tts_instance is None:
        _global_tts_instance = TextToSpeech()
    return _global_tts_instance


def speak(text: str) -> bool:
    """Função utilitária direta para sintetizar e falar texto."""
    return get_tts().speak(text)


def stop() -> None:
    """Função utilitária direta para interromper a fala."""
    get_tts().stop()
