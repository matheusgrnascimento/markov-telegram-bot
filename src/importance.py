"""Cálculo simples de importância de uma mensagem (0.0 a 1.0)."""


def compute_importance(text: str, tokens: list[str]) -> float:
    """Retorna um score entre 0.0 e 1.0 baseado em heurísticas simples.

    Critérios:
      + mensagem longa (>10 tokens)
      + pergunta (contém ?)
      + exclamação (contém !)
      + sentimento forte (múltiplas !!! ou ???)
      - mensagem muito curta (<=2 tokens)
    """
    score = 0.0

    # Comprimento
    if len(tokens) > 10:
        score += 0.3
    elif len(tokens) <= 2:
        score -= 0.2

    # Pergunta
    if "?" in text:
        score += 0.2

    # Exclamação
    if "!" in text:
        score += 0.1

    # Sentimento forte (repetição de pontuação)
    if "!!!" in text or "???" in text:
        score += 0.2

    return max(0.0, min(1.0, score))
