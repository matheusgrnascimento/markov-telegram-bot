"""Regras que definem quando o bot deve responder."""

import random
from dataclasses import dataclass

from src.context import Context
from src.settings import ChatSettings


@dataclass(frozen=True)
class ReplyDecision:
    """Resultado da avaliação de uma mensagem antes da geração."""

    context: Context
    reply_chance: float
    roll: float | None
    should_reply: bool


def decide_reply(
    context: Context,
    is_direct: bool,
    is_question: bool,
    settings: ChatSettings,
) -> ReplyDecision:
    """Decide se deve responder com base no contexto já reunido."""
    if not settings.markov_reply:
        return ReplyDecision(context=context, reply_chance=0.0, roll=None, should_reply=False)

    has_seed = context.markov_seed is not None
    reply_chance = settings.question_reply_chance if is_question else settings.reply_chance
    roll = random.random() if has_seed and not is_direct else None
    should_reply = is_direct or (roll is not None and roll < reply_chance)
    return ReplyDecision(context, reply_chance, roll, should_reply)
