"""Acesso ao Redis para transições da cadeia de Markov e memória recente."""

import random
import time

from redis.asyncio import Redis

from src.config import RECENT_MESSAGES_LIMIT


class Repository:
    def __init__(self, redis: Redis):
        self.redis = redis

    # ─── Chaves ────────────────────────────────────────────────────────────────

    @staticmethod
    def _key(chat_id: int, first: str, second: str) -> str:
        return f"markov:{chat_id}:{first}:{second}"

    @staticmethod
    def _recency_key(chat_id: int, first: str, second: str) -> str:
        """Armazena last_seen de cada transição (hash: next_word → timestamp)."""
        return f"recency:{chat_id}:{first}:{second}"

    @staticmethod
    def _contexts_key(chat_id: int) -> str:
        """Set com todos os contextos válidos do chat (para random_context rápido)."""
        return f"contexts:{chat_id}"

    @staticmethod
    def _user_key(chat_id: int, user_id: int, first: str, second: str) -> str:
        """Cadeia por usuário dentro do chat."""
        return f"markov:{chat_id}:u{user_id}:{first}:{second}"

    # ─── Aprendizado ───────────────────────────────────────────────────────────

    async def add_transition(self, chat_id: int, first: str, second: str, next_word: str, *, user_id: int = 0) -> None:
        """Incrementa frequência, atualiza recência e registra contexto válido."""
        key = self._key(chat_id, first, second)
        now = int(time.time())

        pipe = self.redis.pipeline(transaction=False)
        pipe.zincrby(key, 1, next_word)
        pipe.hset(self._recency_key(chat_id, first, second), next_word, now)
        pipe.sadd(self._contexts_key(chat_id), f"{first}:{second}")
        await pipe.execute()

        # Aprendizado por usuário (opcional, se user_id fornecido)
        if user_id:
            await self.redis.zincrby(self._user_key(chat_id, user_id, first, second), 1, next_word)

    # ─── Consulta ──────────────────────────────────────────────────────────────

    async def next_words(self, chat_id: int, first: str, second: str) -> list[tuple[str, float]]:
        """Retorna cada continuação e sua frequência observada."""
        values = await self.redis.zrange(self._key(chat_id, first, second), 0, -1, withscores=True)
        return [(word, score) for word, score in values]

    async def next_words_with_recency(self, chat_id: int, first: str, second: str) -> list[tuple[str, float, int]]:
        """Retorna (palavra, frequência, last_seen) para cada continuação."""
        key = self._key(chat_id, first, second)
        recency_key = self._recency_key(chat_id, first, second)

        pipe = self.redis.pipeline(transaction=False)
        pipe.zrange(key, 0, -1, withscores=True)
        pipe.hgetall(recency_key)
        freq_values, recency_map = await pipe.execute()

        now = int(time.time())
        results = []
        for word, score in freq_values:
            last_seen = int(recency_map.get(word, 0))
            results.append((word, score, last_seen))
        return results

    async def next_words_backoff(self, chat_id: int, word: str) -> list[tuple[str, float]]:
        """Backoff de ordem 1: busca qualquer contexto (*, word) e agrega continuações."""
        prefix = f"markov:{chat_id}:"
        results: dict[str, float] = {}
        async for key in self.redis.scan_iter(match=f"{prefix}*:{word}"):
            # Ignorar chaves de usuário
            parts = key.removeprefix(prefix).split(":")
            if len(parts) >= 2 and parts[0].startswith("u"):
                continue
            values = await self.redis.zrange(key, 0, -1, withscores=True)
            for next_word, score in values:
                results[next_word] = results.get(next_word, 0) + score
        return list(results.items())

    async def next_words_user(self, chat_id: int, user_id: int, first: str, second: str) -> list[tuple[str, float]]:
        """Continuações aprendidas de um usuário específico."""
        key = self._user_key(chat_id, user_id, first, second)
        values = await self.redis.zrange(key, 0, -1, withscores=True)
        return [(word, score) for word, score in values]

    # ─── Random context rápido (#7) ───────────────────────────────────────────

    async def random_context(self, chat_id: int) -> tuple[str, str] | None:
        """Escolhe um contexto válido aleatório do set (O(1))."""
        key = self._contexts_key(chat_id)
        member = await self.redis.srandmember(key)
        if member is None:
            return None
        parts = member.split(":", maxsplit=1)
        if len(parts) != 2:
            return None
        return (parts[0], parts[1])

    # ─── Estatísticas ──────────────────────────────────────────────────────────

    async def count_nodes(self, chat_id: int) -> int:
        """Conta os contextos válidos armazenados para um chat."""
        return await self.redis.scard(self._contexts_key(chat_id))

    # ─── Backup / Delete ───────────────────────────────────────────────────────

    async def backup_chat(self, chat_id: int) -> dict[str, dict[str, float]]:
        """Exporta todas as transições do chat como dicionário chave → {palavra: freq}."""
        data: dict[str, dict[str, float]] = {}
        prefix = f"markov:{chat_id}:"
        async for key in self.redis.scan_iter(match=f"{prefix}*"):
            members = await self.redis.zrange(key, 0, -1, withscores=True)
            data[key] = {word: score for word, score in members}
        return data

    async def delete_chat(self, chat_id: int) -> int:
        """Remove todas as chaves Markov, recência e contextos do chat."""
        deleted = 0
        for pattern in (f"markov:{chat_id}:*", f"recency:{chat_id}:*"):
            async for key in self.redis.scan_iter(match=pattern):
                await self.redis.delete(key)
                deleted += 1
        await self.redis.delete(self._contexts_key(chat_id))
        await self.redis.delete(self._recent_key(chat_id))
        return deleted

    # ─── Memória recente ───────────────────────────────────────────────────────

    @staticmethod
    def _recent_key(chat_id: int) -> str:
        return f"recent:{chat_id}"

    async def push_recent(self, chat_id: int, text: str) -> None:
        """Adiciona uma mensagem à lista recente e mantém o tamanho limitado."""
        key = self._recent_key(chat_id)
        pipe = self.redis.pipeline(transaction=False)
        pipe.lpush(key, text)
        pipe.ltrim(key, 0, RECENT_MESSAGES_LIMIT - 1)
        await pipe.execute()

    async def get_recent(self, chat_id: int) -> list[str]:
        """Retorna as mensagens recentes (mais nova primeiro)."""
        return await self.redis.lrange(self._recent_key(chat_id), 0, -1)
