"""Retrieval evaluation: every chunker x method on evals/data/questions.jsonl (read-only).

A retrieved chunk is relevant when it comes from the question's document and contains
every evidence snippet. Writes per-question ranks to evals/results.json.

    uv run python -m evals.evaluate
"""

import json
import sys
from pathlib import Path

from evals.corpus import norm
from financial_rag.db import get_sessionmaker
from financial_rag.search import METHODS, TOP_K

CHUNKERS = ["recursive_ctx", "page_ctx", "structure_ctx"]
ROOT = Path(__file__).parent


def first_relevant(hits, q: dict) -> int | None:
    evidence = [norm(e) for e in q["evidence"]]
    for rank, h in enumerate(hits, 1):
        if h.filename == f"{q['doc_id']}.pdf" and all(e in norm(h.text) for e in evidence):
            return rank
    return None


def summarise(rows: list[dict]) -> dict:
    n = len(rows)
    return {
        "hit1": sum(r["rank"] == 1 for r in rows) / n,
        "hit5": sum(r["rank"] is not None and r["rank"] <= 5 for r in rows) / n,
        "mrr": sum(1 / r["rank"] for r in rows if r["rank"]) / n,
        "tokens5": sum(r["tokens5"] for r in rows) / n,
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    questions = [json.loads(l) for l in (ROOT / "data" / "questions.jsonl").read_text(encoding="utf-8").splitlines()]
    types = sorted({q["type"] for q in questions})
    results = {}

    with get_sessionmaker()() as s:
        for chunker in CHUNKERS:
            for method, fn in METHODS.items():
                rows = []
                for q in questions:
                    hits = fn(s, q["question"], chunker, TOP_K)
                    rows.append({"id": q["id"], "type": q["type"], "rank": first_relevant(hits, q),
                                 "tokens5": sum(len(h.text) // 4 for h in hits[:5])})
                results[f"{chunker}|{method}"] = {
                    "summary": summarise(rows),
                    "by_type": {t: summarise([r for r in rows if r["type"] == t]) for t in types},
                    "questions": rows,
                }

    print(f"{len(questions)} questions ({', '.join(f'{t}: {sum(q['type'] == t for q in questions)}' for t in types)})\n")
    print(f"| Chunker | Method | Hit@1 | Hit@5 | MRR | ~Tokens@5 | " + " | ".join(f"MRR {t}" for t in types) + " |")
    print("|---|---|---|---|---|---|" + "---|" * len(types))
    for key, r in results.items():
        a = r["summary"]
        print(f"| {key.replace('|', ' | ')} | {a['hit1']:.2f} | {a['hit5']:.2f} | {a['mrr']:.3f} | {a['tokens5']:.0f} | "
              + " | ".join(f"{r['by_type'][t]['mrr']:.2f}" for t in types) + " |")

    (ROOT / "results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    print("\nPer-question ranks: evals/results.json")


if __name__ == "__main__":
    main()
