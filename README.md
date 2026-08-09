# Bot Markov para Telegram

Bot de Telegram que aprende, separadamente por chat, os padrões de escrita das
mensagens e gera respostas ocasionais usando uma cadeia de Markov de ordem 2
(trigramas). É um experimento leve: não usa LLM para responder e passa a gerar
texto apenas quando já há contexto suficiente no histórico daquele chat.

Além da cadeia, o bot mantém uma **memória semântica** no Qdrant. Ela entra em
cena quando nenhum bigrama da mensagem recebida é reconhecido: o bot busca as
mensagens mais parecidas em significado e usa uma delas como semente, o que
permite responder mesmo quando as palavras exatas nunca apareceram antes.

## Resumo

- Aprende transições `(palavra 1, palavra 2) → próxima palavra` no Redis.
- Indexa cada mensagem como vetor no Qdrant e usa busca semântica como fallback
  de contexto.
- Responde de forma probabilística quando reconhece contexto; menções ao bot
  (`BOT_NAME` ou qualquer `BOT_NAME_ALIAS`) e respostas diretas sempre disparam
  uma tentativa de resposta.
- Ajusta a variedade das respostas por temperatura e interrompe ciclos
  repetitivos.
- Emite logs JSON estruturados com `structlog`, em ordem estável
  (`level`, `timestamp`, `logger`, `event`, resto).

## Comandos

| Comando   | O que faz                                                                       |
| --------- | ------------------------------------------------------------------------------- |
| `/memory` | Mostra quantas mensagens do chat estão indexadas na memória semântica (Qdrant). |
| `/markov` | Mostra quantos nós a cadeia de Markov aprendeu no chat (Redis).                 |
| `/reset`  | Faz backup e apaga toda a memória do chat, nas duas camadas.                    |

## Arquitetura

```text
                             ┌─ bigrama conhecido? ──→ contexto
Telegram → handlers → tokens ┤
                             └─ senão: busca semântica (Qdrant) ──→ contexto
                                                │
                                        gerador (Markov/Redis) → resposta
                                                │
                                    aprendizado → Redis + Qdrant
```

Cada mensagem é gravada nas duas camadas:

- **Redis** guarda as transições em sorted sets, com chaves no formato
  `markov:<chat_id>:<palavra_1>:<palavra_2>`.
- **Qdrant** guarda um vetor por mensagem na collection `messages`, com
  `chat_id`, `text` e `tokens` no payload.

O embedding usa `paraphrase-multilingual-MiniLM-L12-v2` (384 dimensões, leve em
CPU e com suporte a português). As menções ao bot são removidas do texto **antes**
de gerar o vetor: como quase toda mensagem direcionada contém o nome dele, manter
esse token aproximaria artificialmente mensagens sem nada em comum. O `text`
original continua no payload, intacto.

## Executar

Requisitos: Python 3.11+, Docker Compose e um token de bot obtido no BotFather.

Crie um `.env` na raiz (o `config.py` carrega com `dotenv`):

```bash
BOT_TOKEN=token-fornecido-pelo-BotFather
```

Tudo em containers:

```bash
make up
```

Só as dependências no Docker e o bot local, útil para desenvolver:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
make dev
```

Alvos disponíveis no `Makefile`:

| Alvo        | O que faz                                               |
| ----------- | ------------------------------------------------------- |
| `make up`   | Sobe bot, Redis e Qdrant (com build).                   |
| `make down` | Para todos os containers.                               |
| `make db`   | Sobe apenas Redis e Qdrant.                             |
| `make dev`  | Sobe Redis e Qdrant e roda `python main.py` localmente. |

Serviços expostos:

- Redis em `localhost:6379`;
- Qdrant em `localhost:6333`, com dashboard web em
  <http://localhost:6333/dashboard>.

Na primeira execução o `sentence-transformers` baixa o modelo de embedding. Em
servidores sem GPU, instale uma distribuição CPU-only do PyTorch antes das demais
dependências para evitar pacotes CUDA desnecessários.

## Persistência e backups

O Redis usa o bind mount `./data:/data`, então os dados sobrevivem à recriação
dos containers e `docker compose down -v` não os remove, pois não é um volume
nomeado. O Qdrant, por outro lado, usa o volume nomeado `qdrant_data` — esse
**é** removido por `docker compose down -v`.

O `/reset` grava um backup em `backups/<chat_id>_<timestamp>.json` antes de
apagar qualquer coisa, contendo as transições do Redis e os payloads do Qdrant
daquele chat. Se o backup falhar, o reset é abortado e nada é apagado. O
diretório `backups/` está no `.gitignore`.

Para importar um export de comandos Redis (por exemplo, um arquivo com `ZADD`)
sem apagar os dados atuais:

```bash
./scripts/import-redis-rdb.sh /caminho/para/arquivo.redis
```

Para restaurar um backup Redis RDB, passe o arquivo `.rdb` ao mesmo script. O
Redis é interrompido, o `dump.rdb` atual é salvo em
`./data/dump.rdb.backup.<data-hora>` e o backup é instalado antes de reiniciar o
serviço. Pare o bot antes desse tipo de restauração.

## Configuração

| Variável                | Padrão                     | Descrição                                                       |
| ----------------------- | -------------------------- | --------------------------------------------------------------- |
| `BOT_TOKEN`             | —                          | Obrigatória. Token fornecido pelo BotFather.                    |
| `REDIS_URL`             | `redis://localhost:6379/0` | URL de conexão com o Redis.                                     |
| `QDRANT_URL`            | `http://localhost:6333`    | URL de conexão com o Qdrant.                                    |
| `MEMORY_COLLECTION`     | `messages`                 | Nome da collection usada na memória semântica.                  |
| `MEMORY_TOP_K`          | `5`                        | Quantas mensagens parecidas a busca semântica traz.             |
| `BOT_NAME`              | `gonsitcha`                | Texto que aciona uma tentativa de resposta direta.              |
| `BOT_NAME_ALIAS`        | `Gonsitcha,Gonsinha,Bot`   | Apelidos extras que também acionam resposta, separados por `,`. |
| `REPLY_CHANCE`          | `0.08`                     | Chance de responder quando há contexto conhecido.               |
| `QUESTION_REPLY_CHANCE` | `0.25`                     | Chance de resposta para perguntas com contexto conhecido.       |
| `TEMPERATURE`           | `1.0`                      | Variedade ao escolher as próximas palavras.                     |

Os efeitos de `TEMPERATURE` e `MEMORY_TOP_K` estão documentados em detalhe, com
as probabilidades resultantes, nos comentários do `src/config.py`. Em resumo:

- **`TEMPERATURE`** controla a aleatoriedade _dentro_ da frase. Subir deixa o
  texto mais imprevisível; descer (abaixo de `1.0`) deixa o bot repetitivo, preso
  aos bordões mais frequentes do grupo.
- **`MEMORY_TOP_K`** controla o quão solta é a escolha da _semente_. Subir faz o
  bot responder com mais frequência, mas com mais desvio de assunto, já que não
  existe corte por score de similaridade.

`MAX_WORDS=30` é o teto de palavras de uma resposta e também vive em
`src/config.py`. O `CHAIN_LENGTH=2` do mesmo arquivo é apenas documental: a ordem
2 está fixa no código (tokenizer, formato das chaves e tipo `Context`), então
alterar a constante não muda o comportamento.

## Logs

Todos os logs são enviados para `stdout` como JSON, com timestamp no formato
`2026-08-04T01:59:56` (UTC). Eventos do processamento de mensagens incluem campos
como `chat_id`, `sender_id`, `should_reply` e `reaction_sent`, facilitando
filtragem e correlação em uma plataforma de observabilidade.
