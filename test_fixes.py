"""Testes manuais e individuais das correções da Fase 3."""

import time

from rock_assistant import config
from rock_assistant.core.intent_parser import ping_gemini
from rock_assistant.tools.stt import SpeechToText
from rock_assistant.tools.tts import TextToSpeech


def test_stt_timing() -> str:
    """Captura uma frase e mede separadamente a etapa após o fim da captura."""
    stt = SpeechToText()
    print(f"pause_threshold configurado: {stt.recognizer.pause_threshold if stt.recognizer else 'indisponível'}s")
    for index, name in enumerate(stt.list_microphones()):
        print(f"Microfone [{index}]: {name}")
    print(f"Microfone configurado: índice={stt.microphone_index}, nome={stt.microphone_name or 'padrão'}")
    started_at = time.perf_counter()
    text = stt.listen(timeout=10, phrase_time_limit=15)
    elapsed = time.perf_counter() - started_at
    transcription_time = None
    if stt.last_capture_finished_at and stt.last_transcription_finished_at:
        transcription_time = stt.last_transcription_finished_at - stt.last_capture_finished_at
    print(f"Transcrição: {text!r}")
    print(f"Tempo total de escuta e transcrição: {elapsed:.3f}s")
    print(
        "Tempo entre o fim da captura e o retorno da transcrição: "
        f"{transcription_time:.3f}s" if transcription_time is not None else "não medido (sem áudio capturado)"
    )
    return text


def test_tts_ptbr() -> bool:
    """Lista vozes e reproduz uma frase de validação em português brasileiro."""
    tts = TextToSpeech()
    voices = tts.engine.getProperty("voices") if tts.engine else []
    print("Vozes instaladas:")
    for voice in voices:
        print(f"- {voice.id}: {getattr(voice, 'name', '')} {getattr(voice, 'languages', '')}")
    print(f"Voz selecionada: {tts.voice_id or 'indisponível'}")
    success = tts.speak("Olá Lucas, sou o Rock. Testando a pronúncia correta em português do Brasil.")
    print(f"Reprodução TTS: {'sucesso' if success else 'falhou; verifique ALSA/aplay'}")
    return success


def test_gemini_ping_pong() -> bool:
    """Valida comunicação de ping-pong com a API do Google Gemini."""
    print("\n--- Teste de Ping-Pong com API do Gemini ---")
    status = ping_gemini()
    print(f"Resultado do ping: {status}")
    return status.get("success", False)


if __name__ == "__main__":
    test_stt_timing()
    test_tts_ptbr()
    test_gemini_ping_pong()