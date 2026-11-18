"""Step 10b review: questions_real_corrected.jsonl plus gold revisions agreed after the 10b run.

    uv run python -m evals.questions_real_revised    # -> evals/data_v2/questions_real_revised.jsonl

A new file, so runs scored against questions_real_corrected.jsonl (10a corrected, 10b) keep their gold.
Revisions (listed per question in q["revisions"]):
  r01: "the Bharat Steel order for GI pipes" can mean the GI pipe line or the whole PO, so both are accepted:
       printed: the line ₹3,62,000 (before GST), the PO ₹5,59,000 (before GST) and ₹6,59,620 (including GST);
       calculated: the line with its 18% GST, ₹4,27,160. Not printed in the PDF, so it counts only when the answer
       says it includes GST (score["calculated"], checked in evaluate_real.score).
       The item row now holds an accepted value, so it is answer evidence again, no longer an identity group.
Checked and unchanged:
  r23: supplier totals over all 8 invoices match the printed invoice totals and sub totals: Nimbus ₹9,06,240
       vs Ganesh ₹8,95,180 including GST; Ganesh ₹7,90,000 vs Nimbus ₹7,68,000 before GST.
"""

import json

import pymupdf

from evals.corpus_v2 import DATA_DIR, PDF_DIR
from evals.questions_real import FILES, flat, inr, item, po, row_s, rs, taxable, total

SOURCE, OUT = DATA_DIR / "questions_real_corrected.jsonl", DATA_DIR / "questions_real_revised.jsonl"
GI = item(204, "Galvanised")
GI_GROSS = GI.amount * (100 + GI.gst) / 100


def revised(q: dict) -> dict:
    q = json.loads(json.dumps(q))  # deep copy
    q["revisions"] = []
    if q["id"] == "r01":
        q["answer"] = (f"Either reading is accepted. The GI pipe line: {rs(GI.amount)} before GST (printed), or "
                       f"{rs(GI_GROSS)} including {GI.gst}% GST (calculated from the line amount and the PO's "
                       f"{GI.gst}% rate, not printed). The whole order {po(204)} (GI pipes and steel tube): "
                       f"{rs(total(204))} including GST ({rs(taxable(204))} before GST), both printed.")
        q["score"]["values"] += [f"{GI.amount:.2f}", f"{GI_GROSS:.2f}"]
        q["score"]["calculated"] = {f"{GI_GROSS:.2f}": "incl_gst"}
        q["assumptions"] = ["'the order for GI pipes' may mean the GI pipe line or the whole PO; both are accepted",
                            f"{rs(GI_GROSS)} is calculated (line amount + {GI.gst}% GST), not printed; it counts "
                            "only when the answer says it includes GST"] + q["assumptions"]
        group = q["evidence"][1]
        q["evidence"][1] = [e for e in group if e["snippet"] == row_s(GI)]
        assert q["identity"] == [1] and len(q["evidence"][1]) == 1
        q["identity"] = []
        q["revisions"].append("GI pipe line total accepted as well as the whole PO (line with GST: calculated, "
                              "basis must be stated); item row is answer evidence")
    return q


def main() -> None:
    text = flat(" ".join(p.get_text() for p in pymupdf.open(PDF_DIR / FILES[po(204)])))
    assert inr(GI.amount) in text and inr(GI_GROSS) not in text  # printed vs calculated
    rows = [revised(json.loads(l)) for l in SOURCE.read_text(encoding="utf-8").splitlines()]
    with open(OUT, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    print(f"{len(rows)} questions -> {OUT.name}")
    for r in rows:
        if r["revisions"]:
            print(f"  {r['id']}: {'; '.join(r['revisions'])}")


if __name__ == "__main__":
    main()
