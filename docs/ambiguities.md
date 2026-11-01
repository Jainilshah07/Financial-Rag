# Ambiguities

Each gap in the problem statement, our resolution, and what would change it. Feeds the final writeup.

## Corpus and data

| ID | Ambiguity | Resolution | Status | Would change if |
|---|---|---|---|---|
| A-01 | No corpus supplied | Generate documents from the mentor's scenarios, with known field values ([ADR-002](adr/ADR-002-corpus.md)) | Decided | A real corpus is provided |
| A-02 | "Scanned": image files or image-only PDFs? | Accept PDF, PNG, JPG; choose the text source per page (text layer, form fields, OCR) | Proposed | — |
| A-03 | One file = one document? | Yes; reject multi-document files | Proposed | Bundled files appear |
| A-04 | Template placeholders (`<Company Name>`) | Treat as missing and flag | Proposed | — |

## Money, dates, identity

| ID | Ambiguity | Resolution | Status | Would change if |
|---|---|---|---|---|
| A-05 | Currency | ₹ primary; currency stored per document and per line; never mix currencies in a total; no FX | Decided | — |
| A-06 | "Q2": calendar or fiscal? | Indian FY (Apr–Mar): Q2 = Jul–Sep; answers state the range | Decided | — |
| A-07 | "Exceeded ₹5 lakh": which amount? | Grand total incl. tax by default; answer states the basis | Proposed | Question wording |
| A-08 | Vendor name variants | Vendor table with aliases; match on GSTIN, else normalised name | Proposed | — |
| A-09 | Date formats, day/month order | Day-first by default; ambiguous dates flagged | Proposed | — |

## Confidence

| ID | Ambiguity | Resolution | Status | Would change if |
|---|---|---|---|---|
| A-10 | Threshold value and scope | Per field type; tuned so trusted fields are ≥ 98 % accurate; start at 0.85 | Proposed | Calibration curve |
| A-11 | Flagged fields in aggregates | Excluded; answer reports how many and which | Proposed | Owner prefers include-with-warning |

## Routing and answering

| ID | Ambiguity | Resolution | Status | Would change if |
|---|---|---|---|---|
| A-12 | Greetings, off-topic, injection | 4th route `out_of_scope`; answer prompt keeps its own guard | Proposed | — |
| A-13 | Router set vs golden set | Separate artifacts, may overlap | Proposed | — |
| A-14 | May the LLM phrase numeric answers? | Yes, but every number must exist in the SQL result (verifier) | Proposed | — |
| A-15 | Hybrid filter matches 0 or hundreds of docs | 0 → say so; many → answer over the top documents and state the cut-off | Proposed | Golden-set results |
| A-16 | Identical boilerplate clauses across documents | Chunks carry document identity (number, vendor, section) | Proposed | Retrieval eval |

## Mismatches and operations

| ID | Ambiguity | Resolution | Status | Would change if |
|---|---|---|---|---|
| A-17 | What is a mismatch? | Link by PO number; types: unmatched invoice, vendor, qty/price, total (tolerance ₹1 or 0.5 %), tax, duplicate, over-billing, invoice before PO | Proposed | Domain feedback |
| A-18 | No latency/cost budget given | Provisional targets in [requirements.md](requirements.md) | Proposed | Measurements |
| A-19 | Re-uploading the same file | Content hash → no duplicate document | Proposed | — |
| A-20 | Language | English; Indian number formats (lakh, crore, Rs., INR, ₹) | Decided | Non-English documents |
