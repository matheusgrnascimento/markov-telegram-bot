#!/usr/bin/env python3
"""Baixa o modelo de embeddings e salva localmente em models/.

Depois de rodar, configure EMBEDDING_MODEL=./models/paraphrase-multilingual-MiniLM-L12-v2
no .env para usar o modelo local sem precisar baixar de novo.
"""

from pathlib import Path

from sentence_transformers import SentenceTransformer

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "models" / "paraphrase-multilingual-MiniLM-L12-v2"


def main():
    print(f"Baixando {MODEL_NAME}...")
    model = SentenceTransformer(MODEL_NAME)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    model.save(str(OUTPUT_DIR))
    print(f"Modelo salvo em: {OUTPUT_DIR}")
    print(f"\nAdicione no .env:")
    print(f"  EMBEDDING_MODEL=./models/paraphrase-multilingual-MiniLM-L12-v2")


if __name__ == "__main__":
    main()
