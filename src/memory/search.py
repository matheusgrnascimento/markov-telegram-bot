"""Tipos de retorno da busca semântica."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryHit:
    """Uma mensagem recuperada da memória semântica."""

    text: str
    tokens: list[str]
    score: float
