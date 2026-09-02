"""Módulo de Reconhecimento de Fala (Speech-to-Text - STT) do Rock Assistant."""

import logging
import os
import sys
from pathlib import Path
from typing import Optional

# Garante acesso a configurações do projeto
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

try:
    import config
    from config import STT_MODEL, VOICE_LANGUAGE
except ImportError:
    from rock_assistant import config
    from rock_assistant.config import STT_MODEL, VOICE_LANGUAGE

logger = logging.getLogger("rock.stt")


class SpeechToText:
    """Captura áudio do microfone e transcreve para texto utilizando SpeechRecognition e Whisper."""

    def __init__(
        self,
        model_name: Optional[str] = None,
        language: Optional[str] = None,
        use_whisper: bool = True,
    ) -> None:
        self.model_name = model_name or getattr(config, "STT_MODEL", "tiny")
        self.language = language or getattr(config, "VOICE_LANGUAGE", "pt-BR")
        self.use_whisper = use_whisper
        self.recognizer = None
        self.last_capture_finished_at: Optional[float] = None
        self.last_transcription_finished_at: Optional[float] = None
        self.microphone_index = self._configured_microphone_index()
        self.microphone_name = os.getenv("MICROPHONE_NAME", getattr(config, "MICROPHONE_NAME", ""))
        self._init_recognizer()

    @staticmethod
    def _configured_microphone_index() -> Optional[int]:
        """Lê opcionalmente o índice ALSA/PyAudio definido pelo usuário."""
        value = os.getenv("MICROPHONE_INDEX", getattr(config, "MICROPHONE_INDEX", "0"))
        try:
            return int(value) if value != "" else None
        except ValueError:
            logger.warning("MICROPHONE_INDEX inválido; usando o microfone padrão.")
            return None

    def list_microphones(self) -> list[str]:
        """Retorna os nomes dos microfones reconhecidos pelo SpeechRecognition."""
        if not self.is_available():
            return []
        try:
            import speech_recognition as sr
            return list(sr.Microphone.list_microphone_names())
        except Exception as exc:
            logger.warning(f"Não foi possível listar microfones: {exc}")
            return []

    def _microphone(self):
        """Cria o microfone Fifine configurado ou usa o dispositivo padrão."""
        import speech_recognition as sr

        if self.microphone_index is not None:
            return sr.Microphone(device_index=self.microphone_index)
        if self.microphone_name:
            for index, name in enumerate(self.list_microphones()):
                if self.microphone_name.lower() in name.lower():
                    self.microphone_index = index
                    return sr.Microphone(device_index=index)
            logger.warning(f"Microfone '{self.microphone_name}' não foi encontrado; usando o padrão.")
        return sr.Microphone()

    def _init_recognizer(self) -> None:
        """Inicializa o componente Recognizer do SpeechRecognition."""
        try:
            import speech_recognition as sr
            self.recognizer = sr.Recognizer()
            self.recognizer.energy_threshold = 300
            self.recognizer.dynamic_energy_threshold = True
            self.recognizer.pause_threshold = 3.0
        except Exception as exc:
            logger.warning(f"Não foi possível inicializar SpeechRecognition: {exc}")
            self.recognizer = None

    def is_available(self) -> bool:
        """Verifica se o componente Recognizer está carregado."""
        return self.recognizer is not None

    def is_microphone_available(self) -> bool:
        """Verifica se há um dispositivo de microfone com PyAudio ou arecord/pw-record funcional."""
        if not self.is_available():
            return False
        try:
            import speech_recognition as sr
            with self._microphone() as source:
                return True
        except Exception:
            # O executável existir não garante que a placa configurada esteja disponível.
            import shutil
            import subprocess

            if shutil.which("arecord"):
                device = f"plughw:{self.microphone_index},0" if self.microphone_index is not None else "default"
                try:
                    subprocess.run(
                        ["arecord", "-q", "-D", device, "-d", "1", "-f", "S16_LE", "-c", "1", "-t", "raw", "/dev/null"],
                        check=True,
                        timeout=3,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    return True
                except (OSError, subprocess.SubprocessError):
                    return False
            return bool(shutil.which("pw-record"))

    def _record_with_cli(self, duration: int = 5) -> Optional[Path]:
        """Grava áudio do microfone usando arecord ou pw-record em arquivo temporário."""
        import shutil
        import subprocess
        import tempfile

        temp_wav = Path(tempfile.gettempdir()) / f"rock_input_{tempfile.mktemp()[-8:]}.wav"
        
        if shutil.which("arecord"):
            device = f"plughw:{self.microphone_index},0" if self.microphone_index is not None else "default"
            cmd = ["arecord", "-q", "-D", device, "-d", str(duration), "-r", "16000", "-f", "S16_LE", "-c", "1", "-t", "wav", str(temp_wav)]
        elif shutil.which("pw-record"):
            cmd = ["pw-record", "--rate", "16000", "--channels", "1", str(temp_wav)]
        else:
            return None

        try:
            subprocess.run(cmd, check=True, timeout=duration + 3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if temp_wav.exists() and temp_wav.stat().st_size > 44:
                return temp_wav
        except Exception as exc:
            logger.warning(f"Erro ao capturar áudio via CLI ({cmd[0]}): {exc}")
            if temp_wav.exists():
                try:
                    temp_wav.unlink()
                except Exception:
                    pass
        return None

    def listen(
        self,
        timeout: Optional[int] = 10,
        phrase_time_limit: Optional[int] = 15,
    ) -> str:
        """Escuta o microfone do usuário com tempo limite e retorna o texto transcrito.

        Args:
            timeout: Tempo limite em segundos para aguardar o início da fala (padrão: 10s).
            phrase_time_limit: Duração máxima da frase gravada em segundos (padrão: 15s).

        Returns:
            str: Texto transcrito em minúsculas ou string vazia em caso de silêncio/erro.
        """
        if not self.is_available():
            logger.warning("Módulo de reconhecimento de voz não disponível.")
            return ""

        import speech_recognition as sr

        # 1. Tentativa via SpeechRecognition com PyAudio
        try:
            with self._microphone() as source:
                # Calibra sensibilidade para ruído ambiente
                self.recognizer.adjust_for_ambient_noise(source, duration=0.4)
                audio = self.recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=phrase_time_limit,
                )
            import time
            self.last_capture_finished_at = time.perf_counter()

            # Transcrição via Whisper ou Google STT
            if self.use_whisper:
                try:
                    text = self.recognizer.recognize_whisper(
                        audio,
                        model=self.model_name,
                        language="pt",
                    )
                    if text and text.strip():
                        self.last_transcription_finished_at = time.perf_counter()
                        return text.strip()
                except Exception as w_exc:
                    logger.debug(f"Transcrição Whisper indisponível, usando fallback Google STT: {w_exc}")

            try:
                text = self.recognizer.recognize_google(
                    audio,
                    language=self.language,
                )
                self.last_transcription_finished_at = time.perf_counter()
                return text.strip() if text else ""
            except sr.UnknownValueError:
                logger.info("Áudio capturado, mas fala não compreendida.")
                return ""
            except sr.RequestError as req_err:
                logger.warning(f"Falha no serviço online de STT: {req_err}")
                return ""

        except (AttributeError, OSError) as portaudio_err:
            # Fallback direto: PyAudio não disponível no ambiente, grava via arecord / pw-record
            logger.info("Utilizando backend de captura nativo do Linux (arecord/pw-record)...")
            duration = phrase_time_limit or 5
            temp_wav = self._record_with_cli(duration=duration)
            if not temp_wav:
                return ""

            try:
                text = self.transcribe_audio_file(temp_wav)
                return text
            finally:
                try:
                    if temp_wav.exists():
                        temp_wav.unlink()
                except Exception:
                    pass

        except sr.WaitTimeoutError:
            logger.info("Tempo limite de escuta atingido (nenhum áudio detectado).")
            return ""
        except Exception as exc:
            logger.error(f"Erro inesperado durante a captura de áudio STT: {exc}")
            return ""

    def transcribe_audio_file(self, file_path: str | Path) -> str:
        """Transcreve um arquivo de áudio pré-gravado (WAV/FLAC/AIFF)."""
        if not self.is_available():
            return ""

        import speech_recognition as sr

        path_obj = Path(file_path)
        if not path_obj.exists():
            logger.error(f"Arquivo de áudio não encontrado: {file_path}")
            return ""

        try:
            with sr.AudioFile(str(path_obj)) as source:
                audio = self.recognizer.record(source)

            if self.use_whisper:
                try:
                    text = self.recognizer.recognize_whisper(
                        audio,
                        model=self.model_name,
                        language="pt",
                    )
                    if text and text.strip():
                        return text.strip()
                except Exception:
                    pass

            try:
                return self.recognizer.recognize_google(audio, language=self.language)
            except Exception:
                return ""

        except Exception as exc:
            logger.error(f"Erro ao transcrever arquivo de áudio: {exc}")
            return ""


_global_stt_instance: Optional[SpeechToText] = None


def get_stt() -> SpeechToText:
    """Obtém a instância global singleton de SpeechToText."""
    global _global_stt_instance
    if _global_stt_instance is None:
        _global_stt_instance = SpeechToText()
    return _global_stt_instance


def listen(timeout: Optional[int] = 10, phrase_time_limit: Optional[int] = 15) -> str:
    """Função utilitária direta para escutar o microfone."""
    return get_stt().listen(timeout=timeout, phrase_time_limit=phrase_time_limit)
