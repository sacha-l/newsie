"""Embedding providers — production OpenAI + deterministic hash for demos."""

from __future__ import annotations

import hashlib
import math
import struct
from datetime import UTC, datetime
from typing import Protocol

from newsie.config import Settings
from newsie.domain import Article, ArticleEmbedding


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class HashEmbeddingProvider:
    """Offline deterministic embeddings for demos/tests (no API)."""

    def __init__(self, dim: int = 1536) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        seed = hashlib.sha256(text.encode("utf-8")).digest()
        values: list[float] = []
        counter = 0
        while len(values) < self.dim:
            block = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
            for i in range(0, len(block) - 3, 4):
                raw = struct.unpack(">I", block[i : i + 4])[0]
                values.append((raw / 2**32) * 2.0 - 1.0)
                if len(values) >= self.dim:
                    break
            counter += 1
        # L2 normalize
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]


class OpenAIEmbeddingProvider:
    def __init__(self, api_key: str, model: str, dim: int) -> None:
        self.api_key = api_key
        self.model = model
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        import httpx

        resp = httpx.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": texts, "dimensions": self.dim},
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        data_sorted = sorted(data, key=lambda d: d["index"])
        return [row["embedding"] for row in data_sorted]


def embed_articles(
    articles: list[Article],
    provider: EmbeddingProvider,
    settings: Settings,
) -> list[ArticleEmbedding]:
    if not articles:
        return []
    vectors = provider.embed([f"{a.title}\n{a.content_text}" for a in articles])
    now = datetime.now(UTC)
    out: list[ArticleEmbedding] = []
    for article, vector in zip(articles, vectors, strict=True):
        if len(vector) != settings.embedding_dim:
            raise ValueError(
                f"embedding dim mismatch: got {len(vector)}, want {settings.embedding_dim}"
            )
        out.append(
            ArticleEmbedding(
                article_id=article.id,
                embedding=vector,
                embedding_model=settings.embedding_model,
                embedding_dim=settings.embedding_dim,
                embedded_at=now,
            )
        )
    return out
