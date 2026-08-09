"""Aprendizado incremental de uma mensagem na cadeia de Markov."""

from src.markov.repository import Repository
from src.tokenizer import trigrams


async def learn(repo: Repository, chat_id: int, tokens: list[str], *, user_id: int = 0) -> None:
    """Alimenta a cadeia de Markov com os trigramas da mensagem."""
    for first, second, next_word in trigrams(tokens):
        await repo.add_transition(chat_id, first, second, next_word, user_id=user_id)
