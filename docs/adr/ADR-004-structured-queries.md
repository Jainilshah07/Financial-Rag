# ADR-004: Structured questions via a validated query plan

**Status:** Proposed · 2026-10-22

**Context.** All arithmetic must come from the database, yet the model must understand questions like "POs from Q2 above ₹5 lakh for vendor X".

| Option | For | Against |
|---|---|---|
| Free-form text-to-SQL | Flexible | Hallucinated columns, injection risk, hard to audit |
| Fixed templates | Safe | Too rigid |
| **LLM → typed QueryPlan → code builds SQL** | Model only fills a validated structure; parameterised SQL; rows keep their sources | Vocabulary grows with the question set |

**Decision.**
1. The router returns a QueryPlan: route, doc type, vendor, date range, amount condition, currency, aggregate, group-by, sort, limit.
2. Code compiles it to parameterised SQL; the model never writes SQL.
3. A verifier checks every number in the answer exists in the result; otherwise the plain table is returned.
4. Flagged fields are excluded from aggregates and reported.

**Revisit if** coverage of the question set is too low; then allow-listed, read-only SQL.
