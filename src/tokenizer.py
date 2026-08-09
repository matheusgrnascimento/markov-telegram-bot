"""Normalização e criação de trigramas."""

import re

URL_OR_MENTION = re.compile(r"https?://\S+|@\w+")
# Captura palavras Unicode OU pontuação relevante como tokens separados
TOKEN = re.compile(r"[^\W_]+|[.!?,…]", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Remove URLs/menções e devolve palavras em minúsculas + pontuação preservada."""
    text = URL_OR_MENTION.sub("", text.lower())
    # Normaliza reticências
    text = text.replace("...", "…")
    return TOKEN.findall(text)


def trigrams(tokens: list[str]) -> list[tuple[str, str, str]]:
    """Inclui um marcador de fim para que a geração saiba quando parar."""
    if len(tokens) < 2:
        return []
    padded = [*tokens, "<STOP>"]
    return [tuple(padded[i : i + 3]) for i in range(len(padded) - 2)]
