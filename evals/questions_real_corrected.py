"""Step 10a, corrected: questions_real.jsonl plus the corrections agreed after the first 10a run.

    uv run python -m evals.questions_real_corrected    # -> evals/data_v2/questions_real_corrected.jsonl

The original dataset and its builder (questions_real.py) are not changed. Corrections:
  1. r10: "buyer pays freight" is enough; "ex-works" is no longer required.
  2. r25: the PO number identifies the winning order; the supplier name is no longer required.
  3. r22: each Q2 order's sub total and total may come from the PO or from its invoice (same values in corpus v2).
     Q2 membership is still decided by the PO dates.
  4. Identity evidence: item rows that only show which document or item is meant are tagged "identity" (group
     indexes in q["identity"]). They are also satisfied by the document's number or the item's description.
Every added snippet is located in the PDF text, as in the original builder.
"""

import json

import pymupdf

from evals.corpus_v2 import DATA_DIR, PDF_DIR
from evals.questions_real import FILES, P, either, flat, item, locate, po, row_s, subtotal_s, total_s

SOURCE, OUT = DATA_DIR / "questions_real.jsonl", DATA_DIR / "questions_real_corrected.jsonl"
NUMBER = {file: num for num, file in FILES.items()}

# question -> (PO seq, item description start) of each item row used only for identity
IDENTITY = {"r01": [(204, "Galvanised")], "r02": [(205, "Network switch")], "r04": [(202, "Wooden pallet")],
            "r07": [(203, "Projector,")], "r08": [(204, "Galvanised")], "r09": [(201, "Cloud backup")],
            "r10": [(208, "Kraft paper")], "r11": [(206, "A4 copier paper")], "r12": [(208, "Packing tape")],
            "r15": [(205, "Cat6 UTP")], "r16": [(202, "Wooden pallet")],
            "r37": [(204, "Galvanised"), (205, "Network switch")], "r40": [(206, "A4 copier paper")]}


def corrected(q: dict, pages: dict) -> dict:
    q = json.loads(json.dumps(q))  # deep copy
    fixes = []
    if q["id"] == "r10":
        q["score"]["must_include"] = []
        fixes.append("'ex-works' not required; 'buyer pays freight' is enough")
    if q["id"] == "r25":
        q["score"]["must_include"] = [po(205)]
        fixes.append("supplier name not required; the PO number identifies the order")
    if q["id"] == "r22":
        q2 = [n for n in sorted(P) if any(e["snippet"] == total_s(n, "po") for g in q["evidence"] for e in g)]
        assert len(q2) == 4, q2
        membership = [g for g in q["evidence"] if not any(e["snippet"] in {subtotal_s(n, "po") for n in q2}
                                                           | {total_s(n, "po") for n in q2} for e in g)]
        money = [g for n in q2 for g in either(n, subtotal_s) + either(n, total_s)]
        q["evidence"] = membership + [[locate(num, s, pages) for num, s in g] for g in money]
        fixes.append("Q2 amounts from the PO or its invoice; membership still by PO date")
    q["identity"] = []
    for seq, start in IDENTITY.get(q["id"], []):
        it = item(seq, start)
        index = next(i for i, g in enumerate(q["evidence"]) if any(e["snippet"] == row_s(it) for e in g))
        group = q["evidence"][index]
        for file in sorted({e["file"] for e in group}):
            group += [locate(NUMBER[file], NUMBER[file], pages), locate(NUMBER[file], it.desc, pages)]
        q["identity"].append(index)
    if q["identity"]:
        fixes.append("item rows used for identity tagged; document number or item description also accepted")
    q["corrections"] = fixes
    return q


def main() -> None:
    pages = {f: [flat(p.get_text()) for p in pymupdf.open(PDF_DIR / f)] for f in FILES.values()}
    rows = [corrected(json.loads(l), pages) for l in SOURCE.read_text(encoding="utf-8").splitlines()]
    missing = sorted({(r["id"], e["file"], e["snippet"]) for r in rows for g in r["evidence"] for e in g
                      if not e["page"]})
    assert not missing, "not in PDF text:\n" + "\n".join(map(str, missing))
    assert {r["id"] for r in rows if r["identity"]} == set(IDENTITY)
    with open(OUT, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    print(f"{len(rows)} questions, {sum(bool(r['corrections']) for r in rows)} corrected -> {OUT.name}")
    for r in rows:
        if r["corrections"]:
            print(f"  {r['id']}: {'; '.join(r['corrections'])}")


if __name__ == "__main__":
    main()
