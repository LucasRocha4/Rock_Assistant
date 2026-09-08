"""Síntese de fala do Rock usando Piper e fallback final para pyttsx3."""

import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

try:
    import config
except ImportError:
    from rock_assistant import config

logger = logging.getLogger("rock.tts")


class TextToSpeech:
    """Converte texto em fala com Piper e usa pyttsx3 apenas como último recurso."""

    def __init__(self, rate: Optional[int] = None, volume: Optional[float] = None) -> None:
        self.rate = rate if rate is not None else getattr(config, "TTS_RATE", 175)
        self.volume = volume if volume is not None else getattr(config, "TTS_VOLUME", 1.0)
        self.backend = "piper"
        self.engine = None
        self.voice_id: Optional[str] = None
        self._player: Optional[subprocess.Popen] = None
        self._state_lock = threading.Lock()
        self._speak_lock = threading.Lock()

    @staticmethod
    def _prepare_text(text: str) -> str:
        """Remove formatação que tende a ser pronunciada de forma artificial."""
        prepared = re.sub(r"```(?:\w+)?\s*|```", "", text)
        prepared = re.sub(r"https?://\S+|www\.\S+", " um link ", prepared)
        prepared = re.sub(r"[*_#>`]", "", prepared)
        return re.sub(r"\s+", " ", prepared).strip()

    @property
    def _model_path(self) -> Path:
        return Path(getattr(config, "PIPER_MODEL_PATH", ""))

    @property
    def _piper_command(self) -> str:
        configured = str(getattr(config, "PIPER_COMMAND", "piper"))
        if shutil.which(configured):
            return configured
        venv_command = Path(sys.executable).with_name(configured)
        return str(venv_command) if venv_command.is_file() else configured

    def _piper_available(self) -> bool:
        return bool(shutil.which(self._piper_command) and self._model_path.is_file())

    def _select_player(self) -> Optional[str]:
        configured = getattr(config, "TTS_PLAYER", "")
        if configured:
            return configured if shutil.which(configured) else None
        return next((name for name in ("ffplay", "mpv", "pw-play", "aplay") if shutil.which(name)), None)

    def _temp_file(self) -> tempfile.NamedTemporaryFile:
        temp_dir = getattr(config, "TTS_TEMP_DIR", None)
        return tempfile.NamedTemporaryFile(suffix=".wav", dir=temp_dir, delete=False)

    def _piper_speed(self) -> float:
        return max(0.5, min(2.0, 175.0 / max(80, min(260, int(self.rate)))))

    def _build_player_command(self, player: str, audio_path: str) -> list[str]:
        if player == "ffplay":
            return [
                player,
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "quiet",
                "-volume",
                str(round(self.volume * 100)),
                audio_path,
            ]
        if player == "mpv":
            return [player, "--no-video", "--really-quiet", f"--volume={self.volume * 100}", audio_path]
        return [player, audio_path]

    def _play(self, audio_path: str) -> bool:
        player = self._select_player()
        if not player:
            logger.warning("Nenhum player de áudio encontrado para o Piper.")
            return False

        try:
            process = subprocess.Popen(
                self._build_player_command(player, audio_path),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            with self._state_lock:
                self._player = process
            return process.wait() == 0
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("Falha ao reproduzir áudio Piper: %s", exc)
            return False
        finally:
            with self._state_lock:
                self._player = None

    def _speak_with_piper(self, text: str) -> bool:
        if not self._piper_available():
            return False

        audio_file = self._temp_file()
        audio_file.close()
        try:
            command = [
                self._piper_command,
                "--model",
                str(self._model_path),
                "--output_file",
                audio_file.name,
                "--length_scale",
                str(self._piper_speed()),
            ]
            subprocess.run(
                command,
                input=text,
                text=True,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return self._play(audio_file.name)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("Falha ao sintetizar com Piper: %s", exc)
            return False
        finally:
            try:
                os.unlink(audio_file.name)
            except FileNotFoundError:
                pass

    def _init_pyttsx3(self) -> bool:
        if self.engine is not None:
            return True
        try:
            import pyttsx3

            self.engine = pyttsx3.init()
            self.engine.setProperty("rate", max(80, min(260, int(self.rate))))
            self.engine.setProperty("volume", max(0.0, min(1.0, float(self.volume))))
            voices = self.engine.getProperty("voices") or []
            for voice in voices:
                metadata = f"{voice.id} {getattr(voice, 'name', '')} {getattr(voice, 'languages', [])}".lower()
                if "pt-br" in metadata or "brazil" in metadata:
                    self.voice_id = voice.id
                    self.engine.setProperty("voice", self.voice_id)
                    break
            return True
        except Exception as exc:
            logger.warning("Fallback pyttsx3 indisponível: %s", exc)
            self.engine = None
            return False

    def _speak_with_pyttsx3(self, text: str) -> bool:
        if not self._init_pyttsx3():
            return False
        try:
            self.engine.say(text)
            self.engine.runAndWait()
            self.backend = "pyttsx3"
            return True
        except Exception as exc:
            logger.warning("Falha no fallback pyttsx3: %s", exc)
            return False

    def is_available(self) -> bool:
        """Indica se Piper está pronto ou se o fallback pyttsx3 pode ser usado."""
        return self._piper_available() or self._init_pyttsx3()

    def set_rate(self, rate: int) -> None:
        self.rate = max(80, min(260, int(rate)))
        if self.engine is not None:
            self.engine.setProperty("rate", self.rate)

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(1.0, float(volume)))
        if self.engine is not None:
            self.engine.setProperty("volume", self.volume)

    def speak(self, text: str) -> bool:
        """Sintetiza e reproduz uma mensagem, preferindo Piper."""
        cleaned_text = self._prepare_text((text or "").strip())
        if not cleaned_text:
            return False

        with self._speak_lock:
            if self._speak_with_piper(cleaned_text):
                self.backend = "piper"
                return True
            return self._speak_with_pyttsx3(cleaned_text)

    def stop(self) -> None:
        """Interrompe a reprodução atual sem bloquear esperando o lock de fala."""
        with self._state_lock:
            player = self._player
        if player is not None and player.poll() is None:
            player.terminate()
        if self.engine is not None:
            try:
                self.engine.stop()
            except Exception as exc:
                logger.warning("Erro ao interromper pyttsx3: %s", exc)


_global_tts_instance: Optional[TextToSpeech] = None


def get_tts() -> TextToSpeech:
    """Obtém a instância global de TextToSpeech."""
    global _global_tts_instance
    if _global_tts_instance is None:
        _global_tts_instance = TextToSpeech()
    return _global_tts_instance


def speak(text: str) -> bool:
    return get_tts().speak(text)


def stop() -> None:
    get_tts().stop()
