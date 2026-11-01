# ADR-003: Indian locale, currency per document and line

**Status:** Accepted · 2026-10-22

**Decision.**
- ₹ amounts, lakh/crore formatting, GSTIN, GST lines.
- Fiscal year April–March: Q2 = Jul–Sep. Answers state the date range used.
- Currency (ISO code) stored per document and per line item, with exchange rate when converted. Totals never mix currencies; no FX.
- Money is exact: `NUMERIC(18,2)` and `Decimal`, never float.
- Parse `₹`, `Rs.`, `INR`, and "5 lakh" / "1.2 crore" in questions.

**Revisit if** the corpus is mostly non-Indian or cross-currency totals are required.
