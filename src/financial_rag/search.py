"""Retrieval over Postgres: dense (pgvector), keyword (full-text), hybrid (RRF), rerank (cross-encoder),
dense_ids (dense within the documents a question's document number points to),
dense_intent (dense_ids within the document type the question asks about, per the LLM).

Every method searches one chunker's chunks and returns Hits, best first. `score` means:
cosine similarity (dense, dense_ids, dense_intent), ts_rank (keyword), RRF score (hybrid),
cross-encoder relevance (rerank).

    uv run python -m financial_rag.search "What are the payment terms in PO/2026-27/0103?" --chunker structure
"""

import argparse
import re
from dataclasses import dataclass, replace
from functools import cache

from docling_core.types.doc import DoclingDocument
from sqlalchemy import Text, cast, func, select
from sqlalchemy.dialects.postgresql import TSQUERY

from financial_rag.chunkers import doc_header
from financial_rag.db import Chunk, Document, Embedding, get_sessionmaker
from financial_rag.embeddings import MODEL_KEY, embed_query

TOP_K = 10
CANDIDATES = 20  # per list, before fusion or reranking
RRF_K = 60
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
IDENTIFIER = re.compile(r"[A-Za-z0-9]+(?:[/-][A-Za-z0-9]+)+")  # e.g. PO/2026-27/0204, BST-1209


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
    search_text: str  # header + section + text: what was embedded, and what the reranker reads


def _hits(rows) -> list[Hit]:
    return [Hit(c.id, c.document_id, filename, c.page_start, c.page_end, c.section, c.text, float(score),
                c.search_text) for c, filename, score in rows]


def _base(score, chunker: str, document_id: int | None, document_ids: set[int] | None = None):
    stmt = (select(Chunk, Document.filename, score.label("score"))
            .join(Document, Document.id == Chunk.document_id)
            .where(Chunk.chunker == chunker))
    if document_ids:
        stmt = stmt.where(Chunk.document_id.in_(document_ids))
    return stmt.where(Chunk.document_id == document_id) if document_id else stmt


def dense(s, query: str, chunker: str, k: int = TOP_K, document_id: int | None = None,
          document_ids: set[int] | None = None) -> list[Hit]:
    distance = Embedding.embedding.cosine_distance(embed_query(query))
    stmt = (_base(1 - distance, chunker, document_id, document_ids)
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


@cache
def reranker():
    from sentence_transformers import CrossEncoder  # heavy import; only needed when reranking

    return CrossEncoder(RERANK_MODEL)


def rerank(s, query: str, chunker: str, k: int = TOP_K, document_id: int | None = None) -> list[Hit]:
    """Dense top CANDIDATES, re-scored by a cross-encoder that reads the question and each chunk together."""
    candidates = dense(s, query, chunker, CANDIDATES, document_id)
    if not candidates:
        return []
    scores = reranker().predict([(query, h.search_text) for h in candidates])
    ranked = sorted(zip(candidates, scores), key=lambda pair: pair[1], reverse=True)[:k]
    return [replace(h, score=float(score)) for h, score in ranked]


def identifiers(query: str) -> list[str]:
    """Document-number-like tokens: letters, at least 3 digits and a / or - (not dates, not "A4")."""
    return [t for t in IDENTIFIER.findall(query) if any(c.isalpha() for c in t) and sum(c.isdigit() for c in t) >= 3]


def identifier_documents(s, query: str, chunker: str) -> set[int]:
    """Documents whose chunks contain a question's identifier as an exact full-text token.

    Postgres keeps "PO/2026-27/0204" as one token, so this is an exact match, not a similarity.
    A PO number also appears on its invoice, so both are kept; ranking picks between them.
    """
    found: set[int] = set()
    for token in identifiers(query):
        found |= set(s.scalars(select(Chunk.document_id).distinct().where(
            Chunk.chunker == chunker, Chunk.search_tsv.op("@@")(func.plainto_tsquery("english", token)))))
    return found


def dense_ids(s, query: str, chunker: str, k: int = TOP_K, document_id: int | None = None) -> list[Hit]:
    """Dense search; when the question names a known document number, only within those documents."""
    documents = None if document_id else identifier_documents(s, query, chunker)
    return dense(s, query, chunker, k, document_id, documents or None)


def dense_intent(s, query: str, chunker: str, k: int = TOP_K, document_id: int | None = None) -> list[Hit]:
    """dense_ids, limited to the document type the question asks about when the LLM is clear about it.

    "either", "unknown", an API failure, or a filter that leaves no results all fall back to dense_ids.
    """
    from financial_rag.classify import classify_question  # LLM call; only this method needs it

    if document_id:
        return dense(s, query, chunker, k, document_id)
    intent = classify_question(query).doc_type
    if intent in ("purchase_order", "invoice"):
        typed = set(s.scalars(select(Document.id).where(Document.doc_type == intent)))
        by_number = identifier_documents(s, query, chunker)
        documents = (by_number & typed) if by_number else typed
        if documents and (hits := dense(s, query, chunker, k, None, documents)):
            return hits
    return dense_ids(s, query, chunker, k)


METHODS = {"dense": dense, "keyword": keyword, "hybrid": hybrid, "rerank": rerank, "dense_ids": dense_ids,
           "dense_intent": dense_intent}

_headers: dict[tuple, str] = {}


def document_headers(s, document_ids: set[int]) -> dict[int, str]:
    """Each document's header for the answer context: doc_header() on the stored Docling JSON and type, exactly
    as at ingestion, so retrieval and generation see the same identity. Cached per (document, type, content)."""
    out = {}
    for doc_id, doc_type, content_hash in s.execute(
            select(Document.id, Document.doc_type, Document.content_hash).where(Document.id.in_(document_ids))):
        key = (doc_id, doc_type, content_hash)
        if key not in _headers:
            data = s.scalar(select(Document.docling_json).where(Document.id == doc_id))
            _headers[key] = doc_header(DoclingDocument.model_validate(data), doc_type) if data else ""
        out[doc_id] = _headers[key]
    return out


def search(query: str, chunker: str, method: str = "hybrid", k: int = TOP_K, document_id: int | None = None) -> list[Hit]:
    with get_sessionmaker()() as s:
        return METHODS[method](s, query, chunker, k, document_id)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Search one chunker's chunks (read-only).")
    ap.add_argument("query")
    ap.add_argument("--chunker", default="structure", help="structure | hybrid")
    ap.add_argument("--method", choices=METHODS, default="hybrid")
    ap.add_argument("-k", type=int, default=5)
    args = ap.parse_args()
    for n, h in enumerate(search(args.query, args.chunker, args.method, args.k), 1):
        print(f"#{n} {h.score:.4f} {h.filename} p{h.page_start} [{h.section or '-'}]")
        print("   " + h.text[:160].replace("\n", " "))
