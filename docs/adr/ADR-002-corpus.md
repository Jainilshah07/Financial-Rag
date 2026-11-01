# ADR-002: Generated corpus from the mentor's scenarios

**Status:** Accepted · 2026-10-22, updated 2026-11-01

**Context.** No corpus is supplied. Evaluation needs the correct value of every field, and mismatch detection needs linked POs and invoices. Public datasets have no linked pairs. The real freight samples shared earlier are not used.

**Decision.**
1. Generate POs and invoices from the mentor's scenarios, with a ground-truth JSON per document.
2. Several layouts per document type, so extraction can't overfit one.
3. Scanned set: render generated PDFs to images and degrade them (rotation, blur, noise).
4. Start small; scale to 500+ for final evaluation.

Until the scenarios arrive, `evals/corpus.py` provides an interim set (8 linked POs and invoices, 56 questions).

**Revisit if** a real corpus becomes available.
