import pickle
from pathlib import Path

import faiss
import numpy as np

from app.config import settings

INDEX_DIR = Path(settings.INDEX_DIR)

# Minimum cosine similarity to include a chunk in results.
# Vectors are L2-normalized, so inner product == cosine similarity.
SIMILARITY_THRESHOLD = 0.25


def _paths(document_id: str) -> tuple[Path, Path]:
    return (
        INDEX_DIR / f"{document_id}.faiss",
        INDEX_DIR / f"{document_id}.pkl",
    )


def build_index(document_id: str, embeddings: np.ndarray, chunk_ids: list[int]) -> None:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings.astype("float32"))

    index_path, meta_path = _paths(document_id)
    faiss.write_index(index, str(index_path))

    with open(meta_path, "wb") as f:
        pickle.dump(chunk_ids, f)


def search_index(document_id: str, query_vec: np.ndarray, top_k: int = 5) -> list[tuple[int, float]]:
    index_path, meta_path = _paths(document_id)

    if not index_path.exists():
        raise FileNotFoundError(f"Index not found for document {document_id}. Is it still processing?")

    index = faiss.read_index(str(index_path))
    with open(meta_path, "rb") as f:
        chunk_ids: list[int] = pickle.load(f)

    query_vec = query_vec.reshape(1, -1).astype("float32")
    k = min(top_k, len(chunk_ids))
    scores, indices = index.search(query_vec, k)

    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx != -1 and float(score) >= SIMILARITY_THRESHOLD:
            results.append((chunk_ids[int(idx)], float(score)))

    # Keep original document order for the LLM — reading chunks in sequence
    # makes the context easier to follow than ranking purely by similarity score.
    results.sort(key=lambda x: x[0])
    return results


def delete_index(document_id: str) -> None:
    for path in _paths(document_id):
        if path.exists():
            path.unlink()
