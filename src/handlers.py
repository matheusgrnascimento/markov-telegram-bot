"""Handlers de comandos e mensagens recebidos pelo Telegram."""

import json
import random
from dataclasses import fields
from datetime import datetime, timezone

import structlog
from telegram import ReactionTypeEmoji, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from src.config import BOT_NAME, BOT_NAME_ALIAS
from src.context import build_context
from src.decision import decide_reply
from src.learner import learn
from src.markov.generator import generate
from src.markov.repository import Repository
from src.memory import SemanticMemory
from src.settings import ChatSettings, load_settings, reset_settings, save_setting
from src.tokenizer import tokenize

logger = structlog.get_logger(__name__)

BACKUP_DIR = "backups"


def choice_emoji():
    return random.choice(
        [
            "🙈",
            "💅",
            "🫃🏿",
        ]
    )


def message_log_context(update: Update) -> dict[str, object]:
    """Monta os identificadores úteis para correlacionar logs de uma mensagem."""
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return {}

    sender = message.from_user
    sender_label = sender.username or sender.full_name if sender else "desconhecido"
    return {
        "chat_id": chat.id,
        "sender": sender_label,
        "sender_id": sender.id if sender else None,
    }


async def memory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Informa quantas mensagens deste chat estão na memória semântica (Qdrant)."""
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    redis = context.application.bot_data["redis"]
    settings = await load_settings(redis, chat.id)
    semantic_memory: SemanticMemory = context.application.bot_data["memory"]
    try:
        indexed = await semantic_memory.count(chat.id)
    except Exception:
        logger.exception("falha_ao_contar_memoria_semantica", chat_id=chat.id)
        await message.reply_text("Não consegui consultar a memória semântica agora.")
        return

    await message.reply_text(f"Memória semântica: {indexed} mensagens indexadas nesta conversa.\n" f"Busco as {settings.memory_top_k} mais parecidas quando não reconheço o contexto.")


async def markov(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Informa quantos nós a cadeia de Markov possui no chat atual (Redis)."""
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    repo: Repository = context.application.bot_data["repository"]
    try:
        node_count = await repo.count_nodes(chat.id)
    except Exception:
        logger.exception("falha_ao_contar_nos_markov", chat_id=chat.id)
        await message.reply_text("Não consegui consultar a cadeia de Markov agora.")
        return

    await message.reply_text(f"Cadeia de Markov: {node_count} nós aprendidos nesta conversa.")


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Faz backup e limpa toda a memória (Redis + Qdrant) do chat atual."""
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    reset_logger = logger.bind(chat_id=chat.id)
    repo: Repository = context.application.bot_data["repository"]
    semantic_memory: SemanticMemory = context.application.bot_data["memory"]

    await message.reply_text("Fazendo backup e limpando memórias...")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = f"{BACKUP_DIR}/{chat.id}_{timestamp}.json"

    try:
        markov_backup = await repo.backup_chat(chat.id)
        qdrant_backup = await semantic_memory.backup_chat(chat.id)

        import os

        os.makedirs(BACKUP_DIR, exist_ok=True)
        backup_data = {
            "chat_id": chat.id,
            "timestamp": timestamp,
            "markov": markov_backup,
            "qdrant": qdrant_backup,
        }
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(backup_data, f, ensure_ascii=False, indent=2)

        reset_logger.info("backup_criado", path=backup_path)
    except Exception:
        reset_logger.exception("falha_ao_criar_backup")
        await message.reply_text("Falha ao criar o backup. Reset cancelado.")
        return

    try:
        deleted_nodes = await repo.delete_chat(chat.id)
        await semantic_memory.delete_chat(chat.id)
        reset_logger.info("reset_concluido", deleted_nodes=deleted_nodes)
    except Exception:
        reset_logger.exception("falha_ao_limpar_memorias")
        await message.reply_text(f"Backup salvo em `{backup_path}`, mas houve falha ao limpar. Verifique os logs.")
        return

    await message.reply_text(f"Memórias limpas.\n" f"Nós Markov removidos: {deleted_nodes}\n" f"Backup salvo em `{backup_path}`")


async def config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/config — mostra ou altera parâmetros do bot nesta conversa.

    Uso:
        /config              → mostra todos os parâmetros atuais
        /config <param>      → mostra o valor de um parâmetro
        /config <param> <v>  → altera o valor
        /config reset        → volta tudo ao padrão
    """
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    redis = context.application.bot_data["redis"]
    args = context.args or []

    # /config reset
    if args and args[0].lower() == "reset":
        await reset_settings(redis, chat.id)
        await message.reply_text("⚙️ Todos os parâmetros voltaram ao padrão.")
        return

    settings = await load_settings(redis, chat.id)

    # /config (sem args) → mostra tudo
    if not args:
        lines = ["⚙️ <b>Configuração atual:</b>\n"]
        for f in fields(ChatSettings):
            info = ChatSettings.PARAM_INFO.get(f.name, {})
            value = getattr(settings, f.name)
            desc = info.get("desc", "")
            lines.append(f"<code>{f.name}</code> = <b>{value}</b>\n  ↳ {desc}")
        lines.append("\nUso: /config &lt;param&gt; &lt;valor&gt;")
        await message.reply_text("\n".join(lines), parse_mode="HTML")
        return

    param = args[0].lower()

    # Valida se o parâmetro existe
    valid_params = {f.name for f in fields(ChatSettings)}
    if param not in valid_params:
        await message.reply_text(
            f"❌ Parâmetro desconhecido: <code>{param}</code>\n\n" f"Disponíveis: {', '.join(sorted(valid_params))}",
            parse_mode="HTML",
        )
        return

    # /config <param> (sem valor) → mostra só ele
    if len(args) < 2:
        info = ChatSettings.PARAM_INFO[param]
        value = getattr(settings, param)
        default = getattr(ChatSettings(), param)
        text = f"⚙️ <code>{param}</code> = <b>{value}</b>\n" f"Padrão: {default}\n" f"{info['desc']}"
        if info["min"] is not None:
            text += f"\nRange: {info['min']} – {info['max']}"
        await message.reply_text(text, parse_mode="HTML")
        return

    # /config <param> <valor> → altera
    raw_value = args[1]
    info = ChatSettings.PARAM_INFO[param]
    ptype = info["type"]

    try:
        if ptype is bool:
            if raw_value.lower() in ("true", "1", "yes", "on", "sim"):
                parsed = True
            elif raw_value.lower() in ("false", "0", "no", "off", "nao", "não"):
                parsed = False
            else:
                raise ValueError("Use true/false")
        elif ptype is int:
            parsed = int(raw_value)
        elif ptype is float:
            parsed = float(raw_value)
        else:
            raise ValueError("Tipo não suportado")
    except (ValueError, TypeError) as e:
        await message.reply_text(f"❌ Valor inválido: {e}")
        return

    # Valida range
    if info["min"] is not None and parsed < info["min"]:
        await message.reply_text(f"❌ Valor mínimo: {info['min']}")
        return
    if info["max"] is not None and parsed > info["max"]:
        await message.reply_text(f"❌ Valor máximo: {info['max']}")
        return

    await save_setting(redis, chat.id, param, parsed)
    await message.reply_text(f"✅ <code>{param}</code> = <b>{parsed}</b>", parse_mode="HTML")


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Decide, gera uma resposta quando apropriado e aprende a mensagem."""
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat or not message.text:
        return

    log_context = message_log_context(update)
    message_logger = logger.bind(**log_context)
    message_logger.info("mensagem_recebida", message_text=message.text)

    repo: Repository = context.application.bot_data["repository"]
    bot_id: int = context.application.bot_data["bot_id"]
    semantic_memory: SemanticMemory = context.application.bot_data["memory"]
    redis = context.application.bot_data["redis"]
    settings = await load_settings(redis, chat.id)
    text_lower = message.text.casefold()
    mentions_bot = BOT_NAME in text_lower or any(alias in text_lower for alias in BOT_NAME_ALIAS)
    is_reply_to_bot = bool(message.reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.id == bot_id)
    is_direct = mentions_bot or is_reply_to_bot
    tokens = tokenize(message.text)
    if not tokens and not is_direct:
        message_logger.info("mensagem_ignorada", reason="sem_tokens_e_sem_chamada_direta")
        return

    ctx = await build_context(
        repo,
        chat.id,
        tokens,
        settings=settings,
        memory=semantic_memory,
        message_text=message.text,
    )
    message_logger.info("context_created", markov_seed=ctx.markov_seed, memory_count=len(ctx.memories))

    decision = decide_reply(
        ctx,
        is_direct,
        is_question="?" in message.text,
        settings=settings,
    )
    message_logger.info(
        "decisao_de_resposta",
        mentioned_bot=mentions_bot,
        replied_to_bot=is_reply_to_bot,
        is_question="?" in message.text,
        markov_seed=" ".join(decision.context.markov_seed) if decision.context.markov_seed else None,
        reply_chance=decision.reply_chance if decision.context.markov_seed else None,
        roll=decision.roll,
        should_reply=decision.should_reply,
    )

    if decision.should_reply:
        source = "contexto da mensagem" if decision.context.markov_seed else "contexto aleatório"
        message_logger.info("gerando_resposta", source=source)
        reply = await generate(
            repo,
            chat.id,
            context=decision.context,
            settings=settings,
            allow_random_context=is_direct,
        )
        if reply:
            message_logger.info("respondendo", reply=reply)
            await message.reply_text(reply)
        else:
            try:
                await message.set_reaction(ReactionTypeEmoji(choice_emoji()))
                reacted = True
            except TelegramError:
                reacted = False
            message_logger.info("resposta_nao_gerada", reaction_sent=reacted)
    else:
        message_logger.info("nao_respondendo")

    await learn(repo, chat.id, tokens, settings=settings, memory=semantic_memory, text=message.text, user_id=message.from_user.id if message.from_user else 0)
    await repo.push_recent(chat.id, message.text)
    message_logger.info(
        "aprendizado_concluido",
        token_count=len(tokens),
        transition_count=max(len(tokens) - 1, 0),
    )
