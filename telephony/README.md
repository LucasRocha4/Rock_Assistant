# Telefonia (Asterisk) — preparativos

Estrutura reservada para a próxima feature do Rock: atender e realizar ligações
telefônicas conduzindo a conversa como assistente, usando o Asterisk (via ARI —
Asterisk REST Interface).

Nenhum código funcional foi implementado ainda; esta pasta só define onde as
peças futuras vão morar.

## Visão de arquitetura planejada

```
Asterisk (PBX) --ARI/WebSocket--> telephony/core/call_handler.py --> ContactingTool.make_call()/answer_call()
```

- `config/`: arquivos de configuração do Asterisk (ex.: `pjsip.conf`, `extensions.conf`) quando a integração começar.
- `core/call_handler.py`: stub da classe que vai receber eventos do ARI e conduzir a chamada.
- A ponte com o restante do Rock acontece por `rock_assistant/tools/contacting.py` (`ContactingTool.make_call` / `ContactingTool.answer_call`), que hoje só levantam `NotImplementedError`.
- Dependências candidatas (ainda não instaladas, ver `requirements.txt`): `ari` (cliente ARI) ou `panoramisk` (cliente AMI assíncrono).
