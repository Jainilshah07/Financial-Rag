"""Database models (PostgreSQL + pgvector) and session factory.

Schema changes go through Alembic migrations in `migrations/`.
"""

from datetime import datetime
from functools import cache

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Computed, DateTime, Enum, Float, ForeignKey, Identity, Index, MetaData, String, Text,
    UniqueConstraint, create_engine, func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from financial_rag.config import settings

EMBEDDING_DIM = 768


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention={
        "pk": "pk_%(table_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ix": "ix_%(table_name)s_%(column_0_name)s",
    })


def _enum(*values: str, name: str) -> Enum:
    return Enum(*values, name=name, native_enum=False, length=20)


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = {"comment": "One execution of the ingestion pipeline."}

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    status: Mapped[str] = mapped_column(_enum("running", "succeeded", "failed", name="runstatus"))
    pipeline_version: Mapped[str] = mapped_column(String(32))
    config: Mapped[dict] = mapped_column(JSONB, default=dict, comment="Chunker, params, embedding model.")
    stats: Mapped[dict] = mapped_column(JSONB, default=dict, comment="Counts and errors.")
    started_at: Mapped[datetime] = _now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = {"comment": "One uploaded file; canonical record of the source."}

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    doc_type: Mapped[str] = mapped_column(
        _enum("purchase_order", "invoice", "unknown", name="documenttype"), default="unknown")
    doc_number: Mapped[str | None] = mapped_column(String(100), comment="Set by extraction.")
    page_count: Mapped[int]
    is_scanned: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(
        _enum("pending", "ingested", "needs_ocr", "empty", "failed", name="documentstatus"), default="pending")
    status_detail: Mapped[str | None] = mapped_column(Text)
    latest_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingestion_runs.id"), comment="Set when a run starts on this document, even if it fails.")
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, comment="SHA-256 of the file bytes.")
    storage_uri: Mapped[str] = mapped_column(String(1024))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DocumentPage(Base):
    __tablename__ = "document_pages"
    __table_args__ = (UniqueConstraint("document_id", "page_number"),
                      {"comment": "Extracted text of one page; the unit of citation."})

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    page_number: Mapped[int] = mapped_column(comment="1-based.")
    text: Mapped[str] = mapped_column(Text)
    text_source: Mapped[str] = mapped_column(_enum("native", "form", "ocr", name="textsource"))
    ocr_mean_confidence: Mapped[float | None] = mapped_column(Float, comment="0-1; NULL for native text.")
    created_at: Mapped[datetime] = _now()


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunker", "chunk_index"),
        Index("ix_chunks_search_tsv", "search_tsv", postgresql_using="gin"),
        {"comment": "Retrievable, citable unit of text produced by one chunker."},
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    chunker: Mapped[str] = mapped_column(String(50), index=True, comment="e.g. recursive_1000.")
    chunk_index: Mapped[int] = mapped_column(comment="0-based within document + chunker.")
    page_start: Mapped[int]
    page_end: Mapped[int]
    section: Mapped[str | None] = mapped_column(String(200))
    chunk_type: Mapped[str] = mapped_column(
        _enum("header", "table", "clause", "text", "footer", name="chunktype"), default="text")
    text: Mapped[str] = mapped_column(Text, comment="Shown in citations.")
    search_text: Mapped[str] = mapped_column(
        Text, comment="Context prefix + text: what is embedded and keyword-indexed.")
    text_hash: Mapped[str] = mapped_column(
        String(64), index=True, comment="SHA-256 of search_text; joins to embeddings.")
    token_count: Mapped[int]
    search_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', search_text)", persisted=True))
    created_at: Mapped[datetime] = _now()


class Embedding(Base):
    __tablename__ = "embeddings"
    __table_args__ = (
        Index("ix_embeddings_embedding", "embedding", postgresql_using="hnsw",
              postgresql_ops={"embedding": "vector_cosine_ops"}),
        {"comment": "One vector per (model, text); shared by identical texts."},
    )

    model: Mapped[str] = mapped_column(String(100), primary_key=True, comment="e.g. gemini-embedding-001:768.")
    text_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    embedding = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    created_at: Mapped[datetime] = _now()


@cache
def get_sessionmaker() -> sessionmaker:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not set in .env")
    return sessionmaker(create_engine(settings.database_url))
