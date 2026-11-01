# ADR-001: PostgreSQL + pgvector as the single store

**Status:** Accepted · 2026-10-22

**Context.** We need a relational store for extracted fields and arithmetic, and vector search. Hybrid questions filter numerically first, then search semantically. PostgreSQL 18 with pgvector 0.8.7 is installed locally.

| Option | For | Against |
|---|---|---|
| **Postgres + pgvector** | Filter and vector ranking in one query; one transaction per document; built-in full-text search | Retires Qdrant code |
| Postgres + Qdrant | Keeps existing work | Two stores to keep in sync; more to deploy |

**Decision.** Postgres + pgvector only. Vectors and a full-text index sit on chunks, next to filter metadata (HNSW for vectors, GIN for text).

**Consequences.** Qdrant and `rank-bm25` are removed. `ts_rank` is not true BM25; `pg_search` is the fallback if evaluation shows a gap.

**Revisit if** the corpus reaches millions of chunks or latency exceeds budget after index tuning.
