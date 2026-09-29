"""Pipeline de processamento de voz para chamadas telefônicas (STT -> LLM -> TTS)."""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from rock_assistant.setup import config
from rock_assistant.core.local_llm import LocalLLMAgent
from rock_assistant.tools.tts import TextToSpeech, get_tts
from rock_assistant.tools.stt import SpeechToText
from telephony.core.session import CallSession

logger = logging.getLogger("rock.telephony.pipeline")

PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompts" / "voice_system.md"

DEFAULT_VOICE_SYSTEM_PROMPT = (
    "Você é o Rock, o assistente pessoal de IA do usuário, conduzindo uma conversa telefônica.\n"
    "Responda sempre em português do Brasil de forma natural, amigável e direta.\n"
    "Seja muito conciso: fale no máximo 2 a 3 frases curtas por turno.\n"
    "Não utilize formatação markdown, listas, links ou tabelas, pois sua resposta será sintetizada em voz.\n"
    "Nunca invente fatos. Se for solicitado falar com um humano, informe que fará a transferência ou registrará o recado."
)


def load_voice_system_prompt() -> str:
    """Carrega o prompt de sistema especializado para voz."""
    if PROMPT_FILE.exists():
        try:
            return PROMPT_FILE.read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.warning("Falha ao ler %s: %s. Usando prompt padrão.", PROMPT_FILE, exc)
    return DEFAULT_VOICE_SYSTEM_PROMPT


class VoicePipeline:
    """Orquestra o ciclo conversacional de voz durante a chamada."""

    def __init__(
        self,
        llm_agent: Optional[LocalLLMAgent] = None,
        tts: Optional[TextToSpeech] = None,
        stt: Optional[SpeechToText] = None,
    ) -> None:
        self.system_prompt = load_voice_system_prompt()
        self.llm = llm_agent or LocalLLMAgent(
            model=getattr(config, "OLLAMA_MODEL", "llama3.2"),
            system_prompt=self.system_prompt,
        )
        self.tts = tts or get_tts()
        self.stt = stt

    def _get_stt(self) -> SpeechToText:
        if self.stt is None:
            self.stt = SpeechToText()
        return self.stt

    @staticmethod
    def clean_text_for_speech(text: str) -> str:
        """Limpa textos para evitar artefatos indesejados no TTS."""
        cleaned = re.sub(r"[*_#>`]", "", text)
        cleaned = re.sub(r"https?://\S+|www\.\S+", " link ", cleaned)
        cleaned = re.sub(r"```.*?```", "", cleaned, flags=re.DOTALL)
        cleaned = re.sub(r"\{.*?\}", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def process_turn(self, session: CallSession, user_text: str) -> str:
        """Executa um turno de diálogo do usuário com o Llama 3.2 mantendo o histórico da chamada."""
        cleaned_user_text = user_text.strip()
        if not cleaned_user_text:
            return "Não consegui te ouvir bem. Você pode repetir, por favor?"

        session.add_user_message(cleaned_user_text)

        # Constrói o histórico da sessão
        history = session.get_dialogue_history()

        # Monta o prompt do sistema contextualizado com script (se for outbound)
        system_content = self.system_prompt
        if session.script:
            system_content += f"\n\nContexto / Objetivo desta ligação: {session.script}"

        messages: List[Dict[str, str]] = [{"role": "system", "content": system_content}]
        messages.extend(history)

        try:
            client = self.llm._get_client()
            response = client.chat(
                model=self.llm.model,
                messages=messages,
                options={"temperature": 0.3},
            )
            raw_reply = response.get("message", {}).get("content", "")
        except Exception as exc:
            logger.error("Erro ao chamar Llama 3.2 para chamada %s: %s", session.channel_id, exc)
            raw_reply = "Desculpe, tive uma instabilidade momentânea. Pode repetir o que disse?"

        assistant_reply = self.clean_text_for_speech(raw_reply)
        if not assistant_reply:
            assistant_reply = "Entendido. Como posso te ajudar?"

        session.add_assistant_message(assistant_reply)
        return assistant_reply

    def synthesize_audio_file(self, text: str, output_path: Optional[Path] = None) -> Path:
        """Gera um arquivo WAV 8kHz ou 16kHz compatível com Asterisk para reprodução."""
        cleaned_text = self.clean_text_for_speech(text)
        piper_cmd = self.tts._piper_command
        model_path = self.tts._model_path

        if output_path is None:
            temp_dir = getattr(config, "TELEPHONY_RECORDINGS_DIR", Path(tempfile.gettempdir()))
            temp_dir.mkdir(parents=True, exist_ok=True)
            output_file = tempfile.NamedTemporaryFile(suffix=".wav", dir=str(temp_dir), delete=False)
            output_path = Path(output_file.name)
            output_file.close()

        if self.tts._piper_available():
            try:
                subprocess.run(
                    [
                        piper_cmd,
                        "--model",
                        str(model_path),
                        "--output_file",
                        str(output_path),
                        "--length_scale",
                        "1.0",
                    ],
                    input=cleaned_text,
                    text=True,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return output_path
            except (OSError, subprocess.SubprocessError) as exc:
                logger.warning("Falha ao gerar WAV com Piper: %s. Tentando fallback.", exc)

        # Fallback: cria arquivo de áudio via pyttsx3 se disponível
        try:
            if self.tts._init_pyttsx3() and self.tts.engine:
                self.tts.engine.save_to_file(cleaned_text, str(output_path))
                self.tts.engine.runAndWait()
                return output_path
        except Exception as exc:
            logger.warning("Falha ao gerar áudio com pyttsx3 fallback: %s", exc)

        # Se nenhum método gerou o arquivo, cria um arquivo de onda vazio ou existente
        if not output_path.exists():
            output_path.touch()

        return output_path

    def transcribe_audio_file(self, audio_path: Path) -> str:
        """Transcreve arquivo de áudio gravado do canal Asterisk."""
        if not audio_path.exists():
            return ""

        try:
            import whisper

            model = whisper.load_model(getattr(config, "STT_MODEL", "tiny"))
            result = model.transcribe(str(audio_path), language="pt")
            return result.get("text", "").strip()
        except Exception as exc:
            logger.warning("Falha na transcrição Whisper do arquivo %s: %s", audio_path, exc)
            return ""
