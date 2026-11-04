"""Retrieval over Postgres: dense (pgvector), keyword (full-text), hybrid (RRF).

Every method searches one chunker's chunks and returns Hits, best first. `score` means:
cosine similarity (dense), ts_rank (keyword), RRF score (hybrid).

    uv run python -m financial_rag.search "What are the payment terms in PO/2026-27/0103?" --chunker structure_ctx
"""

import argparse
from dataclasses import dataclass, replace

from sqlalchemy import Text, cast, func, select
from sqlalchemy.dialects.postgresql import TSQUERY

from financial_rag.db import Chunk, Document, Embedding, get_sessionmaker
from financial_rag.embeddings import MODEL_KEY, embed_query

TOP_K = 10
CANDIDATES = 20  # per list, before fusion
RRF_K = 60


@dataclass
class Hit:
    chunk_id: int
    document_id: int
    filename: str
    page_start: int
    page_end: int
    section: str | None
    text: str
    score: float


def _hits(rows) -> list[Hit]:
    return [Hit(c.id, c.document_id, filename, c.page_start, c.page_end, c.section, c.text, float(score))
            for c, filename, score in rows]


def _base(score, chunker: str, document_id: int | None):
    stmt = (select(Chunk, Document.filename, score.label("score"))
            .join(Document, Document.id == Chunk.document_id)
            .where(Chunk.chunker == chunker))
    return stmt.where(Chunk.document_id == document_id) if document_id else stmt


def dense(s, query: str, chunker: str, k: int = TOP_K, document_id: int | None = None) -> list[Hit]:
    distance = Embedding.embedding.cosine_distance(embed_query(query))
    stmt = (_base(1 - distance, chunker, document_id)
            .join(Embedding, (Embedding.text_hash == Chunk.text_hash) & (Embedding.model == MODEL_KEY))
            .order_by(distance).limit(k))
    return _hits(s.execute(stmt))


def keyword(s, query: str, chunker: str, k: int = TOP_K, document_id: int | None = None) -> list[Hit]:
    """Postgres full-text search. Any query word may match (OR, like BM25), but ranking is ts_rank:
    term frequency with length normalisation and no IDF, so it is not true BM25."""
    # same parser and stemming as the stored search_tsv; turn its AND (&) into OR (|)
    tsquery = cast(func.replace(cast(func.plainto_tsquery("english", query), Text), "&", "|"), TSQUERY)
    rank = func.ts_rank(Chunk.search_tsv, tsquery, 1)  # 1 = divide by log(document length)
    stmt = (_base(rank, chunker, document_id)
            .where(Chunk.search_tsv.op("@@")(tsquery))
            .order_by(rank.desc()).limit(k))
    return _hits(s.execute(stmt))


def hybrid(s, query: str, chunker: str, k: int = TOP_K, document_id: int | None = None) -> list[Hit]:
    """Reciprocal Rank Fusion of the dense and keyword lists."""
    scores, hits = {}, {}
    for ranked in (dense(s, query, chunker, CANDIDATES, document_id),
                   keyword(s, query, chunker, CANDIDATES, document_id)):
        for rank, h in enumerate(ranked):
            scores[h.chunk_id] = scores.get(h.chunk_id, 0) + 1 / (RRF_K + rank + 1)
            hits[h.chunk_id] = h
    best = sorted(scores, key=scores.get, reverse=True)[:k]
    return [replace(hits[i], score=scores[i]) for i in best]


METHODS = {"dense": dense, "keyword": keyword, "hybrid": hybrid}


def search(query: str, chunker: str, method: str = "hybrid", k: int = TOP_K, document_id: int | None = None) -> list[Hit]:
    with get_sessionmaker()() as s:
        return METHODS[method](s, query, chunker, k, document_id)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Search one chunker's chunks (read-only).")
    ap.add_argument("query")
    ap.add_argument("--chunker", default="structure_ctx", help="recursive_ctx | page_ctx | structure_ctx")
    ap.add_argument("--method", choices=METHODS, default="hybrid")
    ap.add_argument("-k", type=int, default=5)
    args = ap.parse_args()
    for n, h in enumerate(search(args.query, args.chunker, args.method, args.k), 1):
        print(f"#{n} {h.score:.4f} {h.filename} p{h.page_start} [{h.section or '-'}]")
        print("   " + h.text[:160].replace("\n", " "))
