import re

import numpy as np
from langchain_core.vectorstores.utils import maximal_marginal_relevance
from qdrant_client import models
from rank_bm25 import BM25Okapi

from financial_rag.rag import llm
from financial_rag.vector_store import _scroll_all, chunk_from_point, document_point_ids

TOP_K = 4
FETCH_K = 20
SCORE_THRESHOLD = 0.6
RRF_K = 60


def _document_filter(client, document_id):
    if not document_id:
        return None
    ids = document_point_ids(client, document_id)
    return models.Filter(must=[models.HasIdCondition(has_id=ids)])


def _dense(vector_store, question, limit, query_filter, with_vectors=False):
    vector = vector_store.embeddings.embed_query(question)
    response = vector_store.client.query_points(
        vector_store.collection_name,
        query=vector,
        query_filter=query_filter,
        limit=limit,
        with_payload=True,
        with_vectors=with_vectors,
    )
    return vector, response.points


def _rrf(ranked_lists):
    """Reciprocal Rank Fusion: merge several ranked lists of points."""
    scores, points = {}, {}
    for ranked in ranked_lists:
        for rank, point in enumerate(ranked):
            scores[point.id] = scores.get(point.id, 0) + 1 / (RRF_K + rank + 1)
            points[point.id] = point
    ordered = sorted(scores, key=scores.get, reverse=True)
    return [(points[i], scores[i]) for i in ordered]


def _bm25(client, question, limit, query_filter):
    points = _scroll_all(client, query_filter)
    if not points:
        return []

    def tokenize(text):
        return re.findall(r"\w+", text.lower())

    corpus = [tokenize(chunk_from_point(p)["text"]) for p in points]
    scores = BM25Okapi(corpus).get_scores(tokenize(question))
    ranked = sorted(zip(points, scores), key=lambda x: x[1], reverse=True)
    return [p for p, score in ranked[:limit] if score > 0]


def similarity(vs, question, query_filter):
    _, points = _dense(vs, question, TOP_K, query_filter)
    return [(p, p.score) for p in points]


def mmr(vs, question, query_filter):
    vector, points = _dense(vs, question, FETCH_K, query_filter, with_vectors=True)
    if not points:
        return []
    picked = maximal_marginal_relevance(
        np.array(vector), [p.vector for p in points], lambda_mult=0.5, k=TOP_K
    )
    return [(points[i], points[i].score) for i in picked]


def threshold(vs, question, query_filter):
    _, points = _dense(vs, question, TOP_K * 2, query_filter)
    return [(p, p.score) for p in points if p.score >= SCORE_THRESHOLD]


def multi_query(vs, question, query_filter):
    reply = llm.invoke(
        "Rewrite the following question as 3 different search queries that "
        "could retrieve relevant passages from a financial document. "
        "Return one query per line, with no numbering or extra text.\n\n"
        f"Question: {question}"
    )
    variants = [
        line.strip(" -*0123456789.")
        for line in reply.content.splitlines()
        if line.strip()
    ][:3]

    ranked_lists = [
        _dense(vs, q, 10, query_filter)[1] for q in [question, *variants]
    ]
    return _rrf(ranked_lists)[:TOP_K]


def hybrid(vs, question, query_filter):
    _, dense_points = _dense(vs, question, FETCH_K, query_filter)
    keyword_points = _bm25(vs.client, question, FETCH_K, query_filter)
    return _rrf([dense_points, keyword_points])[:TOP_K]


STRATEGIES = {
    "similarity": {
        "label": "Similarity (top-k)",
        "description": f"Plain vector search, top {TOP_K} chunks by cosine similarity.",
        "score_label": "cosine",
        "fn": similarity,
    },
    "mmr": {
        "label": "MMR",
        "description": f"Max Marginal Relevance: top {TOP_K} chunks chosen from the best {FETCH_K}, balancing relevance and diversity.",
        "score_label": "cosine",
        "fn": mmr,
    },
    "threshold": {
        "label": "Similarity + score threshold",
        "description": f"Only chunks with cosine similarity >= {SCORE_THRESHOLD} (up to {TOP_K * 2}); may return none.",
        "score_label": "cosine",
        "fn": threshold,
    },
    "multi_query": {
        "label": "Multi-query",
        "description": "The LLM rewrites the question into 3 variants; results are merged with Reciprocal Rank Fusion.",
        "score_label": "RRF",
        "fn": multi_query,
    },
    "hybrid": {
        "label": "Hybrid (BM25 + vector)",
        "description": "Keyword (BM25) and vector search results merged with Reciprocal Rank Fusion.",
        "score_label": "RRF",
        "fn": hybrid,
    },
}


def list_strategies():
    return [
        {"id": key, "label": s["label"], "description": s["description"]}
        for key, s in STRATEGIES.items()
    ]


def retrieve(vector_store, strategy: str, question: str, document_id: str | None):
    spec = STRATEGIES[strategy]
    query_filter = _document_filter(vector_store.client, document_id)
    results = spec["fn"](vector_store, question, query_filter)

    return [
        {
            **chunk_from_point(point),
            "index": rank + 1,
            "score": round(float(score), 4),
            "score_label": spec["score_label"],
        }
        for rank, (point, score) in enumerate(results)
    ]
