"""Store the Docling document per file

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("documents", sa.Column(
        "docling_json", postgresql.JSONB(), nullable=True,
        comment="DoclingDocument from extraction; chunkers read it, so a file is converted once."))


def downgrade():
    op.drop_column("documents", "docling_json")
