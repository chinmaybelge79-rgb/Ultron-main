"""Tests for local embeddings and vector memory search."""

from __future__ import annotations

import numpy as np

from ultron.memory.embeddings import LocalEmbeddingModel, cosine_similarity
from ultron.memory.vector import VectorMemorySearch


def test_embedding_model_shape():
    model = LocalEmbeddingModel(dim=384)
    vec = model.embed("Hello world")
    assert isinstance(vec, np.ndarray)
    assert vec.shape == (384,)
    assert vec.dtype == np.float32


def test_embedding_model_empty():
    model = LocalEmbeddingModel(dim=384)
    vec = model.embed("")
    assert np.all(vec == 0)


def test_cosine_similarity():
    v1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    v2 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    v3 = np.array([0.0, 1.0, 0.0], dtype=np.float32)

    assert cosine_similarity(v1, v2) == 1.0
    assert cosine_similarity(v1, v3) == 0.0


def test_vector_memory_search_roundtrip(memory):
    vec_search = VectorMemorySearch(memory)
    vec_search.remember("My favorite food is sushi", tags="food")
    vec_search.remember("The weather in San Francisco is foggy", tags="weather")

    results = vec_search.search("sushi food", limit=2)
    assert len(results) >= 1
    assert "sushi" in results[0][1]
