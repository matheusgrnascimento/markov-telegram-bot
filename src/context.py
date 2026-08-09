"""Context Engine — reúne e pontua os contextos disponíveis para a geração."""

from dataclasses import dataclass, field

import structlog

from src.markov.repository import Repository
from src.memory import MemoryHit, SemanticMemory
from src.settings import ChatSettings
from src.tokenizer import tokenize

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ScoredSeed:
    """Um bigrama candidato com sua pontuação."""

    seed: tuple[str, str]
    score: float
    source: str  # "message", "recent", "memory"


@dataclass(frozen=True)
class Context:
    """Contexto reunido para o gerador."""

    markov_seed: tuple[str, str] | None = None
    candidates: list[ScoredSeed] = field(default_factory=list)
    memories: list[MemoryHit] = field(default_factory=list)
    recent_messages: list[str] = field(default_factory=list)


async def _score_seed(repo: Repository, chat_id: int, seed: tuple[str, str], position: float, total_tokens: int) -> float:
    """Pontua um candidato a seed com base em frequência, posição e riqueza.

    Critérios:
      - frequência total das continuações (o quão popular é esse bigrama)
      - posição na mensagem (mais perto do fim = mais relevante)
      - riqueza (quantas continuações distintas existem)
    """
    choices = await repo.next_words(chat_id, *seed)
    if not choices:
        return 0.0

    total_freq = sum(score for _, score in choices)
    diversity = len(choices)

    # position: 0.0 = início, 1.0 = fim. Quanto mais perto do fim, mais relevante.
    position_bonus = 0.5 + (position * 0.5)

    # Score composto
    return total_freq * position_bonus * (1 + diversity * 0.1)


async def _find_seeds_from_tokens(repo: Repository, chat_id: int, tokens: list[str], source: str, max_candidates: int = 5) -> list[ScoredSeed]:
    """Encontra e pontua todos os bigramas válidos de uma lista de tokens."""
    candidates: list[ScoredSeed] = []
    total = len(tokens)
    if total < 2:
        return candidates

    for index in range(total - 1):
        seed = (tokens[index], tokens[index + 1])
        position = index / max(total - 2, 1)
        score = await _score_seed(repo, chat_id, seed, position, total)
        if score > 0:
            candidates.append(ScoredSeed(seed=seed, score=score, source=source))
            if len(candidates) >= max_candidates:
                break

    return candidates


async def build_context(
    repo: Repository,
    chat_id: int,
    tokens: list[str],
    settings: ChatSettings,
    memory: SemanticMemory | None = None,
    message_text: str = "",
) -> Context:
    """Reúne e pontua todos os contextos disponíveis."""
    all_candidates: list[ScoredSeed] = []

    # 1. Buscar mensagens recentes
    recent_messages = await repo.get_recent(chat_id)

    # 2. Contextos da mensagem recente (prioridade mais alta: recent > message)
    # (#10) Procurar contexto primeiro nas mensagens recentes
    for i, recent_text in enumerate(recent_messages[:5]):
        recent_tokens = tokenize(recent_text)
        recent_candidates = await _find_seeds_from_tokens(repo, chat_id, recent_tokens, source="recent", max_candidates=2)
        # Bônus de recência: mais recente = mais bônus
        recency_bonus = 1.0 + (0.3 * (5 - i) / 5)
        for c in recent_candidates:
            all_candidates.append(ScoredSeed(seed=c.seed, score=c.score * recency_bonus, source=c.source))

    # 3. Contextos da mensagem atual
    message_candidates = await _find_seeds_from_tokens(repo, chat_id, tokens, source="message", max_candidates=5)
    # Bônus forte para a mensagem direta (é o que o usuário acabou de dizer)
    for c in message_candidates:
        all_candidates.append(ScoredSeed(seed=c.seed, score=c.score * 2.0, source=c.source))

    # 4. Buscar memórias semânticas (#8, #9)
    memories: list[MemoryHit] = []
    if settings.memory_reply and memory is not None and message_text:
        raw_memories = await memory.search(chat_id, message_text)
        memories = [h for h in raw_memories if h.score >= settings.memory_score_threshold]
        filtered_count = len(raw_memories) - len(memories)
        logger.info(
            "memory_hits",
            chat_id=chat_id,
            hits=len(memories),
            filtered=filtered_count,
            threshold=settings.memory_score_threshold,
            top_score=raw_memories[0].score if raw_memories else None,
        )

        # (#9) Extrair contextos de MÚLTIPLAS memórias
        for hit in memories:
            memory_candidates = await _find_seeds_from_tokens(repo, chat_id, hit.tokens, source="memory", max_candidates=2)
            # Ponderar pelo score de similaridade
            for c in memory_candidates:
                all_candidates.append(ScoredSeed(seed=c.seed, score=c.score * hit.score, source=c.source))

    # 5. Selecionar o melhor candidato
    all_candidates.sort(key=lambda c: c.score, reverse=True)
    markov_seed = all_candidates[0].seed if all_candidates else None

    if markov_seed:
        best = all_candidates[0]
        logger.info(
            "markov_seed_found",
            chat_id=chat_id,
            seed=markov_seed,
            score=round(best.score, 2),
            source=best.source,
            total_candidates=len(all_candidates),
        )

    return Context(
        markov_seed=markov_seed,
        candidates=all_candidates[:10],
        memories=memories,
        recent_messages=recent_messages,
    )
