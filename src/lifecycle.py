"""Inicialização e encerramento dos recursos compartilhados do bot."""

import structlog
from redis.asyncio import from_url
from telegram.ext import Application

from src.config import MARKOV_LEARN, MARKOV_REPLY, MEMORY_LEARN, MEMORY_REPLY, REDIS_URL
from src.markov.repository import Repository
from src.memory import SemanticMemory

logger = structlog.get_logger(__name__)


async def post_init(application: Application) -> None:
    logger.info(
        "modulos_defaults",
        markov_learn=MARKOV_LEARN,
        markov_reply=MARKOV_REPLY,
        memory_learn=MEMORY_LEARN,
        memory_reply=MEMORY_REPLY,
        info="valores padrão, ajustáveis por chat via /config",
    )

    redis = from_url(REDIS_URL, decode_responses=True)
    application.bot_data["redis"] = redis
    application.bot_data["repository"] = Repository(redis)

    if MEMORY_LEARN or MEMORY_REPLY:
        memory = SemanticMemory()
        await memory.initialize()
        application.bot_data["memory"] = memory
    else:
        application.bot_data["memory"] = None

    bot = await application.bot.get_me()
    application.bot_data["bot_id"] = bot.id


async def post_shutdown(application: Application) -> None:
    await application.bot_data["redis"].aclose()
