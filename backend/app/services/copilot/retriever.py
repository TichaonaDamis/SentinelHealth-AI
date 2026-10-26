"""Hybrid retrieval: BM25 lexical + dense vector similarity fused with Reciprocal Rank Fusion.

Lexical search catches exact terms (ICD codes, pathogen names, county names);
dense search catches paraphrases ("kids with rash and fever" ~ measles case
definition). RRF is robust to the two scores being on different scales.

``SQLHybridRetriever`` works on any database (scores computed in-process over
the candidate set) and is used for MVP / tests. ``OpenSearchHybridRetriever``
pushes both legs down to Amazon OpenSearch (k-NN + BM25) for national scale.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import KnowledgeChunk
from app.services.copilot.embeddings import Embedder, tokenize

RRF_K = 60


@dataclass
class RetrievedChunk:
    chunk_id: int
    document_title: str
    document_source: str | None
    doc_type: str
    text: str
    score: float
    lexical_rank: int | None
    vector_rank: int | None


def bm25_scores(query: str, docs: list[str], k1: float = 1.5, b: float = 0.75) -> np.ndarray:
    q = tokenize(query)
    toks = [tokenize(d) for d in docs]
    n = len(docs)
    if not n or not q:
        return np.zeros(n)
    avgdl = sum(map(len, toks)) / n or 1.0
    df = Counter(t for doc in toks for t in set(doc))
    scores = np.zeros(n)
    for i, doc in enumerate(toks):
        tf = Counter(doc)
        for term in q:
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            scores[i] += idf * tf[term] * (k1 + 1) / (tf[term] + k1 * (1 - b + b * len(doc) / avgdl))
    return scores


def rrf(rankings: list[list[int]], k: int = RRF_K) -> dict[int, float]:
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return fused


class SQLHybridRetriever:
    def __init__(self, db: AsyncSession, embedder: Embedder):
        self.db, self.embedder = db, embedder

    async def search(self, query: str, top_k: int = 6, disease: str | None = None,
                     candidate_limit: int = 5000) -> list[RetrievedChunk]:
        stmt = select(KnowledgeChunk).options(selectinload(KnowledgeChunk.document)).limit(candidate_limit)
        chunks = list((await self.db.scalars(stmt)).all())
        if disease:
            # Prefer disease-specific and general documents; drop other diseases' documents.
            chunks = [c for c in chunks if c.document.disease_code in (None, disease)]
        if not chunks:
            return []
        texts = [f"{c.document.title}. {c.text}" for c in chunks]
        lex = bm25_scores(query, texts)
        qv = (await self.embedder.embed([query]))[0]
        mat = np.array([c.embedding if c.embedding is not None else np.zeros(len(qv)) for c in chunks], dtype=np.float32)
        dense = mat @ qv
        depth = min(len(chunks), 50)
        lex_rank = [int(i) for i in np.argsort(-lex)[:depth] if lex[i] > 0]
        vec_rank = [int(i) for i in np.argsort(-dense)[:depth]]
        fused = rrf([lex_rank, vec_rank])
        best = sorted(fused.items(), key=lambda kv: -kv[1])[:top_k]
        return [
            RetrievedChunk(
                chunk_id=chunks[i].id, document_title=chunks[i].document.title,
                document_source=chunks[i].document.source, doc_type=chunks[i].document.doc_type,
                text=chunks[i].text, score=round(s, 5),
                lexical_rank=lex_rank.index(i) + 1 if i in lex_rank else None,
                vector_rank=vec_rank.index(i) + 1 if i in vec_rank else None,
            )
            for i, s in best
        ]


class OpenSearchHybridRetriever:  # pragma: no cover - exercised in integration environments
    """Uses an OpenSearch search pipeline with ``normalization-processor`` for hybrid queries."""

    def __init__(self, url: str, embedder: Embedder, index: str = "sentinel-knowledge"):
        from opensearchpy import AsyncOpenSearch

        self.client = AsyncOpenSearch(hosts=[url], use_ssl=url.startswith("https"), verify_certs=True)
        self.embedder, self.index = embedder, index

    async def search(self, query: str, top_k: int = 6, disease: str | None = None) -> list[RetrievedChunk]:
        qv = (await self.embedder.embed([query]))[0].tolist()
        flt = [{"terms": {"disease_code": [disease, "GENERAL"]}}] if disease else []
        body = {
            "size": top_k,
            "query": {"hybrid": {"queries": [
                {"bool": {"must": {"match": {"text": query}}, "filter": flt}},
                {"knn": {"embedding": {"vector": qv, "k": 50, "filter": {"bool": {"filter": flt}} if flt else None}}},
            ]}},
        }
        res = await self.client.search(index=self.index, body=body, params={"search_pipeline": "sentinel-hybrid"})
        return [
            RetrievedChunk(chunk_id=int(h["_id"]), document_title=h["_source"]["title"],
                           document_source=h["_source"].get("source"), doc_type=h["_source"]["doc_type"],
                           text=h["_source"]["text"], score=float(h["_score"]), lexical_rank=None, vector_rank=None)
            for h in res["hits"]["hits"]
        ]


def chunk_text(text: str, max_words: int = 180, overlap: int = 40) -> list[str]:
    """Paragraph-aware chunking with word overlap."""
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks, buf = [], []
    for p in paras:
        words = p.split()
        if len(buf) + len(words) > max_words and buf:
            chunks.append(" ".join(buf))
            buf = buf[-overlap:]
        buf.extend(words)
        while len(buf) > max_words:
            chunks.append(" ".join(buf[:max_words]))
            buf = buf[max_words - overlap:]
    if buf:
        chunks.append(" ".join(buf))
    return chunks
