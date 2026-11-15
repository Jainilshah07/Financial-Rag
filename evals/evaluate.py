"""Retrieval evaluation: every chunker x method on a question set (read-only).

A retrieved chunk is relevant when it comes from the question's document and contains
every evidence snippet. The lenient MRR also accepts the linked document (a PO and its
invoice), which often holds the same answer. Writes per-question ranks to a results file.

    uv run python -m evals.evaluate                                    # test set v2 -> results_v2.json
    uv run python -m evals.evaluate --data data --out results_v1.json  # v1 questions (results.json is the regex baseline)
"""

import argparse
import json
import sys
from pathlib import Path

from evals.corpus import norm
from financial_rag.chunkers import count_tokens
from financial_rag.db import get_sessionmaker
from financial_rag.search import METHODS, TOP_K

ROOT = Path(__file__).parent


def first_relevant(hits, q: dict, doc_ids: set[str]) -> int | None:
    evidence = [norm(e) for e in q["evidence"]]
    for rank, h in enumerate(hits, 1):
        if h.filename[:-4] in doc_ids and all(e in norm(h.text) for e in evidence):
            return rank
    return None


def linked_docs(data: Path) -> dict[str, set[str]]:
    """doc_id -> the doc ids of its PO + invoice pair (from documents.json)."""
    docs = json.loads((data / "documents.json").read_text(encoding="utf-8"))
    pairs: dict[str, set[str]] = {}
    for d in docs:
        pairs.setdefault(d.get("po_number") or d["number"], set()).add(d["doc_id"])
    return {d["doc_id"]: pairs[d.get("po_number") or d["number"]] for d in docs}


def summarise(rows: list[dict]) -> dict:
    n = len(rows)
    return {
        "hit1": sum(r["rank"] == 1 for r in rows) / n,
        "hit5": sum(r["rank"] is not None and r["rank"] <= 5 for r in rows) / n,
        "mrr": sum(1 / r["rank"] for r in rows if r["rank"]) / n,
        "mrr_linked": sum(1 / r["rank_linked"] for r in rows if r["rank_linked"]) / n,
        "tokens5": sum(r["tokens5"] for r in rows) / n,  # what the LLM would read: text of the top 5 chunks
    }


def breakdown(rows: list[dict], key: str) -> dict:
    return {v: summarise([r for r in rows if r[key] == v]) for v in sorted({r[key] for r in rows})}


def main():
    ap = argparse.ArgumentParser(description="Evaluate retrieval for each chunker x method.")
    ap.add_argument("--data", default="data_v2", help="folder under evals/ with questions.jsonl")
    ap.add_argument("--chunkers", nargs="+", default=["hybrid", "structure"])
    ap.add_argument("--out", default="results_v2.json", help="file under evals/")
    args = ap.parse_args()
    if args.out == "results.json":
        sys.exit("results.json is the regex baseline; choose another --out")

    sys.stdout.reconfigure(encoding="utf-8")
    questions = [json.loads(l) for l in (ROOT / args.data / "questions.jsonl").read_text(encoding="utf-8").splitlines()]
    linked = linked_docs(ROOT / args.data)
    results = {}

    with get_sessionmaker()() as s:
        for chunker in args.chunkers:
            for method, fn in METHODS.items():
                rows = []
                for q in questions:
                    hits = fn(s, q["question"], chunker, TOP_K)
                    rows.append({"id": q["id"], "type": q["type"], "layout": q.get("layout", "-"),
                                 "rank": first_relevant(hits, q, {q["doc_id"]}),
                                 "rank_linked": first_relevant(hits, q, linked[q["doc_id"]]),
                                 "tokens5": sum(count_tokens(h.text) for h in hits[:5])})
                results[f"{chunker}|{method}"] = {"summary": summarise(rows), "by_type": breakdown(rows, "type"),
                                                  "by_layout": breakdown(rows, "layout"), "questions": rows}

    types = sorted({q["type"] for q in questions})
    layouts = sorted({q.get("layout", "-") for q in questions})
    print(f"{len(questions)} questions from evals/{args.data}\n")
    print("| Chunker | Method | Hit@1 | Hit@5 | MRR | MRR linked | Tokens@5 | " + " | ".join(f"MRR {t}" for t in types) + " |")
    print("|---|---|---|---|---|---|---|" + "---|" * len(types))
    for key, r in results.items():
        a = r["summary"]
        print(f"| {key.replace('|', ' | ')} | {a['hit1']:.2f} | {a['hit5']:.2f} | {a['mrr']:.3f} | {a['mrr_linked']:.3f} "
              f"| {a['tokens5']:.0f} | "
              + " | ".join(f"{r['by_type'][t]['mrr']:.2f}" for t in types) + " |")
    print("\n| Chunker | Method | " + " | ".join(f"MRR {l}" for l in layouts) + " |")
    print("|---|---|" + "---|" * len(layouts))
    for key, r in results.items():
        print(f"| {key.replace('|', ' | ')} | " + " | ".join(f"{r['by_layout'][l]['mrr']:.2f}" for l in layouts) + " |")

    (ROOT / args.out).write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"\nPer-question ranks: evals/{args.out}")


if __name__ == "__main__":
    main()
