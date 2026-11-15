"""Structure-aware chunking: our own rules on Docling's labels, for when its structure is imperfect.

    uv run python -m financial_rag.chunkers data/docling/po-po-2026-27-0201.json --chunker structure

Rules (from the step 2 and 3 findings):
- A heading directly after another heading is content (e.g. a party name under "Ship To"), not a section.
- A table takes only the heading directly above it, and ends the section.
- Tables: header row + as many rows as fit, header repeated, never split by column; spanning cells
  written once. Without a header row, a short digit-free text line just above the table is the header.
  A table continuing from the previous page joins it.
- List items (clauses): one chunk each.
- Text: neighbours in a section merged up to the limit; oversized text split by sentence.
"""

import re
from dataclasses import dataclass, field

from docling_core.types.doc import DocItemLabel, DoclingDocument, TableItem, TextItem

from financial_rag.chunkers import MAX_TOKENS, Chunk, count_tokens, doc_header, table_rows

HEADINGS = {DocItemLabel.TITLE, DocItemLabel.SECTION_HEADER}
HEADER_LINE_TOKENS = 40
TINY_TOKENS = 12 # e.g. "Authorised Signatory": attached to the previous chunk instead of standing alone


@dataclass
class Block:
    """One document element, before packing into chunks."""
    kind: str  # "text" | "clause" | "table"
    section: str
    lines: list[tuple[str, int]]  # (text, page); one line for text, one per row for tables
    header: list[str] = field(default_factory=list)  # table header, repeated in every table chunk


@dataclass
class Piece:
    kind: str
    section: str
    lines: list[tuple[str, int]]
    mergeable: bool  # text pieces may absorb following text in the same section

    @property
    def text(self) -> str:
        return "\n".join(t for t, _ in self.lines)


def page(item) -> int:
    return item.prov[0].page_no if item.prov else 0


def is_header_line(text: str) -> bool:
    return count_tokens(text) <= HEADER_LINE_TOKENS and not any(ch.isdigit() for ch in text)


def blocks(doc: DoclingDocument) -> list[Block]:
    out: list[Block] = []
    section, after_heading = "", False

    for item, _ in doc.iterate_items():  # body only: page headers and footers are skipped
        if isinstance(item, TableItem):
            rows = [(row, page(item)) for row in table_rows(item)]
            has_header = any(c.column_header for c in item.data.table_cells)
            prev = out[-1] if out else None
            if prev and prev.kind == "table" and page(item) > prev.lines[-1][1]:
                prev.lines += rows[1:] if has_header else rows  # continued from the previous page
                continue
            header = []
            if has_header:
                header, rows = [rows[0][0]], rows[1:]
            elif prev and prev.kind == "text" and is_header_line(prev.lines[0][0]):
                header = [out.pop().lines[0][0]]  # column headings extracted as text
            out.append(Block("table", section if after_heading else "", rows, header))
            section, after_heading = "", False
        elif isinstance(item, TextItem) and item.text.strip():
            if item.label in HEADINGS and not after_heading:
                section, after_heading = item.text.strip(), True
                continue
            kind = "clause" if item.label == DocItemLabel.LIST_ITEM else "text"
            out.append(Block(kind, section, [(item.text.strip(), page(item))]))
            after_heading = False
    return out


def split_sentences(text: str, pg: int, budget: int) -> list[list[tuple[str, int]]]:
    """Greedy sentence packing for text over the budget (e.g. layout D's merged terms)."""
    groups, current = [], ""
    for sentence in re.split(r"(?<=[.;])\s+", text):
        if current and count_tokens(f"{current} {sentence}") > budget:
            groups.append([(current, pg)])
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    return groups + [[(current, pg)]] if current else groups


def pieces(doc: DoclingDocument) -> list[Piece]:
    out: list[Piece] = []
    for b in blocks(doc):
        budget = MAX_TOKENS - count_tokens(b.section)
        if b.kind == "table":
            group: list[tuple[str, int]] = []
            for row in b.lines:
                if group and count_tokens("\n".join([*b.header, *(t for t, _ in group), row[0]])) > budget:
                    out.append(Piece("table", b.section, [(h, group[0][1]) for h in b.header] + group, False))
                    group = []
                group.append(row)
            if group:
                out.append(Piece("table", b.section, [(h, group[0][1]) for h in b.header] + group, False))
            continue

        text, pg = b.lines[0]
        prev = out[-1] if out else None
        same_section = prev is not None and prev.section == b.section
        if (b.kind == "text" and same_section and (prev.mergeable or count_tokens(text) <= TINY_TOKENS)
                and count_tokens(f"{prev.text}\n{text}") <= budget):
            prev.lines.append((text, pg))
        elif count_tokens(text) > budget:
            if same_section and prev.mergeable:  # keep a lead-in such as "Payment Terms" with its text
                text = f"{out.pop().text}\n{text}"
            out += [Piece(b.kind, b.section, g, False) for g in split_sentences(text, pg, budget)]
        else:
            out.append(Piece(b.kind, b.section, [(text, pg)], b.kind == "text"))
    return out


def structure_chunks(doc: DoclingDocument) -> list[Chunk]:
    header = doc_header(doc)
    chunks = []
    for i, p in enumerate(pieces(doc)):
        search_text = "\n".join(filter(None, [header, p.section, p.text]))
        chunks.append(Chunk(i, p.text, search_text, [p.section] if p.section else [],
                            sorted({pg for _, pg in p.lines}), count_tokens(search_text), p.kind))
    return chunks
