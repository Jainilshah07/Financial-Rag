"""PDF extraction with Docling: layout, tables and reading order as a DoclingDocument.

    uv run python -m financial_rag.extraction evals/data/corpus/po-po-2026-27-0101.pdf [--ocr]

Writes <name>.json (full document) and <name>.md (for reading) to data/docling/ and prints a summary.
"""

import argparse
from collections import Counter
from functools import cache
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import DoclingDocument, TableItem

OUT_DIR = Path("data/docling")


@cache
def converter(ocr: bool = False) -> DocumentConverter:
    """Models load once per process. OCR is only needed for scanned pages."""
    options = PdfPipelineOptions(do_ocr=ocr, do_table_structure=True)
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})


def extract(path: Path, ocr: bool = False) -> DoclingDocument:
    return converter(ocr).convert(path).document


def summary(doc: DoclingDocument) -> str:
    """Label counts, then every element in reading order with its page."""
    labels = Counter(item.label.value for item, _ in doc.iterate_items())
    lines = [f"pages: {doc.num_pages()}  elements: {dict(labels)}", ""]
    for item, level in doc.iterate_items():
        page = item.prov[0].page_no if item.prov else "?"
        if isinstance(item, TableItem):
            text = f"{item.data.num_rows} rows x {item.data.num_cols} cols"
        else:
            text = getattr(item, "text", "")[:80]
        lines.append(f"p{page} {'  ' * level}{item.label.value:<15} {text}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdfs", nargs="+", type=Path)
    parser.add_argument("--ocr", action="store_true", help="run OCR (scanned PDFs)")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in args.pdfs:
        doc = extract(path, args.ocr)
        doc.save_as_json(OUT_DIR / f"{path.stem}.json")
        doc.save_as_markdown(OUT_DIR / f"{path.stem}.md")
        print(f"== {path.name}\n{summary(doc)}\n")


if __name__ == "__main__":
    main()
