"""Ingest PDFs: Docling converts each file once, then every chunker runs on the stored result.

    uv run python -m financial_rag.ingest evals/data_v2/corpus [--chunker hybrid structure] [--dry-run]

Per file: document + Docling JSON + page texts, then this file's chunks per chunker are replaced.
Missing embeddings are added at the end. `run(paths, chunkers)` is also used by the API for uploads.
"""

import argparse
import hashlib
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from docling_core.types.doc import DoclingDocument
from sqlalchemy import delete, func, select

from financial_rag import chunkers as ch
from financial_rag.db import Chunk, Document, DocumentPage, Embedding, IngestionRun, get_sessionmaker
from financial_rag.embeddings import BATCH_SIZE, MODEL_KEY, embed_documents
from financial_rag.extraction import extract
from financial_rag.structure_aware_chunker import structure_chunks

PIPELINE_VERSION = "docling-1"
CHUNKERS = {"hybrid": ch.hybrid_chunks, "structure": structure_chunks}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_or_convert(s, path: Path) -> tuple[Document, DoclingDocument]:
    """Reuse the stored Docling result for a known file; otherwise convert and store document + pages."""
    data = path.read_bytes()
    doc = s.scalar(select(Document).where(Document.content_hash == sha256(data)))
    if doc is not None and doc.docling_json:
        return doc, DoclingDocument.model_validate(doc.docling_json)

    dl = extract(path)
    pages = [dl.export_to_markdown(page_no=n).strip() for n in range(1, dl.num_pages() + 1)]
    if doc is None:
        doc = Document(filename=path.name, mime_type="application/pdf", content_hash=sha256(data),
                       storage_uri=str(path.resolve()), page_count=len(pages))
        s.add(doc)
        s.flush()
    doc.docling_json, doc.page_count, doc.is_scanned = dl.export_to_dict(), len(pages), not any(pages)
    s.execute(delete(DocumentPage).where(DocumentPage.document_id == doc.id))  # e.g. pages from the old pipeline
    s.add_all(DocumentPage(document_id=doc.id, page_number=n, text=t, text_source="native")
              for n, t in enumerate(pages, 1))
    return doc, dl


def ingest_file(s, path: Path, run_id: int, names: list[str]) -> int:
    """Store one PDF and replace its chunks for each chunker. Returns the chunk count."""
    doc, dl = load_or_convert(s, path)
    doc.latest_run_id, total = run_id, 0
    for name in names:
        chunks = CHUNKERS[name](dl)
        s.execute(delete(Chunk).where(Chunk.document_id == doc.id, Chunk.chunker == name))
        s.add_all(Chunk(document_id=doc.id, run_id=run_id, chunker=name, chunk_index=c.index,
                        page_start=c.pages[0] if c.pages else 1, page_end=c.pages[-1] if c.pages else 1,
                        section=" > ".join(c.headings)[:200] or None, chunk_type=c.kind, text=c.text,
                        search_text=c.search_text, text_hash=sha256(c.search_text.encode()), token_count=c.tokens)
                  for c in chunks)
        total += len(chunks)
    if total:
        doc.status, doc.status_detail = "ingested", None
    else:
        doc.status, doc.status_detail = ("needs_ocr", "No text layer") if doc.is_scanned else ("empty", "No chunks")
    return total


def mark_failed(Session, path: Path, run_id: int, error: Exception) -> None:
    with Session() as s, s.begin():
        doc = s.scalar(select(Document).where(Document.content_hash == sha256(path.read_bytes())))
        if doc:
            doc.status, doc.status_detail, doc.latest_run_id = "failed", str(error)[:500], run_id


def embed_missing(Session, chunker: str) -> int:
    """Embed this chunker's texts that have no vector yet; commits per batch so progress is kept."""
    with Session() as s:
        rows = s.execute(
            select(Chunk.text_hash, func.min(Chunk.search_text))
            .outerjoin(Embedding, (Embedding.text_hash == Chunk.text_hash) & (Embedding.model == MODEL_KEY))
            .where(Chunk.chunker == chunker, Embedding.text_hash.is_(None))
            .group_by(Chunk.text_hash)).all()
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        vectors = embed_documents([text for _, text in batch])
        with Session() as s, s.begin():
            s.add_all(Embedding(model=MODEL_KEY, text_hash=h, embedding=v) for (h, _), v in zip(batch, vectors))
        print(f"  {chunker}: embedded {min(i + BATCH_SIZE, len(rows))}/{len(rows)}", flush=True)
    return len(rows)


def run(paths: list[Path], names: list[str]) -> dict:
    Session = get_sessionmaker()
    with Session() as s, s.begin():
        r = IngestionRun(status="running", pipeline_version=PIPELINE_VERSION, config={
            "chunkers": names, "max_tokens": ch.MAX_TOKENS, "header_tokens": ch.HEADER_TOKENS,
            "tokenizer": ch.TOKENIZER, "embedding_model": MODEL_KEY, "docling": version("docling")})
        s.add(r)
        s.flush()
        run_id = r.id

    stats, status = {"documents": 0, "chunks": 0, "failed": {}}, "failed"
    try:
        for path in paths:
            try:
                with Session() as s, s.begin():
                    stats["chunks"] += ingest_file(s, path, run_id, names)
                stats["documents"] += 1
                print(f"  {path.name}: done", flush=True)
            except Exception as e:
                stats["failed"][path.name] = str(e)[:300]
                mark_failed(Session, path, run_id, e)
        stats["embedded"] = {name: embed_missing(Session, name) for name in names}
        status = "failed" if stats["failed"] else "succeeded"
    finally:
        with Session() as s, s.begin():
            r = s.get(IngestionRun, run_id)
            r.status, r.stats, r.finished_at = status, stats, datetime.now(timezone.utc)
    return {"run_id": run_id, "status": status, **stats}


def dry_run(paths: list[Path], names: list[str]) -> None:
    """Convert and chunk without touching the database or the embedding API."""
    for path in paths:
        dl = extract(path)
        counts = "  ".join(f"{name} {len(CHUNKERS[name](dl)):3d}" for name in names)
        print(f"{path.name:34s} pages {dl.num_pages()}  {counts}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Ingest PDFs into Postgres with Docling and the chosen chunkers.")
    ap.add_argument("folder")
    ap.add_argument("--chunker", nargs="+", choices=CHUNKERS, default=list(CHUNKERS))
    ap.add_argument("--dry-run", action="store_true", help="convert and chunk only; no database, no API calls")
    args = ap.parse_args()
    files = sorted(Path(args.folder).glob("*.pdf"))
    if args.dry_run:
        dry_run(files, args.chunker)
    else:
        print(run(files, args.chunker))
