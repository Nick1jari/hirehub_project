from __future__ import annotations

import numpy as np
from sentence_transformers import SentenceTransformer

# Module-level singleton — loading the model takes ~1s, so we do it once.
_model: SentenceTransformer | None = None
MODEL_NAME = "all-MiniLM-L6-v2"


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed_texts(texts: list[str]) -> np.ndarray:
    """Return L2-normalized embeddings for a list of strings."""
    model = _get_model()
    return model.encode(texts, normalize_embeddings=True, show_progress_bar=False, batch_size=32)


def embed_query(query: str) -> np.ndarray:
    model = _get_model()
    return model.encode([query], normalize_embeddings=True)[0]
