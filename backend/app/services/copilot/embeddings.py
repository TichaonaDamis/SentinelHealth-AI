"""Text embeddings.

``OpenAIEmbedder`` is used when an API key is configured; otherwise the
deterministic ``HashingEmbedder`` (signed feature hashing over word unigrams,
bigrams and character trigrams) keeps retrieval fully offline, which is useful
for air-gapped public-health deployments and for tests.
"""

from __future__ import annotations

import hashlib
import re
from typing import Protocol

import numpy as np

from app.core.config import get_settings

TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


class Embedder(Protocol):
    name: str
    dim: int

    async def embed(self, texts: list[str]) -> np.ndarray: ...


class HashingEmbedder:
    name = "hashing-v1"

    def __init__(self, dim: int = 384):
        self.dim = dim

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        toks = tokenize(text)
        feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
        for t in toks:
            padded = f"#{t}#"
            feats += [padded[i:i + 3] for i in range(len(padded) - 2)]
        for f in feats:
            h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "little")
            v[h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
        n = np.linalg.norm(v)
        return v / n if n else v

    async def embed(self, texts: list[str]) -> np.ndarray:
        return np.vstack([self._vec(t) for t in texts]) if texts else np.zeros((0, self.dim), dtype=np.float32)


class OpenAIEmbedder:
    def __init__(self, api_key: str, model: str, dim: int):
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(api_key=api_key)
        self.model, self.dim, self.name = model, dim, f"openai:{model}"

    async def embed(self, texts: list[str]) -> np.ndarray:
        resp = await self.client.embeddings.create(model=self.model, input=texts, dimensions=self.dim)
        arr = np.array([d.embedding for d in resp.data], dtype=np.float32)
        return arr / np.linalg.norm(arr, axis=1, keepdims=True)


def get_embedder() -> Embedder:
    s = get_settings()
    if s.openai_api_key:
        return OpenAIEmbedder(s.openai_api_key, s.openai_embedding_model, s.embedding_dim)
    return HashingEmbedder(s.embedding_dim)
