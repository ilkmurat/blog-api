"""Qdrant vector store for semantic post search."""

import hashlib
import math
import re
from functools import lru_cache
from typing import Protocol

from qdrant_client import QdrantClient, models

from app.config import get_settings
from app.models import Post


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FastEmbedder:
    def __init__(self, model_name: str) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name)
        self.dim = len(next(iter(self._model.embed(["dim"]))))

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.embed(texts)]


class HashEmbedder:
    """Deterministic bag-of-words hashing embedder; no model download. Used for tests."""

    dim = 256

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vec = [0.0] * self.dim
            for word in re.findall(r"[a-z0-9]+", text.lower()):
                vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dim] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vectors.append([v / norm for v in vec])
        return vectors


class VectorStore:
    def __init__(self, client: QdrantClient, collection: str, embedder: Embedder) -> None:
        self.client = client
        self.collection = collection
        self.embedder = embedder

    def ensure_collection(self) -> None:
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                self.collection,
                vectors_config=models.VectorParams(size=self.embedder.dim, distance=models.Distance.COSINE),
            )

    @staticmethod
    def _document(post: Post) -> str:
        tags = " ".join(t.name for t in post.tags)
        return f"{post.title}\n{post.excerpt}\n{post.category.name} {tags}\n{post.content}"

    def upsert(self, post: Post) -> None:
        [vector] = self.embedder.embed([self._document(post)])
        self.client.upsert(
            self.collection,
            points=[models.PointStruct(id=post.id, vector=vector, payload={"slug": post.slug})],
            wait=True,
        )

    def delete(self, post_id: int) -> None:
        self.client.delete(self.collection, points_selector=models.PointIdsList(points=[post_id]), wait=True)

    def search(self, query: str, limit: int) -> list[tuple[int, float]]:
        [vector] = self.embedder.embed([query])
        result = self.client.query_points(self.collection, query=vector, limit=limit)
        return [(int(p.id), p.score) for p in result.points]

    def healthy(self) -> bool:
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False


@lru_cache
def get_vector_store() -> VectorStore:
    settings = get_settings()
    embedder: Embedder = (
        HashEmbedder() if settings.embedding_provider == "hash" else FastEmbedder(settings.embedding_model)
    )
    return VectorStore(QdrantClient(url=settings.qdrant_url), settings.qdrant_collection, embedder)
