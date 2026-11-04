"""Chunking strategies: recursive, page, structure-aware.

Each returns Chunk objects. `text` is what we cite; `search_text` adds the optional
document context and section, and is what gets embedded and keyword-indexed.

Dry run (no database):  uv run python -m financial_rag.chunking <file.pdf> [--strategy structure] [--context "..."]
"""

import argparse
import re
import statistics
import unicodedata
from dataclasses import dataclass

import pymupdf
from langchain_text_splitters import RecursiveCharacterTextSplitter

CHUNK_SIZE, CHUNK_OVERLAP = 1000, 150
MERGE_LIMIT = 600  # merge small neighbouring text blocks (e.g. addresses) up to this size
CLAUSE_START = re.compile(r"^\d{1,2}\.\s+\S")  # "4. Payment Terms: ..."


@dataclass
class Chunk:
    text: str
    search_text: str
    page_start: int  # 1-based
    page_end: int
    section: str | None = None
    chunk_type: str = "text"  # header | table | clause | text


def normalise(text: str) -> str:
    """NFKC expands PDF ligatures ("oﬃce" -> "office") and odd spaces."""
    return unicodedata.normalize("NFKC", text)


def _search_text(text: str, section: str | None, context: str | None) -> str:
    return "\n".join(p for p in (context, section and f"Section: {section}", text) if p)


_splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)


# ---------------------------------------------------------------- recursive and page

# [result for item in collection]
def recursive(doc: pymupdf.Document, context: str | None = None) -> list[Chunk]:
    return [
        Chunk(part, _search_text(part, None, context), n, n)
        for n, page in enumerate(doc, 1)
        for part in _splitter.split_text(normalise(page.get_text()))
    ]


def page(doc: pymupdf.Document, context: str | None = None) -> list[Chunk]:
    chunks = []
    for n, p in enumerate(doc, 1):
        text = normalise(p.get_text()).strip()
        if text:
            chunks.append(Chunk(text, _search_text(text, None, context), n, n))
    return chunks


# ---------------------------------------------------------------- structure-aware


def _table_text(rows: list[list]) -> tuple[str, bool]:
    """Serialise a table row by row. Returns (text, has_header_row).

    Tables with a header row become 'Column: value | ...' so numbers keep their meaning;
    key-value grids ('PO No. | PO/... | Date | ...') are kept as they are.
    """
    rows = [[normalise(c or "").replace("\n", " ").strip() for c in r] for r in rows]
    rows = [r for r in rows if any(r)]
    if not rows:
        return "", False
    head = rows[0]
    if len(head) < 3 or not all(head) or any(re.search(r"\d", c) for c in head):
        return "\n".join(" | ".join(c for c in r if c) for r in rows), False
    lines = []
    for r in rows[1:]:
        cells = [(h, c) for h, c in zip(head, r) if c]
        if len(cells) * 2 < len(head):  # totals row spanning most columns: "Sub Total: 10,56,000.00"
            lines.append(": ".join(c for _, c in cells))
        else:
            lines.append(" | ".join(f"{h}: {c}" for h, c in cells))
    return "\n".join(lines), True


def _elements(doc: pymupdf.Document) -> list[tuple]:
    """Tables and text lines in reading order: (page, y, kind, payload)."""
    items = []
    for n, p in enumerate(doc, 1):
        found = p.find_tables().tables
        # wrapped header cells ("HSN/ SAC") can be detected as tiny tables inside a real one
        tables = [t for t in found if not any(
            o is not t and pymupdf.Rect(o.bbox).contains(pymupdf.Rect(t.bbox)) for o in found)]
        rects = [pymupdf.Rect(t.bbox) for t in tables]
        for t, r in zip(tables, rects):
            text, has_header = _table_text(t.extract())
            if text:
                items.append((n, r.y0, "table", (text, has_header)))

        lines = []
        for block in p.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = [s for s in line["spans"] if s["text"].strip()]
                bbox = pymupdf.Rect(line["bbox"])
                if spans and not any(r.intersects(bbox) for r in rects):
                    lines.append((bbox.y0, spans))
        body_size = statistics.median(s["size"] for _, spans in lines for s in spans) if lines else 0
        for y, spans in lines:
            text = normalise("".join(s["text"] for s in spans)).strip()
            bold = all(s["flags"] & 16 for s in spans)
            larger = max(s["size"] for s in spans) > body_size + 0.5
            heading = len(text) <= 40 and len(text.split()) <= 6 and (larger or (bold and text.isupper()))
            items.append((n, y, "heading" if heading else "line", text))
    return sorted(items, key=lambda i: (i[0], i[1]))


def _units(doc: pymupdf.Document) -> list[dict]:
    """Group elements into units: one per clause, per table, or per text block under a heading."""
    units, section, current = [], "Document header", None
    for n, _y, kind, payload in _elements(doc):
        if kind in ("heading", "table") or (kind == "line" and CLAUSE_START.match(payload)):
            current = None
        if kind == "heading":
            section = payload.title() if payload.isupper() else payload
        elif kind == "table":
            text, has_header = payload
            if has_header:
                section = "Line items"
            units.append({"page_start": n, "page_end": n, "section": section, "text": text,
                          "type": "table" if has_header else "block"})
        elif current is None:
            label = payload.split(":", 1)[0] if CLAUSE_START.match(payload) and ":" in payload[:60] else None
            label = label and re.sub(r"^\d{1,2}\.\s*", "", label)
            current = {"page_start": n, "page_end": n, "section": f"{section} > {label}" if label else section,
                       "text": payload, "type": "clause" if CLAUSE_START.match(payload) else "block"}
            units.append(current)
        else:
            current["text"] += "\n" + payload
            current["page_end"] = n
    return units


def structure(doc: pymupdf.Document, context: str | None = None) -> list[Chunk]:
    merged = []
    for u in _units(doc):
        prev = merged[-1] if merged else None
        if prev and u["type"] == prev["type"] == "block" and len(prev["text"]) + len(u["text"]) <= MERGE_LIMIT:
            prev["text"] += "\n" + u["text"]
            prev["page_end"] = u["page_end"]
            if u["section"] not in prev["section"].split(", "):
                prev["section"] += ", " + u["section"]
        else:
            merged.append(dict(u))

    chunks = []
    for u in merged:
        kind = "header" if u["type"] == "block" and u["section"].startswith("Document header") else (
            "text" if u["type"] == "block" else u["type"])
        for part in _splitter.split_text(u["text"]) if len(u["text"]) > CHUNK_SIZE * 1.5 else [u["text"]]:
            chunks.append(Chunk(part, _search_text(part, u["section"], context),
                                u["page_start"], u["page_end"], u["section"], kind))
    return chunks


STRATEGIES = {"recursive": recursive, "page": page, "structure": structure}


def chunk_pdf(path: str, strategy: str, context: str | None = None) -> list[Chunk]:
    with pymupdf.open(path) as doc:
        return STRATEGIES[strategy](doc, context)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Print the chunks of a PDF (no database).")
    ap.add_argument("pdf")
    ap.add_argument("--strategy", choices=STRATEGIES, default="structure")
    ap.add_argument("--context", help='e.g. "Purchase Order PO/2026-27/0101 | Vendor: Kumar Office Solutions"')
    args = ap.parse_args()
    for i, c in enumerate(chunk_pdf(args.pdf, args.strategy, args.context)):
        print(f"--- #{i} {c.chunk_type} p{c.page_start}-{c.page_end} [{c.section or '-'}] {len(c.text)} chars")
        print(c.search_text, "\n")
