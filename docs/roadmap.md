# Roadmap – approach 2 (Docling)

Goal 1 is a proper RAG pipeline whose extraction works across document layouts, not one template.
One step at a time; each step is reviewed before the next starts.

| # | Step | Learning focus | Status |
|---|---|---|---|
| 0 | Remove old Qdrant code; this roadmap | — | Done |
| 1 | Docling extraction: run on sample PDFs, read the `DoclingDocument` (labels, tables, pages, reading order), store its JSON per document | Layout and table models, OCR options | Done (JSON in files; DB in step 5) |
| 2 | Test set with varied layouts (the current corpus is one template) | Evaluation design, avoiding a biased test set | Done (`evals/data_v2/`) |
| 3 | Chunker: Docling `HybridChunker`, token limit matched to the embedding model | Token-aware chunking, chunk context | — |
| 4 | Chunker: our own structure-aware chunker over Docling output, with a fallback when extraction is weak | Chunking by labels, not regex | — |
| 5 | Ingestion into Postgres with Docling; remove regex code (`chunking.py` structure part, `doc_info.py`) | Pipeline design, idempotency | — |
| 6 | Retrieval evaluation: chunkers (HybridChunker, ours, recursive baseline) × dense / keyword / hybrid | Choosing by measurement | — |
| 7 | Retrieval improvements: keyword search fix, reranker, metadata filters | Why hybrid underperformed; reranking | — |
| 8 | Generation: grounded answers, page citations, guardrails, answer-quality checks | Faithfulness, citations | — |
| 9 | API and UI on the new pipeline | — | — |

**Decisions.** Chunks carry a light context prefix taken from Docling (title, section); field extraction waits.
`evals/results.json` is kept as the regex baseline.

## Step 1 findings (one PO, one invoice)

- **Settings:** Docling defaults (accurate tables), OCR off; `--ocr` for scanned PDFs.
- **Good:** line-item and key-value tables come out as clean grids; terms come out as `list_item` under their heading.
- **Weak:** company names are labelled `section_header`; "PURCHASE ORDER" is not a `title`; "TAX INVOICE" merged into address text.
- **Spanning cells** repeat in every column (e.g. "CGST @ 9%" six times). Read cells from the JSON (start/end column), not the Markdown.
- **Heading hierarchy option:** levels don't follow meaning (Vendor 3, vendor name 5, Terms 4). Off.
- **Fast table mode:** splits totals rows ("Sub" / "Total"), no speed gain. Off.
- **Speed (CPU):** about 16s model load once, then about 8–20s per page. The API must load models once.

## Step 2: test set v2 (`evals/corpus_v2.py`)

- 8 new linked PO + invoice pairs, 2 per layout: 16 documents, 20 pages, 40 questions (about 10 per layout).
- **A** bordered tables, numbered clauses · **B** "Label: value" fields, side-by-side parties, different wording ·
  **C** borderless line items breaking across pages, running header and footer · **D** terms as unnumbered paragraphs.
- Same data model, clause texts and question pools as v1, so differences come from layout, not wording.
- Every evidence snippet is checked against the PDF text; each question records its `layout`.
- `evaluate.py` reads v2 and reports per layout in step 6. The v1 set stays as the regex baseline.

**Docling on one PO per layout** (input for step 4):

- **A:** as in step 1; "Vendor" and the vendor name merged into one heading.
- **B:** "Label: value" lines come out cleanly; side-by-side parties scramble reading order (address lines out of order, title after the supplier, "Deliver To" not a heading).
- **C:** running header and footer correctly moved to `page_header` / `page_footer`. The borderless table splits at the page break: its column headings come out as text, page 2 has different columns ("2 Nos"), "Grand Total" falls out as text. The borderless header grid becomes loose text.
- **D:** all 9 terms merge into one text block; only the first bold heading is detected. No text lost, but no term boundaries.
- **Chunker needs (step 4):** split oversized text blocks; join tables continued across pages; attach a header line found just before a table.
- Invoices not checked yet.

**Out of scope for Goal 1.** Structured fields in SQL (unless steps above overlap), query routing,
PO/invoice mismatch detection, hardening (Docker, CI eval gate).

**Open.** The mentor's scenarios (not shared yet) may replace or extend test set v2. Real public invoices: later.
