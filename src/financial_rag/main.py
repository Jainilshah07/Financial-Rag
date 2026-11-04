"""FastAPI app: upload, documents and their chunks, and ask (SSE). Data lives in PostgreSQL + pgvector.

    uv run uvicorn financial_rag.main:app --reload --app-dir src
"""

import json
import time
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select

from financial_rag.db import Chunk, Document, get_sessionmaker
from financial_rag.ingest import chunker_name, run as ingest, sha256
from financial_rag.rag import stream_answer
from financial_rag.search import METHODS

UPLOAD_DIR = Path("data/uploads").resolve()
UPLOAD_STRATEGY = "structure"  # uploads use structure-aware chunking with document context
DEFAULT_CHUNKER = chunker_name(UPLOAD_STRATEGY, context=True)
ASK_TOP_K = 5
CHUNKER_LABELS = {"structure_ctx": "Structure-aware", "recursive_ctx": "Recursive (1000 chars)", "page_ctx": "One per page"}
METHOD_LABELS = {"dense": "Dense (vector)", "keyword": "Keyword (full-text)", "hybrid": "Hybrid (RRF)"}
SCORE_LABELS = {"dense": "cosine", "keyword": "ts_rank", "hybrid": "RRF"}

app = FastAPI(title="Financial Document RAG")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def session():
    with get_sessionmaker()() as s:
        yield s


class AskRequest(BaseModel):
    question: str
    chunker: str = DEFAULT_CHUNKER
    method: str = "dense"
    document_id: int | None = None


def sse(event: str, data: dict, started: float) -> str:
    # `elapsed_ms` (time since the request started) lets the UI show real step timings
    data = {**data, "elapsed_ms": round((time.perf_counter() - started) * 1000)}
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def chunk_json(c: Chunk, filename: str) -> dict:
    return {"chunk_id": c.id, "index": c.chunk_index + 1, "page": c.page_start, "section": c.section,
            "chunk_type": c.chunk_type, "text": c.text, "filename": filename}


def document_chunks(s, document_id: int, chunker: str) -> list[Chunk]:
    return s.scalars(select(Chunk).where(Chunk.document_id == document_id, Chunk.chunker == chunker)
                     .order_by(Chunk.chunk_index)).all()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/upload")
def upload(file: UploadFile = File(...), s=Depends(session)):
    name = Path(file.filename or "").name
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a PDF file")

    data = file.file.read()
    path = UPLOAD_DIR / sha256(data)[:16] / name  # one folder per file content keeps the original name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)

    result = ingest([path], UPLOAD_STRATEGY)
    if result["failed"]:
        raise HTTPException(500, f"Ingestion failed: {next(iter(result['failed'].values()))}")
    doc = s.scalar(select(Document).where(Document.content_hash == sha256(data)))
    chunks = document_chunks(s, doc.id, DEFAULT_CHUNKER)
    if not chunks:
        raise HTTPException(400, doc.status_detail or "No readable text found in the PDF")
    return {"document_id": doc.id, "filename": doc.filename, "chunker": DEFAULT_CHUNKER,
            "chunks_indexed": len(chunks), "chunks": [chunk_json(c, doc.filename) for c in chunks]}


@app.get("/documents")
def documents(s=Depends(session)):
    counts: dict[int, dict[str, int]] = {}
    for doc_id, chunker, n in s.execute(
            select(Chunk.document_id, Chunk.chunker, func.count()).group_by(Chunk.document_id, Chunk.chunker)):
        counts.setdefault(doc_id, {})[chunker] = n
    docs = s.scalars(select(Document).order_by(Document.created_at.desc(), Document.id.desc())).all()
    return {"documents": [{
        "document_id": d.id, "filename": d.filename, "doc_type": d.doc_type, "doc_number": d.doc_number,
        "status": d.status, "page_count": d.page_count, "uploaded_at": d.created_at.isoformat(),
        "chunkers": counts.get(d.id, {}), "chunk_count": counts.get(d.id, {}).get(DEFAULT_CHUNKER, 0),
    } for d in docs]}


@app.get("/documents/{document_id}/chunks")
def chunks(document_id: int, chunker: str = DEFAULT_CHUNKER, s=Depends(session)):
    doc = s.get(Document, document_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    return {"document_id": doc.id, "filename": doc.filename, "chunker": chunker,
            "chunks": [chunk_json(c, doc.filename) for c in document_chunks(s, doc.id, chunker)]}


@app.delete("/documents/{document_id}")
def delete_document(document_id: int, s=Depends(session)):
    doc = s.get(Document, document_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    n = s.scalar(select(func.count()).select_from(Chunk).where(Chunk.document_id == doc.id))
    path = Path(doc.storage_uri)
    s.delete(doc)  # pages and chunks cascade; embeddings stay as the cache
    s.commit()
    if path.is_relative_to(UPLOAD_DIR) and path.exists():  # never delete files outside uploads
        path.unlink()
        if not any(path.parent.iterdir()):
            path.parent.rmdir()
    return {"document_id": document_id, "chunks_deleted": n}


@app.get("/options")
def options(s=Depends(session)):
    present = sorted(s.scalars(select(Chunk.chunker).distinct()), key=lambda c: c != DEFAULT_CHUNKER)
    return {
        "chunkers": [{"id": c, "label": CHUNKER_LABELS.get(c, c)} for c in present or [DEFAULT_CHUNKER]],
        "methods": [{"id": m, "label": METHOD_LABELS[m]} for m in METHODS],
        "defaults": {"chunker": DEFAULT_CHUNKER, "method": "dense"},
    }


@app.post("/ask")
def ask(request: AskRequest):
    """Server-Sent Events: `retrieval` (the chunks), then `token` events (the answer), then `done` or `error`."""
    if request.method not in METHODS:
        raise HTTPException(400, "Unknown retrieval method")

    def events():
        started = time.perf_counter()
        try:
            with get_sessionmaker()() as s:
                hits = METHODS[request.method](s, request.question, request.chunker, ASK_TOP_K, request.document_id)
            chunks = [{"chunk_id": h.chunk_id, "document_id": h.document_id, "index": i, "page": h.page_start,
                       "section": h.section, "text": h.text, "filename": h.filename, "score": round(h.score, 4),
                       "score_label": SCORE_LABELS[request.method]} for i, h in enumerate(hits, 1)]
            yield sse("retrieval", {"chunker": request.chunker, "method": request.method, "chunks": chunks}, started)
            for text in stream_answer(chunks, request.question):
                yield sse("token", {"text": text}, started)
            yield sse("done", {}, started)
        except Exception as e:
            yield sse("error", {"detail": str(e)}, started)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
