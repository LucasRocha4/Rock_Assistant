# Telefonia (Asterisk ARI + Llama 3.2) — Rota A

Módulo de telefonia do **Rock Assistant** para atendimento e realização de chamadas telefônicas via **Asterisk (ARI - Asterisk REST Interface)** com inteligência local orientada por **Llama 3.2 (Ollama)** e síntese de voz com **Piper TTS**.

---

## 1. Arquitetura

```
               +--------------------------------------------+
               |              Asterisk PBX                  |
               | (PJSIP / Softphone / Tronco PSTN / DID)    |
               +---------------------+----------------------+
                                     |
                          Stasis(rock_agent)
                                     |
                          ARI (REST + WebSocket)
                                     v
                 +---------------------------------------+
                 |    telephony/core/call_handler.py     |
                 |      (CallHandler & Sessões)          |
                 +-------------------+-------------------+
                                     |
                       +-------------+-------------+
                       |                           |
                       v                           v
          +-------------------------+ +-------------------------+
          | telephony/core/pipeline | | telephony/core/session  |
          |  (STT -> LLM -> TTS)    | |  (Histórico & Estados)  |
          +------------+------------+ +-------------------------+
                       |
        +--------------+---------------+
        |                              |
        v                              v
+----------------+             +----------------+
|  LocalLLMAgent |             | TextToSpeech   |
|   (Llama 3.2)  |             |  (Piper TTS)   |
+----------------+             +----------------+
```

---

## 2. Estrutura de Arquivos

- `telephony/config/`
  - `ari.conf.example`: Configuração de usuário ARI com permissões completas.
  - `extensions.conf.example`: Dialplan com contexto `[rock-inbound]` chamando `Stasis(rock_agent)`.
  - `pjsip.conf.example`: Configuração de transportes, endpoints locais (softphone 6001) e troncos PSTN.
- `telephony/prompts/`
  - `voice_system.md`: Prompt de sistema otimizado para chamadas (2-3 frases por turno, sem formatação markdown).
- `telephony/core/`
  - `session.py`: Estruturas `CallSession` e `SessionManager` com isolamento de histórico por canal.
  - `pipeline.py`: Orquestração de diálogo com `LocalLLMAgent` (Llama 3.2), Whisper (STT) e Piper (TTS).
  - `call_handler.py`: `CallHandler` para gerenciamento ARI, originação outbound, atendimento inbound e playback.
  - `__init__.py`: Exportações centrais do módulo.
- `rock_assistant/tools/contacting.py`:
  - `ContactingTool.make_call(recipient, script=None)`: Resolve contatos pelo banco local e origina chamada.
  - `ContactingTool.answer_call(call_id)`: Atende a chamada via `CallHandler`.

---

## 3. Configuração de Variáveis de Ambiente (`.env`)

```env
# Asterisk ARI
ASTERISK_ARI_URL=http://127.0.0.1:8088/ari
ASTERISK_ARI_USER=rock
ASTERISK_ARI_PASS=rock_secret_password_change_me
ASTERISK_STASIS_APP=rock_agent
ASTERISK_PJSIP_ENDPOINT=PJSIP

# Cérebro e Voz
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3.2
TTS_BACKEND=piper
PIPER_MODEL_PATH=models/piper/pt_BR-faber-medium.onnx
```

---

## 4. Testes e Validação

Execute os testes unitários da telefonia com:

```bash
pytest tests/test_telephony.py
```
