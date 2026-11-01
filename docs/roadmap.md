# Roadmap

One step at a time; each step is reviewed before the next starts.

| # | Step | Status |
|---|---|---|
| 0 | Requirements, ambiguities, architecture, ADRs | Done |
| 1 | Retrieval evaluation on PostgreSQL + pgvector | In progress |
| 1a | Schema (documents, pages, chunks, embeddings, runs) | Next |
| 1b | Three chunking strategies | — |
| 1c | Retrieval: dense, BM25, hybrid | — |
| 1d | Essential metrics; choose chunking and retrieval | — |
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
