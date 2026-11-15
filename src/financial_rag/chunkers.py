"""Chunk a DoclingDocument for retrieval.

    uv run python -m financial_rag.chunkers data/docling/po-po-2026-27-0201.json [--chunker structure]

Each chunk keeps two texts: `text` (shown and sent to the LLM) and `search_text`
(what gets embedded: document header, headings above the chunk, then its text).
MAX_TOKENS limits headings + text; the document header comes on top.
"""

import argparse
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from docling.chunking import HybridChunker
from docling_core.transforms.chunker.hierarchical_chunker import ChunkingDocSerializer, ChunkingSerializerProvider
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from docling_core.transforms.serializer.markdown import MarkdownTableSerializer
from docling_core.types.doc import DocItemLabel, DoclingDocument, TableItem, TextItem

# Gemini's tokenizer isn't available locally; this one approximates token counts.
TOKENIZER = "sentence-transformers/all-MiniLM-L6-v2"
MAX_TOKENS = 256
HEADER_TOKENS = 64  # document header added to every chunk's search_text
HEADER_ITEM_TOKENS = 24  # longer page-1 texts (addresses, paragraphs) are left out of the header


@dataclass
class Chunk:
    index: int
    text: str
    search_text: str
    headings: list[str]
    pages: list[int]
    tokens: int
    kind: str  # "table" | "clause" | "text"


@cache
def tokenizer() -> HuggingFaceTokenizer:
    return HuggingFaceTokenizer.from_pretrained(model_name=TOKENIZER, max_tokens=MAX_TOKENS)


def count_tokens(text: str) -> int:
    return tokenizer().count_tokens(text)


def table_rows(table: TableItem) -> list[str]:
    """One "a | b | c" line per row; a cell spanning several columns is written once."""
    rows: dict[int, list[str]] = {}
    for cell in sorted(table.data.table_cells, key=lambda c: (c.start_row_offset_idx, c.start_col_offset_idx)):
        rows.setdefault(cell.start_row_offset_idx, []).append(cell.text.strip())
    return [" | ".join(cells) for cells in rows.values()]


def doc_header(doc: DoclingDocument) -> str:
    """Short page-1 lines (title, numbers, dates, party names) that identify the document.

    Taken in reading order, skipping long texts and line-item tables, until HEADER_TOKENS.
    No field extraction: it works the same for any layout.
    """
    parts, used = [], 0
    for item, _ in doc.iterate_items():
        if not item.prov or item.prov[0].page_no != 1:
            break
        if isinstance(item, TableItem):
            if any(c.column_header for c in item.data.table_cells) or item.data.num_rows > 4:
                continue  # line items, not identity
            lines = table_rows(item)
        elif isinstance(item, TextItem) and count_tokens(item.text) <= HEADER_ITEM_TOKENS:
            lines = [item.text]
        else:
            continue
        for line in lines:
            parts.append(line)
            used += count_tokens(line)
            if used >= HEADER_TOKENS:
                return " | ".join(parts)
    return " | ".join(parts)


class MarkdownTables(ChunkingSerializerProvider):
    """Write tables as Markdown instead of Docling's default "row, column = value" sentences."""

    def get_serializer(self, doc: DoclingDocument) -> ChunkingDocSerializer:
        return ChunkingDocSerializer(doc=doc, table_serializer=MarkdownTableSerializer())


@cache
def hybrid_chunker() -> HybridChunker:
    return HybridChunker(tokenizer=tokenizer(), serializer_provider=MarkdownTables())


def hybrid_chunks(doc: DoclingDocument) -> list[Chunk]:
    """Docling's HybridChunker: split by document structure, then fit chunks to MAX_TOKENS."""
    chunker, header = hybrid_chunker(), doc_header(doc)
    chunks = []
    for i, chunk in enumerate(chunker.chunk(doc)):
        search_text = f"{header}\n{chunker.contextualize(chunk)}"
        items = chunk.meta.doc_items
        pages = sorted({prov.page_no for item in items for prov in item.prov})
        kind = ("table" if any(isinstance(item, TableItem) for item in items)
                else "clause" if any(item.label == DocItemLabel.LIST_ITEM for item in items) else "text")
        chunks.append(Chunk(i, chunk.text, search_text, chunk.meta.headings or [], pages,
                            count_tokens(search_text), kind))
    return chunks


def main() -> None:
    from financial_rag.structure_aware_chunker import structure_chunks  # imports this module

    chunkers = {"hybrid": hybrid_chunks, "structure": structure_chunks}
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("json", type=Path, help="Docling JSON from financial_rag.extraction")
    parser.add_argument("--chunker", choices=chunkers, default="hybrid")
    args = parser.parse_args()

    chunks = chunkers[args.chunker](DoclingDocument.load_from_json(args.json))
    print(f"{len(chunks)} chunks ({args.chunker}, max {MAX_TOKENS} tokens + document header)\n")
    for c in chunks:
        print(f"--- #{c.index}  pages {c.pages}  {c.tokens} tokens  headings {c.headings}")
        print(c.search_text, "\n")


if __name__ == "__main__":
    main()
