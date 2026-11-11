# Roadmap – approach 2 (Docling)

Goal 1 is a proper RAG pipeline whose extraction works across document layouts, not one template.
One step at a time; each step is reviewed before the next starts.

| # | Step | Learning focus | Status |
|---|---|---|---|
| 0 | Remove old Qdrant code; this roadmap | — | Done |
| 1 | Docling extraction: run on sample PDFs, read the `DoclingDocument` (labels, tables, pages, reading order), store its JSON per document | Layout and table models, OCR options | — |
| 2 | Test set with varied layouts (the current corpus is one template) | Evaluation design, avoiding a biased test set | — |
| 3 | Chunker: Docling `HybridChunker`, token limit matched to the embedding model | Token-aware chunking, chunk context | — |
| 4 | Chunker: our own structure-aware chunker over Docling output, with a fallback when extraction is weak | Chunking by labels, not regex | — |
| 5 | Ingestion into Postgres with Docling; remove regex code (`chunking.py` structure part, `doc_info.py`) | Pipeline design, idempotency | — |
| 6 | Retrieval evaluation: chunkers (HybridChunker, ours, recursive baseline) × dense / keyword / hybrid | Choosing by measurement | — |
| 7 | Retrieval improvements: keyword search fix, reranker, metadata filters | Why hybrid underperformed; reranking | — |
| 8 | Generation: grounded answers, page citations, guardrails, answer-quality checks | Faithfulness, citations | — |
| 9 | API and UI on the new pipeline | — | — |

**Decisions.** Chunks carry a light context prefix taken from Docling (title, section); field extraction waits.
`evals/results.json` is kept as the regex baseline.

**Out of scope for Goal 1.** Structured fields in SQL (unless steps above overlap), query routing,
PO/invoice mismatch detection, hardening (Docker, CI eval gate).

**Open.** Test documents for step 2: the mentor's scenarios are not shared yet.
