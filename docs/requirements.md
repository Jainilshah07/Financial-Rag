# Requirements

Source: problem statement "Structured and unstructured routing over financial documents". Resolutions of its gaps are in [ambiguities.md](ambiguities.md).

## Scenario

Finance asks numeric questions (*"Which POs from Q2 exceeded ₹5 lakh for vendor X?"*) and semantic ones (*"What delivery terms did we agree with them?"*). Embeddings can't tell ₹5,00,000 from ₹4,99,000, so numbers need SQL over extracted fields; meaning needs retrieval; some questions need both.

**Corpus:** 500+ invoices and purchase orders, at least 50 scanned.

## Functional requirements

| ID | Requirement |
|---|---|
| FR-1 | Extract header fields, line items and totals into a relational store |
| FR-2 | Route each question: `structured`, `semantic`, `hybrid` (+ `out_of_scope`, A-12) |
| FR-3 | All arithmetic computed by the database; the LLM never produces a number |
| FR-4 | OCR for scanned documents, with a confidence score per field |
| FR-5 | Fields below a documented threshold are flagged, never guessed |
| FR-6 | Hybrid: filter numerically first, then answer semantically over the filtered documents |
| FR-7 | Detect and report PO/invoice mismatches |
| FR-8 | Every answer cites document and page |
| FR-9 | Upload, list, inspect and delete documents |

## Acceptance criteria

- Router accuracy measured on a 40-question test set.
- Arithmetic computed from the structured store, verifiable against source documents.
- OCR confidence present; low-confidence fields flagged.
- 5+ hybrid questions answered correctly.
- PO/invoice mismatches detected and reported.

## Deliverables (Part D)

| # | Artifact | Due |
|---|---|---|
| 1 | Ingestion pipeline: re-runnable, incremental | Week 2 → 9 |
| 2 | `/ask`: cited answers, containerised, structured logging | Week 3 |
| 3 | Golden set: 40 questions (30 standard, 10 adversarial) | Week 4 |
| 4 | CI eval: runs on every commit, fails on regression | Week 4 |
| 5 | Ablation table | Week 8 |
| 6 | Budget report: p95 latency and ₹/query | Declared week 4, measured week 9 |
| 7 | 2-page writeup: ambiguities, what broke, what the numbers say, next month | Week 9 |

## Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-1 | Idempotent, versioned ingestion; every reported number reproducible |
| NFR-2 | Structured logs: request id, stage timings, tokens, cost |
| NFR-3 | Question and document text treated as untrusted; no model-written SQL |
| NFR-4 | Models, thresholds and budgets in config |
| NFR-5 | API, worker and database start with Docker Compose |

## Budgets (provisional)

| Route | p95 latency | p95 time to first result |
|---|---|---|
| Structured | ≤ 5 s | ≤ 3 s |
| Semantic | ≤ 8 s | ≤ 3 s |
| Hybrid | ≤ 10 s | ≤ 4 s |

Cost: ≤ ₹0.50 per query on average.

**Out of scope:** auth, FX conversion, non-English documents.
