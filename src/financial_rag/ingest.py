"""Ingest a folder of PDFs with one chunker: documents, pages, chunks, then missing embeddings.

Each chunker's rows are stored under their own `chunks.chunker` name, so strategies sit side by side.

    uv run python -m financial_rag.ingest evals/data/corpus --strategy structure [--no-context] [--dry-run]

`run(paths, ...)` is also used by the API for single uploads.
"""

import argparse
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pymupdf
from sqlalchemy import delete, func, select

from financial_rag.chunking import CHUNK_OVERLAP, CHUNK_SIZE, STRATEGIES, normalise
from financial_rag.db import Chunk, Document, DocumentPage, Embedding, IngestionRun, get_sessionmaker
from financial_rag.doc_info import extract_doc_info
from financial_rag.embeddings import BATCH_SIZE, MODEL_KEY, embed_documents

PIPELINE_VERSION = "1c"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def chunker_name(strategy: str, context: bool) -> str:
    return f"{strategy}_ctx" if context else strategy


def chunk_file(pdf: pymupdf.Document, strategy: str, context: bool):
    info = extract_doc_info(pdf)
    return info, STRATEGIES[strategy](pdf, info.context() if context else None)


def ingest_file(s, path: Path, run_id: int, strategy: str, context: bool) -> int:
    """Store one PDF and replace its chunks for this chunker. Returns the chunk count."""
    data = path.read_bytes()
    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        info, chunks = chunk_file(pdf, strategy, context)
        doc = s.scalar(select(Document).where(Document.content_hash == sha256(data)))
        if doc is None:
            pages = [normalise(p.get_text()).strip() for p in pdf]
            doc = Document(filename=path.name, mime_type="application/pdf", page_count=len(pages),
                           content_hash=sha256(data), storage_uri=str(path.resolve()), is_scanned=not any(pages))
            s.add(doc)
            s.flush()
            s.add_all(DocumentPage(document_id=doc.id, page_number=n, text=t, text_source="native")
                      for n, t in enumerate(pages, 1))

    name = chunker_name(strategy, context)
    doc.doc_type, doc.doc_number, doc.latest_run_id = info.doc_type or "unknown", info.number, run_id
    s.execute(delete(Chunk).where(Chunk.document_id == doc.id, Chunk.chunker == name))
    s.add_all(Chunk(document_id=doc.id, run_id=run_id, chunker=name, chunk_index=i, page_start=c.page_start,
                    page_end=c.page_end, section=c.section and c.section[:200], chunk_type=c.chunk_type,
                    text=c.text, search_text=c.search_text, text_hash=sha256(c.search_text.encode()),
                    token_count=max(1, len(c.search_text) // 4))  # approximate: ~4 characters per token
              for i, c in enumerate(chunks))
    if chunks:
        doc.status, doc.status_detail = "ingested", None
    else:
        doc.status, doc.status_detail = ("needs_ocr", "No text layer") if doc.is_scanned else ("empty", "No chunks")
    return len(chunks)


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
        print(f"  embedded {min(i + BATCH_SIZE, len(rows))}/{len(rows)}", flush=True)
    return len(rows)


def run(paths: list[Path], strategy: str, context: bool = True) -> dict:
    Session = get_sessionmaker()
    name = chunker_name(strategy, context)
    with Session() as s, s.begin():
        r = IngestionRun(status="running", pipeline_version=PIPELINE_VERSION, config={
            "chunker": name, "strategy": strategy, "context": context, "chunk_size": CHUNK_SIZE,
            "chunk_overlap": CHUNK_OVERLAP, "embedding_model": MODEL_KEY})
        s.add(r)
        s.flush()
        run_id = r.id

    stats, status = {"documents": 0, "chunks": 0, "failed": {}}, "failed"
    try:
        for path in paths:
            try:
                with Session() as s, s.begin():
                    stats["chunks"] += ingest_file(s, path, run_id, strategy, context)
                stats["documents"] += 1
            except Exception as e:
                stats["failed"][path.name] = str(e)[:300]
                mark_failed(Session, path, run_id, e)
        stats["embedded"] = embed_missing(Session, name)
        status = "failed" if stats["failed"] else "succeeded"
    finally:
        with Session() as s, s.begin():
            r = s.get(IngestionRun, run_id)
            r.status, r.stats, r.finished_at = status, stats, datetime.now(timezone.utc)
    return {"run_id": run_id, "chunker": name, "status": status, **stats}


def dry_run(folder: str, strategy: str, context: bool) -> None:
    """Show what would be stored, without touching the database or the embedding API."""
    total = 0
    for path in sorted(Path(folder).glob("*.pdf")):
        with pymupdf.open(path) as pdf:
            info, chunks = chunk_file(pdf, strategy, context)
        total += len(chunks)
        print(f"{path.name:34s} {len(chunks):3d} chunks  context: {info.context() if context else '-'}")
    print(f"{chunker_name(strategy, context)}: {total} chunks")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Ingest PDFs into Postgres with one chunking strategy.")
    ap.add_argument("folder")
    ap.add_argument("--strategy", choices=STRATEGIES, required=True)
    ap.add_argument("--no-context", action="store_true", help="omit the document context prefix")
    ap.add_argument("--dry-run", action="store_true", help="print chunk counts; no database, no API calls")
    args = ap.parse_args()
    if args.dry_run:
        dry_run(args.folder, args.strategy, not args.no_context)
    else:
        print(run(sorted(Path(args.folder).glob("*.pdf")), args.strategy, not args.no_context))
