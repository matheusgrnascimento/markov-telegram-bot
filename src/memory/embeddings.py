"""Memória semântica baseada em Qdrant e sentence-transformers."""

import asyncio
import re
import uuid
from datetime import datetime, timezone

import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)
from sentence_transformers import SentenceTransformer

from src.config import (
    BOT_NAME,
    BOT_NAME_ALIAS,
    EMBEDDING_MODEL,
    MEMORY_COLLECTION,
    MEMORY_TOP_K,
    QDRANT_URL,
)
from src.memory.search import MemoryHit

logger = structlog.get_logger(__name__)

_BOT_NAMES_PATTERN: re.Pattern[str] | None = None


def _build_bot_names_pattern() -> re.Pattern[str]:
    """Regex que casa qualquer nome/alias do bot (case-insensitive)."""
    global _BOT_NAMES_PATTERN
    if _BOT_NAMES_PATTERN is None:
        names = [re.escape(BOT_NAME)] + [re.escape(a) for a in BOT_NAME_ALIAS if a]
        _BOT_NAMES_PATTERN = re.compile("|".join(names), re.IGNORECASE)
    return _BOT_NAMES_PATTERN


def _strip_bot_name(text: str) -> str:
    """Remove menções ao bot para que o embedding capture só o conteúdo semântico."""
    cleaned = _build_bot_names_pattern().sub("", text)
    return " ".join(cleaned.split())


class SemanticMemory:
    """Indexa mensagens e busca as mais próximas semanticamente."""

    def __init__(self) -> None:
        self._model: SentenceTransformer | None = None
        self._client: QdrantClient | None = None
        self._lock = asyncio.Lock()
        self._dimension: int = 0

    async def initialize(self) -> None:
        """Carrega o modelo e garante que a collection existe no Qdrant."""
        async with self._lock:
            if self._model is not None:
                return
            self._model = await asyncio.to_thread(
                SentenceTransformer,
                EMBEDDING_MODEL,
            )
            self._dimension = self._model.get_sentence_embedding_dimension()
            self._client = QdrantClient(url=QDRANT_URL)
            await asyncio.to_thread(self._ensure_collection)
            logger.info(
                "memoria_semantica_inicializada",
                model_dimension=self._dimension,
            )

    def _ensure_collection(self) -> None:
        """Cria a collection se ainda não existir."""
        collections = [c.name for c in self._client.get_collections().collections]
        if MEMORY_COLLECTION not in collections:
            self._client.create_collection(
                collection_name=MEMORY_COLLECTION,
                vectors_config=VectorParams(size=self._dimension, distance=Distance.COSINE),
            )

    async def store(self, chat_id: int, text: str, tokens: list[str], *, user_id: int = 0, importance: float = 0.0) -> None:
        """Gera embedding e armazena a mensagem no Qdrant."""
        if not tokens or self._model is None:
            return
        clean_text = _strip_bot_name(text)
        if not clean_text:
            return
        embedding = await asyncio.to_thread(self._model.encode, clean_text, show_progress_bar=False)
        point = PointStruct(
            id=str(uuid.uuid4()),
            vector=embedding.tolist(),
            payload={
                "chat_id": chat_id,
                "user_id": user_id,
                "text": text,
                "tokens": tokens,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "importance": importance,
            },
        )
        await asyncio.to_thread(
            self._client.upsert,
            collection_name=MEMORY_COLLECTION,
            points=[point],
        )

    async def count(self, chat_id: int) -> int:
        """Conta quantas mensagens do chat estão indexadas na memória semântica."""
        if self._client is None:
            return 0
        result = await asyncio.to_thread(
            self._client.count,
            collection_name=MEMORY_COLLECTION,
            count_filter=Filter(must=[FieldCondition(key="chat_id", match=MatchValue(value=chat_id))]),
            exact=True,
        )
        return result.count

    async def search(self, chat_id: int, text: str) -> list[MemoryHit]:
        """Busca as mensagens semanticamente mais próximas no mesmo chat."""
        if self._model is None:
            return []
        clean_text = _strip_bot_name(text)
        if not clean_text:
            return []
        embedding = await asyncio.to_thread(self._model.encode, clean_text, show_progress_bar=False)
        results = await asyncio.to_thread(
            self._client.query_points,
            collection_name=MEMORY_COLLECTION,
            query=embedding.tolist(),
            query_filter=Filter(must=[FieldCondition(key="chat_id", match=MatchValue(value=chat_id))]),
            limit=MEMORY_TOP_K,
        )
        hits = []
        for point in results.points:
            hits.append(
                MemoryHit(
                    text=point.payload["text"],
                    tokens=point.payload["tokens"],
                    score=point.score,
                )
            )
        return hits

    async def backup_chat(self, chat_id: int) -> list[dict]:
        """Exporta todos os pontos do chat como lista de payloads."""
        if self._client is None:
            return []
        points: list[dict] = []
        offset = None
        while True:
            result = await asyncio.to_thread(
                self._client.scroll,
                collection_name=MEMORY_COLLECTION,
                scroll_filter=Filter(must=[FieldCondition(key="chat_id", match=MatchValue(value=chat_id))]),
                limit=100,
                offset=offset,
            )
            batch, next_offset = result
            for point in batch:
                points.append(point.payload)
            if next_offset is None:
                break
            offset = next_offset
        return points

    async def delete_chat(self, chat_id: int) -> None:
        """Remove todos os pontos do chat da memória semântica."""
        if self._client is None:
            return
        await asyncio.to_thread(
            self._client.delete,
            collection_name=MEMORY_COLLECTION,
            points_selector=Filter(must=[FieldCondition(key="chat_id", match=MatchValue(value=chat_id))]),
        )
