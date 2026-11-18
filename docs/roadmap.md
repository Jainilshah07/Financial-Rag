# Roadmap – approach 2 (Docling)

Goal 1 is a proper RAG pipeline whose extraction works across document layouts, not one template.
One step at a time; each step is reviewed before the next starts.

| # | Step | Learning focus | Status |
|---|---|---|---|
| 0 | Remove old Qdrant code; this roadmap | — | Done |
| 1 | Docling extraction: run on sample PDFs, read the `DoclingDocument` (labels, tables, pages, reading order), store its JSON per document | Layout and table models, OCR options | Done (JSON in files; DB in step 5) |
| 2 | Test set with varied layouts (the current corpus is one template) | Evaluation design, avoiding a biased test set | Done (`evals/data_v2/`) |
| 3 | Chunker: Docling `HybridChunker`, token limit matched to the embedding model | Token-aware chunking, chunk context | Done (`chunkers.py`) |
| 4 | Chunker: our own structure-aware chunker over Docling output, with a fallback when extraction is weak | Chunking by labels, not regex | Done (`structure_aware_chunker.py`) |
| 5 | Ingestion into Postgres with Docling; remove regex code (`chunking.py`, `doc_info.py`) | Pipeline design, idempotency | Done (run 4) |
| 6 | Retrieval evaluation on test set v2: chunkers (HybridChunker as baseline, ours) × dense / keyword / hybrid | Choosing by measurement | Done (`results_v2.json`) |
| 7 | Retrieval improvements: keyword search fix, reranker, metadata filters | Why hybrid underperformed; reranking | Done (7a–7e) |
| 8 | Generation: grounded answers, page citations, guardrails, answer-quality checks | Faithfulness, citations | Done (8a–8c) |
| 9 | API and UI on the new pipeline | Transparency of retrieval decisions | Done (9a, 9b) |
| 10 | Real users' questions; toward hybrid RAG + structured SQL | Realistic evaluation, where RAG stops | 10a, 10b done; 10c design awaiting schema review |

**Decisions.** No field extraction: each document gets a header (LLM type, page-1 lines, item names) used for
search and, since 8c, in the answer context. Default: our structure-aware chunker + `dense_intent` (number filter +
LLM question intent → document-type filter). `evals/results.json` is kept as the regex baseline. No recursive
baseline: HybridChunker (Docling's default) is the one to beat. Current design: [architecture.md](architecture.md).

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

## Step 3: HybridChunker (`chunkers.py`)

- **Settings:** 256 tokens; MiniLM tokenizer as a local approximation of Gemini's; tables as Markdown.
- **Texts:** `text` = chunk text (for the LLM), `search_text` = headings + text (embedded).
- **Markdown vs default "row, column = value" tables** (layout A and D POs):
  - Markdown: about 35% fewer table tokens (333 vs 510), header row kept, key-value grid readable.
  - Default: "PO No., 2 = PO Date"; spanning cells repeated as sentences; split mid-cell.
- **Known limits (for step 4 / step 6):**
  - A table over the limit is split by column: the Amount column lands alone, without item names.
  - Spanning cells repeat ("Sub Total | Sub Total | …").
  - Wrong headings become context (site name above the line items).
  - Neighbouring items are merged up to the limit: layout A terms grouped 6 + 3, not one per clause.
  - Layout D: all terms filed under "Payment Terms".
  - Step 6: also test 512 tokens (the table would fit in one chunk).

## Step 4: structure-aware chunker (`structure_aware_chunker.py`)

- **Document header** (`doc_header`, both chunkers): short page-1 lines in reading order, up to 64 tokens,
  skipping long texts and line-item tables. Gives document number, date and vendor in all four layouts, without field extraction.
- **Rules** (on Docling labels, same 256-token limit and tokenizer as HybridChunker):
  - A heading directly after a heading is content (party name under "Ship To").
  - A table takes only the heading directly above it, and ends the section.
  - Tables: header + rows up to the limit, header repeated, never split by column; spanning cells written once.
  - No header row: a short, digit-free text line just above the table becomes the header (layout C).
  - A table continuing on the next page joins the previous one.
  - One chunk per clause; text merged up to the limit; oversized text split by sentence (keeping a lead-in like "Payment Terms").
  - Very short texts ("Authorised Signatory") attach to the previous chunk.
- **Result (POs):** line items + totals in one chunk (A, B, D); layout C table joined across pages with header in every chunk;
  one clause per chunk. Chunks: A 16, B 15, C 18, D 9 (HybridChunker: 8, 12, 14, 8).
- **Still weak:** layout D term boundaries (lost in Docling, sentence split cuts at the limit);
  layout B reading order; chunks reach about 320 tokens with the header. Rules are heuristics: step 6 decides.

## Step 5: ingestion (`ingest.py`, migration 0002)

- Docling converts each file once; its JSON is stored in `documents.docling_json`. A known file (same hash) reuses it.
- Page texts come from Docling; every chunker (`hybrid`, `structure`) replaces the file's chunks; embeddings are stored once per text.
- Run config records the Docling version, chunker settings and tokenizer. `--dry-run` converts and chunks without DB or API.
- `chunking.py` and `doc_info.py` removed; `doc_type` / `doc_number` stay empty until field extraction.
- **Run 4 (test set v2):** 16 documents, 20 pages. hybrid 182 chunks, structure 201; 49 texts identical in both, so embedded once.
- Old v1 rows are kept; search always filters by chunker, so they don't affect the new chunkers.

## Step 6: retrieval evaluation (`evals/evaluate.py` → `evals/results_v2.json`)

- `evaluate.py`: `--data` / `--chunkers` / `--out`; tokens counted with our tokenizer; breakdown by type and layout.
  Refuses to overwrite `results.json` (regex baseline).

| Chunker | Method | Hit@1 | Hit@5 | MRR | Tokens@5 |
|---|---|---|---|---|---|
| hybrid | dense | 0.35 | 0.72 | 0.506 | 763 |
| hybrid | keyword | 0.45 | 0.57 | 0.509 | 666 |
| hybrid | hybrid | 0.35 | 0.62 | 0.480 | 728 |
| structure | dense | 0.40 | 0.80 | 0.564 | 319 |
| structure | keyword | 0.35 | 0.55 | 0.457 | 343 |
| structure | hybrid | 0.35 | 0.72 | 0.530 | 321 |

- **Chunkers:** structure + dense is best (MRR 0.564 vs 0.506, Hit@5 0.80 vs 0.72) with less than half the tokens.
  By layout (dense MRR A/B/C/D): structure 0.85/0.64/0.48/0.29, hybrid 0.53/0.60/0.53/0.36. 10 questions per layout: indicative only.
- **Measurement is sound:** evidence is reachable for 40/40 (structure) and 39/40 (hybrid: one row split from its price).
- **Main failure is document identity, not chunking.** Structure + dense: 23 of 40 top-1 results come from the wrong document:
  - 10 PO ↔ its own invoice (same items and rates; about 5 are arguably correct answers under a strict metric),
  - 8 same vendor, other PO (clause chunks don't name the items; the header has number, date, vendor only),
  - 5 neighbouring document numbers (dense embeddings blur "0204" vs "0206"; keyword search too weak to rescue).
- **Next (step 7):** item names in the document header; keyword search for document numbers; reranker;
  a lenient metric (linked PO + invoice) next to the strict one. 512 tokens: low priority.

## Step 7: retrieval improvements

**7a. Item names in the document header** (`item_names()`, run 5 → `evals/results_v2_items.json`)

- Header ends with "Items: …": first 3 descriptions from the largest table's longest-text column (no field extraction).
  Correct for all 16 documents, including layout C. Header now about 90–117 tokens.
- `evaluate.py`: lenient **MRR linked** (a PO and its invoice both count) next to the strict MRR.
- **structure + dense:** MRR 0.564 → 0.619, MRR linked 0.644 → 0.697, Hit@1 0.40 → 0.50, Hit@5 0.80 → 0.78,
  paraphrase MRR 0.47 → 0.63. hybrid + dense: 0.506 → 0.525.
- **Misses at rank 1:** same vendor, other PO 8 → 4; PO ↔ own invoice 10 → 11; neighbouring numbers 5 → 5.
- **Side effects:** rate (table) questions dropped (e.g. rank 2 → 6): every chunk now names the items, so the
  line-items chunk stands out less. Keyword search worse (0.457 → 0.403): item words in every chunk, no IDF.
- Kept: net gain. Next: reranker (table questions, PO vs invoice) or keyword search on chunk text for numbers.

**7b. Reranker** (`rerank` method, run 5 → `evals/results_v2_rerank.json`)

- Dense top 20 → `cross-encoder/ms-marco-MiniLM-L-6-v2` scores (question, `search_text`) → top 10.
- **structure:** dense MRR 0.619 → rerank 0.603, Hit@1 0.50 → 0.47, Hit@5 0.78 → 0.82; 10 questions better, 11 worse.
  Layout C 0.56 → 0.41, D 0.45 → 0.63.
- **hybrid:** dense 0.525 → rerank 0.602, Hit@1 0.42 → 0.50; 12 better, 8 worse.
- Correct chunk in the dense top 20: 37/40 (structure), 35/40 (hybrid), so candidates are not the limit.
- **Misses at rank 1 (structure):** PO ↔ invoice 11 → 8, same vendor 4 → 1, numbers 5 → 5, but right document /
  wrong chunk 0 → 7. Picks the right document more often, the right chunk less often: table rows lost
  (two rate questions dropped out of the top 10). Likely cause: MS MARCO is trained on prose passages, not table rows.
- **Decision:** dense stays the default for the structure chunker; `rerank` kept as an optional method.
  A stronger reranker (`bge-reranker-base`) is untested.

**7c. Document-number filter** (`dense_ids` method, run 5 → `evals/results_v2_numbers.json`)

- If the question has an identifier (letters, 3+ digits, a `/` or `-`; e.g. PO/2026-27/0204, BST-1209),
  dense search runs only within documents whose chunks contain it as an exact Postgres token
  (Postgres keeps such numbers as one token). No match → normal dense search. No field extraction.
- Caught all 13 identifier questions, no false positives ("A4"). Kept the right documents for all 13:
  invoice number → that invoice; PO number → the PO and its invoice.
- **structure:** dense → dense_ids MRR 0.619 → 0.707, Hit@1 0.50 → 0.60, Hit@5 0.78 → 0.85,
  identifier MRR 0.59 → 0.86. Layouts A/B/C/D 0.74/0.83/0.63/0.62. 7 questions better, none worse.
- **hybrid:** dense 0.525 → dense_ids 0.642.
- **Misses at rank 1 (structure):** numbers 5 → 0; PO ↔ invoice 11 (unchanged, now the main problem);
  same vendor 2; right document / wrong chunk 3 (e.g. "which PO is this invoice against?": every chunk
  carries the number in its header, so the header-grid chunk doesn't stand out).
- Measured alone; not combined with rerank yet.

**7d. LLM document type** (`classify.py`, runs 6–7 → `evals/results_v2_doctype.json`)

- At ingestion Groq (`gpt-oss-120b`, temperature 0) classifies page 1 (first 2,000 characters of Docling Markdown)
  as `purchase_order` / `invoice` / `unknown`; stored in `documents.doc_type`. Prompt: terms don't decide the type;
  an invoice citing a PO is still an invoice; document text is data, not instructions.
- Only an exact allowed value is stored, else `unknown`. API failures (retries after 5 s, 15 s), invalid replies
  and `unknown` answers are counted separately in run stats, with the last error text. Never fails ingestion.
- Runs when the type is missing or `unknown`, or with `--reclassify`. Chunks are always rebuilt; embeddings no
  chunk uses are deleted after each run (668 stale vectors removed).
- `search_text` starts with "Document type: Purchase order" / "Invoice" (no line for `unknown`).
- Run 6: 3 API failures (likely rate limit) → `unknown`; run 7: **16/16 types correct**, 0 failures, 0 invalid.
- **structure + dense_ids:** MRR 0.707 → 0.698, MRR linked 0.785 → 0.805, Hit@5 0.85 → 0.80,
  identifier 0.86 → 0.91, table 0.64 → 0.57; 5 better, 8 worse. hybrid + dense_ids 0.642 → 0.583.
- PO ↔ invoice misses 11 → 12, all still "wanted PO, got invoice". The type line is a weak embedding signal:
  correct as data, ineffective as text. Kept as stored metadata for filtering (7e).

**7e. Intent-aware retrieval** (`dense_intent` method, run 7 → `evals/results_v2_intent.json`)

- Per question, Groq classifies which document type holds the answer: `purchase_order` / `invoice` / `either` /
  `unknown` (same validation and retries as 7d; cached per question). The prompt is generic: decide by where the
  answer is written, not by words; it lists no test topics.
- Clear `purchase_order` / `invoice` → dense_ids within documents of that type (number filter and type filter
  intersect). `either`, `unknown`, API failure, or no results → plain dense_ids.
- Intent: 39/40 correct, 1 `unknown` (q32 → fallback), never `either`, 0 failures.
- **structure:** dense_ids → dense_intent MRR 0.698 → **0.897**, Hit@1 0.60 → 0.85, Hit@5 0.80 → 0.97,
  table MRR 0.57 → 1.00; layouts A/B/C/D 0.92/1.00/0.87/0.80. 13 better, 0 worse.
  MRR linked = MRR: no PO ↔ invoice confusion left.
- **hybrid:** 0.583 → 0.760; 13 better, 0 worse.
- **The 12 PO ↔ invoice errors (structure):** 10 now at rank 1; q03 not found → 5, q33 not found → 2.
- **Still not rank 1 (structure):** q03, q24, q28, q32 (fallback), q33, q38: same-document or same-vendor misses.
- **Caveats:** our questions use clear "order" / "bill" wording, so expect lower intent accuracy on real phrasing.
  A confident wrong intent filters out the right document (no fallback). One extra LLM call per question (~0.5–1 s).

## Step 8: generation evaluation (`evals/evaluate_answers.py`)

**8a. Answers** (40 questions → `evals/answers_v2_8a_qwen_fixed.jsonl` + `_summary.json`)

- Pipeline as `/ask`, unchanged: structure + dense_intent, top 5, `rag.stream_answer`. Answers generated once, reused.
- Judge `qwen/qwen3.8-27b` (Groq; a different family from the answer model), temperature 0, strict JSON schema,
  `max_tokens` 200 (limit: 1,000 output tokens/min, counted as requested). Correctness sees question + evidence
  + table context, never passages; groundedness sees passages + answer. Citations are checked in code.
- Gemini (`gemini-3.5-flash`) was dropped: free tier allows 20 requests/day. Its 13 judgments stay in
  `answers_v2_8a.jsonl`. A daily-quota 429 now stops the run; per-minute 429s are retried.
- The first Qwen run (`answers_v2_8a_qwen.jsonl`, kept) read the empty `reference_answer` "(none)" as "not in the
  documents", and table evidence lacked qty/unit. Fixed: no empty reference block; judge-only `judge_context`
  (verbatim table row) for the 10 table questions; Unicode hyphens normalised in citations.
- **Result:** correct 35/40 (first run 22), not_found 4, wrong 1; layouts A/B/C/D 7/9/10/9 of 10.
  Citations 42/44 valid, 2 incorrect, 0 answers without one. Groundedness 30 grounded, 3 no claims, 7 ungrounded.
- **Failures:** q03, q05, q08, q20 say "not found" although the answer is in the retrieved passages; q32 answers
  from the wrong PO (retrieval miss). Most "ungrounded" answers only repeat the supplier or item from the question:
  passages carry no document identity.
- **Caveats:** q28 judged correct but hedges between 0.5% and 1% (should be partial; judge lenient). q17/q38
  evidence is cut at 60 characters, so list completeness isn't checked. Single judge, single run.

**8b. Guardrails** (`evals/data_v2/guardrails.jsonl`, 12 questions → `evals/guardrails_v2_8b_qwen.jsonl`)

- Kinds: unanswerable 4, off-topic 3, injection 3, mixed (document question + off-topic or injection) 2. Each has
  an expected behaviour (Qwen judge) and code checks: no prompt leak, one sentence for off-topic/injection,
  required facts for mixed (g11 "30 days", g12 account 921020044718391, both verified in the PDFs).
- **Result: 12/12 pass** (judge and checks agree). No invented values for unanswerable questions; one-sentence
  refusals; mixed questions answered with a citation, then one refusal sentence.
- **Caveats:** direct attacks only; no injection inside a document (the more relevant RAG risk). Small set, one run.
- **Trade-off with 8a:** the same caution that passes every guardrail causes the 4 false "not found" answers.

**8c-1. Document identity in the answer context** (`rag.build_context`, `search.document_headers` →
`evals/answers_v2_8c.jsonl`, `evals/guardrails_v2_8c.jsonl`)

- Passages are grouped by document; each group starts with `Document: <file>` and the document header, rebuilt
  with `doc_header()` from the stored Docling JSON and type (same function and inputs as ingestion; checked
  against all 383 stored `search_text`s, and asserted per hit in the eval). Cached per document, type and content.
- Groups follow their best-ranked passage; passages keep retrieval order, all 5 kept (no de-duplication), each
  labelled `[rank] file, Page n:`. Verified on all 40 retrievals and synthetic duplicates. Prompt unchanged.
- The groundedness judge now sees the exact context the model saw (saved per row).
- Retrieval identical to 8a for all 40 questions, so changes come from the context only.
- **Result:** correct 35 → **38/40**, not found 4 → **0**, ungrounded 7 → **3**, citations 42/44 → **44/45** valid.
  Guardrails still **12/12**. q03, q05, q08, q20 now answered with valid citations; q28 no longer mixes two POs.
- **q07 regression:** answers "5% per week" (passage says 0.5%) and computes a hold-back from the header's
  "Amount in words". Retrieval was the same; the header (page-1 lines beyond identity) or sampling may cause it.
- **q32:** still wrong ("4 hours"; the answer is "1 hour"). Retrieval miss: the right PO isn't retrieved.
- **Limitations:** answer model at default temperature, one run per question, so single-question changes may be
  noise. Single judge (Qwen); q12/q33 marked ungrounded for inferring who pays freight from "F.O.R. destination"
  (judge strict). Evidence for q17/q38 is cut at 60 characters. Synthetic documents with clear wording.
- **Open:** temperature 0 for the answer model; header limited to identity (type, parties, items).

## Step 9: API and UI on the new pipeline

**9a. API** (`main.py`, `search.dense_intent_traced`)

- v1 documents (no Docling JSON) stay in the database but are hidden: not listed, opened, deleted or searched
  by id (404). Only the current chunkers (`structure`, `hybrid`) are offered or accepted (else 400).
- `doc_number` is no longer returned (column kept for later structured extraction). `/upload` returns `doc_type`.
- `/ask` with `dense_intent` sends a `trace`: question intent, filters actually applied (type, number) and the
  fallback reason. Same searches as `dense_intent` (checked on 52 questions, every path, without API calls).

**9b. UI**

- Documents: no number column; document detail opens `structure` first; `text` chunks get a colour.
- Upload: progress message covers Docling, classification, chunking, embedding; result shows the detected type.
- Ask: each control is labelled (chunker, retrieval method, document, question) with a one-line explanation of
  the choice; dropdown options explain themselves. Document picker shows file name and type. Cited chunks are matched by file and page (was page only,
  which marked page 1 of every document); same parsing as the eval (checked on 52 answers).
- Pipeline panel shows intent, applied filters and any fallback; a filter is shown only if it was applied.
  The chunk drawer shows the document header sent to the model.

## Step 10: real users' questions, toward hybrid RAG + structured SQL

Mentor feedback: "Think how real world users would ask questions." The app becomes a hybrid of RAG and structured
SQL; the benchmark measures that progress and is not a score to maximise.

| Sub-step | Scope | Status |
|---|---|---|
| 10a | Realistic question set and baseline | Done |
| 10b | Bounded RAG improvements: answer header, reference date, ADR-003, assumptions, completeness | Done |
| 10c | Structured extraction: document fields, line items, provenance, validation, PO/invoice linking | Design proposed, awaiting schema review |
| 10d | Router and query plan compiled to SQL (ADR-004) | Not started |
| 10e | Answers from SQL rows, number verifier, combined route | Not started |

**10a. Realistic question set** (`evals/questions_real.py` → `evals/data_v2/questions_real.jsonl`;
`evals/evaluate_real.py`)

- 40 questions worded as users ask (short vendor names, "bill", month names, quarters, "so far", "overdue"), six
  kinds: lookup, clause, filter, aggregate, list, compare. Gold answers computed from the generator's data; every
  evidence snippet located in the PDFs. Reference date 31-10-2026. Expected behaviour per question: answer,
  answer with a stated assumption, or clarify / answer every option.
- Evaluator: pipeline as `/ask`; the Qwen judge reports verdict, value, GST basis, listed items, missing required
  items and assumptions; code scores values, counts and sets. Evidence is split into answer and identity groups;
  one failure label per question (document_missing, field_missing, evidence_not_retrievable, ...).
- First run (`answers_v2_10a*`, kept as it was): 17/39 judged (r17 judge failure).
- Corrections (`questions_real_corrected.py` → `questions_real_corrected.jsonl`): r10 "buyer pays freight" is
  enough; r25 the PO number is enough; r22 Q2 amounts from the PO or its invoice (membership by PO date); identity
  groups; judge replies mapped to ids in code. Answers not regenerated; only r17 re-judged.
- **Measured, corrected baseline** (`answers_v2_10a_corrected*`): **18/40** passed, answer correct 19, refused 9.
  By kind: lookup 5/6, clause 5/5, filter 3/8, aggregate 1/8, list 2/7, compare 2/6. Failures: document_missing 17,
  field_missing 3, evidence_not_retrievable 1, assumption_missing 1. Assumptions stated 0/9.

**10b. Bounded RAG improvements** (`answers_v2_10b*`, `guardrails_v2_10b*`)

- Answer header (`chunkers.answer_header`, up to 192 tokens): page-1 text, small page-1 tables (PO number and date),
  item names. Used only in the answer context; the search header, embeddings, retrieval and database are unchanged.
- `REFERENCE_DATE` setting (`config.today()`; real date by default, 31-10-2026 in the evaluation).
- Prompt rules: fiscal year April–March and its quarters, with the date range stated (ADR-003); POs and invoices
  are our spend, not revenue; state the assumption when a question has more than one reading; never present a
  total, count, ranking or list over retrieved passages as complete.
- `rag.answer_chunks()` builds the context for both `/ask` and the evaluators.
- **Measured (judge):** **24/40** passed (18), refused 4 (9), assumptions stated 3/9 (0/9), counts 3/4 (2/4),
  sets exact 2/6 (1/6), amounts 5/13 (5/13). By kind: lookup 5/6, clause 5/5, filter 6/8, aggregate 2/8,
  list 3/7, compare 3/6. Failures: document_missing 15, calculation_error 1. Ungrounded 10 → 14.
  **Guardrails 12/12** (8c: 12/12).
- **Manual review** (not measured):
  - **23/40**: r28 is a judge false pass (the answer says 1 PO in Q2; the gold is 4).
  - Gains: r12, r16 (PO date now in the header), r37, r13, r21 (states it covers only the documents shown), r19
    (asks which Ganesh order, with both totals).
  - Regressions: r01 gives the GI pipe line total, not "not found" (see the gold revision below); r17 resolves
    "last month" correctly but the September PO isn't retrieved, so it says there is none.
  - 11 of the 14 aggregate and list answers (r20–r33) say they cover only the documents shown. Misses: r20
    ("none in the uploaded documents"), r29 (complete only because both invoices were retrieved), r30 (one
    invoice as the whole answer). r23 and r32 open with a wrong conclusion, then the caveat.
  - Side effects: bold markdown in 5 answers (3 before) despite "plain text only"; r19's clarification ends with
    the off-topic sentence. Part of the ungrounded rise is the checker: it sees passages only, so facts from the
    prompt rules (fiscal year, spend not revenue) count as unsupported.
- **Gold revision after 10b** (`questions_real_revised.py` → `questions_real_revised.jsonl`, now used by
  `evaluate_real.py`; 10a and 10b keep the corrected gold, recorded in their summaries, and are not rescored):
  - r01 "the Bharat Steel order for GI pipes" can mean the GI pipe line or the whole PO. Accepted: ₹3,62,000 (line,
    printed), ₹5,59,000 and ₹6,59,620 (PO, printed), ₹4,27,160 (line with 18% GST, calculated, not printed; counts
    only when the answer says it includes GST). Checked offline: under this gold, 10b's stored r01 answer would pass.
  - r23 checked against the generator data and all 8 invoice PDFs: Nimbus ₹9,06,240 vs Ganesh ₹8,95,180 including
    GST; Ganesh ₹7,90,000 vs Nimbus ₹7,68,000 before GST. Gold unchanged.
- **Remaining limits (multi-document retrieval):** 19 of 40 questions need more than 5 documents, and retrieval
  returns 5 chunks. No aggregate question had all its answer evidence in context in either run (0/8);
  document_missing is still the largest failure (15). Compare questions need a PO and its invoice together, but the
  intent filter keeps one type (r36) or one side isn't retrieved (r35, r40). Caveats make partial answers honest,
  not correct: totals, counts and rankings over all documents need structured data (10c–10e).

**10c. Structured extraction** (design proposed, awaiting schema review; not started)

- Tables: parties, financial_documents, line_items, tax_lines, field_sources (provenance), extraction_runs.
- The model points to values, code copies them from the document; validation (sub total + tax = total), PO/invoice
  linking, and the layout C defects (e.g. invoice 0768's unlabelled date).

**Out of scope for Goal 1.** Structured fields in SQL (unless steps above overlap), query routing,
PO/invoice mismatch detection, hardening (Docker, CI eval gate).

**Open.**

- The mentor's scenarios (not shared yet) may replace or extend test set v2. Real public invoices: later.
- Off-topic questions still run retrieval (top 5 always returned; the prompt refuses). Options: an `off_topic`
  intent that skips retrieval, a similarity threshold (measure the score gap first), or marking unused chunks in the UI.
- Answer model at temperature 0 for repeatable per-question comparisons; header limited to identity (q07 regression).
- q32: retrieval miss (wrong PO). A stronger reranker (`bge-reranker-base`) is untested.
