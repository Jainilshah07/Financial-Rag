# ADR-005: Scanned documents via per-page triage and local OCR

**Status:** Proposed · 2026-10-22

**Context.** 50+ documents are scanned; every extracted field needs a confidence score and flagging below a threshold.

| Approach | Per-field confidence | Verdict |
|---|---|---|
| **Local OCR** (Tesseract, PaddleOCR, RapidOCR) | Word confidence, rolled up to fields | Primary |
| Cloud document AI (Azure, Textract) | Built in | One comparison run |
| Vision LLM | Not calibrated | Second opinion only |
| Page-image embeddings (ColPali) | No text | Can't feed SQL |

**Decision.**
1. Per page: text layer, else form fields, else OCR.
2. Same LLM extraction for all sources; each value mapped back to its OCR words.
3. Field confidence = minimum word confidence, adjusted by validation checks (Σ lines = subtotal, totals, date and GSTIN formats).
4. Threshold per field type, calibrated on generated scans with known values.
5. Engine chosen by a bake-off on the degraded set.

**Revisit if** no local engine is accurate enough; then a cloud service with its own confidences.
