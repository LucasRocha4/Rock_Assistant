# Bateria de testes do Rock

## Objetivo

Validar toda mensagem que o usuário possa enviar ao Rock antes de considerar uma função pronta. Cada caso deve ser executado pelo parser e pelo roteador, sem chamar serviços externos quando o teste não exigir isso.

Para cada caso, registrar:

- entrada enviada;
- intenção identificada;
- payload produzido;
- resultado obtido;
- `PASS` ou `FAIL`;
- erro e reprodução, quando houver falha.

Uma execução só passa quando a intenção **e** todos os campos do payload coincidirem com o esperado.

## Ordem obrigatória de decisão

O parser deve aplicar as regras nesta ordem:

1. comando direto ou prefixado;
2. busca na web;
3. lembrete;
4. mensagem;
5. comando por palavra-chave;
6. conversa geral.

## Testes do parser

### 1. Entrada vazia e conversa geral

| Entrada | Intenção esperada | Payload esperado |
|---|---|---|
| `None` | `None` | `{}` |
| ` ` | `None` | `{}` |
| `Olá Rock` | `general` | `{"text": "Olá Rock"}` |
| `Explique o que é DNS` | `general` | `{"text": "Explique o que é DNS"}` |

### 2. Busca na web

| Entrada | Intenção esperada | Payload esperado |
|---|---|---|
| `busca tutoriais de Python` | `search` | `{"query": "tutoriais de Python"}` |
| `buscar por vagas de trabalho` | `search` | `{"query": "vagas de trabalho"}` |
| `pesquise sobre redes` | `search` | `{"query": "redes"}` |
| `google clima em Recife` | `search` | `{"query": "clima em Recife"}` |
| `procure documentação do nmap` | `search` | `{"query": "documentação do nmap"}` |
| `Você pode pesquisar livros de Linux?` | `search` | `{"query": "Você pode pesquisar livros de Linux?"}` |
| `busca` | `search` | `{"query": "busca"}` |

### 3. Lembretes

| Entrada | Intenção esperada | Payload esperado |
|---|---|---|
| `lembre-me de estudar às 15:00` | `reminder` | `{"text": "estudar", "when": "às 15:00"}` |
| `lembrete reunião amanhã` | `reminder` | `{"text": "reunião", "when": "amanhã"}` |
| `agende pagar conta no dia 10` | `reminder` | `{"text": "pagar conta", "when": "no dia 10"}` |
| `alarme para revisar o relatório` | `reminder` | `{"text": "revisar o relatório", "when": null}` |
| `lembrete` | `reminder` | validar que `text` não fica vazio |

Também testar horários, datas, dias da semana, `hoje`, `depois de amanhã`, `20h30`, manhã, tarde e noite.

### 4. Mensagens

| Entrada | Intenção esperada | Payload esperado |
|---|---|---|
| `mandar whatsapp para joao: tudo certo` | `message` | `{"target": "joao", "text": "tudo certo"}` |
| `enviar mensagem para maria reunião às 10` | `message` | `{"target": "maria", "text": "reunião às 10"}` |
| `enviar mensagem bom dia` | `message` | `{"target": "default", "text": "bom dia"}` |
| `notificar telegram para grupo123: servidor online` | `message` | `{"target": "grupo123", "text": "servidor online"}` |
| `mensagem` | `message` | validar que `target` é `default` |

Testar destinatário com acentos, hífen, número, dois-pontos, vírgula e ausência de destinatário.

### 5. Comandos do sistema

| Entrada | Intenção esperada | Payload esperado |
|---|---|---|
| `exec nmap 127.0.0.1` | `command` | `{"command": "nmap 127.0.0.1"}` |
| `run ping -c 1 localhost` | `command` | `{"command": "ping -c 1 localhost"}` |
| `rode ip a` | `command` | `{"command": "ip a"}` |
| `ls -la` | `command` | `{"command": "ls -la"}` |
| `cat /etc/hosts` | `command` | `{"command": "cat /etc/hosts"}` |
| `abrir terminal` | `command` | `{"command": "x-terminal-emulator"}` |
| `ligar bluetooth` | `command` | `{"command": "ligar bluetooth"}` |
| `exec` | `command` | validar que `command` não fica vazio |

Repetir os testes para `ifconfig`, `ss`, `netstat`, `uname`, `uptime`, `pwd`, `ip addr` e `ip -4`.

### 6. Precedência e entradas ambíguas

| Entrada | Resultado obrigatório |
|---|---|
| `exec buscar arquivos` | `command`, comando `buscar arquivos` |
| `run enviar mensagem` | `command`, comando `enviar mensagem` |
| `buscar lembrete de rede` | `search` |
| `mandar mensagem para joao: pesquisar isso` | `message` |
| `abrir terminal` | `command`, comando `x-terminal-emulator` |
| `ping` | `command`, comando `ping` |

## Testes do `Router`

1. Registrar um handler e confirmar que `route()` devolve o resultado do handler.
2. Confirmar que o payload omitido chega ao handler como `{}`.
3. Confirmar que o payload informado chega sem alteração.
4. Registrar novamente a mesma intenção e confirmar que o último handler substitui o anterior.
5. Roteiar uma intenção inexistente e confirmar `ValueError` com mensagem identificando a intenção.
6. Confirmar que exceções lançadas pelo handler não são engolidas pelo roteador.

## Testes de integração parser + Router

Registrar um handler para cada intenção `search`, `reminder`, `message`, `command` e `general`. Para cada entrada da bateria:

1. executar `IntentParser.parse()`;
2. enviar `intent` e `payload` ao `Router`;
3. confirmar que o handler correto recebeu exatamente o payload produzido;
4. confirmar que nenhuma intenção foi roteada para ferramenta diferente.

## Testes do roteamento com Gemini

Sem fazer chamadas reais por padrão:

1. `LLM_ROUTER_ENABLED=False`: deve usar somente o parser local.
2. Chave ausente: deve usar o fallback local.
3. Resposta JSON válida com intenção permitida e payload dicionário: deve retornar a resposta do Gemini.
4. JSON inválido: deve usar o fallback local.
5. Intenção desconhecida: deve usar o fallback local.
6. Payload ausente ou não dicionário: deve usar o fallback local.
7. Erro de SDK, API, timeout ou rede: deve usar o fallback local.
8. Entrada vazia ou `None`: deve retornar `{"intent": null, "payload": {}}` sem chamar a API.

## Testes do `ping_gemini`

Com o SDK e a rede simulados:

1. chave ausente: `success=False` e erro de chave ausente;
2. resposta com `ping`: `success=True`;
3. SDK ausente: `success=False` e erro `sdk_ausente`;
4. quota, `429` ou `RESOURCE_EXHAUSTED`: erro de quota;
5. erro `401`, `403`, `invalid` ou `unauthenticated`: erro de credencial;
6. bloqueio de segurança: erro de rejeição por segurança;
7. `TimeoutError` e mensagens de timeout: erro `timeout`;
8. erro inesperado: erro de rede/comunicação;
9. modelo explícito: confirmar que o nome recebido é usado na chamada.

## Critérios de segurança

- Nunca executar comandos do sistema durante os testes do parser.
- Testar parsing e roteamento com mocks; deixar execução real de `nmap`, `ping`, `cat` e outros comandos para um ambiente isolado.
- Não expor chaves da API, tokens ou credenciais nos resultados.
- Registrar a mensagem de falha sem registrar segredos.

## Formato do relatório

```text
Data: AAAA-MM-DD
Ambiente: local / mock / integração

[PASS] search: busca tutoriais de Python
[PASS] reminder: lembre-me de estudar às 15:00
[FAIL] message: enviar mensagem bom dia
Esperado: target=default, text=bom dia
Obtido: ...

Resumo: X passaram, Y falharam, Z não executados
Falhas bloqueantes: listar aqui
```

Não declarar o Rock pronto enquanto houver teste `FAIL` em parsing, payload, precedência ou roteamento. Testes que dependem de rede devem ser marcados como `NÃO EXECUTADO` quando a credencial ou o serviço não estiver disponível, nunca como `PASS`.
