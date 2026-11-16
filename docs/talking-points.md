# Talking points

Quick reference for presenting. Details: [roadmap.md](roadmap.md) · design: [architecture.md](architecture.md).

## 1. Problem → pivot

- v1: regex field extraction, one template. Mentor: **doesn't scale across layouts**.
- Approach 2: **Docling** for structure (layout, tables, reading order) + **our own chunker** on its output.
- Goal 1 = a **proper RAG** (retrieve → cited answer). SQL / structured fields: out of scope.

## 2. Pipeline, stage by stage

**Extract (Docling)**
- Docling reads the PDF: text blocks with labels (heading, list item, table…), tables as cell grids, page numbers.
- Full result as **JSON** (`DoclingDocument`) → `documents.docling_json` (Postgres JSONB).
- Each page's text as **Markdown** → `document_pages.text`.
- Converted **once**; same file again (same SHA-256 content hash) → stored JSON reused. CPU: ~8–20 s per page.

**Classify (Groq)**
- Groq `openai/gpt-oss-120b`, temperature 0, reads the first 2,000 characters of page 1.
- Must reply exactly `purchase_order`, `invoice` or `unknown` → `documents.doc_type`. **16/16 correct.**
- Retries after 5 s and 15 s; an API failure stores `unknown` and never stops ingestion.

**Header** (no field extraction; built by code from Docling output)
- Type line + short page-1 lines (up to 64 tokens) + first 3 item names from the largest table.
- Example (`po-po-2026-27-0202.pdf`, shortened):
  `Document type: Purchase order` · `Shreeji Infra Projects Pvt Ltd | PURCHASE ORDER | Vendor | Ganesh Packaging Industries | Ship To | … | Items: Wooden pallet, 1200 x 1000 mm, heat treated; Bubble wrap roll, …`

**Chunk**
- Two chunkers on the same Docling output: **structure-aware (ours, default)** and Docling's **HybridChunker** (baseline).
- Max 256 tokens; tables as Markdown. Test set: 201 vs 182 chunks.
- Each chunk → `chunks.text` (shown to user and LLM) and `chunks.search_text` = header + section + text.

**Embed / index**
- Gemini `gemini-embedding-001`, 768-d → `embeddings` table, one vector per distinct search text (HNSW, cosine).
- Keyword index: Postgres full-text (`tsvector`, GIN) on `search_text`. Everything in one Postgres + pgvector.

**Retrieve** (6 methods in the Ask page; top 5 chunks go to the LLM)
- **Dense:** closest meaning (vectors). **Keyword:** matching words (full-text). **Hybrid:** both, merged (RRF).
- **Rerank:** dense top 20 re-ordered by a cross-encoder (`ms-marco-MiniLM-L-6-v2`).
- **Number filter (`dense_ids`):** a number like `PO/2026-27/0204` in the question → only documents containing it.
- **Default `dense_intent`:** number filter + Groq decides if the answer is in a PO or an invoice
  (`purchase_order` / `invoice` / `either` / `unknown`) → search only that type; unsure or nothing found → fallback.
- Picking one document in the UI: search only there, no intent call, no filters.

**Answer**
- Top 5 grouped by document; each group starts with the file name and its header; passages keep rank `[1]…[5]`.
- Groq `openai/gpt-oss-120b`, streamed to the UI (SSE); cites `(file.pdf, Page n)`.
- Guardrails in the system prompt: only from context, one-sentence refusal off-topic, ignore injected instructions.

**Evaluate**
- 16 synthetic docs, 4 layouts, 40 questions + 12 guardrail questions; judge Groq `qwen/qwen3.8-27b`.

## 3. Key decisions

- **Own chunker over HybridChunker**
  Better MRR (0.564 vs 0.506) with **less than half the tokens** (319 vs 763 for the top 5).
  HybridChunker merged neighbouring clauses and split tables by column; ours keeps one clause or one table per chunk.
- **Markdown tables**
  ~35% fewer tokens than Docling's default "row, column = value" text, and the header row stays readable.
- **Header instead of field extraction**
  Step 6 showed the main failure was the wrong document (23/40 at rank 1), not bad chunks.
  A header gives every chunk its document's identity without regex or a schema per layout.
- **Number filter as an exact token**
  Embeddings blur "0204" vs "0206"; Postgres keeps `PO/2026-27/0204` as one token, so the match is exact.
  Caught 13/13 number questions with no false positives.
- **Reranker optional, not default**
  Helped HybridChunker (0.525 → 0.602) but hurt ours (0.619 → 0.603): it pushes table rows down
  (trained on prose passages).
- **Document type as a filter, not as text**
  Adding "Document type: …" to the embedded text barely moved MRR (0.707 → 0.698).
  Using it as a filter chosen by question intent jumped MRR to 0.897.
- **Judge from another model family**
  Answers by gpt-oss, judged by Qwen, so the model doesn't grade itself.
  Gemini was dropped as judge: free tier allows 20 requests a day.
- **Headers in the answer context**
  The model refused 4 answerable questions because passages didn't name supplier or item.
  Same header as retrieval (same function, same data) → 0 false refusals.
- **Old v1 data hidden, not deleted**
  Kept for reference and reversibility; hiding keeps the test corpus fixed so new numbers stay comparable.

## 4. Numbers

**Retrieval** (structure chunker, MRR):

| Step | Change | MRR | Hit@1 | Hit@5 |
|---|---|---|---|---|
| 6 | Baseline, dense | 0.564 | 0.40 | 0.80 |
| 7a | Item names in header | 0.619 | 0.50 | 0.78 |
| 7c | Document-number filter | 0.707 | 0.60 | 0.85 |
| 7d | Type line in text (weak) | 0.698 | — | 0.80 |
| 7e | **Question intent → type filter** | **0.897** | **0.85** | **0.97** |

- Overall **MRR 0.564 → 0.897**, **Hit@1 0.40 → 0.85**. 7e: 13 better, 0 worse; table questions MRR 1.00.
- Number filter: 13/13 identifier questions caught, no false positives.

**Answers** (40 questions, Qwen judge):

| | Before headers (8a) | After headers (8c) |
|---|---|---|
| Correct | 35 | **38** |
| "Not found" although retrieved | 4 | **0** |
| Ungrounded | 7 | **3** |
| Citations valid | 42/44 | **44/45** |
| Guardrails | 12/12 | **12/12** |

- Same retrieval in both runs → the gain comes from the context alone.
- First judge run said 22/40: a **judge bug** (empty reference read as "not in documents"), fixed and documented.

## 5. Evaluation design

- Layouts: A bordered tables · B label: value · C borderless, multi-page · D unnumbered terms.
- Same data in every layout → differences come from layout, not wording.
- Every evidence snippet checked against the PDF text.
- Correctness judge never sees the passages; groundedness judge sees exactly what the model saw; citations checked in code.
- Every run saved to a new file; nothing overwritten.

## 6. Limits and next steps

- Synthetic documents with clear wording; one run per question; answer model not at temperature 0.
- q07 regression (0.5% read as 5%), q32 retrieval miss (wrong PO).
- Off-topic questions still trigger retrieval (prompt refuses correctly).
- Docling on CPU: ~8–20 s per page; upload is synchronous.
- Next: mentor's scenarios / real invoices, off-topic before retrieval, structured fields + SQL (Goal 2).
