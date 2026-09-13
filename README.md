# Rock Assistant

## Webhook e Integração com Evolution API (WhatsApp)

O servidor local utiliza FastAPI e expõe o endpoint `POST /webhook` para receber eventos da **Evolution API** (`messages.upsert`). Mensagens de texto e áudio/respostas são processadas pelo assistente e as respostas são enviadas pela rota REST da Evolution API com simulação de digitação (`presence: composing`). Comandos locais do sistema operacional permanecem bloqueados por segurança através deste canal.

### Configuração no `.env`

```env
EVOLUTION_API_URL=http://localhost:8080
EVOLUTION_API_KEY=sua_chave_global_evolution
EVOLUTION_INSTANCE=SuporteBot
```

### Inicialização do Servidor

```bash
uvicorn rock_assistant.api:app --host 0.0.0.0 --port 8000 --reload
```

Configure a Evolution API para apontar o Webhook para `http://<seu-host-ou-ip>:8000/webhook` (ou via túnel ngrok/Cloudflare durante o desenvolvimento) habilitando o evento `MESSAGES_UPSERT`.

# Rock_Assistant

## Gmail

O suporte inicial usa a Gmail API com OAuth 2.0. As dependências já estão em
`requirements.txt`; crie um cliente OAuth para aplicação desktop no Google Cloud
Console e salve o arquivo baixado como `rock_assistant/data/credentials.json`.

Na primeira operação, o assistente abrirá o fluxo de autorização e salvará o
token em `rock_assistant/data/gmail_token.json`. Esse arquivo é local e não deve
ser versionado ou incluído em logs.

Configuração opcional no `.env`:

```env
GMAIL_TOKEN_FILE=rock_assistant/data/gmail_token.json
GMAIL_SCOPES=https://www.googleapis.com/auth/gmail.modify
GMAIL_USER_ID=me
GMAIL_MAX_MESSAGES=10
GMAIL_MONITORING_ENABLED=False
```

Exemplos de comandos: `enviar email para pessoa@example.com, assunto: Oi,
corpo: Tudo bem?`, `envie email para pessoa@example.com para tratar da reunião
de amanhã`, `listar emails não lidos`, `ler email ID`, `responder email ID:
texto` e `marcar email ID como lido`.

Um pedido com `para tratar de`, `por mim`, `tome as rédeas`, `acompanhe` ou
`aguarde retorno` vira uma delegação: o Rock envia o primeiro contato, salva o
assunto e o thread do Gmail e verifica respostas nos próximos ciclos do
assistente. Quando chega uma resposta, ele informa você e aguarda uma decisão;
não responde nem negocia sozinho. O arquivo de estado é
`rock_assistant/data/gmail_delegations.json`.

O monitoramento contínuo geral permanece desativado por padrão. A delegação
ativa seu acompanhamento próprio enquanto o assistente estiver em execução;
uma consulta pode ocorrer no início de cada novo ciclo de interação.
