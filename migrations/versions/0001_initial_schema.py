"""Initial schema: runs, documents, pages, chunks, embeddings (pgvector)

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _enum(*values, name):
    return sa.Enum(*values, name=name, native_enum=False, length=20)


def _ts(name):
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("status", _enum("running", "succeeded", "failed", name="runstatus"), nullable=False),
        sa.Column("pipeline_version", sa.String(32), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False, comment="Chunker, params, embedding model."),
        sa.Column("stats", postgresql.JSONB(), nullable=False, comment="Counts and errors."),
        _ts("started_at"),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        comment="One execution of the ingestion pipeline.",
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("doc_type", _enum("purchase_order", "invoice", "unknown", name="documenttype"), nullable=False),
        sa.Column("doc_number", sa.String(100), comment="Set by extraction."),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("is_scanned", sa.Boolean(), nullable=False),
        sa.Column("status", _enum("pending", "ingested", "needs_ocr", "empty", "failed", name="documentstatus"),
                  nullable=False),
        sa.Column("status_detail", sa.Text()),
        sa.Column("latest_run_id", sa.Integer(), sa.ForeignKey("ingestion_runs.id"),
                  comment="Set when a run starts on this document, even if it fails."),
        sa.Column("content_hash", sa.String(64), nullable=False, unique=True, comment="SHA-256 of the file bytes."),
        sa.Column("storage_uri", sa.String(1024), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        comment="One uploaded file; canonical record of the source.",
    )

    op.create_table(
        "document_pages",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False,
                  index=True),
        sa.Column("page_number", sa.Integer(), nullable=False, comment="1-based."),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_source", _enum("native", "form", "ocr", name="textsource"), nullable=False),
        sa.Column("ocr_mean_confidence", sa.Float(), comment="0-1; NULL for native text."),
        _ts("created_at"),
        sa.UniqueConstraint("document_id", "page_number"),
        comment="Extracted text of one page; the unit of citation.",
    )

    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("ingestion_runs.id")),
        sa.Column("chunker", sa.String(50), nullable=False, index=True, comment="e.g. recursive_1000."),
        sa.Column("chunk_index", sa.Integer(), nullable=False, comment="0-based within document + chunker."),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(200)),
        sa.Column("chunk_type", _enum("header", "table", "clause", "text", "footer", name="chunktype"),
                  nullable=False),
        sa.Column("text", sa.Text(), nullable=False, comment="Shown in citations."),
        sa.Column("search_text", sa.Text(), nullable=False,
                  comment="Context prefix + text: what is embedded and keyword-indexed."),
        sa.Column("text_hash", sa.String(64), nullable=False, index=True,
                  comment="SHA-256 of search_text; joins to embeddings."),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("search_tsv", postgresql.TSVECTOR(),
                  sa.Computed("to_tsvector('english', search_text)", persisted=True)),
        _ts("created_at"),
        sa.UniqueConstraint("document_id", "chunker", "chunk_index"),
        comment="Retrievable, citable unit of text produced by one chunker.",
    )
    op.create_index("ix_chunks_search_tsv", "chunks", ["search_tsv"], postgresql_using="gin")

    op.create_table(
        "embeddings",
        sa.Column("model", sa.String(100), primary_key=True, comment="e.g. gemini-embedding-001:768."),
        sa.Column("text_hash", sa.String(64), primary_key=True),
        sa.Column("embedding", Vector(768), nullable=False),
        _ts("created_at"),
        comment="One vector per (model, text); shared by identical texts.",
    )
    op.create_index("ix_embeddings_embedding", "embeddings", ["embedding"], postgresql_using="hnsw",
                    postgresql_ops={"embedding": "vector_cosine_ops"})


def downgrade():
    for table in ("embeddings", "chunks", "document_pages", "documents", "ingestion_runs"):
        op.drop_table(table)
