"""Parâmetros ajustáveis por chat, persistidos no Redis.

Cada chat pode ter overrides dos valores padrão. Se não houver override,
usa o valor que veio do .env / config.py.
"""

from dataclasses import dataclass, field, fields
from typing import ClassVar

from redis.asyncio import Redis

from src.config import (
    MARKOV_LEARN,
    MARKOV_REPLY,
    MAX_WORDS,
    MEMORY_LEARN,
    MEMORY_REPLY,
    MEMORY_SCORE_THRESHOLD,
    MEMORY_TOP_K,
    QUESTION_REPLY_CHANCE,
    RECENT_MESSAGES_LIMIT,
    REPLY_CHANCE,
    TEMPERATURE,
)

_REDIS_KEY_PREFIX = "settings"


@dataclass
class ChatSettings:
    """Parâmetros tunáveis por conversa."""

    reply_chance: float = REPLY_CHANCE
    question_reply_chance: float = QUESTION_REPLY_CHANCE
    temperature: float = TEMPERATURE
    max_words: int = MAX_WORDS
    memory_top_k: int = MEMORY_TOP_K
    memory_score_threshold: float = MEMORY_SCORE_THRESHOLD
    markov_learn: bool = MARKOV_LEARN
    markov_reply: bool = MARKOV_REPLY
    memory_learn: bool = MEMORY_LEARN
    memory_reply: bool = MEMORY_REPLY

    # Metadados para validação e display
    PARAM_INFO: ClassVar[dict[str, dict]] = {
        "reply_chance": {"type": float, "min": 0.0, "max": 1.0, "desc": "Chance de responder mensagens normais"},
        "question_reply_chance": {"type": float, "min": 0.0, "max": 1.0, "desc": "Chance de responder perguntas"},
        "temperature": {"type": float, "min": 0.01, "max": 10.0, "desc": "Criatividade (baixo=previsível, alto=aleatório)"},
        "max_words": {"type": int, "min": 1, "max": 200, "desc": "Máximo de palavras por resposta"},
        "memory_top_k": {"type": int, "min": 1, "max": 50, "desc": "Quantas memórias buscar no Qdrant"},
        "memory_score_threshold": {"type": float, "min": 0.0, "max": 1.0, "desc": "Score mínimo para aceitar memória"},
        "markov_learn": {"type": bool, "min": None, "max": None, "desc": "Aprender novas mensagens (Markov/Redis)"},
        "markov_reply": {"type": bool, "min": None, "max": None, "desc": "Gerar respostas pela cadeia de Markov"},
        "memory_learn": {"type": bool, "min": None, "max": None, "desc": "Indexar mensagens na memória semântica"},
        "memory_reply": {"type": bool, "min": None, "max": None, "desc": "Usar memória semântica como fallback"},
    }


def _redis_key(chat_id: int) -> str:
    return f"{_REDIS_KEY_PREFIX}:{chat_id}"


async def load_settings(redis: Redis, chat_id: int) -> ChatSettings:
    """Carrega os settings do chat. Retorna defaults se não houver overrides."""
    data = await redis.hgetall(_redis_key(chat_id))
    if not data:
        return ChatSettings()

    kwargs = {}
    for f in fields(ChatSettings):
        if f.name in data:
            raw = data[f.name]
            if f.type is bool or f.type == "bool":
                kwargs[f.name] = raw.lower() in ("1", "true", "yes")
            elif f.type is int or f.type == "int":
                kwargs[f.name] = int(raw)
            elif f.type is float or f.type == "float":
                kwargs[f.name] = float(raw)
    return ChatSettings(**kwargs)


async def save_setting(redis: Redis, chat_id: int, param: str, value) -> None:
    """Persiste um único parâmetro no Redis."""
    str_value = str(value).lower() if isinstance(value, bool) else str(value)
    await redis.hset(_redis_key(chat_id), param, str_value)


async def reset_settings(redis: Redis, chat_id: int) -> None:
    """Remove todos os overrides, voltando aos defaults."""
    await redis.delete(_redis_key(chat_id))
