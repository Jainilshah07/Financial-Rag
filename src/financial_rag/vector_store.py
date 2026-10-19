import hashlib

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient, models

from financial_rag.config import settings

QDRANT_PATH = "./qdrant_data"
COLLECTION = "financial_documents"


def create_vector_store(chunks):
    embeddings = GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        google_api_key=settings.gemini_api_key,
        output_dimensionality=768,
    )

    texts = [prepare_chunk_text(chunk) for chunk in chunks]
    metadatas = [chunk.metadata for chunk in chunks]

    vector_store = QdrantVectorStore.from_texts(
        texts=texts,
        embedding=embeddings,
        metadatas=metadatas,
        path=QDRANT_PATH,
        collection_name=COLLECTION,
    )

    return vector_store


def prepare_chunk_text(chunk):
    section = chunk.metadata.get("section", "General")
    page = chunk.metadata.get("page", 0) + 1

    return (
        f"Document section: {section}\n"
        f"Page: {page}\n"
        f"{chunk.page_content}"
    )

def open_vector_store():
    embeddings = GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        google_api_key=settings.gemini_api_key,
        output_dimensionality=768,
    )

    return QdrantVectorStore.from_existing_collection(
        embedding=embeddings,
        path=QDRANT_PATH,
        collection_name=COLLECTION,
    )


def _document_id(metadata):
    # Chunks indexed before document_id existed are grouped by their source path
    if metadata.get("document_id"):
        return metadata["document_id"]
    source = metadata.get("source", "unknown")
    return "legacy-" + hashlib.sha1(source.encode()).hexdigest()[:12]


def _scroll_all(client, scroll_filter=None):
    points, offset = [], None   
    while True:
        batch, offset = client.scroll(
            COLLECTION,
            scroll_filter=scroll_filter,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        points.extend(batch)
        if offset is None:
            return points


def chunk_from_point(point):
    metadata = point.payload.get("metadata", {})

    # Stored text carries the "Document section/Page" prefix added for
    # embedding; strip it so cards match what /upload returns.
    text = point.payload.get("page_content", "")
    if text.startswith("Document section:"):
        text = text.split("\n", 2)[-1]

    return {
        "point_id": str(point.id),
        "document_id": _document_id(metadata),
        "filename": metadata.get("filename") or "Unnamed (legacy upload)",
        "chunk_index": metadata.get("chunk_index"),
        "page": metadata.get("page", 0) + 1,
        "section": metadata.get("section"),
        "chunk_type": metadata.get("chunk_type"),
        "text": text,
    }


def document_point_ids(client, document_id: str):
    return [
        point.id
        for point in _scroll_all(client)
        if _document_id(point.payload.get("metadata", {})) == document_id
    ]


def delete_document(document_id: str) -> int:
    client = QdrantClient(path=QDRANT_PATH)

    try:
        if not client.collection_exists(COLLECTION):
            return 0

        ids = document_point_ids(client, document_id)
        if ids:
            client.delete(COLLECTION, points_selector=models.PointIdsList(points=ids))
        return len(ids)
    finally:
        client.close()


def list_documents():
    client = QdrantClient(path=QDRANT_PATH)

    try:
        if not client.collection_exists(COLLECTION):
            return []

        documents = {}
        for point in _scroll_all(client):
            metadata = point.payload.get("metadata", {})
            doc = documents.setdefault(
                _document_id(metadata),
                {
                    "document_id": _document_id(metadata),
                    "filename": metadata.get("filename") or "Unnamed (legacy upload)",
                    "uploaded_at": metadata.get("uploaded_at"),
                    "chunk_count": 0,
                    "pages": set(),
                },
            )
            doc["chunk_count"] += 1
            doc["pages"].add(metadata.get("page", 0) + 1)

        result = [
            {
                **{k: v for k, v in doc.items() if k != "pages"},
                "page_count": len(doc["pages"]),
            }
            for doc in documents.values()
        ]
        # Newest first; legacy documents (no timestamp) last
        result.sort(key=lambda d: d["uploaded_at"] or "", reverse=True)
        return result
    finally:
        client.close()


def get_document_chunks(document_id: str):
    client = QdrantClient(path=QDRANT_PATH)

    try:
        if not client.collection_exists(COLLECTION):
            return []

        chunks = [
            chunk_from_point(point)
            for point in _scroll_all(client)
            if _document_id(point.payload.get("metadata", {})) == document_id
        ]

        # Legacy chunks have no chunk_index, so they fall back to page order
        chunks.sort(key=lambda c: (c["chunk_index"] is None, c["chunk_index"] or 0, c["page"]))
        return [{**c, "index": i + 1} for i, c in enumerate(chunks)]
    finally:
        client.close()
