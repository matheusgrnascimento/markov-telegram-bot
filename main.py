"""Ponto de entrada do bot Telegram."""

from telegram.ext import Application, CommandHandler, MessageHandler, filters

from src.config import BOT_TOKEN
from src.handlers import config, markov, memory, on_message, reset
from src.lifecycle import post_init, post_shutdown
from src.logging_config import configure_logging


def main() -> None:
    configure_logging()

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    app.add_handler(CommandHandler("memory", memory))
    app.add_handler(CommandHandler("markov", markov))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("settings", config))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.run_polling()


if __name__ == "__main__":
    main()
