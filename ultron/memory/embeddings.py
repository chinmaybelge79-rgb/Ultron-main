"""Embedding generation for Ultron memory subsystem.

Provides vector embeddings using sentence-transformers (when available) or a lightweight
TF-IDF / hashed n-gram fallback (zero external heavy dependency).

The fallback vectorizer uses a deterministic hash (FNV-1a) so vectors are
stable across processes; Python's built-in :func:`hash` is randomized per
process and would silently break persisted vector search.
"""

from __future__ import annotations

import logging
import re

import numpy as np

from ultron.utils import EmbeddingError

_TOKEN_RE = re.compile(r"\w+")
_DIM = 384

_log = logging.getLogger("ultron.memory.embeddings")


def _stable_bucket(token: str, buckets: int) -> int:
    """Map a token to a bucket using a deterministic 32-bit FNV-1a hash."""
    h = 2166136261
    for byte in token.encode("utf-8"):
        h ^= byte
        h = (h * 16777619) & 0xFFFFFFFF
    return h % buckets


class LocalEmbeddingModel:
    """Generates vector embeddings for memory search.

    Uses sentence-transformers if installed; otherwise uses a fast 384-dimensional
    normalized hashed n-gram vectorizer for offline semantic similarity.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", dim: int = 384) -> None:
        self.model_name = model_name
        self.dim = dim
        self._st_model = None
        self._attempted_load = False

    def _load_model(self) -> None:
        if self._attempted_load:
            return
        try:
            from sentence_transformers import SentenceTransformer

            self._st_model = SentenceTransformer(self.model_name)
            self._attempted_load = True
        except ImportError:
            self._attempted_load = True
            self._st_model = None
        except Exception as exc:  # e.g. model download/init failure
            self._attempted_load = True
            self._st_model = None
            _log.warning(
                "SentenceTransformer unavailable (%s); "
                "using the built-in vectorizer.",
                exc,
            )

    def embed(self, text: str) -> np.ndarray:
        """Embed a single text string into a float32 vector.

        Returns:
            Normalized 1D numpy array of shape (dim,).
        """
        if not text or not text.strip():
            return np.zeros(self.dim, dtype=np.float32)

        self._load_model()
        if self._st_model is not None:
            try:
                vec = self._st_model.encode(text, convert_to_numpy=True)
                norm = np.linalg.norm(vec)
                return (
                    (vec / norm).astype(np.float32)
                    if norm > 0
                    else vec.astype(np.float32)
                )
            except Exception as exc:
                raise EmbeddingError(
                    f"SentenceTransformer embedding failed: {exc}"
                ) from exc

        # Lightweight deterministic fallback: hashed term frequency vector
        tokens = _TOKEN_RE.findall(text.lower())
        vec = np.zeros(self.dim, dtype=np.float32)
        if not tokens:
            return vec

        for token in tokens:
            vec[_stable_bucket(token, self.dim)] += 1.0

        # Also add bigrams for local context
        for i in range(len(tokens) - 1):
            bigram = f"{tokens[i]}_{tokens[i + 1]}"
            vec[_stable_bucket(bigram, self.dim)] += 0.5

        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec /= norm
        return vec.astype(np.float32)

    def embed_many(self, texts: list[str]) -> list[np.ndarray]:
        """Embed multiple texts into vectors."""
        return [self.embed(t) for t in texts]


def cosine_similarity(v1: np.ndarray, v2: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    dot = float(np.dot(v1, v2))
    n1 = float(np.linalg.norm(v1))
    n2 = float(np.linalg.norm(v2))
    if n1 == 0.0 or n2 == 0.0:
        return 0.0
    return dot / (n1 * n2)
