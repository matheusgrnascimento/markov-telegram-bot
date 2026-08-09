"""Configurações centralizadas do bot."""

import os
import re

import dotenv

dotenv.load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

BOT_NAME = os.getenv("BOT_NAME", "Gonsitcha").casefold()
BOT_NAME_ALIAS: tuple[str, ...] = tuple(alias.casefold() for alias in os.getenv("BOT_NAME_ALIAS", "Gonsitcha,Gonsinha,Bot").split(",") if alias.strip())

# Ordem da cadeia de Markov: quantas palavras formam o contexto que prevê a
# próxima. ATENÇÃO: esta constante é apenas documental, nada a importa. Mudar
# para 3 não muda o comportamento do bot, porque a ordem 2 está fixa no código:
#
#   - `tokenizer.trigrams`      janelas de 3 (`padded[i : i + 3]`)
#   - `repository._key`         chave `markov:<chat>:<palavra_1>:<palavra_2>`
#   - `repository.next_words`   assinatura `(first, second)`
#   - `repository.random_context`  `split(":", maxsplit=1)` espera 2 partes
#   - `generator.Context`       `tuple[str, str]`
#
# Subir a ordem deixaria o texto mais fiel ao original e menos criativo, além de
# exigir muito mais dados para a cadeia sair do lugar e invalidar as chaves já
# gravadas no Redis. Baixar para 1 (bigramas) geraria texto bem mais aleatório.
CHAIN_LENGTH = 2

# Teto de palavras de uma resposta gerada: é o número de iterações do laço em
# `generator.generate`, e cada iteração acrescenta no máximo uma palavra.
#
# Na prática as respostas quase sempre saem menores, porque a geração para antes
# ao encontrar o marcador `STOP`, ao chegar num contexto sem continuação conhecida
# ou ao repetir um bigrama já visitado (proteção contra ciclo).
#
# Aumentar: permite respostas longas, mas como a cadeia é de ordem 2 o texto
# tende a divagar e perder o sentido quanto mais se afasta da semente.
# Diminuir: respostas curtas e mais coerentes, com risco de cortar no meio da
# frase. Note que o tokenizer descarta pontuação, então o resultado é uma
# sequência de palavras sem vírgula ou ponto em qualquer tamanho.
MAX_WORDS = 30

REPLY_CHANCE = float(os.getenv("REPLY_CHANCE", "0.08"))
QUESTION_REPLY_CHANCE = float(os.getenv("QUESTION_REPLY_CHANCE", "0.25"))

# Controla a aleatoriedade da escolha da próxima palavra em
# `generator.choose_word`, que pondera cada candidata por
# `frequência ** (1 / TEMPERATURE)`.
#
# Para um nó com as frequências 10 / 5 / 1, as probabilidades ficam:
#
#   0.01 -> 100% /  0% /  0%   determinístico: sempre a palavra mais frequente
#   0.30 ->  91% /  9% /  0%   conservador, repete os bordões do grupo
#   1.00 ->  62% / 31% /  6%   proporcional à frequência observada
#   2.00 ->  49% / 35% / 16%   criativo, dá chance real ao que é raro
#   5.00 ->  40% / 35% / 25%   quase uniforme, tende à incoerência
#
# Abaixo de 1 o bot fica previsível e repetitivo; acima de 1 ele arrisca mais e
# soa mais aleatório, perdendo o "sotaque" do chat. Valores <= 0.01 são fixados
# em 0.01 pelo gerador, e temperaturas muito baixas podem estourar
# `OverflowError` em nós de frequência alta, porque o expoente `1 / TEMPERATURE`
# chega a 100 (ex.: 20000 ** 100 excede o limite do float).
#
# A penalidade fixa de 0.2 para palavras já usadas na mesma resposta é aplicada
# depois e não é afetada por este valor.
TEMPERATURE = float(os.getenv("TEMPERATURE", "1.0"))
STOP = "<STOP>"

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
MEMORY_COLLECTION = os.getenv("MEMORY_COLLECTION", "messages")
# Quantas mensagens parecidas a busca semântica traz do Qdrant quando a cadeia
# de Markov não reconhece nenhum bigrama da mensagem recebida. Os resultados vêm
# ordenados por similaridade e `generator.find_context_from_memory` usa o
# primeiro que contém um bigrama já aprendido.
#
# Aumentar: encontra contexto com mais frequência, então o bot responde mais e
# fica menos mudo em assunto novo. Em troca, os candidatos do fim da lista são
# pouco relacionados e a resposta sai fora de contexto. Também custa latência,
# porque cada candidato dispara novas consultas ao Redis até achar um bigrama.
#
# Diminuir (1 ou 2): só aceita contexto muito próximo, as respostas ficam mais
# coerentes e o bot se cala com mais frequência.
#
# Não há corte por score: com um valor alto, mensagens fracamente similares
# ainda podem virar semente de resposta.
MEMORY_TOP_K = int(os.getenv("MEMORY_TOP_K", "5"))

# Score mínimo de similaridade para considerar uma memória válida.
# Resultados do Qdrant abaixo desse threshold são descartados.
# Range: 0.0 a 1.0 (cosseno). Com 0.0 aceita tudo (comportamento antigo).
MEMORY_SCORE_THRESHOLD = float(os.getenv("MEMORY_SCORE_THRESHOLD", "0.45"))

# Quantas mensagens recentes manter no Redis por chat (memória de curto prazo).
RECENT_MESSAGES_LIMIT = int(os.getenv("RECENT_MESSAGES_LIMIT", "20"))

# ─── Toggles de módulos ────────────────────────────────────────────────────────
# Cada módulo pode ter aprendizado e resposta controlados independentemente.
#
# MARKOV_LEARN: se True, continua alimentando a cadeia (Redis) a cada mensagem.
# MARKOV_REPLY: se True, o bot pode gerar texto pela cadeia e responder.
#
# MEMORY_LEARN: se True, armazena embeddings no Qdrant a cada mensagem.
# MEMORY_REPLY: se True, usa busca semântica como fallback de contexto.
#
# Exemplo: desativar MEMORY_REPLY mas manter MEMORY_LEARN faz o bot acumular
# memória sem usá-la para responder — útil para "esquentar" o banco antes de
# ativar a resposta semântica.

MARKOV_LEARN = os.getenv("MARKOV_LEARN", "true").casefold() in ("1", "true", "yes")
MARKOV_REPLY = os.getenv("MARKOV_REPLY", "true").casefold() in ("1", "true", "yes")
MEMORY_LEARN = os.getenv("MEMORY_LEARN", "true").casefold() in ("1", "true", "yes")
MEMORY_REPLY = os.getenv("MEMORY_REPLY", "false").casefold() in ("1", "true", "yes")
