<<<<<<< HEAD
# Rock Assistant

## Webhook local do WhatsApp

O servidor local usa FastAPI e expõe `GET /webhook` e `POST /webhook` para a
WhatsApp Cloud API. Mensagens de texto são processadas pelo assistente e a
resposta é enviada pela Graph API. Comandos do sistema são bloqueados nesse
canal.

Crie um `.env` com:

```env
META_VERIFY_TOKEN=um-token-criado-por-voce
META_APP_SECRET=segredo-do-app-meta
META_ACCESS_TOKEN=token-de-acesso
META_PHONE_NUMBER_ID=id-do-numero
```

Inicie o servidor:

```bash
uvicorn rock_assistant.api:app --host 0.0.0.0 --port 8000 --reload
ngrok http 8000
```

Na configuração do app Meta, use `https://SEU-DOMINIO-NGROK/webhook` como
callback e o mesmo valor de `META_VERIFY_TOKEN` como token de verificação.
O WhatsApp não consegue acessar diretamente `localhost`; o túnel HTTPS é
necessário durante o desenvolvimento.
=======
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
corpo: Tudo bem?`, `listar emails não lidos`, `ler email ID`, `responder email
ID: texto` e `marcar email ID como lido`. O monitoramento contínuo permanece
desativado por padrão; nesta etapa, ativá-lo apenas registra a preferência e o
polling automático ainda não está conectado.
>>>>>>> 8a29f95 (Melhora do sistema de busca v1.1.)
