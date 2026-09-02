# Prompt de refatoração: migração de Ollama para Gemini

## Objetivo
Migrar a arquitetura atual do assistente Rock para usar o modelo Gemini da Google como provedor principal de LLM, removendo toda dependência local de Ollama e mantendo a experiência funcional do sistema.

## Escopo
A refatoração deve cobrir as seguintes etapas:

1. Configuração do ambiente para Gemini
2. Ajuste de autenticação e variáveis de ambiente
3. Substituição das chamadas ao Ollama pela API do Gemini
4. Remoção de referências e lógica local de Ollama
5. Validação de ping-pong com a API do Gemini para confirmar comunicação funcional

## Regras gerais
- Remover qualquer referência explícita a Ollama do projeto.
- Não manter `OLLAMA_BASE_URL`, `MODEL_ROUTER`, `MODEL_SPECIALIST`, `OLLAMA_CONFIG`, `OLLAMA_KEEP_ALIVE`, `OLLAMA_TIMEOUT` como parte ativa do runtime.
- A LLM passa a rodar nos servidores da Google, não localmente.
- A interface do app deve continuar funcionando do ponto de vista do usuário; a troca deve ser transparente.
- Manter a lógica de roteamento, especialista, memória, STT/TTS e fluxo principal do assistente intactos, apenas trocando o backend da IA.
- O sistema deve continuar funcionando mesmo em cenário de erro de API, com mensagens claras e fallback seguro.

## Etapa 1 — Configuração para Gemini
Atualizar o arquivo de configuração para incluir:
- `GEMINI_API_KEY`
- `GEMINI_MODEL_ROUTER`
- `GEMINI_MODEL_SPECIALIST`
- `GEMINI_GENERATION_CONFIG`
- `GEMINI_TIMEOUT`

Definir valores defaults seguros, por exemplo:
- modelo roteador: `gemini-2.0-flash-lite` ou equivalente disponível na API
- modelo especialista: `gemini-2.0-flash` ou equivalente disponível na API
- timeout: 30s a 60s
- configuração com temperatura baixa para respostas objetivas

A configuração deve ser compatível com leitura via `os.getenv()` e deve refletir uso em nuvem.

## Etapa 2 — Autenticação e variáveis de ambiente
- Ler a chave da API do Gemini a partir de variável de ambiente.
- Tratar ausência da chave com erro explícito e amigável.
- Não depender de `ollama serve`, container local ou modelo baixado.
- Validar a presença de `GEMINI_API_KEY` antes da primeira chamada de IA.
- Garantir que o projeto possa ser executado em ambiente local com credenciais externas válidas.

## Etapa 3 — Substituição das chamadas ao Ollama
No módulo de roteamento, substituir a lógica atual que faz `requests.post(.../api/generate)` por uma chamada para a API do Gemini.

No módulo do especialista, substituir a lógica atual que faz `requests.post(.../api/chat)` por uma integração com Gemini.

### Requisitos
- Usar a biblioteca oficial da Google para Gemini.
- Enviar o histórico de conversa e o prompt atual no formato adequado para o SDK.
- Preservar o prompt de sistema (system prompt) e instruções de comportamento.
- O retorno da API deve ser convertido em texto limpo para uso na aplicação.
- O modelo deve continuar retornando JSON estruturado no roteador, conforme o contrato atual.

## Etapa 4 — Remoção de referências ao Ollama
Remover completamente qualquer menção a:
- `ollama serve`
- `ollama pull`
- `http://localhost:11434`
- `/api/generate`
- `/api/chat`
- `OLLAMA_BASE_URL`
- `MODEL_ROUTER`
- `MODEL_SPECIALIST`
- `OLLAMA_CONFIG`
- `OLLAMA_KEEP_ALIVE`
- `OLLAMA_TIMEOUT`
- mensagens de diagnóstico que dizem que o daemon local do Ollama está indisponível

Também remover qualquer lógica de fallback para `regex` que exista apenas porque a LLM local falhou. O fallback pode continuar existindo como estratégia de segurança, mas não deve depender do servidor Ollama.

A documentação, logs e comentários devem refletir a nova arquitetura com Gemini.

## Etapa 5 — Validação de ping-pong com a API do Gemini
Adicionar validação explícita para confirmar que a API do Gemini responde corretamente.

### Objetivo
Executar um teste mínimo de comunicação em que:
- a aplicação envia uma mensagem simples
- a API do Gemini retorna resposta válida
- o sistema interpreta a resposta corretamente
- o fluxo do assistente continua operacional

### Critérios de sucesso
- A chamada ao Gemini retorna HTTP 200 ou uma resposta válida do SDK
- O texto retornado não está vazio
- O prompt de ping-pong funciona em inglês ou português
- O sistema identifica corretamente a resposta e não cai em erro de autenticação ou timeout

### Validação recomendada
Criar um método simples de teste com a seguinte lógica:

- enviar: "responda apenas com: ping"
- verificar se a resposta contém `ping` ou uma forma equivalente
- imprimir o resultado em log para confirmação

Se a API falhar, o sistema deve reportar:
- chave ausente
- quota excedida
- rejeição por segurança
- timeout
- erro de rede

A validação deve ser usada como smoke test do backend Gemini antes de permitir uso normal do assistente.

## Estrutura de implementação esperada
- Manter em [rock_assistant/config.py](rock_assistant/config.py) a configuração do Gemini
- Ajustar [rock_assistant/core/intent_parser.py](rock_assistant/core/intent_parser.py) para usar Gemini no roteamento
- Ajustar [rock_assistant/core/specialist.py](rock_assistant/core/specialist.py) para usar Gemini no agente especialista
- Atualizar [requirements.txt](requirements.txt) com SDK do Google
- Atualizar [DOCUMENTACAO.md](DOCUMENTACAO.md) para refletir nova arquitetura

## Resultado esperado
Ao final da migração:
- o projeto não depende mais de Ollama local
- o assistente usa Gemini via API da Google
- o roteador continua extraindo intenção e payload em JSON
- o especialista continua gerando respostas contextuais
- a aplicação validada por ping-pong com a API do Gemini funciona corretamente

## Observação importante
A migração deve ser feita sem quebrar o funcionamento da aplicação principal. O objetivo é trocar o provedor de IA, não reescrever a arquitetura geral do assistente.
