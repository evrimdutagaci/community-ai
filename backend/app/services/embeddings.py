from functools import lru_cache
import numpy as np
from fastembed import TextEmbedding


@lru_cache(maxsize=1)
def get_embedding_model() -> TextEmbedding:
    return TextEmbedding("BAAI/bge-small-en-v1.5")


def embed_text(text: str) -> list[float]:
    model = get_embedding_model()
    result = list(model.embed([text]))
    return result[0].tolist()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.array(a, dtype=float)
    vb = np.array(b, dtype=float)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)
