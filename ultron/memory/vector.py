"""Vector search over memory embeddings."""

from __future__ import annotations

import logging

import numpy as np

from ultron.memory.embeddings import LocalEmbeddingModel, cosine_similarity
from ultron.memory.store import MemoryStore


class VectorMemorySearch:
    """Vector similarity search engine for Ultron memories."""

    def __init__(
        self,
        store: MemoryStore,
        model: LocalEmbeddingModel | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._store = store
        self._model = model or LocalEmbeddingModel()
        self._log = logger or logging.getLogger("ultron.memory.vector")

    def remember(
        self,
        content: str,
        memory_type: str = "long_term",
        source: str = "user",
        importance: float = 0.5,
        tags: str = "",
    ) -> int:
        """Embed content and persist it to the SQLite store."""
        vec = self._model.embed(content)
        vector_bytes = vec.tobytes()
        row_id = self._store.store_embedding(
            content=content,
            vector=vector_bytes,
            memory_type=memory_type,
            source=source,
            importance=importance,
            tags=tags,
        )
        self._log.debug("Stored embedding entry #%d (%s)", row_id, memory_type)
        return row_id

    def search(
        self, query: str, limit: int = 5, min_score: float = 0.1
    ) -> list[tuple[float, str]]:
        """Search memory entries by semantic vector similarity.

        Args:
            query: Natural language query.
            limit: Top N results.
            min_score: Minimum cosine similarity threshold.

        Returns:
            List of (similarity_score, content) tuples, highest similarity first.
        """
        query_vec = self._model.embed(query)
        entries = self._store.get_all_embeddings()
        results: list[tuple[float, str]] = []

        for row_id, content, vector_bytes in entries:
            if vector_bytes is None:
                continue
            try:
                doc_vec = np.frombuffer(vector_bytes, dtype=np.float32)
                score = cosine_similarity(query_vec, doc_vec)
                if score >= min_score:
                    results.append((score, content))
            except ValueError:
                continue

        results.sort(key=lambda item: item[0], reverse=True)
        return results[:limit]
