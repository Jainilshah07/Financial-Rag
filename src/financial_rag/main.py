import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from financial_rag.ingestion import load_and_split_pdf
from financial_rag.vector_store import (
    create_vector_store,
    delete_document,
    get_document_chunks,
    list_documents,
    open_vector_store,
)
from financial_rag.rag import stream_answer
from financial_rag.retrieval import STRATEGIES, list_strategies, retrieve
from financial_rag.router import route_question


app = FastAPI(title="Financial Document RAG")
# uv run uvicorn financial_rag.main:app --reload --app-dir src

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class AskRequest(BaseModel):
    question: str
    strategy: str = "similarity"
    document_id: str | None = None


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file")

    temp_path = None

    try:
        with NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
            temp_file.write(await file.read())
            temp_path = Path(temp_file.name)

        chunks = load_and_split_pdf(str(temp_path))

        if not chunks:
            raise HTTPException(
                status_code=400,
                detail="No readable text found in PDF",
            )

        document_id = uuid4().hex
        uploaded_at = datetime.now(timezone.utc).isoformat()
        for i, chunk in enumerate(chunks):
            chunk.metadata.update(
                document_id=document_id,
                filename=file.filename,
                uploaded_at=uploaded_at,
                chunk_index=i,
            )

        vector_store = create_vector_store(chunks)
        vector_store.client.close()

        return {
            "document_id": document_id,
            "filename": file.filename,
            "chunks_indexed": len(chunks),
            "status": "success",
            "chunks": [
                {
                    "index": i + 1,
                    "page": chunk.metadata.get("page", 0) + 1,
                    "section": chunk.metadata.get("section"),
                    "chunk_type": chunk.metadata.get("chunk_type"),
                    "text": chunk.page_content,
                }
                for i, chunk in enumerate(chunks)
            ],
        }

    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


@app.get("/documents")
def documents():
    return {"documents": list_documents()}


@app.get("/documents/{document_id}/chunks")
def document_chunks(document_id: str):
    chunks = get_document_chunks(document_id)

    if not chunks:
        raise HTTPException(status_code=404, detail="Document not found")

    return {"document_id": document_id, "chunks": chunks}


@app.delete("/documents/{document_id}")
def remove_document(document_id: str):
    deleted = delete_document(document_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")

    return {"document_id": document_id, "chunks_deleted": deleted}


@app.get("/strategies")
def strategies():
    return {"strategies": list_strategies()}


@app.post("/ask")
def ask(request: AskRequest):
    """Server-Sent Events: a `route` event (rag | greeting | out_of_scope). For
    `rag`: a `retrieval` event with the chunks, then `token` events with the answer.
    Otherwise just the router's reply as `token`. Ends with `done` (or `error`)."""
    if request.strategy not in STRATEGIES:
        raise HTTPException(status_code=400, detail="Unknown retrieval strategy")

    def events():
        vector_store = None
        try:
            decision = route_question(request.question)
            yield sse("route", {"route": decision.route})

            if decision.route != "rag":
                yield sse("token", {"text": decision.reply})
                yield sse("done", {})
                return

            vector_store = open_vector_store()
            chunks = retrieve(
                vector_store, request.strategy, request.question, request.document_id
            )
            yield sse("retrieval", {"strategy": request.strategy, "chunks": chunks})

            if chunks:
                for text in stream_answer(chunks, request.question):
                    yield sse("token", {"text": text})
            else:
                yield sse(
                    "token",
                    {"text": "I could not find relevant information in the selected documents."},
                )

            yield sse("done", {})
        except Exception as e:
            yield sse("error", {"detail": str(e)})
        finally:
            if vector_store:
                vector_store.client.close()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )
