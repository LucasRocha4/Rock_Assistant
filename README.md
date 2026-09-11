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
