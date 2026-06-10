from functools import lru_cache
import numpy as np
from fastembed import TextEmbedding


# lru_cache keeps a single model instance in memory (~130 MB).
# The model is also pre-downloaded in the Dockerfile so the first request isn't slow.
@lru_cache(maxsize=1)
def get_embedding_model() -> TextEmbedding:
    return TextEmbedding("BAAI/bge-small-en-v1.5")


def embed_text(text: str) -> list[float]:
    """Return a 384-dimensional embedding for the given text."""
    model = get_embedding_model()
    result = list(model.embed([text]))
    return result[0].tolist()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Return cosine similarity in [-1, 1]. Returns 0.0 for zero vectors."""
    va = np.array(a, dtype=float)
    vb = np.array(b, dtype=float)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)
