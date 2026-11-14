"""Chunk a DoclingDocument for retrieval.

    uv run python -m financial_rag.chunkers data/docling/po-po-2026-27-0201.json

Each chunk keeps two texts: `text` (shown and sent to the LLM) and `search_text`
(what gets embedded: the headings above the chunk, then its text).
"""

import argparse
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from docling.chunking import HybridChunker
from docling_core.transforms.chunker.hierarchical_chunker import ChunkingDocSerializer, ChunkingSerializerProvider
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from docling_core.transforms.serializer.markdown import MarkdownTableSerializer
from docling_core.types.doc import DoclingDocument

# Gemini's tokenizer isn't available locally; this one approximates token counts.
TOKENIZER = "sentence-transformers/all-MiniLM-L6-v2"
MAX_TOKENS = 256


@dataclass
class Chunk:
    index: int
    text: str
    search_text: str
    headings: list[str]
    pages: list[int]
    tokens: int


class MarkdownTables(ChunkingSerializerProvider):
    """Write tables as Markdown instead of Docling's default "row, column = value" sentences."""

    def get_serializer(self, doc: DoclingDocument) -> ChunkingDocSerializer:
        return ChunkingDocSerializer(doc=doc, table_serializer=MarkdownTableSerializer())


@cache
def hybrid_chunker() -> HybridChunker:
    tokenizer = HuggingFaceTokenizer.from_pretrained(model_name=TOKENIZER, max_tokens=MAX_TOKENS)
    return HybridChunker(tokenizer=tokenizer, serializer_provider=MarkdownTables())


def hybrid_chunks(doc: DoclingDocument) -> list[Chunk]:
    """Docling's HybridChunker: split by document structure, then fit chunks to MAX_TOKENS."""
    chunker = hybrid_chunker()
    chunks = []
    for i, chunk in enumerate(chunker.chunk(doc)):
        search_text = chunker.contextualize(chunk)
        pages = sorted({prov.page_no for item in chunk.meta.doc_items for prov in item.prov})
        chunks.append(Chunk(i, chunk.text, search_text, chunk.meta.headings or [], pages,
                            chunker.tokenizer.count_tokens(search_text)))
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("json", type=Path, help="Docling JSON from financial_rag.extraction")
    args = parser.parse_args()

    chunks = hybrid_chunks(DoclingDocument.load_from_json(args.json))
    print(f"{len(chunks)} chunks (max {MAX_TOKENS} tokens)\n")
    for c in chunks:
        print(f"--- #{c.index}  pages {c.pages}  {c.tokens} tokens  headings {c.headings}")
        print(c.search_text, "\n")


if __name__ == "__main__":
    main()
