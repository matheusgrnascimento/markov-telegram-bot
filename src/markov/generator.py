"""Geração de texto percorrendo a cadeia de Markov."""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

from src.config import STOP
from src.markov.repository import Repository
from src.settings import ChatSettings

if TYPE_CHECKING:
    from src.context import Context

logger = structlog.get_logger(__name__)

# Pontuação que funciona como terminador natural
_SENTENCE_ENDERS = frozenset({".", "!", "?", "…"})

# Teto extra de palavras após max_words para buscar terminador (#12)
_GRACE_WORDS = 5


@dataclass
class GenerationStats:
    """Métricas coletadas durante a geração (#13)."""

    words: int = 0
    backoff_count: int = 0
    entropy_sum: float = 0.0
    entropy_steps: int = 0
    used_grace: bool = False
    source: str = ""

    @property
    def avg_entropy(self) -> float:
        return self.entropy_sum / self.entropy_steps if self.entropy_steps else 0.0


def _compute_entropy(weights: list[float]) -> float:
    """Shannon entropy da distribuição de pesos (normalizada)."""
    total = sum(weights)
    if total <= 0:
        return 0.0
    probs = [w / total for w in weights if w > 0]
    return -sum(p * math.log2(p) for p in probs)


def choose_word(
    choices: list[tuple[str, float, int]],
    word_counts: dict[str, int],
    temperature: float,
    now: int,
) -> str:
    """Amostragem avançada com temperatura, recência e diversidade progressiva.

    Parâmetros por candidato:
      - frequência: fator principal
      - recência: bônus suave para transições vistas recentemente (#5)
      - diversidade: penalidade progressiva por repetição (#11)
      - temperatura: controla dispersão
    """
    temperature = max(temperature, 0.01)

    weights: list[float] = []
    for word, freq, last_seen in choices:
        # Base: frequência ajustada pela temperatura
        base = freq ** (1 / temperature)

        # Recência: bônus suave (max 1.3x) para transições das últimas 24h (#5)
        if last_seen > 0:
            age_hours = max((now - last_seen) / 3600, 0.1)
            recency_factor = 1.0 + 0.3 / (1 + age_hours / 24)
        else:
            recency_factor = 1.0

        # Diversidade progressiva: penalidade crescente por repetição (#11)
        count = word_counts.get(word, 0)
        if count == 0:
            diversity_factor = 1.0
        elif count == 1:
            diversity_factor = 0.3
        elif count == 2:
            diversity_factor = 0.05
        else:
            diversity_factor = 0.01

        weights.append(base * recency_factor * diversity_factor)

    words = [w for w, _, _ in choices]
    return random.choices(words, weights=weights, k=1)[0]


async def generate(
    repo: Repository,
    chat_id: int,
    context: Context,
    settings: ChatSettings,
    allow_random_context: bool = False,
) -> str | None:
    """Gera texto com backoff, recência, diversidade e parada inteligente."""
    seed = context.markov_seed

    if seed is None and allow_random_context:
        seed = await repo.random_context(chat_id)
    if seed is None:
        return None

    stats = GenerationStats(source="seed")
    now = int(time.time())
    first, second = seed
    result: list[str] = []
    word_counts: dict[str, int] = {}
    used_contexts: set[tuple[str, str]] = {seed}
    hit_max = False

    max_total = settings.max_words + _GRACE_WORDS

    for step in range(max_total):
        # Atingiu max_words — entra em modo grace (#12)
        if step >= settings.max_words and not hit_max:
            hit_max = True
            stats.used_grace = True

        # Se em grace e encontra terminador, para
        if hit_max and result and result[-1] in _SENTENCE_ENDERS:
            break

        # Ordem 2 com recência
        choices = await repo.next_words_with_recency(chat_id, first, second)

        # Backoff para ordem 1 (#2)
        if not choices:
            backoff_raw = await repo.next_words_backoff(chat_id, second)
            # Converter para formato com recência=0
            choices = [(w, s, 0) for w, s in backoff_raw]
            if choices:
                stats.backoff_count += 1

        if not choices:
            break

        # Entropia (#13)
        raw_weights = [s for _, s, _ in choices]
        stats.entropy_sum += _compute_entropy(raw_weights)
        stats.entropy_steps += 1

        next_word = choose_word(choices, word_counts, settings.temperature, now)
        if next_word == STOP:
            break

        result.append(next_word)
        word_counts[next_word] = word_counts.get(next_word, 0) + 1
        first, second = second, next_word

        # Anti-ciclo
        if (first, second) in used_contexts:
            break
        used_contexts.add((first, second))

    stats.words = len(result)
    generated = " ".join(result) or None

    if generated:
        logger.info(
            "response_generated",
            chat_id=chat_id,
            words=stats.words,
            backoffs=stats.backoff_count,
            avg_entropy=round(stats.avg_entropy, 2),
            used_grace=stats.used_grace,
            source=context.candidates[0].source if context.candidates else "random",
        )

    return generated
