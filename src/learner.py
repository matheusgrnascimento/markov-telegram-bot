"""Orquestra o aprendizado de uma mensagem (Markov + memória semântica)."""

from src.importance import compute_importance
from src.markov.learner import learn as markov_learn
from src.markov.repository import Repository
from src.memory import SemanticMemory
from src.settings import ChatSettings


async def learn(
    repo: Repository,
    chat_id: int,
    tokens: list[str],
    settings: ChatSettings,
    memory: SemanticMemory | None = None,
    text: str = "",
    user_id: int = 0,
) -> None:
    """Aprende a mensagem nos módulos habilitados."""
    if settings.markov_learn:
        await markov_learn(repo, chat_id, tokens, user_id=user_id)

    if settings.memory_learn and memory is not None and text:
        importance = compute_importance(text, tokens)
        await memory.store(chat_id, text, tokens, user_id=user_id, importance=importance)
