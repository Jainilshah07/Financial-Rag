# Roadmap

One step at a time; each step is reviewed before the next starts.

| # | Step | Status |
|---|---|---|
| 0 | Requirements, ambiguities, architecture, ADRs | Done |
| 1 | Retrieval evaluation on PostgreSQL + pgvector | In progress |
| 1a | Schema (documents, pages, chunks, embeddings, runs) | Done |
| 1b | Chunking: recursive, page, structure-aware (+ optional document context) | Done |
| 1c | Ingestion into Postgres (context from the PDF); retrieval: dense, keyword (Postgres full-text), hybrid | Done |
| 1d | Metrics (`evals/evaluate.py`): Hit@1, Hit@5, MRR, tokens; choose chunking and retrieval | In review |
| 1e | App on Postgres: backend → frontend → (later) remove old Qdrant code | Backend done; frontend in review |
| 2 | Corpus from the mentor's scenarios; golden set (40 questions) | Waiting on scenarios |
| 3 | Structured extraction + SQL answers with verifier | — |
| 4 | Router (structured / semantic / hybrid / out-of-scope) + hybrid answering | — |
| 5 | OCR + confidence threshold | — |
| 6 | PO/invoice mismatch detection | — |
| 7 | Hardening: Docker, logging, CI eval gate, budget, ablation, writeup | — |

Interim test data: `evals/` holds a generated set of 8 linked POs and invoices with 56 questions, until the mentor's scenarios arrive.

## Known issues in the current app

- PDF ligatures ("oﬃce") are not normalised; fix with NFKC at ingestion.
- `ingestion.py` misses numbered clauses whose first line is longer than 80 characters.
